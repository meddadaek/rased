/* ─── راصد / Rased — map application ──────────────────────────────────────
   Reads three payloads:
     data/wilayas.geojson   48 wilaya polygons + code, names, fuel class
     data/mock_risk.json    7-day FWI series per wilaya   (-> /api/v1/risk)
     data/mock_fires.json   clustered satellite hotspots  (-> /api/v1/fires)
   The two mock files carry the exact shape the live API will serve, so moving to
   real data is a change of URL, not a change of code.
   ───────────────────────────────────────────────────────────────────────── */

const CLASS_COLOR = {
  very_low: "#177A55", low: "#8FBF3F", moderate: "#F7D01E",
  high: "#EF7A1A", very_high: "#C01818", extreme: "#5E1030",
};
const CLASS_ORDER = ["very_low", "low", "moderate", "high", "very_high", "extreme"];
const CLASS_BOUNDS = [0, 5.2, 11.2, 21.3, 38, 50];

/* Opacity carries a second channel of meaning: how much fuel is actually there.
   The Sahara can be meteorologically dry and still be nearly transparent here,
   which is the honest picture.

   These are deliberately faint. The choropleth is a *forecast* covering all 48
   wilayas; the fires are what is happening right now. When the risk layer was
   opaque it shouted over the thing the reader actually came for, so it now sits
   as a tint behind the fires rather than beside them. */
const FUEL_OPACITY = { forest: 0.30, steppe: 0.19, desert: 0.07 };

/* Full-scale values for the component bars. FFMC saturates near 101, DC can run
   past 800 by late summer — these are display maxima, not physical limits. */
const CODE_MAX = { ffmc: 101, dmc: 150, dc: 900, isi: 50, bui: 200 };

const S = {
  lang: "ar",
  day: 0,
  geo: null,
  risk: null,
  fires: null,
  selected: null,
  markers: [],
  showFires: true,
  assets: null,
  exposure: null,
  expoById: {},
};

const $ = (id) => document.getElementById(id);
const t = () => I18N[S.lang];
const num = (v) => String(v);   // Western digits in both languages

/* ─── map ─────────────────────────────────────────────────────────────── */

let map;

/* Arabic is a cursive script: every letter changes shape depending on its
   neighbours, and the run is laid out right-to-left. MapLibre's default shaper
   does neither, so Algerian place names render as disconnected isolated glyphs
   in logical order — "قسنطينة" comes out as ق س ن ط ي ن ة, which is not merely
   ugly, it is unreadable to the people this map is for.

   The RTL plugin does the joining and the bidi reordering. It has to be
   installed before any Arabic label is rendered, and only once per page.
   MapLibre recommends Mapbox's build; there is no @maplibre-scoped equivalent
   published on npm. */
const RTL_PLUGIN = "https://unpkg.com/@mapbox/mapbox-gl-rtl-text@0.2.3/mapbox-gl-rtl-text.js";

async function ensureRTLPlugin() {
  try {
    const status = maplibregl.getRTLTextPluginStatus
      ? maplibregl.getRTLTextPluginStatus()
      : "unavailable";
    if (status !== "unavailable") return;               // already installed
    await maplibregl.setRTLTextPlugin(RTL_PLUGIN, false);
  } catch (err) {
    // A missing plugin degrades label rendering; it must never block the map.
    console.warn("RTL text plugin unavailable, Arabic labels will not join:", err.message);
  }
}

