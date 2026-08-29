/* ─── shared route map ────────────────────────────────────────────────────
   An embedded map with "where am I" and "draw me the road to that place".

   Used by the shelters page and the associations page. Handing someone an
   openstreetmap.org link was the wrong answer: it drops them onto a different
   site, loses the context they came for, and on a phone often opens a browser
   tab rather than anything useful. The route is drawn here instead.

   Location handling, stated plainly because it matters in a disaster zone:
   position is requested only when the user presses the button, is used only in
   the browser to measure distance and ask OSRM for a road route, and is never
   sent to the Rased server or stored anywhere.
   ───────────────────────────────────────────────────────────────────────── */

const OSRM = "https://router.project-osrm.org/route/v1/driving";

function createRouteMap(opts) {
  const state = {
    map: null,
    here: null,
    hereMarker: null,
    destMarker: null,
    pickMode: false,
    onLocate: opts.onLocate || function () {},
    onRoute: opts.onRoute || function () {},
    hintEl: document.getElementById(opts.hintId),
    infoEl: document.getElementById(opts.infoId),
  };

  async function init(style) {
    state.map = new maplibregl.Map({
      container: opts.container,
      style,
      center: opts.center || [5.9, 36.6],
      zoom: opts.zoom || 7.4,
      attributionControl: false,
    });
    state.map.addControl(new maplibregl.NavigationControl({ showCompass: false }),
                         "bottom-right");

    // MapLibre only watches window resizes; a container that changes size on its
    // own (a pane, a collapsing phone URL bar) otherwise keeps a stale canvas.
    if (typeof ResizeObserver !== "undefined") {
      new ResizeObserver(() => state.map.resize()).observe(state.map.getContainer());
    }

    state.map.on("click", (e) => {
      if (!state.pickMode) return;
      state.pickMode = false;
      setHere(e.lngLat.lat, e.lngLat.lng);
    });

    return state.map;
  }

  /* Run a function that adds sources/layers, retrying until the style accepts it.

     Checking getStyle().layers.length is NOT sufficient: addSource calls
     MapLibre's _checkLoaded(), which requires style.loaded() — a different and
     later condition. Gating on the first and then calling the second throws
     "Style is not done loading". Rather than guess which predicate is the right
     one, attempt the actual operation and retry on failure; the thing we care
     about is whether the layer went on. */
  async function whenReady(fn, maxMs) {
    const started = Date.now();
    let lastErr = null;
    for (;;) {
      try {
        return fn();
      } catch (err) {
        lastErr = err;
      }
      if (Date.now() - started > (maxMs || 20000)) {
        throw new Error("map style never became ready" +
          (lastErr ? ": " + lastErr.message : ""));
      }
      await new Promise((r) => setTimeout(r, 90));
    }
  }

  function hint(txt) { if (state.hintEl) state.hintEl.textContent = txt; }

  function setHere(lat, lon) {
    state.here = { lat, lon };
    if (state.hereMarker) state.hereMarker.remove();
    const el = document.createElement("div");
    el.className = "herepin";
    el.title = opts.hereLabel || "";
    state.hereMarker = new maplibregl.Marker({ element: el })
      .setLngLat([lon, lat]).addTo(state.map);
    state.map.flyTo({ center: [lon, lat],
                      zoom: Math.max(state.map.getZoom(), 10), duration: 800 });
    state.onLocate(state.here);
  }

  function locateMe(onFail) {
    if (!navigator.geolocation) { if (onFail) onFail("unsupported"); return; }
    hint("…");
    navigator.geolocation.getCurrentPosition(
      (pos) => setHere(pos.coords.latitude, pos.coords.longitude),
      () => { if (onFail) onFail("denied"); },
      { enableHighAccuracy: true, timeout: 10000 });
  }

  function pick(hintText) { state.pickMode = true; hint(hintText); }

  async function route(dest, labels) {
    if (!state.here) return { error: "no-origin" };
    if (state.infoEl) state.infoEl.textContent = "…";

    let r;
    try {
      const res = await fetch(OSRM + "/" + state.here.lon + "," + state.here.lat +
        ";" + dest.lon + "," + dest.lat + "?overview=full&geometries=geojson");
      const d = await res.json();
      if (d.code !== "Ok" || !d.routes.length) throw new Error("no route");
      r = d.routes[0];
    } catch (e) {
      return { error: "no-route" };
    }

    const data = { type: "Feature", geometry: r.geometry, properties: {} };
    if (state.map.getSource("route")) {
      state.map.getSource("route").setData(data);
    } else {
      state.map.addSource("route", { type: "geojson", data });
      state.map.addLayer({ id: "route-glow", type: "line", source: "route",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#E4572E", "line-width": 11,
                 "line-opacity": 0.20, "line-blur": 3 } });
      state.map.addLayer({ id: "route-line", type: "line", source: "route",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#E4572E", "line-width": 3.5 } });
    }

    if (state.destMarker) state.destMarker.remove();
    const el = document.createElement("div");
    el.className = "destpin";
    el.textContent = dest.icon || "📍";
    state.destMarker = new maplibregl.Marker({ element: el })
      .setLngLat([dest.lon, dest.lat]).addTo(state.map);

    const cs = r.geometry.coordinates;
    const lons = cs.map((c) => c[0]), lats = cs.map((c) => c[1]);
    state.map.fitBounds([[Math.min(...lons), Math.min(...lats)],
                         [Math.max(...lons), Math.max(...lats)]],
                        { padding: 60, duration: 900 });

    const out = { km: +(r.distance / 1000).toFixed(1),
                  min: Math.round(r.duration / 60), name: dest.name };
    if (state.infoEl && labels) {
      state.infoEl.innerHTML = "<b>" + dest.name + "</b> — " +
        '<b style="color:var(--ember)">' + out.min + " " + labels.min + "</b> · " +
        out.km + " " + labels.km + " " + labels.by;
    }
    state.onRoute(out);
    state.map.getContainer().scrollIntoView({ behavior: "smooth", block: "center" });
    return out;
  }

  function clearRoute() {
    for (const id of ["route-line", "route-glow"]) {
      if (state.map.getLayer(id)) state.map.removeLayer(id);
    }
    if (state.map.getSource("route")) state.map.removeSource("route");
    if (state.destMarker) { state.destMarker.remove(); state.destMarker = null; }
    if (state.infoEl) state.infoEl.textContent = "";
  }

  return {
    init, whenReady, setHere, locateMe, pick, route, clearRoute, hint,
    get map() { return state.map; },
    get here() { return state.here; },
  };
}

/* Great-circle distance, for "which of these is nearest" before asking OSRM for
   a road answer on just the winner. */
function kmBetween(lat1, lon1, lat2, lon2) {
  const p = Math.PI / 180;
  const a = Math.sin((lat2 - lat1) * p / 2) ** 2 +
            Math.cos(lat1 * p) * Math.cos(lat2 * p) * Math.sin((lon2 - lon1) * p / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(a));
}

/* Trust badge shared by every page that shows public submissions. */
function trustBadge(trust, L) {
  const map = {
    verified:  ["badge-open", L.trustVerified],
    confirmed: ["badge-conf", L.trustConfirmed],
    disputed:  ["badge-disp", L.trustDisputed],
    reported:  ["badge-cand", L.trustReported],
  };
  const [cls, txt] = map[trust] || map.reported;
  return '<span class="' + cls + '">' + txt + "</span>";
}
