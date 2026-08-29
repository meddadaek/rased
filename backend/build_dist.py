"""Build a slimmed deployment bundle in dist/.

    python build_dist.py

The working frontend/ directory carries convenience data a live deployment does
not need. This trims it without changing behaviour:

* mock_risk / mock_fires — fallbacks for when the pipeline has never run. A
  deployment always ships with real payloads, so they are dead weight there.
* the `place` layer in assets_map — 9 825 settlements, ~700 KB, powering one
  optional map toggle. Every operational use of place data (which villages are
  near which fire, and their populations) is precomputed server-side into
  exposure.json, so dropping it costs one cosmetic layer and no information.
* coordinate precision — 4 decimal places is ~11 m, far finer than anything
  drawn at these zooms.

Everything else ships intact: all 13 pages, real fire and danger data, the
verified relief records, and the affected-areas list with its satellite verdicts.
"""
import json
import os
import re
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SRC = os.path.join(ROOT, "frontend")
DIST = os.path.join(ROOT, "dist")

DROP_FILES = {"mock_risk.json", "mock_fires.json"}
SHIP_DATA = False
DROP_ASSET_LAYERS = {"place"}

# Wilayas with vegetation that carries fire — the same forest/steppe split the
# danger index uses. Saharan wilayas are excluded from the shipped facility list.
FIRE_PRONE = {
    "02", "04", "05", "06", "09", "10", "12", "13", "14", "15", "16", "18",
    "19", "20", "21", "22", "23", "24", "25", "26", "27", "29", "31", "34",
    "35", "36", "38", "40", "41", "42", "43", "44", "46", "48",
    "03", "07", "17", "28", "32", "45",
}


def simplify_ring(ring, tol):
    """Douglas-Peucker on a closed ring.

    The choropleth is read between zoom 4 and 11, where a wilaya border spans a
    handful of screen pixels. Carrying survey-grade vertices there costs a few
    hundred KB to draw a line nobody can see the detail of. ~330 m of tolerance
    is invisible at these zooms and removes most of the points.
    """
    if len(ring) < 4:
        return ring

    def perp(pt, a, b):
        (x, y), (x1, y1), (x2, y2) = pt[:2], a[:2], b[:2]
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 and dy == 0:
            return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
        t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
        px, py = x1 + t * dx, y1 + t * dy
        return ((x - px) ** 2 + (y - py) ** 2) ** 0.5

    def dp(pts):
        if len(pts) < 3:
            return pts
        dmax, idx = 0.0, 0
        for i in range(1, len(pts) - 1):
            d = perp(pts[i], pts[0], pts[-1])
            if d > dmax:
                dmax, idx = d, i
        if dmax <= tol:
            return [pts[0], pts[-1]]
        return dp(pts[:idx + 1])[:-1] + dp(pts[idx:])

    out = dp(ring[:-1] if ring[0] == ring[-1] else ring)
    # A polygon ring must stay closed and keep enough vertices to have an area.
    if len(out) < 3:
        return ring
    if out[0] != out[-1]:
        out = out + [out[0]]
    return out


def simplify_geometry(geom, tol=0.003):
    if geom["type"] == "Polygon":
        rings = [simplify_ring(r, tol) for r in geom["coordinates"]]
        geom["coordinates"] = [r for r in rings if len(r) >= 4]
    elif geom["type"] == "MultiPolygon":
        polys = []
        for poly in geom["coordinates"]:
            rings = [simplify_ring(r, tol) for r in poly]
            rings = [r for r in rings if len(r) >= 4]
            if rings:
                polys.append(rings)
        geom["coordinates"] = polys
    return geom


def round_coords(obj, dp=4):
    """Recursively round every float. Geometry dominates these files."""
    if isinstance(obj, float):
        return round(obj, dp)
    if isinstance(obj, list):
        return [round_coords(v, dp) for v in obj]
    if isinstance(obj, dict):
        return {k: round_coords(v, dp) for k, v in obj.items()}
    return obj