function createMap(style) {
  map = new maplibregl.Map({
    container: "map",
    attributionControl: false,
    style,
    // Algeria is enormous but the fire problem lives in the northern strip, so the
    // default view is weighted north rather than centred on the country's centroid.
    center: [2.9, 33.4],
    zoom: 4.55,
    minZoom: 3.6,
    maxZoom: 11,
    maxBounds: [[-12, 15], [17, 40]],
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

  /* MapLibre's trackResize only listens for *window* resize events. If the
     container's size changes without one — an embedded pane being resized, a
     phone's URL bar collapsing, a CSS layout settling after fonts load — the
     canvas keeps whatever size it had at construction. Observed exactly that:
     a 400x300 canvas on a 1280x720 viewport, so the map drew into the top-left
     corner and the rest of the page was blank.

     A ResizeObserver on the container catches every one of those cases. */
  if (typeof ResizeObserver !== "undefined") {
    const ro = new ResizeObserver(() => map.resize());
    ro.observe(map.getContainer());
  }

  return map;
}

/* Add the data layers as soon as the style will accept them.

   Three gates were tried here and two were wrong:

     "load"        also waits on every tile, sprite and glyph font, so one
                   stalled font request hangs the app forever.
     isStyleLoaded also never reliably flips true under main-thread load — it
                   reports on pending work we do not actually depend on.

   So stop asking a proxy question and attempt the real operation instead. If
   the style genuinely is not ready, addSource throws, we wait a tick and try
   again. The thing we care about is whether the layers went on, and that is
   exactly what this tests. */
async function addLayersWhenReady(maxMs = 25000) {
  const started = Date.now();
  let lastErr = null;
  for (;;) {
    try {
      const style = map.getStyle();
      if (style && (style.layers || []).length) {
        addLayers();
        return;
      }
    } catch (err) {
      lastErr = err;
    }
    if (Date.now() - started > maxMs) {
      throw new Error("could not add map layers within " + maxMs + "ms"
        + (lastErr ? ": " + lastErr.message : ""));
    }
    await new Promise((r) => setTimeout(r, 80));
  }
}

/* Insert the choropleth beneath place labels so town names stay readable on top
   of it. The vector style names its layers however it likes, so find the first
   symbol layer rather than hard-coding an id. */
function firstSymbolLayer() {
  const layers = map.getStyle().layers || [];
  const s = layers.find((l) => l.type === "symbol");
  return s ? s.id : undefined;
}

function fillColorExpr(day) {
  const prop = ["get", "fwi_d" + day];
  const e = ["step", prop, CLASS_COLOR.very_low];
  for (let i = 1; i < CLASS_ORDER.length; i++) {
    e.push(CLASS_BOUNDS[i], CLASS_COLOR[CLASS_ORDER[i]]);
  }
  return e;
}

function addLayers() {
  const before = firstSymbolLayer();
  map.addSource("wilayas", { type: "geojson", data: S.geo, promoteId: "code" });

  map.addLayer({
    id: "w-fill", type: "fill", source: "wilayas",
    paint: {
      "fill-color": fillColorExpr(0),
      "fill-opacity": [
        "case",
        ["boolean", ["feature-state", "hover"], false], 0.52,
        ["match", ["get", "fuel"],
          "forest", FUEL_OPACITY.forest,
          "steppe", FUEL_OPACITY.steppe,
          FUEL_OPACITY.desert],
      ],
      "fill-opacity-transition": { duration: 220 },
      "fill-color-transition": { duration: 420 },
    },
  }, before);

  map.addLayer({
    id: "w-line", type: "line", source: "wilayas",
    paint: {
      "line-color": ["case", ["boolean", ["feature-state", "hover"], false],
        "#0B6F63", "rgba(20,55,45,0.20)"],
      "line-width": ["case", ["boolean", ["feature-state", "hover"], false], 1.8, 0.5],
    },
  }, before);

  map.addLayer({
    id: "w-sel", type: "line", source: "wilayas",
    filter: ["==", ["get", "code"], ""],
    paint: { "line-color": "#E4572E", "line-width": 2.4, "line-blur": 0.3 },
  }, before);

  let hovered = null;
  map.on("mousemove", "w-fill", (e) => {
    map.getCanvas().style.cursor = "pointer";
    const id = e.features[0].properties.code;
    if (hovered === id) return;
    if (hovered) map.setFeatureState({ source: "wilayas", id: hovered }, { hover: false });
    hovered = id;
    map.setFeatureState({ source: "wilayas", id }, { hover: true });
  });
  map.on("mouseleave", "w-fill", () => {
    map.getCanvas().style.cursor = "";
    if (hovered) map.setFeatureState({ source: "wilayas", id: hovered }, { hover: false });
    hovered = null;
  });
  map.on("click", "w-fill", (e) => select(e.features[0].properties.code));
}

/* ─── fire rendering ──────────────────────────────────────────────────── */

/* Drawn as GPU circle layers rather than DOM markers.

   With real FIRMS data this went from 19 mock fires to 238 real ones. Each DOM
   marker carried two CSS-animated pulse rings, so that would have been ~700
   independently animating elements and a map that stutters on the phones most
   people in Algeria actually own. Circle layers render on the GPU and stay
   smooth regardless of count; only the largest fires keep an animated halo. */
function fireGeoJSON() {
  const fires = (S.fires && S.fires.fires) || [];
  return {
    type: "FeatureCollection",
    features: fires
      // Gas flares are flagged upstream; a fire map must not show Hassi Messaoud
      // burning every day next to a village that is genuinely on fire.
      .filter((f) => f.category !== "industrial")
      // And only what is actually still burning. The 48h feed holds hundreds of
      // fires that are already out — drawing them all makes a map of where fire
      // *was*, which is a different and far less useful map.
      .filter((f) => f.active)
      .map((f) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [f.lon, f.lat] },
        properties: {
          id: f.id, frp: f.frp_total || 0, det: f.detections || 0,
          wilaya: f.wilaya || "", growing: f.growing ? 1 : 0,
        },
      })),
  };
}

