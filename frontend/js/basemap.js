/* ─── basemap ─────────────────────────────────────────────────────────────
   OpenFreeMap "positron": community-run, ODbL, no key, no signup, no rate
   limit. CARTO now demands an API key and Esri's free endpoints sit in a
   licensing grey zone, neither of which is acceptable for something that has
   to keep working without a billing relationship.

   Positron is already a light, low-contrast style, which is exactly what this
   map needs: the basemap is context, and the fires are the message. Rather
   than restyling it, we mute it slightly further and force the background to
   match the page, so nothing on the basemap competes with a fire marker.
   ───────────────────────────────────────────────────────────────────────── */

const OFM_STYLE = "https://tiles.openfreemap.org/styles/positron";

const PAGE_BG = "#F4F7F5";

/* If OpenFreeMap is unreachable the map still has to draw: the country
   polygons carry the product, so degrading to "no basemap" is survivable
   where degrading to "no map" is not. */
const FALLBACK_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": PAGE_BG } }],
};

async function basemapStyle() {
  let style;
  try {
    const res = await fetch(OFM_STYLE);
    if (!res.ok) throw new Error("HTTP " + res.status);
    style = await res.json();
  } catch (err) {
    console.warn("OpenFreeMap unavailable, falling back to a plain canvas:", err.message);
    return structuredClone(FALLBACK_STYLE);
  }

  for (const layer of style.layers || []) {
    if (layer.type === "background" && layer.paint) {
      // Key the basemap's ground to the page background so the map does not
      // read as a separate rectangle pasted onto the page.
      layer.paint["background-color"] = PAGE_BG;
      continue;
    }
    if (!layer.paint) continue;

    // Push the basemap back a step. Anything still fully opaque here would sit
    // at the same visual weight as the data drawn on top of it.
    if (layer.type === "fill" && layer.paint["fill-opacity"] === undefined) {
      layer.paint["fill-opacity"] = 0.75;
    }
    if (layer.type === "line" && layer.paint["line-opacity"] === undefined) {
      layer.paint["line-opacity"] = 0.55;
    }
    if (layer.type === "symbol") {
      layer.paint["text-opacity"] = 0.78;
      if (layer.paint["text-halo-width"] === undefined) {
        layer.paint["text-halo-width"] = 1.2;
      }
    }
  }

  return style;
}

/* The map page and the report page both loaded this under the old name while
   the theme was dark. Keeping the alias avoids a rename across pages for no
   behavioural gain. */
const darkBasemapStyle = basemapStyle;