def main():
    if os.path.exists(DIST):
        shutil.rmtree(DIST)
    os.makedirs(os.path.join(DIST, "data"))

    saved = 0

    # ── static assets, copied verbatim ───────────────────────────────────
    for sub in ("js", "css"):
        shutil.copytree(os.path.join(SRC, sub), os.path.join(DIST, sub))
    for f in os.listdir(SRC):
        if f.endswith(".html"):
            shutil.copy2(os.path.join(SRC, f), os.path.join(DIST, f))

    # The mock fallbacks no longer exist in the bundle, so stop asking for them:
    # a 404 on every page load is slow and looks like a fault in the console.
    for f in os.listdir(DIST):
        if not f.endswith(".html"):
            continue
        p = os.path.join(DIST, f)
        with open(p, encoding="utf-8") as fh:
            s = fh.read()
        s = s.replace('loadJSON("data/risk.json", "data/mock_risk.json")',
                      'loadJSON("data/risk.json", "data/risk.json")')
        s = s.replace('loadJSON("data/fires.json", "data/mock_fires.json")',
                      'loadJSON("data/fires.json", "data/fires.json")')
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(s)

    js = os.path.join(DIST, "js", "common.js")
    with open(js, encoding="utf-8") as fh:
        s = fh.read()
    s = s.replace('return getJSON(null, "data/mock_risk.json");',
                  'throw e;')
    s = s.replace('return getJSON(null, "data/mock_fires.json");',
                  'throw e;')
    with open(js, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(s)

    # ── data ─────────────────────────────────────────────────────────────
    # Production reads its payloads from the CDN (see js/config.js), so the
    # deployed bundle carries code only. That keeps the upload small and, more
    # usefully, decouples data refreshes from deployments.
    if SHIP_DATA:
      for f in sorted(os.listdir(os.path.join(SRC, "data"))):
          src = os.path.join(SRC, "data", f)
          if not os.path.isfile(src):
              continue
          before = os.path.getsize(src)

          if f in DROP_FILES:
              saved += before
              print("  dropped   %-22s %6.0f KB" % (f, before / 1024))
              continue

          with open(src, encoding="utf-8") as fh:
              data = json.load(fh)

          if f == "wilayas.geojson":
              before_pts = sum(len(r) for ft in data["features"]
                               for r in (ft["geometry"]["coordinates"]
                                         if ft["geometry"]["type"] == "Polygon"
                                         else [x for p in ft["geometry"]["coordinates"] for x in p]))
              for ft in data["features"]:
                  simplify_geometry(ft["geometry"])
              after_pts = sum(len(r) for ft in data["features"]
                              for r in (ft["geometry"]["coordinates"]
                                        if ft["geometry"]["type"] == "Polygon"
                                        else [x for p in ft["geometry"]["coordinates"] for x in p]))
              print("            geometry: %d -> %d rings kept" % (before_pts, after_pts))

          if f == "assets_map.json":
              for layer in DROP_ASSET_LAYERS:
                  data["assets"].pop(layer, None)
              # Facilities only where forest fires actually happen. A clinic in
              # Tamanrasset is real, but this is a wildfire tool and the Sahara is
              # fuel-masked out of every other layer for the same reason.
              keep = FIRE_PRONE
              for k, items in list(data["assets"].items()):
                  data["assets"][k] = [a for a in items if a.get("wilaya") in keep]

          if f == "exposure.json":
              # place_ids exists so the pipeline can deduplicate national totals.
              # The browser never reads it, and it is thousands of strings.
              for e in data.get("fires", []):
                  for ring in e.get("rings", {}).values():
                      ring.pop("place_ids", None)

          data = round_coords(data)
          out = os.path.join(DIST, "data", f)
          with open(out, "w", encoding="utf-8") as fh:
              json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))

          after = os.path.getsize(out)
          saved += before - after
          flag = "  trimmed" if after < before * 0.95 else "  copied "
          print("%s %-22s %6.0f KB -> %6.0f KB" % (flag, f, before / 1024, after / 1024))

    total = sum(os.path.getsize(os.path.join(r, f))
                for r, _, fs in os.walk(DIST) for f in fs)
    print("\ndist/ total: %.0f KB (saved %.0f KB)" % (total / 1024, saved / 1024))
    print("dropped layers: %s — every operational use is precomputed in exposure.json"
          % ", ".join(DROP_ASSET_LAYERS))


if __name__ == "__main__":
    main()