function addFireLayers() {
  const before = firstSymbolLayer();
  // No promoteId here. MapLibre requires feature ids to be integers (or strings
  // that parse as integers); ours look like "F0126", and pointing promoteId at
  // a non-numeric value makes it drop every feature from the tile index without
  // raising an error — the source holds the data, the map renders nothing.
  // Nothing here uses feature-state, so the id stays an ordinary property.
  map.addSource("fires", { type: "geojson", data: fireGeoJSON() });

  // Radiative power spans four orders of magnitude, so the radius is scaled on
  // sqrt(FRP) — linear scaling would make one fire a blob and hide the rest.
  //
  // The zoom interpolation has to be the OUTERMOST expression: MapLibre rejects
  // a "zoom" expression nested inside anything else ("must be a top-level step
  // or interpolate"). So the glow is built by scaling the stop values, not by
  // multiplying a finished zoom expression.
  const radiusExpr = (scale) => [
    "interpolate", ["linear"], ["zoom"],
    4, ["interpolate", ["linear"], ["sqrt", ["get", "frp"]],
        0, 2.5 * scale, 100, 9 * scale],
    9, ["interpolate", ["linear"], ["sqrt", ["get", "frp"]],
        0, 5 * scale, 100, 22 * scale],
  ];

  map.addLayer({
    id: "fire-glow", type: "circle", source: "fires",
    paint: {
      "circle-radius": radiusExpr(2.6),
      "circle-color": "#E4572E",
      "circle-opacity": 0.20,
      "circle-blur": 1,
    },
  }, before);

  map.addLayer({
    id: "fire-core", type: "circle", source: "fires",
    paint: {
      "circle-radius": radiusExpr(1),
      "circle-color": ["case", ["==", ["get", "growing"], 1], "#F5A623", "#E4572E"],
      "circle-opacity": 0.92,
      "circle-stroke-width": 1,
      "circle-stroke-color": "rgba(255,255,255,.85)",
    },
  }, before);

  map.on("mouseenter", "fire-core", () => { map.getCanvas().style.cursor = "pointer"; });
  map.on("mouseleave", "fire-core", () => { map.getCanvas().style.cursor = ""; });
  map.on("click", "fire-core", (e) => {
    const id = e.features[0].properties.id;
    const f = S.fires.fires.find((x) => x.id === id);
    if (f) selectFire(f);
  });
}

function renderFires() {
  if (!map || !S.fires) return;
  if (!map.getSource("fires")) {
    if (S.showFires) addFireLayers();
    return;
  }
  map.getSource("fires").setData(fireGeoJSON());
  for (const id of ["fire-glow", "fire-core"]) {
    if (map.getLayer(id)) {
      map.setLayoutProperty(id, "visibility", S.showFires ? "visible" : "none");
    }
  }
}

/* ─── day strip ───────────────────────────────────────────────────────── */

