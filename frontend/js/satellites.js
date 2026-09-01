/* ─── live satellite tracking ─────────────────────────────────────────────
   The five spacecraft that detect every fire on this map, drawn where they
   actually are right now.

   This is live in the strict sense: nothing is being fetched. The orbital
   elements are a small file, and positions are propagated from them in the
   browser with SGP4 — the same model NORAD publishes the elements for — so the
   satellites move continuously and stay correct to within a kilometre or so
   for a week without another byte from the network.

   Why it belongs on a fire map rather than being decoration: this system is
   blind between overpasses. Algeria gets roughly eight looks a day, and a fire
   that starts just after a pass is invisible until the next one. Putting the
   satellites on the globe with a countdown to the next overpass turns that
   from a hidden caveat into something a reader can see and plan around.
   ───────────────────────────────────────────────────────────────────────── */

/* The point overpasses are measured against: the Tell Atlas and the coastal
   forests, where effectively every Algerian wildfire burns. A pass that only
   catches the far south is not a look at the fire belt. */
const OVERPASS_TARGET = { lat: 36.2, lon: 3.2 };

const SAT_COLORS = {
  VIIRS: "#4FC3F7",
  MODIS: "#B39DDB",
};

let satData = [];        // { meta, satrec }
let satEntities = [];
let satTimer = null;
let satsVisible = false;
let overpassCache = [];

/* satellite.js is loaded from a <script> tag; if it failed, every function here
   degrades to a no-op rather than throwing into the boot sequence. */
function sgp4Ready() {
  return typeof satellite !== "undefined" && satellite && satellite.twoline2satrec;
}

async function loadSatellites() {
  if (!sgp4Ready()) return [];
  const payload = await getJSON(null, dataURL("satellites.json"));
  satData = payload.satellites.map((meta) => ({
    meta,
    satrec: satellite.twoline2satrec(meta.tle1, meta.tle2),
  })).filter((s) => s.satrec && !s.satrec.error);
  return satData;
}

/* ─── propagation ─────────────────────────────────────────────────────── */

/* Sub-satellite point and altitude at a given instant. Returns null when the
   propagator rejects the epoch, which happens with stale elements rather than
   never. */
function subPoint(satrec, when) {
  const pv = satellite.propagate(satrec, when);
  if (!pv || !pv.position) return null;
  const gd = satellite.eciToGeodetic(pv.position, satellite.gstime(when));
  return {
    lat: satellite.degreesLat(gd.latitude),
    lon: satellite.degreesLong(gd.longitude),
    altKm: gd.height,
  };
}

const R_EARTH_KM = 6371.0;

function greatCircleKm(aLat, aLon, bLat, bLon) {
  const toRad = Math.PI / 180;
  const dLat = (bLat - aLat) * toRad;
  const dLon = (bLon - aLon) * toRad;
  const h = Math.sin(dLat / 2) ** 2 +
    Math.cos(aLat * toRad) * Math.cos(bLat * toRad) * Math.sin(dLon / 2) ** 2;
  return 2 * R_EARTH_KM * Math.asin(Math.min(1, Math.sqrt(h)));
}

/* ─── overpasses ──────────────────────────────────────────────────────── */

/* When is this satellite next in a position to see the fire belt?

   "Seeing it" means the target falls inside the instrument's swath, so the test
   is whether the sub-satellite track passes within half a swath width of the
   target. Stepping a minute at a time over the next day is more than precise
   enough — these are 100-minute orbits, and the answer is used to say "in about
   two hours", not to point an antenna. */
function nextOverpass(entry, from) {
  const half = entry.meta.swath_km / 2;
  const start = from || new Date();
  const STEP_MIN = 1;
  const HORIZON_MIN = 24 * 60;

  let best = null;
  for (let m = 0; m <= HORIZON_MIN; m += STEP_MIN) {
    const when = new Date(start.getTime() + m * 60000);
    const p = subPoint(entry.satrec, when);
    if (!p) continue;
    const d = greatCircleKm(p.lat, p.lon, OVERPASS_TARGET.lat, OVERPASS_TARGET.lon);
    if (d > half) continue;
    // First minute inside the swath. Refine to ~10 s so the countdown does not
    // visibly disagree with itself.
    let refined = when;
    for (let s = -60; s <= 0; s += 10) {
      const t = new Date(when.getTime() + s * 1000);
      const q = subPoint(entry.satrec, t);
      if (!q) continue;
      if (greatCircleKm(q.lat, q.lon, OVERPASS_TARGET.lat, OVERPASS_TARGET.lon) <= half) {
        refined = t;
        break;
      }
    }
    best = { when: refined, minutes: (refined - start) / 60000 };
    break;
  }
  return best;
}

/* Whether the fire belt is inside this satellite's swath at this instant —
   i.e. whether it is looking at Algeria right now. */
function isOverhead(entry, when) {
  const p = subPoint(entry.satrec, when || new Date());
  if (!p) return false;
  return greatCircleKm(p.lat, p.lon, OVERPASS_TARGET.lat, OVERPASS_TARGET.lon)
    <= entry.meta.swath_km / 2;
}

