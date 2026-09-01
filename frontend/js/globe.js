/* ─── 3D globe ────────────────────────────────────────────────────────────
   A CesiumJS cockpit over Algeria, rendering the same real data the rest of
   the site runs on: NASA FIRMS detections and the Canadian FWI danger index.

   Runs keyless. Cesium's default imagery needs an ion token, so the viewer is
   built with Esri World Imagery instead — no account, no key, no card. An ion
   token is read from localStorage if the user pastes one in, which unlocks
   world terrain and photorealistic tiles, but nothing here requires it.

   Approach borrowed, with thanks, from bilawalsidhu/gods-eye-view (MIT): the
   cinematic opening, the idle drift, the radar-ping markers and the guided
   tour are all that project's grammar for making live public signal legible.
   The code below is our own; the debt is conceptual.
   ───────────────────────────────────────────────────────────────────────── */

const ION_KEY = "rased.ionToken";

/* The opening view, framed on Algeria's fire belt — the Tell Atlas and the
   coastal forests, where effectively every wildfire is. The Sahara is two
   thirds of the territory and none of the fires.

   These are camera *position* coordinates, not a look-at target, which is the
   trap here: a camera placed on the fire belt and pitched down is aiming at
   whatever lies beyond it, and at this altitude that is Italy. So the camera
   sits well south, over the desert, and looks north across the country. At
   height h and pitch p the view centres roughly h/tan(|p|) metres downrange —
   about 870 km from here, which lands on the coast. */
const HOME = {
  lon: 3.0, lat: 30.9, height: 1_420_000,
  pitch: -74,
};

/* Where the opening shot begins: far enough out that the whole disc of the
   Earth is in frame, so the flight down reads as an arrival. */
const ORBIT_HEIGHT = 24_000_000;

const FIRE_COLORS = {
  hot: "#FFD166",     // seen within the last couple of hours
  warm: "#E4572E",    // seen recently, inside the active window
  cool: "#8E4B2E",    // in the feed, but the satellite has moved on
};

let viewer = null;
let fireEntities = [];
let firesShown = [];

function ionToken() {
  try {
    return localStorage.getItem(ION_KEY) || "";
  } catch (e) {
    return "";
  }
}

function saveIonToken(t) {
  try {
    if (t) localStorage.setItem(ION_KEY, t);
    else localStorage.removeItem(ION_KEY);
  } catch (e) { /* private mode; the globe still runs keyless */ }
}

/* ─── viewer ──────────────────────────────────────────────────────────── */