function renderDays() {
  const strip = $("dayStrip");
  strip.innerHTML = "";

  S.risk.dates.forEach((iso, i) => {
    const d = new Date(iso + "T12:00:00");
    // The dot shows the worst class anywhere with real fuel that day — the
    // national headline, so the week's shape is legible without clicking.
    let worst = 0;
    for (const code in S.risk.wilayas) {
      const w = S.risk.wilayas[code];
      if (w.fuel === "desert") continue;
      worst = Math.max(worst, CLASS_ORDER.indexOf(w.days[i].class));
    }
    const b = document.createElement("button");
    b.className = "day" + (i === S.day ? " active" : "");
    b.innerHTML =
      '<span class="dow">' + t().dow[d.getDay()] + "</span>" +
      '<span class="dnum">' + num(d.getDate()) + "</span>" +
      '<span class="dot" style="background:' + CLASS_COLOR[CLASS_ORDER[worst]] + '"></span>';
    b.addEventListener("click", () => setDay(i));
    strip.appendChild(b);
  });
}

function setDay(i) {
  S.day = i;
  map.setPaintProperty("w-fill", "fill-color", fillColorExpr(i));
  renderDays();
  renderRiskList();
  if (S.selected) renderDetail(S.selected);
}

/* ─── risk list ───────────────────────────────────────────────────────── */

function renderRiskList() {
  const rows = [];
  for (const f of S.geo.features) {
    const p = f.properties;
    const d = S.risk.wilayas[p.code].days[S.day];
    rows.push({ p, fwi: d.fwi, cls: d.class });
  }
  rows.sort((a, b) => b.fwi - a.fwi);
  const top = rows.slice(0, 10);

  const list = $("riskList");
  list.innerHTML = "";
  for (const r of top) {
    const li = document.createElement("li");
    li.className = "risk" + (S.selected === r.p.code ? " sel" : "");
    const name = S.lang === "ar" ? r.p.name_ar : r.p.name_fr;
    li.innerHTML =
      '<i class="bar" style="background:' + CLASS_COLOR[r.cls] + '"></i>' +
      '<span class="rn"><b>' + name + "</b><span>" + t().cls[r.cls] + "</span></span>" +
      '<span class="rf">' + t().fuel[r.p.fuel] + "</span>" +
      '<span class="rv" style="color:' + CLASS_COLOR[r.cls] + '">' + num(r.fwi.toFixed(0)) + "</span>";
    li.addEventListener("click", () => { select(r.p.code); flyTo(r.p); });
    list.appendChild(li);
  }

  const atRisk = rows.filter((r) => CLASS_ORDER.indexOf(r.cls) >= 3).length;
  $("riskCount").textContent = num(atRisk) + " / " + num(48) + " " + t().wilayas;
}

/* ─── fire stats ──────────────────────────────────────────────────────── */

function renderFireStats() {
  const all = S.fires.fires;
  const veg = all.filter((f) => f.category !== "industrial");
  const fires = veg.filter((f) => f.active);          // still burning
  const industrial = all.length - veg.length;
  const growing = fires.filter((f) => f.is_new).length;   // newly started
  // Satellite hotspots need a NASA FIRMS key. Until one is configured this panel
  // is simulated, and says so — an unlabelled fake fire on a fire map is the one
  // failure this project cannot afford.
  const live = S.fires.source !== "MOCK";
  $("fireStat").innerHTML =
    '<div class="fs hot"><b>' + num(fires.length) + "</b><span>" + t().burningNow + "</span></div>" +
    '<div class="fs"><b>' + num(growing) + "</b><span>" + t().newBadge + "</span></div>" +
    '<div class="fs-src' + (live ? " live" : "") + '">' +
    (live ? t().firesLive : t().firesMock) +
    (industrial ? "<br>" + t().industrialNote.replace("{n}", industrial) : "") + "</div>";
}

/* ─── exposure totals ─────────────────────────────────────────────────── */

/* Thousands separators in the reader's own locale, then Arabic-Indic digits.
   A population figure without grouping is unreadable at a glance, and this
   panel exists to be read at a glance. */
function fmtInt(n) {
  return num(Math.round(n).toLocaleString(t().locale === "ar-DZ" ? "en-US" : "fr-FR"));
}

