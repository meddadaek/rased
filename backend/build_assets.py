"""Pull responder assets and populated places from OpenStreetMap.

    python build_assets.py                 # all categories
    python build_assets.py --only place    # one category

Writes frontend/data/assets.json. Run rarely — this data changes on the scale of
months, and Overpass is a free community service.
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))

import firms  # noqa: E402  - reuse the point-in-polygon wilaya locator
import osm  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
GEO = os.path.join(ROOT, "frontend", "data", "wilayas.geojson")
OUT = os.path.join(ROOT, "data", "work", "assets.json")

ORDER = ["fire_station", "hospital", "place", "school", "water", "aid", "aid_office", "vet"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=ORDER, help="fetch a single category")
    args = ap.parse_args()

    geo = json.load(open(GEO, encoding="utf-8"))
    locate = firms.build_locator(geo)

    existing = {}
    if os.path.exists(OUT):
        existing = json.load(open(OUT, encoding="utf-8")).get("assets", {})

    cats = [args.only] if args.only else ORDER
    assets = dict(existing)

    for cat in cats:
        print("fetching %s ..." % cat, flush=True)
        try:
            items = osm.fetch_category(cat)
        except Exception as exc:  # noqa: BLE001
            print("  FAILED: %s" % exc)
            continue

        # An empty category is almost always a transient Overpass failure (an
        # overloaded mirror answers 200 with zero elements and no remark), not a
        # country that genuinely has no fire stations. Never let that silently
        # overwrite good data already on disk.
        if not items:
            print("  EMPTY result - treating as failure, keeping previous data")
            continue

        for it in items:
            it["wilaya"] = locate(it["lat"], it["lon"])
        # Drop anything that fell outside Algeria - the bbox overlaps Tunisia,
        # Morocco and the sea, and a Tunisian fire station is not our responder.
        items = [it for it in items if it["wilaya"]]

        assets[cat] = items
        print("  %d kept (inside Algeria)" % len(items))

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "source": "openstreetmap-overpass",
        "bbox": osm.NORTH,
        "assets": assets,
    }
    json.dump(payload, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)

    print("\nwrote %s (%.0f KB)" % (OUT, os.path.getsize(OUT) / 1024))
    for cat in ORDER:
        if cat in assets:
            print("  %-13s %5d" % (cat, len(assets[cat])))

    if "place" in assets:
        pop = sum(p.get("pop", 0) for p in assets["place"])
        est = sum(1 for p in assets["place"] if p.get("pop_est"))
        print("\npopulated places: %d, total tagged+estimated population %s"
              % (len(assets["place"]), "{:,}".format(pop)))
        print("  %d of them use an estimated population (no OSM tag)" % est)


if __name__ == "__main__":
    main()
