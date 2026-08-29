/* ─── responder + settlement layers ───────────────────────────────────────
   Real OpenStreetMap data: Protection Civile units, hospitals, populated
   places, reservoirs. These are what make the map operational rather than
   merely informative — a danger index says a wilaya is dangerous, these say
   who is in the way and who can reach them.
   ───────────────────────────────────────────────────────────────────────── */

const ASSET_STYLE = {
  fire_station: { color: "#4da3ff", radius: 4.5, minzoom: 5.5, on: true },
  hospital:     { color: "#ff8fa3", radius: 3.5, minzoom: 7.0, on: false },
  place:        { color: "#cfc3b6", radius: 2.2, minzoom: 7.5, on: false },
  water:        { color: "#3fd0d6", radius: 3.5, minzoom: 7.0, on: false },
};

const ASSET_ORDER = ["fire_station", "hospital", "place", "water"];

function assetGeoJSON(items) {
  return {
    type: "FeatureCollection",
    features: items.map((it) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [it.lon, it.lat] },
      properties: {
        name: it.name || it.name_fr || "",
        pop: it.pop || 0,
        wilaya: it.wilaya || "",
      },
    })),
  };
}

function addAssetLayers(map, assets, before) {
  for (const key of ASSET_ORDER) {
    const items = assets[key];
    if (!items || !items.length) continue;
    const st = ASSET_STYLE[key];

    map.addSource("a-" + key, { type: "geojson", data: assetGeoJSON(items) });

    map.addLayer({
      id: "a-" + key,
      type: "circle",
      source: "a-" + key,
      minzoom: st.minzoom,
      layout: { visibility: st.on ? "visible" : "none" },
      paint: {
        // Grow the dots with zoom so they stay findable when zoomed out and
        // become individually clickable when zoomed in.
        "circle-radius": [
          "interpolate", ["linear"], ["zoom"],
          st.minzoom, st.radius * 0.7,
          11, st.radius * 2.0,
        ],
        "circle-color": st.color,
        "circle-opacity": 0.9,
        "circle-stroke-width": 1,
        "circle-stroke-color": "rgba(10,9,8,0.85)",
      },
    }, before);
  }
}

/* Make the dots answer for themselves.

   A coloured dot with no affordance is just noise — the reader cannot tell what
   it is or click it to find out. Every asset layer gets a cursor, a hover state
   and a popup naming the facility, so "what is the blue dot" is answerable by
   clicking it rather than by reading documentation. */
function bindAssetPopups(map, getLabels, fmtNum, getText) {
  for (const key of ASSET_ORDER) {
    const id = "a-" + key;
    if (!map.getLayer(id)) continue;
    const st = ASSET_STYLE[key];

    map.on("mouseenter", id, () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", id, () => { map.getCanvas().style.cursor = ""; });

    map.on("click", id, (e) => {
      const f = e.features && e.features[0];
      if (!f) return;
      const p = f.properties || {};

      const labels = getLabels();
      const popText = getText();
      let meta = "";
      if (key === "place" && p.pop) {
        meta = "<div class=\"pop-meta\">" + popText.people + ": <b>" + fmtNum(p.pop) + "</b></div>";
      }

      const html =
        '<div class="pop-kind"><i style="background:' + st.color + '"></i>' +
        (labels[key] || key) + "</div>" +
        '<div class="pop-name">' + (p.name || popText.unnamed) + "</div>" + meta;

      new maplibregl.Popup({ offset: 12, closeButton: true, maxWidth: "260px" })
        .setLngLat(e.lngLat)
        .setHTML(html)
        .addTo(map);
    });
  }
}

function setAssetVisible(map, key, on) {
  const id = "a-" + key;
  if (map.getLayer(id)) {
    map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
  }
}

function renderLayerToggles(map, assets, container, labels, fmtNum) {
  container.innerHTML = "";
  for (const key of ASSET_ORDER) {
    const items = assets[key];
    if (!items || !items.length) continue;
    const st = ASSET_STYLE[key];

    const lab = document.createElement("label");
    lab.className = "lay";
    lab.innerHTML =
      '<input type="checkbox"' + (st.on ? " checked" : "") + ">" +
      '<i class="swatch" style="background:' + st.color + '"></i>' +
      '<span class="lname">' + (labels[key] || key) + "</span>" +
      '<span class="lcount">' + fmtNum(items.length) + "</span>" +
      '<span class="chk">✓</span>';

    lab.querySelector("input").addEventListener("change", (e) => {
      st.on = e.target.checked;
      setAssetVisible(map, key, st.on);
    });
    container.appendChild(lab);
  }
}