function renderTotals() {
  const box = $("totals");
  if (!box) return;
  if (!S.exposure) { box.innerHTML = ""; return; }

  const T = S.exposure.totals;
  box.innerHTML =
    '<div class="tot danger"><b>' + fmtInt(T.pop_5km) + "</b>" +
      "<span>" + t().people + "<br>" + t().within5 + " " + t().atRisk + "</span></div>" +
    '<div class="tot warn"><b>' + fmtInt(T.pop_10km) + "</b>" +
      "<span>" + t().people + "<br>" + t().within10 + "</span></div>" +
    '<div class="tot"><b>' + num(T.places_10km) + "</b>" +
      "<span>" + t().villages + "<br>" + t().within10 + "</span></div>";
}

/* ─── fire detail ─────────────────────────────────────────────────────── */

function selectFire(f) {
  S.selected = null;
  safeSetFilter("w-sel", ["==", ["get", "code"], ""]);
  renderRiskList();
  map.flyTo({ center: [f.lon, f.lat], zoom: Math.max(map.getZoom(), 8.5), duration: 900 });
  renderFireDetail(f);
}

function renderFireDetail(f) {
  const e = S.expoById[f.id];
  const w = f.wilaya ? S.geo.features.find((x) => x.properties.code === f.wilaya) : null;
  const wname = w ? (S.lang === "ar" ? w.properties.name_ar : w.properties.name_fr) : "—";

  $("dCode").textContent = t().fireDetail + " · " + f.id;
  $("dName").textContent = wname;
  $("dSub").textContent = (f.satellites || []).join(", ") || "—";

  $("dFwi").textContent = num(Math.round(f.frp_total));
  $("dFwi").style.color = "#ff6b35";
  $("dClass").textContent = "MW";
  $("dClass").style.color = "#ff6b35";

  $("dWeather").innerHTML =
    wxCard(num(f.detections), t().detections) +
    wxCard(num(f.first_seen_h.toFixed(0)) + t().hours, t().detected) +
    wxCard(num(Math.round(f.frp_max)), t().radiative) +
    wxCard(f.growing ? "▲" : "—", t().growing);

  $("dCodes").innerHTML = "";
  document.querySelector(".codes").hidden = true;

  if (!e) {
    $("dFires").innerHTML = '<div class="none">' + t().noRoute + "</div>";
    $("detail").hidden = false;
    return;
  }

  const r5 = e.rings.r5, r10 = e.rings.r10;
  let html = '<div class="expo">';

  html +=
    '<div class="expo-rings">' +
      '<div class="ring-card"><span class="rk">' + t().within5 + "</span>" +
        "<b>" + fmtInt(r5.pop) + "</b><span>" + t().people + " · " +
        num(r5.places) + " " + t().villages + "</span></div>" +
      '<div class="ring-card"><span class="rk">' + t().within10 + "</span>" +
        "<b>" + fmtInt(r10.pop) + "</b><span>" + t().people + " · " +
        num(r10.places) + " " + t().villages + "</span></div>" +
    "</div>";

  if (r5.nearest.length) {
    html += '<div class="df-title">' + t().exposedPlaces + "</div><div class=\"vlist\">";
    for (const p of r5.nearest.slice(0, 6)) {
      html +=
        '<div class="vrow">' +
          '<span class="vd">' + num(p.km.toFixed(1)) + " " + t().km + "</span>" +
          '<span class="vn">' + (p.name || "—") + "</span>" +
          '<span class="vp">' + fmtInt(p.pop) + "</span>" +
        "</div>";
    }
    html += "</div>";
  }

  html += '<div class="resp">';
  if (e.station) {
    const rt = e.station.route;
    html +=
      '<div class="resp-row"><span class="ri">🚒</span>' +
        '<span class="rt"><b>' + (e.station.name || "—") + "</b>" +
        "<span>" + t().nearestStation + "</span></span>" +
        '<span class="rd">' + (rt ? num(rt.min) + " " + t().min : num(e.station.km_direct) + " " + t().km) +
        "<small>" + (rt ? num(rt.km) + " " + t().km + " " + t().driveTime : t().direct) +
        "</small></span></div>";
  }
  if (e.hospital) {
    html +=
      '<div class="resp-row"><span class="ri">🏥</span>' +
        '<span class="rt"><b>' + (e.hospital.name || "—") + "</b>" +
        "<span>" + t().nearestHospital + "</span></span>" +
        '<span class="rd">' + num(e.hospital.km_direct) + " " + t().km +
        "<small>" + t().direct + "</small></span></div>";
  }
  html += "</div>";

  html += '<p class="est">' + t().popEstimate + "</p></div>";

  $("dFires").innerHTML = html;
  $("detail").hidden = false;
}

