"""Join the wilaya reference table onto the geoBoundaries polygons.

Produces frontend/data/wilayas.geojson - one feature per wilaya carrying its official
code, Arabic/French names, fuel class and a representative point for weather sampling.
Run once; the output is committed.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))
import wilayas  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "data", "dza_adm1.geojson")
OUT = os.path.join(ROOT, "frontend", "data", "wilayas.geojson")


def ring_centroid(ring):
    """Area-weighted centroid of a closed ring via the shoelace formula.

    Falls back to the mean vertex when the ring is degenerate (zero area).
    """
    a = cx = cy = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[i + 1][0], ring[i + 1][1]
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(a) < 1e-12:
        n = max(len(ring) - 1, 1)
        return [sum(p[0] for p in ring[:-1]) / n, sum(p[1] for p in ring[:-1]) / n]
    a *= 0.5
    return [cx / (6 * a), cy / (6 * a)]


def ring_area(ring):
    a = 0.0
    for i in range(len(ring) - 1):
        a += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return abs(a) * 0.5


def outer_rings(geom):
    """Yield every outer ring, whether the feature is a Polygon or a MultiPolygon."""
    if geom["type"] == "Polygon":
        yield geom["coordinates"][0]
    elif geom["type"] == "MultiPolygon":
        for poly in geom["coordinates"]:
            yield poly[0]


def representative_point(geom):
    """Centroid of the single largest outer ring.

    Using the largest ring rather than an average over all of them keeps the point
    inside the mainland for coastal wilayas that also own small offshore islands.
    """
    rings = sorted(outer_rings(geom), key=ring_area, reverse=True)
    return ring_centroid(rings[0])


def bbox(geom):
    xs, ys = [], []
    for ring in outer_rings(geom):
        for p in ring:
            xs.append(p[0])
            ys.append(p[1])
    return [min(xs), min(ys), max(xs), max(ys)]


def main():
    src = json.load(open(SRC, encoding="utf-8"))
    out, missing = [], []

    for feat in src["features"]:
        name = feat["properties"].get("shapeName", "")
        meta = wilayas.lookup(name)
        if not meta:
            missing.append(name)
            continue
        pt = representative_point(feat["geometry"])
        out.append({
            "type": "Feature",
            "geometry": feat["geometry"],
            "properties": {
                **meta,
                "lon": round(pt[0], 4),
                "lat": round(pt[1], 4),
                "bbox": [round(v, 4) for v in bbox(feat["geometry"])],
            },
        })

    if missing:
        raise SystemExit("unmatched wilayas in boundary file: %s" % missing)
    if len(out) != 48:
        raise SystemExit("expected 48 wilayas, joined %d" % len(out))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": out}, fh, ensure_ascii=False)

    print("wrote %s (%d features, %.0f KB)" % (OUT, len(out), os.path.getsize(OUT) / 1024))
    for f in out[:3]:
        p = f["properties"]
        print("  %s %-18s %-14s fuel=%-6s pt=(%.3f, %.3f)"
              % (p["code"], p["name_latin"], p["name_ar"], p["fuel"], p["lon"], p["lat"]))


if __name__ == "__main__":
    main()
