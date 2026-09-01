"""Current Algerian wilaya boundaries, from OpenStreetMap.

Why this exists: every downloadable ADM1 boundary set for Algeria — geoBoundaries,
GADM, Natural Earth and the various GeoJSON mirrors — still ships the pre-2019
48-wilaya geometry. Algeria has been administered differently since 2021, and a
fire map for an Algerian audience that cannot name the wilaya a fire is in, or
names the wrong one, is not credible.

OSM maps 69 relations at admin_level=4, which is what the country actually runs
on today:

  01-48  the historic wilayas
  49-58  the ten southern wilayas promoted from delegated status in 2021
  59-69  the circonscriptions administratives created in the same reform —
         Aflou, Barika, El Kantara, Bir El Ater, El Aricha, Ksar Chellala,
         Aïn Oussara, Messaad, Ksar El Boukhari, Bou Saâda and El Abiodh Sidi
         Cheikh — which are administered at wilaya level.

Overpass is free, keyless and rate-limited by courtesy, so this is a
run-it-once script whose output is committed, not something the site calls.

Usage:  python backend/fetch_wilayas_osm.py
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "dza_adm1_osm.geojson")

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

QUERY = """
[out:json][timeout:600];
area["ISO3166-1"="DZ"][admin_level=2]->.dz;
rel(area.dz)["admin_level"="4"]["boundary"="administrative"];
out geom;
"""


def overpass(query):
    """Try each mirror in turn. Overpass instances go busy rather than down, so
    a failure on one is routine and not a reason to give up."""
    last = None
    for url in ENDPOINTS:
        for attempt in range(2):
            try:
                print("  querying %s (attempt %d)..." % (url.split("/")[2], attempt + 1))
                req = urllib.request.Request(
                    url, data=query.encode("utf-8"),
                    headers={"User-Agent": "rased/1.0 (wildfire monitoring, Algeria)"})
                with urllib.request.urlopen(req, timeout=620) as r:
                    raw = r.read()
                print("  received %.1f MB" % (len(raw) / 1e6))
                return json.loads(raw.decode("utf-8"))
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
                last = exc
                print("  failed: %s" % exc)
                time.sleep(6)
    raise SystemExit("every Overpass mirror failed: %s" % last)


def assemble_rings(members):
    """Stitch a relation's outer ways into closed rings.

    OSM stores a boundary as an unordered pile of way fragments whose direction
    is arbitrary. Walking them means repeatedly finding a fragment that starts
    or ends where the current ring left off, flipping it if needed. Fragments
    that never close are kept anyway — a coastline traced in pieces is still
    better than dropping the wilaya.
    """
    segments = []
    for m in members:
        if m.get("type") != "way" or m.get("role") not in ("outer", ""):
            continue
        geom = m.get("geometry")
        if not geom or len(geom) < 2:
            continue
        segments.append([[p["lon"], p["lat"]] for p in geom])

    rings, pool = [], list(segments)
    while pool:
        ring = pool.pop(0)
        joined = True
        while joined and ring[0] != ring[-1]:
            joined = False
            for i, seg in enumerate(pool):
                if seg[0] == ring[-1]:
                    ring.extend(seg[1:]); pool.pop(i); joined = True; break
                if seg[-1] == ring[-1]:
                    ring.extend(list(reversed(seg))[1:]); pool.pop(i); joined = True; break
                if seg[-1] == ring[0]:
                    ring = seg[:-1] + ring; pool.pop(i); joined = True; break
                if seg[0] == ring[0]:
                    ring = list(reversed(seg))[:-1] + ring; pool.pop(i); joined = True; break
        if ring[0] != ring[-1]:
            ring.append(ring[0])           # force closure; a sliver beats a hole
        if len(ring) >= 4:
            rings.append(ring)
    return rings


def ring_area(ring):
    """Unsigned shoelace area, used only to rank rings by size."""
    a = 0.0
    for i in range(len(ring) - 1):
        a += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return abs(a) / 2.0


def main():
    print("fetching Algerian wilaya boundaries from OpenStreetMap")
    data = overpass(QUERY)
    elements = data.get("elements", [])
    print("  %d relations returned" % len(elements))

    features, skipped = [], []
    for el in elements:
        tags = el.get("tags", {})
        ref = (tags.get("ref") or "").strip()
        name = tags.get("name:en") or tags.get("name") or ""
        if not ref:
            skipped.append(name or el.get("id"))
            continue

        rings = assemble_rings(el.get("members", []))
        if not rings:
            skipped.append(name)
            continue
        rings.sort(key=ring_area, reverse=True)

        # Largest ring is the wilaya; the rest are islands or exclaves, kept as
        # separate polygons rather than merged or discarded.
        geometry = ({"type": "Polygon", "coordinates": [rings[0]]} if len(rings) == 1
                    else {"type": "MultiPolygon",
                          "coordinates": [[r] for r in rings]})

        features.append({
            "type": "Feature",
            "properties": {
                "code": ref.zfill(2),
                "osm_id": el.get("id"),
                "name_en": name,
                "name_ar": tags.get("name:ar", ""),
                "name_fr": tags.get("name:fr") or name,
            },
            "geometry": geometry,
        })

    features.sort(key=lambda f: f["properties"]["code"])
    if skipped:
        print("  skipped (no ref or no geometry): %s" % ", ".join(str(s) for s in skipped))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": features},
                  fh, ensure_ascii=False)

    size = os.path.getsize(OUT) / 1e6
    print("wrote %s (%.1f MB, %d wilayas)" % (OUT, size, len(features)))
    codes = [f["properties"]["code"] for f in features]
    missing = [("%02d" % i) for i in range(1, 70) if ("%02d" % i) not in codes]
    if missing:
        print("  MISSING codes: %s" % ", ".join(missing))
    else:
        print("  all 69 wilaya-level entities present")


if __name__ == "__main__":
    main()