async function buildViewer(containerId) {
  const token = ionToken();
  if (token) Cesium.Ion.defaultAccessToken = token;

  /* Esri World Imagery: keyless, global, good enough to read terrain by.

     The tiles are addressed by template rather than through
     `ArcGisMapServerImageryProvider.fromUrl`. That helper reads the MapServer's
     `?f=json` metadata to derive a tiling scheme, and on this service it comes
     back with a level-of-detail list Cesium resolves to level 23 — so the very
     first request is for tile 23/0/0, which does not exist, and the globe stays
     black with no error anywhere. Esri's tile layout is plain WebMercator
     {z}/{y}/{x}, so stating it outright skips the negotiation entirely. */
  const baseLayer = new Cesium.ImageryLayer(
    new Cesium.UrlTemplateImageryProvider({
      url: "https://services.arcgisonline.com/ArcGIS/rest/services/"
         + "World_Imagery/MapServer/tile/{z}/{y}/{x}",
      maximumLevel: 19,
      credit: "Esri, Maxar, Earthstar Geographics",
    }));

  viewer = new Cesium.Viewer(containerId, {
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    navigationHelpButton: false,
    animation: false,
    timeline: false,
    fullscreenButton: false,
    infoBox: false,
    selectionIndicator: false,
    baseLayer,
    // Terrain needs an ion token. Without one the globe is an ellipsoid, which
    // is perfectly readable — the fires are what matter, not the relief.
    terrainProvider: new Cesium.EllipsoidTerrainProvider(),
    contextOptions: { webgl: { preserveDrawingBuffer: true } },
  });

  const s = viewer.scene;
  /* Real sun lighting is off deliberately. With it on, Cesium renders the
     day/night terminator — so between roughly 19:00 and 06:00 Algerian time the
     entire country is unlit and the globe reads as a black screen with dots
     floating on it. A fire monitoring tool has to be legible at 3am, which is
     exactly when someone is most likely to be looking at it. */
  s.globe.enableLighting = false;
  s.globe.showGroundAtmosphere = true;
  s.fog.enabled = true;
  s.skyAtmosphere.show = true;
  s.highDynamicRange = true;
  s.globe.depthTestAgainstTerrain = false;

  /* Bloom is what makes a hotspot read as *hot* rather than as a coloured
     circle. Tuned dark and tight: the glow should bleed off the fire markers
     without washing out the imagery underneath them. */
  try {
    const bloom = s.postProcessStages.bloom;
    bloom.enabled = true;
    bloom.uniforms.glowOnly = false;
    bloom.uniforms.contrast = 132;
    bloom.uniforms.brightness = -0.36;
    bloom.uniforms.delta = 1.0;
    bloom.uniforms.sigma = 2.4;
    bloom.uniforms.stepSize = 1.0;
  } catch (e) { /* software rendering; the globe is still usable without it */ }

  viewer.cesiumWidget.creditContainer.style.display = "none";

  if (token) {
    try {
      viewer.terrainProvider = await Cesium.createWorldTerrainAsync();
    } catch (e) {
      console.warn("world terrain unavailable, staying on ellipsoid:", e.message);
    }
  }

  installIdleDrift();
  return viewer;
}

/* ─── camera ──────────────────────────────────────────────────────────── */

function homeView(height) {
  return {
    destination: Cesium.Cartesian3.fromDegrees(HOME.lon, HOME.lat,
      height === undefined ? HOME.height : height),
    orientation: {
      heading: Cesium.Math.toRadians(0),
      pitch: Cesium.Math.toRadians(HOME.pitch),
      roll: 0,
    },
  };
}

function flyHome(duration) {
  if (!viewer) return;
  bumpIdle();
  viewer.camera.flyTo(Object.assign(homeView(), {
    duration: duration === undefined ? 3.0 : duration,
    easingFunction: Cesium.EasingFunction.QUINTIC_IN_OUT,
  }));
}

/* The opening shot: park the camera in orbit, then fall towards the country.
   Returns a promise that settles when the flight lands, so the caller can
   sequence the HUD against it. */
function cinematicIntro() {
  return new Promise((resolve) => {
    if (!viewer) return resolve();
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(HOME.lon, HOME.lat - 6, ORBIT_HEIGHT),
    });
    viewer.camera.flyTo(Object.assign(homeView(), {
      duration: 5.2,
      easingFunction: Cesium.EasingFunction.QUINTIC_IN_OUT,
      complete: resolve,
      cancel: resolve,
    }));
    bumpIdle();
  });
}

function flyToFire(f, onArrive) {
  if (!viewer) return;
  bumpIdle();
  // Offset south of the fire and pitched down, so the marker sits in the upper
  // third of frame with its surroundings visible below it.
  viewer.camera.flyTo({
    destination: Cesium.Cartesian3.fromDegrees(f.lon, f.lat - 0.12, 26000),
    orientation: {
      heading: Cesium.Math.toRadians(0),
      pitch: Cesium.Math.toRadians(-42),
      roll: 0,
    },
    duration: 2.4,
    easingFunction: Cesium.EasingFunction.QUADRATIC_IN_OUT,
    complete: onArrive,
  });
}

/* ─── idle drift ──────────────────────────────────────────────────────── */

/* When nobody has touched the globe for a while it starts turning slowly.
   It is the difference between a screenshot and something that is watching. */
const IDLE_AFTER_MS = 12000;
const DRIFT_RATE = 0.0055;          // radians/second around Earth's axis

let lastInput = 0;
let driftOn = true;

function bumpIdle() { lastInput = performance.now(); }
function setDrift(on) { driftOn = on; bumpIdle(); }
function driftEnabled() { return driftOn; }