/* ─── legend ──────────────────────────────────────────────────────────── */

function renderLegend() {
  $("legendScale").innerHTML = CLASS_ORDER.map((c, i) =>
    '<div class="lg"><i style="background:' + CLASS_COLOR[c] + '"></i><span>' +
    (i === 0 ? "0" : num(CLASS_BOUNDS[i])) + "</span></div>"
  ).join("");
}

/* ─── detail drawer ───────────────────────────────────────────────────── */

/* The selected-wilaya outline is decoration. MapLibre throws "Style is not done
   loading" from setFilter during the window between our layers being accepted
   and the style fully settling, and a click in that window must not break the
   app over a highlight. */
/* Keep the detail drawer clear of the map key.

   Both are fixed to the same edge, so the drawer's ceiling depends on how tall
   the key actually renders — which varies with the number of asset layers and
   how the legend wraps at a given width. Measure it rather than guess. */
function layoutPanels() {
  const key = $("mapKey");
  const gap = 18;
  let reserved = 70;
  if (key && key.offsetParent) {
    const r = key.getBoundingClientRect();
    reserved = (window.innerHeight - r.top) + gap;
  }
  document.documentElement.style.setProperty(
    "--detail-max", "calc(100vh - 78px - " + Math.round(reserved) + "px)");
}

window.addEventListener("resize", layoutPanels);

function safeSetFilter(layerId, filter) {
  try {
    if (map && map.getLayer(layerId)) map.setFilter(layerId, filter);
  } catch (err) {
    console.debug("deferred setFilter on " + layerId + ":", err.message);
  }
}

function select(code) {
  S.selected = code;
  safeSetFilter("w-sel", ["==", ["get", "code"], code]);
  renderDetail(code);
  renderRiskList();
}

function flyTo(p) {
  map.fitBounds([[p.bbox[0], p.bbox[1]], [p.bbox[2], p.bbox[3]]], {
    padding: { top: 110, bottom: 130, left: 360, right: 360 }, duration: 900,
  });
}

function renderDetail(code) {
  const feat = S.geo.features.find((f) => f.properties.code === code);
  if (!feat) return;
  document.querySelector(".codes").hidden = false;
  const p = feat.properties;
  const d = S.risk.wilayas[code].days[S.day];

  $("dCode").textContent = t().wilayas.slice(0, 1) + " " + num(p.code);
  $("dName").textContent = S.lang === "ar" ? p.name_ar : p.name_fr;
  $("dSub").textContent = (S.lang === "ar" ? p.name_fr : p.name_ar) + " · " + t().fuel[p.fuel];

  $("dFwi").textContent = num(d.fwi.toFixed(1));
  $("dFwi").style.color = CLASS_COLOR[d.class];
  $("dClass").textContent = t().cls[d.class];
  $("dClass").style.color = CLASS_COLOR[d.class];

  const w = d.weather;
  $("dWeather").innerHTML =
    wxCard(num(w.temp.toFixed(0)) + "°", t().temp) +
    wxCard(num(w.rh.toFixed(0)) + "%", t().rh) +
    wxCard('<span class="arrow" style="transform:rotate(' + (w.wind_dir + 180) + 'deg)">↑</span> ' +
           num(w.wind.toFixed(0)), t().wind + " km/h") +
    wxCard(num(w.rain.toFixed(1)), t().rain + " mm");

  $("dCodes").innerHTML = ["ffmc", "dmc", "dc", "isi", "bui"].map((k) => {
    const pct = Math.min(100, (d[k] / CODE_MAX[k]) * 100);
    return '<div class="code-row">' +
      '<span class="ck">' + k.toUpperCase() + "</span>" +
      '<span class="cbar"><i style="width:' + pct.toFixed(1) + "%;background:" + CLASS_COLOR[d.class] + '"></i></span>' +
      '<span class="cv">' + num(d[k].toFixed(1)) + "</span></div>";
  }).join("");

  const mine = S.fires.fires.filter(
    (f) => f.wilaya === code && f.category !== "industrial" && f.active);
  let html = '<div class="df-title">' + t().firesTitle + "</div>";
  if (!mine.length) {
    html += '<div class="none">' + t().noFires + "</div>";
  } else {
    mine.sort((a, b) => b.frp_total - a.frp_total);
    html += mine.map((f) =>
      '<div class="fire-row"><i class="fdot"></i><span class="fmeta">' +
      "<b>" + f.id + " · " + num(f.frp_total.toFixed(0)) + " MW</b>" +
      num(f.detections) + " " + t().detections + " · " + t().since + " " +
      num(f.first_seen_h.toFixed(0)) + " " + t().hours +
      "</span>" + (f.growing ? '<span class="grow">' + t().growing + "</span>" : "") + "</div>"
    ).join("");
  }
  $("dFires").innerHTML = html;

  $("detail").hidden = false;
}

