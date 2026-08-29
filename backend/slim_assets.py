"""Derive a browser-sized asset file from the full OSM extract.

The full assets.json (3.5 MB) is the backend's working set — exposure analysis
needs schools, full names and every tag we kept. The browser needs only what it
draws. On Algerian mobile data the difference between 3.5 MB and ~700 KB is the
difference between a map that opens and one that does not.
"""
import json
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DATA = os.path.join(ROOT, "frontend", "data")
SRC = os.path.abspath(os.path.join(ROOT, "data", "work", "assets.json"))
OUT = os.path.join(DATA, "assets_map.json")

# Schools are kept server-side (they matter as potential shelters) but nothing
# renders them, so they are not shipped to the browser.
RENDERED = ["fire_station", "hospital", "place", "water", "aid", "vet"]

# OSM files aid organisations under several unrelated tags; the browser only
# needs one "aid" layer, so they are unioned here rather than in the UI.
MERGED = {"aid": ["aid", "aid_office"]}


def main():
    full = json.load(open(SRC, encoding="utf-8"))
    slim = {}

    for cat in RENDERED:
        sources = MERGED.get(cat, [cat])
        items = []
        for src in sources:
            items.extend(full["assets"].get(src) or [])
        out = []
        for it in items:
            rec = {
                "lat": round(it["lat"], 4),      # ~11 m precision, ample for a dot
                "lon": round(it["lon"], 4),
                "name": it.get("name") or it.get("name_fr") or "",
                "wilaya": it.get("wilaya"),
            }
            if cat == "place":
                rec["pop"] = it.get("pop", 0)
            out.append(rec)
        slim[cat] = out

    json.dump({
        "generated_at": full["generated_at"],
        "source": full["source"],
        "assets": slim,
    }, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

    before = os.path.getsize(SRC) / 1024
    after = os.path.getsize(OUT) / 1024
    print("%s  %.0f KB  ->  %s  %.0f KB  (%.0f%% smaller)"
          % (os.path.basename(SRC), before, os.path.basename(OUT), after,
             100 * (1 - after / before)))
    for cat in RENDERED:
        print("  %-13s %5d" % (cat, len(slim[cat])))


if __name__ == "__main__":
    main()