function installIdleDrift() {
  bumpIdle();
  const canvas = viewer.canvas;
  ["pointerdown", "wheel", "touchstart", "keydown"].forEach((ev) =>
    canvas.addEventListener(ev, bumpIdle, { passive: true }));

  let last = performance.now();
  viewer.scene.postUpdate.addEventListener(() => {
    const now = performance.now();
    const dt = Math.min((now - last) / 1000, 0.1);
    last = now;
    if (!driftOn) return;
    if (now - lastInput < IDLE_AFTER_MS) return;
    // Rotating the camera about the polar axis spins the world beneath it,
    // which keeps the current pitch and altitude intact.
    viewer.camera.rotate(Cesium.Cartesian3.UNIT_Z, -DRIFT_RATE * dt);
  });
}

/* ─── fires ───────────────────────────────────────────────────────────── */

function fireColour(f) {
  if (f.last_seen_h <= 2) return FIRE_COLORS.hot;
  if (f.last_seen_h <= 6) return FIRE_COLORS.warm;
  return FIRE_COLORS.cool;
}

/* Radiative power spans four orders of magnitude, so the marker scales on its
   square root — linear scaling turns one fire into a blob and hides the rest. */
function fireRadius(frp) {
  return 2200 + Math.sqrt(Math.max(frp, 0)) * 900;
}

const PING_PERIOD = 2.8;   // seconds for one expand-and-fade cycle

function pingPhase(offset) {
  return ((performance.now() / 1000 + offset) % PING_PERIOD) / PING_PERIOD;
}

/* Render every fire whose last detection falls inside `windowH` hours.

   The ping is deliberately reserved for the freshest detections. With every
   marker pulsing the display becomes noise; with only the last few hours
   moving, the eye goes straight to what is still developing. */