const wxCard = (v, l) => '<div class="wxc"><b>' + v + "</b><span>" + l + "</span></div>";

/* ─── language ────────────────────────────────────────────────────────── */

function setLang(lang) {
  S.lang = lang;
  const L = t();
  document.documentElement.lang = L.lang;
  document.documentElement.dir = L.dir;
  document.title = L.brand + " — " + L.tagline;

  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const v = L[el.dataset.i18n];
    if (v) el.textContent = v;
  });
  document.querySelectorAll(".lang").forEach((b) =>
    b.classList.toggle("active", b.dataset.lang === lang));

  // The about copy is long-form prose, so both languages live in the HTML and we
  // swap which one is shown rather than rebuilding paragraphs from string keys.
  const ar = document.querySelector(".about-ar");
  const fr = document.querySelector(".about-fr");
  if (ar && fr) { ar.hidden = lang !== "ar"; fr.hidden = lang !== "fr"; }

  stamp();
  renderAppLinks();
  renderTotals();
  if (S.assets && map) {
    renderLayerToggles(map, S.assets, $("layerList"), t().lyr, num);
    S.popLabels = t().lyr;
    S.popText = { people: t().people, unnamed: t().unnamed };
  }
  renderDays();
  renderRiskList();
  renderFireStats();
  renderLegend();
  layoutPanels();
  if (S.selected) renderDetail(S.selected);
}

/* Links to the document pages. The map is an app shell with its own chrome, so
   it gets a compact link row rather than the full site nav. */
const APP_LINKS = [
  { href: "index.html",   ar: "الرئيسية",       fr: "Accueil" },
  { href: "fires.html",   ar: "الحرائق النشطة", fr: "Foyers actifs" },
  { href: "wilayas.html", ar: "الولايات",       fr: "Wilayas" },
  { href: "report.html",  ar: "بلّغ",           fr: "Signaler" },
  { href: "prepare.html", ar: "احمِ نفسك",      fr: "Se protéger" },
];

function renderAppLinks() {
  const box = $("appLinks");
  if (!box) return;
  box.innerHTML = APP_LINKS.map((l) =>
    '<a href="' + l.href + '">' + l[S.lang] + "</a>").join("");
}

