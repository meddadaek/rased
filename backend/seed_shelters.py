"""Seed candidate shelters from OpenStreetMap.

An empty shelters page is useless during an emergency, and a coordinator has no
time to type in sixty schools. Algeria's actual practice is to open schools and
youth centres as reception centres when a village is evacuated, so those make
sensible *candidates*.

They are inserted with status 'candidate', never 'open'. This distinction is the
whole point: the platform is saying "this building exists and is the right kind
of place", not "displaced people can sleep here tonight". Only a human who has
checked can promote it — telling a family to drive to a school that is locked is
worse than telling them nothing.

    python seed_shelters.py                 # north-east campaign wilayas
    python seed_shelters.py --wilaya 18     # one wilaya
    python seed_shelters.py --all           # every wilaya with forest fuel
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "app"))

import relief  # noqa: E402
import wilayas as wilayas_ref  # noqa: E402

DATA = os.path.abspath(os.path.join(HERE, "..", "frontend", "data"))
WORK = os.path.abspath(os.path.join(HERE, "..", "data", "work"))

# The wilayas of the 2026 north-east campaign, the same set Hiba covers.
CAMPAIGN = ["18", "06", "43", "21", "23", "36", "24", "19"]

# School buildings and community centres are what actually gets opened.
SOURCE_KINDS = {"school": "school", "aid": "community"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wilaya")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--per-wilaya", type=int, default=12,
                    help="cap per wilaya so the list stays reviewable")
    args = ap.parse_args()

    if args.wilaya:
        codes = [args.wilaya]
    elif args.all:
        codes = [w["code"] for w in wilayas_ref.as_dicts() if w["fuel"] == "forest"]
    else:
        codes = CAMPAIGN

    with open(os.path.join(WORK, "assets.json"), encoding="utf-8") as fh:
        assets = json.load(fh)["assets"]

    relief.configure(os.path.join(HERE, "rased.db"))

    # Do not re-seed something already present: this script may be run again
    # after new OSM data, and duplicating shelters would be worse than useless.
    with relief.db() as conn:
        existing = {(r["name"], r["wilaya"])
                    for r in conn.execute("SELECT name, wilaya FROM shelters")}

    added, skipped = 0, 0
    now = relief.now()

    for code in codes:
        meta = wilayas_ref.BY_CODE.get(code)
        if not meta:
            print("unknown wilaya code:", code)
            continue
        count = 0
        for src, kind in SOURCE_KINDS.items():
            for it in assets.get(src, []):
                if count >= args.per_wilaya:
                    break
                if it.get("wilaya") != code or not it.get("name"):
                    continue
                key = (it["name"], code)
                if key in existing:
                    skipped += 1
                    continue
                existing.add(key)
                with relief.db() as conn:
                    conn.execute(
                        "INSERT INTO shelters (created_at,name,wilaya,commune,address,"
                        "kind,capacity,phone,lat,lon,notes,status)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (now, it["name"], code, None, None, kind, None, None,
                         it.get("lat"), it.get("lon"),
                         "مُقترح تلقائيًا من OpenStreetMap — يحتاج تأكيدًا ميدانيًا",
                         "candidate"))
                added += 1
                count += 1
        print("  %s %-20s +%d" % (code, meta["name_fr"], count))

    print("\nadded %d candidate shelters (%d already present)" % (added, skipped))
    print("All inserted as status='candidate'. A coordinator must confirm a site")
    print("is actually open before it is presented to displaced families.")


if __name__ == "__main__":
    main()