function addFires(fires, windowH) {
  clearFires();
  const w = windowH || 6;
  const shown = fires
    .filter((f) => f.category !== "industrial")
    .filter((f) => f.last_seen_h <= w);

  for (const f of shown) {
    const colour = Cesium.Color.fromCssColorString(fireColour(f));
    const r = fireRadius(f.frp_total);
    const fresh = f.last_seen_h <= 6;
    // Stagger the pings so a cluster of fires does not throb in lockstep.
    const offset = (parseInt(String(f.id).replace(/\D/g, ""), 10) || 0) * 0.37;

    // The footprint: a ground ellipse scaled to radiative power. It sits on
    // the terrain, so it cannot be mistaken for a UI pin.
    const e = viewer.entities.add({
      name: f.id,
      position: Cesium.Cartesian3.fromDegrees(f.lon, f.lat),
      ellipse: {
        semiMinorAxis: r,
        semiMajorAxis: r,
        material: colour.withAlpha(fresh ? 0.5 : 0.2),
        outline: true,
        outlineColor: colour.withAlpha(0.9),
        outlineWidth: 2,
        height: 0,
      },
      point: {
        pixelSize: fresh ? 9 : 5,
        color: colour,
        outlineColor: Cesium.Color.WHITE.withAlpha(0.85),
        outlineWidth: fresh ? 2 : 1,
        // Keep the dot visible when zoomed out, without it swelling up close.
        scaleByDistance: new Cesium.NearFarScalar(1.0e5, 1.4, 3.0e6, 0.6),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      properties: { fire: f },
    });
    fireEntities.push(e);

    if (!fresh) continue;

    // The ping: a ring that expands out of the footprint and fades, once per
    // cycle. Radius and alpha are callbacks so Cesium re-evaluates them every
    // frame without us holding an animation loop of our own.
    const ping = viewer.entities.add({
      position: Cesium.Cartesian3.fromDegrees(f.lon, f.lat),
      ellipse: {
        semiMinorAxis: new Cesium.CallbackProperty(
          () => r * (1 + pingPhase(offset) * 1.9), false),
        semiMajorAxis: new Cesium.CallbackProperty(
          () => r * (1 + pingPhase(offset) * 1.9), false),
        material: new Cesium.ColorMaterialProperty(
          new Cesium.CallbackProperty(
            () => colour.withAlpha(0.34 * (1 - pingPhase(offset))), false)),
        outline: false,
        height: 0,
      },
      properties: { fire: f },
    });
    fireEntities.push(ping);
  }

  firesShown = shown;
  return shown;
}

function shownFires() { return firesShown; }

function clearFires() {
  for (const e of fireEntities) viewer.entities.remove(e);
  fireEntities = [];
  firesShown = [];
}

function setFiresVisible(on) {
  for (const e of fireEntities) e.show = on;
}

/* ─── guided tour ─────────────────────────────────────────────────────── */

/* Fly the strongest fires one after another, pausing on each. This is how
   someone reads the situation without knowing the map: press play, watch the
   country's hotspots in order of severity. */
let tourTimer = null;
let tourIdx = 0;

function tourRunning() { return tourTimer !== null; }

function startTour(list, onFocus, onEnd) {
  stopTour();
  if (!list.length) return false;
  tourIdx = 0;
  setDrift(false);

  const step = () => {
    if (tourIdx >= list.length) { stopTour(); if (onEnd) onEnd(); return; }
    const f = list[tourIdx++];
    if (onFocus) onFocus(f, tourIdx, list.length);
    flyToFire(f);
    tourTimer = setTimeout(step, 6200);
  };
  step();
  return true;
}

function stopTour() {
  if (tourTimer) clearTimeout(tourTimer);
  tourTimer = null;
  setDrift(true);
}

/* ─── danger layer ────────────────────────────────────────────────────── */

let dangerSource = null;

async function addDangerLayer(geojson, riskByCode, colours, opacityFor) {
  // Colour is baked per feature before load: Cesium's GeoJSON styling runs once
  // at load time, so recolouring later means reloading the source.
  const ds = await Cesium.GeoJsonDataSource.load(geojson, { clampToGround: true });

  for (const entity of ds.entities.values) {
    const code = entity.properties && entity.properties.code
      ? entity.properties.code.getValue() : null;
    const fuel = entity.properties && entity.properties.fuel
      ? entity.properties.fuel.getValue() : "desert";
    const day = code && riskByCode[code] ? riskByCode[code].days[0] : null;
    if (!entity.polygon) continue;

    if (!day) {
      entity.polygon.material = Cesium.Color.TRANSPARENT;
      entity.polygon.outline = false;
      continue;
    }
    const c = Cesium.Color.fromCssColorString(colours[day.class]);
    entity.polygon.material = c.withAlpha(opacityFor(fuel));
    entity.polygon.outline = false;
    entity.polygon.classificationType = Cesium.ClassificationType.TERRAIN;
  }

  dangerSource = ds;
  await viewer.dataSources.add(ds);
  return ds;
}

function setDangerVisible(on) {
  if (dangerSource) dangerSource.show = on;
}

/* ─── picking ─────────────────────────────────────────────────────────── */

function onFirePick(handler) {
  const h = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
  h.setInputAction((click) => {
    const picked = viewer.scene.pick(click.position);
    if (!Cesium.defined(picked) || !picked.id || !picked.id.properties) {
      handler(null);
      return;
    }
    const props = picked.id.properties;
    const fire = props.fire ? props.fire.getValue() : null;
    handler(fire || null);
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
  return h;
}

/* ─── NASA GIBS imagery ───────────────────────────────────────────────────
   Esri's basemap is sharp but it is a mosaic assembled over months — it shows
   the forest as it was, not as it is. GIBS serves the actual satellite pass
   from a given day, which is where the smoke plume and the burn scar are.

   Keyless, and it sends `Access-Control-Allow-Origin: *`, so it works from a
   static site with nothing in between.

   Two layers matter here:

   TRUECOLOR is what the eye would see from orbit. Smoke shows as grey-white
   haze streaming downwind, which is often visible hours before a fire is large
   enough to be newsworthy.

   FIRE is the 7-2-1 shortwave/near-infrared band combination. Healthy
   vegetation renders bright green, bare rock and sand pink-grey, and — the
   reason it exists — burn scars render deep brick red while an actively
   burning front glows orange. It is the standard product for answering "how
   much of the forest is gone", and it answers it visually, without a legend.
   ───────────────────────────────────────────────────────────────────────── */

const GIBS_LAYERS = {
  truecolor: {
    id: "VIIRS_NOAA20_CorrectedReflectance_TrueColor",
    matrix: "GoogleMapsCompatible_Level9", max: 9, ext: "jpg",
  },
  fire: {
    id: "MODIS_Terra_CorrectedReflectance_Bands721",
    matrix: "GoogleMapsCompatible_Level9", max: 9, ext: "jpg",
  },
};

let gibsLayer = null;
let gibsKind = null;

/* GIBS publishes by UTC day and near-real-time imagery lands hours after the
   pass, so "today" is frequently still empty. Yesterday is the most recent day
   that is reliably complete. */
function gibsDefaultDate() {
  const d = new Date(Date.now() - 24 * 3600 * 1000);
  return d.toISOString().slice(0, 10);
}

function setGibs(kind, date) {
  if (!viewer) return;
  if (gibsLayer) { viewer.imageryLayers.remove(gibsLayer, true); gibsLayer = null; }
  gibsKind = kind || null;
  if (!kind) return;

  const L = GIBS_LAYERS[kind];
  const provider = new Cesium.UrlTemplateImageryProvider({
    url: "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/" + L.id +
         "/default/" + (date || gibsDefaultDate()) + "/" + L.matrix +
         "/{z}/{y}/{x}." + L.ext,
    maximumLevel: L.max,
    credit: "NASA EOSDIS GIBS",
  });
  gibsLayer = viewer.imageryLayers.addImageryProvider(provider);
  // Sits over the Esri base at partial opacity, so zooming past the GIBS
  // resolution ceiling reveals the sharp mosaic underneath rather than a
  // blurred-out mush.
  gibsLayer.alpha = 0.82;
  return gibsLayer;
}

function gibsActive() { return gibsKind; }

function setGibsOpacity(a) { if (gibsLayer) gibsLayer.alpha = a; }

/* ─── detection pixels ────────────────────────────────────────────────────
   What a "fire" on this map actually is: a set of satellite pixels that came
   back hotter than their surroundings. Drawing them at their true ground
   footprint — which FIRMS reports per detection, because a pixel grows from
   375 m at nadir to nearly a kilometre at the edge of the swath — replaces an
   implied precision nobody has with the real evidence.
   ───────────────────────────────────────────────────────────────────────── */

let pixelEntities = [];

const KM_PER_DEG_LAT = 111.32;

function detColour(ageH) {
  if (ageH <= 3) return Cesium.Color.fromCssColorString("#FFE066");
  if (ageH <= 8) return Cesium.Color.fromCssColorString("#FF8C42");
  if (ageH <= 20) return Cesium.Color.fromCssColorString("#D64545");
  return Cesium.Color.fromCssColorString("#7A4A4A");
}

function showDetections(fire) {
  clearDetections();
  if (!fire || !fire.points || !fire.points.length) return 0;

  for (const p of fire.points) {
    const halfLat = (p.track || 0.375) / 2 / KM_PER_DEG_LAT;
    const halfLon = (p.scan || 0.375) / 2 /
      (KM_PER_DEG_LAT * Math.cos(p.lat * Math.PI / 180));
    const c = detColour(p.age_h);

    pixelEntities.push(viewer.entities.add({
      rectangle: {
        coordinates: Cesium.Rectangle.fromDegrees(
          p.lon - halfLon, p.lat - halfLat, p.lon + halfLon, p.lat + halfLat),
        material: c.withAlpha(0.30),
        outline: true,
        outlineColor: c.withAlpha(0.95),
        outlineWidth: 1,
        height: 0,
      },
      properties: { detection: p, fire: fire },
    }));
  }
  return fire.points.length;
}

function clearDetections() {
  for (const e of pixelEntities) viewer.entities.remove(e);
  pixelEntities = [];
}

function detectionsShown() { return pixelEntities.length; }

/* Drop to the deck over a fire so the pixel grid is legible against the
   terrain it is sitting on. */
function inspectFire(f, onArrive) {
  if (!viewer) return;
  bumpIdle();
  viewer.camera.flyTo({
    destination: Cesium.Cartesian3.fromDegrees(f.lon, f.lat - 0.035, 7600),
    orientation: {
      heading: Cesium.Math.toRadians(0),
      pitch: Cesium.Math.toRadians(-55),
      roll: 0,
    },
    duration: 2.2,
    easingFunction: Cesium.EasingFunction.QUADRATIC_IN_OUT,
    complete: onArrive,
  });
}

/* ─── burned area ─────────────────────────────────────────────────────────
   What each wilaya actually lost, shaded onto the map.

   The fire markers answer "where is it burning". This answers "what is gone",
   which is the question that survives the fire — the one people are still
   asking a week later when the hotspots have cleared and the coverage has
   moved on. It is computed from the footprint of every detection, deduplicated
   onto a 375 m grid, so it is a floor rather than an estimate: ground a
   satellite positively saw burning.
   ───────────────────────────────────────────────────────────────────────── */

/* Sequential scale, dark to bright. Deliberately not the danger palette: the
   two layers mean different things and must never be read as the same scale. */
const BURN_STOPS = [
  { ha:     0, c: "#000000", a: 0.00 },
  { ha:   200, c: "#4A1D14", a: 0.30 },
  { ha:  1000, c: "#7B2A16", a: 0.42 },
  { ha:  4000, c: "#A83A18", a: 0.54 },
  { ha: 10000, c: "#D2551C", a: 0.64 },
  { ha: 20000, c: "#F5852F", a: 0.74 },
];

function burnStyle(ha) {
  let s = BURN_STOPS[0];
  for (const stop of BURN_STOPS) if (ha >= stop.ha) s = stop;
  return s;
}

let burnedSource = null;

async function addBurnedLayer(geojson, burnedByCode, windowKey) {
  if (burnedSource) {
    await viewer.dataSources.remove(burnedSource, true);
    burnedSource = null;
  }
  const ds = await Cesium.GeoJsonDataSource.load(geojson, { clampToGround: true });

  for (const entity of ds.entities.values) {
    if (!entity.polygon) continue;
    const code = entity.properties && entity.properties.code
      ? entity.properties.code.getValue() : null;
    const rec = code ? burnedByCode[code] : null;
    const ha = rec ? (rec[windowKey] || 0) : 0;

    if (ha <= 0) {
      entity.polygon.material = Cesium.Color.TRANSPARENT;
      entity.polygon.outline = false;
      continue;
    }
    const s = burnStyle(ha);
    entity.polygon.material =
      Cesium.Color.fromCssColorString(s.c).withAlpha(s.a);
    // An outline here, unlike on the danger layer: a burn scar has a hard
    // administrative edge in this rendering and pretending otherwise invites
    // reading the shading as a smooth field.
    entity.polygon.outline = true;
    entity.polygon.outlineColor =
      Cesium.Color.fromCssColorString("#F5852F").withAlpha(0.5);
    entity.polygon.classificationType = Cesium.ClassificationType.TERRAIN;
  }

  burnedSource = ds;
  ds.show = false;
  await viewer.dataSources.add(ds);
  return ds;
}

function setBurnedVisible(on) {
  if (burnedSource) burnedSource.show = on;
}

async function setBurnedWindow(geojson, burnedByCode, windowKey, visible) {
  await addBurnedLayer(geojson, burnedByCode, windowKey);
  setBurnedVisible(visible);
}

/* Frame a whole wilaya — used when someone picks one off the damage list and
   wants to see the extent of it rather than a single hotspot. */
function flyToWilaya(feature) {
  if (!viewer || !feature) return;
  bumpIdle();
  const b = feature.properties.bbox;
  if (!b) return;
  viewer.camera.flyTo({
    destination: Cesium.Rectangle.fromDegrees(b[0], b[1], b[2], b[3]),
    duration: 2.2,
    easingFunction: Cesium.EasingFunction.QUADRATIC_IN_OUT,
  });
}