function stamp() {
  const dt = new Date(S.risk.generated_at);
  $("updatedAt").textContent = dt.toLocaleString(t().locale, {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
  const live = S.risk.source !== "MOCK";
  $("srcBadge").textContent = live ? "LIVE" : "MOCK";
  $("srcBadge").classList.toggle("live", live);
}

/* ─── boot ────────────────────────────────────────────────────────────── */

/* Prefer the live payload, fall back to the mock. The mock is not a fixture for
   tests — it is what the page shows when the ingestion has never run or has
   fallen over, and the UI labels it as such rather than passing it off as real. */
async function loadJSON(primary, fallback) {
  try {
    const r = await fetch(primary, { cache: "no-store" });
    if (r.ok) return await r.json();
  } catch (e) {
    console.warn("live payload unavailable (" + primary + "), using mock:", e.message);
  }
  return fetch(fallback).then((r) => r.json());
}

/* Two-stage boot.

   The map used to wait on ~1.7 MB — boundaries, risk, fires, exposure and a
   1 MB asset extract — before it drew a single pixel, which meant 15-20 seconds
   of blank loading screen. On Algerian mobile data that reads as a broken site,
   and a fire map nobody waits for is a fire map nobody uses.

   Stage one loads only what the first paint genuinely needs: the basemap style,
   the wilaya polygons and the risk series. The map is interactive from there.
   Stage two streams in fires, exposure and the responder layers afterwards and
   slots them in as each arrives. Nothing in stage two is required to read the
   danger map, so nothing in stage two is allowed to delay it. */
async function boot() {
  const [geo, risk, style] = await Promise.all([
    fetch(dataURL("wilayas.geojson")).then((r) => r.json()),
    loadJSON(dataURL("risk.json"), dataURL("risk.json")),
    darkBasemapStyle(),
  ]);

  // Must precede map creation: the plugin cannot retro-shape labels already drawn.
  await ensureRTLPlugin();
  createMap(style);

  // Flatten the 7-day series onto the polygons so the fill can switch days with
  // a paint-property change instead of re-uploading 600 KB of geometry.
  for (const f of geo.features) {
    const series = risk.wilayas[f.properties.code];
    series.days.forEach((d, i) => { f.properties["fwi_d" + i] = d.fwi; });
  }

  S.geo = geo;
  S.risk = risk;
  S.fires = { source: "MOCK", fires: [] };   // placeholder until stage two lands

  await addLayersWhenReady();
  setLang(S.lang);
  $("loader").classList.add("gone");

  loadSecondary();   // deliberately not awaited
}

async function loadSecondary() {
  try {
    const fires = await loadJSON(dataURL("fires.json"), dataURL("fires.json"));
    S.fires = fires;
    renderFires();
    renderFireStats();
  } catch (err) {
    console.warn("fires unavailable:", err.message);
  }

  try {
    const exposure = await fetch(dataURL("exposure.json")).then((r) => r.json());
    S.exposure = exposure;
    for (const e of exposure.fires) S.expoById[e.id] = e;
    renderTotals();
  } catch (err) {
    console.warn("exposure unavailable:", err.message);
  }

  // Heaviest payload, and the least urgent — always last.
  try {
    const assets = await fetch(dataURL("assets_map.json")).then((r) => r.json());
    S.assets = assets.assets;
    addAssetLayers(map, S.assets, firstSymbolLayer());
    bindAssetPopups(map, () => S.popLabels || {}, fmtInt, () => S.popText || {});
    S.popLabels = t().lyr;
    S.popText = { people: t().people, unnamed: t().unnamed };
    renderLayerToggles(map, S.assets, $("layerList"), t().lyr, num);
    $("mapKey").classList.add("ready");
    layoutPanels();
  } catch (err) {
    console.warn("assets unavailable:", err.message);
  }
}

document.querySelectorAll(".lang").forEach((b) =>
  b.addEventListener("click", () => setLang(b.dataset.lang)));

$("detailClose").addEventListener("click", () => {
  $("detail").hidden = true;
  S.selected = null;
  safeSetFilter("w-sel", ["==", ["get", "code"], ""]);
  renderRiskList();
});

const about = $("about");
$("aboutBtn").addEventListener("click", () => { about.hidden = false; });
$("aboutClose").addEventListener("click", () => { about.hidden = true; });
about.addEventListener("click", (e) => { if (e.target === about) about.hidden = true; });
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!about.hidden) about.hidden = true;
  else if (!$("detail").hidden) $("detailClose").click();
});

$("fireToggle").addEventListener("change", (e) => {
  S.showFires = e.target.checked;
  renderFires();
});

boot().catch((err) => {
  console.error(err);
  $("loader").innerHTML = '<div style="color:#db3b3b">تعذّر تحميل البيانات · ' + err.message + "</div>";
});