/* Recomputed on a timer rather than per frame: an overpass search is a few
   thousand propagations, and the answer changes on the scale of minutes. */
function refreshOverpasses() {
  const now = new Date();
  overpassCache = satData.map((entry) => ({
    meta: entry.meta,
    overhead: isOverhead(entry, now),
    next: nextOverpass(entry, now),
  })).sort((a, b) => {
    if (a.overhead !== b.overhead) return a.overhead ? -1 : 1;
    return (a.next ? a.next.minutes : 1e9) - (b.next ? b.next.minutes : 1e9);
  });
  return overpassCache;
}

function overpasses() { return overpassCache; }

/* ─── drawing ─────────────────────────────────────────────────────────── */

/* One orbit's worth of positions, for the path drawn ahead of and behind the
   satellite. Sampled every 30 s over 100 minutes — dense enough that the
   polyline reads as a curve rather than a chain of chords. */
function orbitPositions(entry, when) {
  const pts = [];
  const start = (when || new Date()).getTime() - 45 * 60000;
  for (let s = 0; s <= 100 * 60; s += 30) {
    const p = subPoint(entry.satrec, new Date(start + s * 1000));
    if (p) pts.push(Cesium.Cartesian3.fromDegrees(p.lon, p.lat, p.altKm * 1000));
  }
  return pts;
}

function addSatellites() {
  clearSatellites();
  if (!sgp4Ready() || !satData.length) return 0;

  for (const entry of satData) {
    const colour = Cesium.Color.fromCssColorString(
      SAT_COLORS[entry.meta.sensor] || "#9FB3C8");

    /* Position is a CallbackProperty, so Cesium re-propagates it every frame
       and the satellite genuinely moves rather than being re-added on a timer. */
    const posProp = new Cesium.CallbackProperty(() => {
      const p = subPoint(entry.satrec, new Date());
      return p ? Cesium.Cartesian3.fromDegrees(p.lon, p.lat, p.altKm * 1000) : undefined;
    }, false);

    satEntities.push(viewer.entities.add({
      name: entry.meta.short,
      position: posProp,
      point: {
        pixelSize: 8,
        color: colour,
        outlineColor: Cesium.Color.WHITE.withAlpha(0.9),
        outlineWidth: 1.5,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      label: {
        text: entry.meta.short,
        font: "500 12px Vazirmatn, sans-serif",
        fillColor: colour,
        outlineColor: Cesium.Color.BLACK.withAlpha(0.85),
        outlineWidth: 3,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -17),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        scaleByDistance: new Cesium.NearFarScalar(1.0e6, 1.0, 2.5e7, 0.55),
      },
      properties: { satellite: entry.meta },
    }));

    // The orbit ahead and behind. Recomputed on the same slow timer as the
    // overpasses: it drifts by metres over a minute, not kilometres.
    satEntities.push(viewer.entities.add({
      polyline: {
        positions: new Cesium.CallbackProperty(() => orbitPositions(entry), false),
        width: 1.4,
        material: new Cesium.PolylineDashMaterialProperty({
          color: colour.withAlpha(0.42),
          dashLength: 12,
        }),
        arcType: Cesium.ArcType.NONE,
      },
    }));

    /* The swath: how wide a strip of ground the instrument is reading. This is
       the honest picture of coverage — a VIIRS pass sees 3060 km at once, which
       is why the whole country is covered in a single overpass. */
    satEntities.push(viewer.entities.add({
      position: posProp,
      ellipse: {
        semiMinorAxis: entry.meta.swath_km * 500,   // half-width, in metres
        semiMajorAxis: entry.meta.swath_km * 500,
        material: colour.withAlpha(0.07),
        outline: true,
        outlineColor: colour.withAlpha(0.30),
        outlineWidth: 1,
        height: 0,
      },
    }));
  }

  setSatellitesVisible(satsVisible);
  return satData.length;
}

function clearSatellites() {
  for (const e of satEntities) viewer.entities.remove(e);
  satEntities = [];
}

function setSatellitesVisible(on) {
  satsVisible = on;
  for (const e of satEntities) e.show = on;
}

function satellitesVisible() { return satsVisible; }

/* Fly to whichever satellite is named, from far enough back that the swath
   circle and the ground beneath it are both in frame. */
function flyToSatellite(shortName) {
  const entry = satData.find((s) => s.meta.short === shortName);
  if (!entry || !viewer) return;
  const p = subPoint(entry.satrec, new Date());
  if (!p) return;
  bumpIdle();
  viewer.camera.flyTo({
    destination: Cesium.Cartesian3.fromDegrees(p.lon, p.lat - 12, 9_500_000),
    orientation: {
      heading: 0,
      pitch: Cesium.Math.toRadians(-52),
      roll: 0,
    },
    duration: 2.6,
    easingFunction: Cesium.EasingFunction.QUADRATIC_IN_OUT,
  });
}

function startSatelliteClock(onTick) {
  if (satTimer) clearInterval(satTimer);
  refreshOverpasses();
  if (onTick) onTick();
  satTimer = setInterval(() => {
    refreshOverpasses();
    if (onTick) onTick();
  }, 30000);
}
