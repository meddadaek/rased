"""Join active fires to people and responders.

    python build_exposure.py            # uses live fires.json if present, else mock
    python build_exposure.py --no-route # skip OSRM (faster, no network courtesy wait)

Writes frontend/data/exposure.json.
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))

import exposure  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DATA = os.path.join(ROOT, "frontend", "data")


def load_fires():
    live = os.path.join(DATA, "fires.json")
    mock = os.path.join(DATA, "mock_fires.json")
    path = live if os.path.exists(live) else mock
    payload = json.load(open(path, encoding="utf-8"))
    return payload, os.path.basename(path)


def totals(exps):
    """National figures, deduplicated.

    Summing each fire's exposed population double-counts every village that sits
    near more than one front — and during a bad week in Kabylie that is most of
    them. The national number has to be a union over places, not a sum over
    fires. Per-fire figures stay as they are: there, the overlap is the point.
    """
    seen5, seen10 = {}, {}
    for e in exps:
        for ids, store in ((e["rings"]["r5"].get("place_ids", []), seen5),
                           (e["rings"]["r10"].get("place_ids", []), seen10)):
            for pid in ids:
                store[pid] = True

    # Recover each unique place's contribution from the per-fire records,
    # keeping the largest share any single fire attributed to it.
    best5, best10 = {}, {}
    for e in exps:
        for key, ring, best in (("r5", e["rings"]["r5"], best5),
                                ("r10", e["rings"]["r10"], best10)):
            ids = ring.get("place_ids", [])
            if not ids:
                continue
            share = ring["pop"] / len(ids)
            for pid in ids:
                best[pid] = max(best.get(pid, 0), share)

    return {
        "fires": len(exps),
        "growing": sum(1 for e in exps if e.get("growing")),
        "pop_5km": int(round(sum(best5.values()))),
        "pop_10km": int(round(sum(best10.values()))),
        "places_5km": len(seen5),
        "places_10km": len(seen10),
        "routed": sum(1 for e in exps if e.get("station", {}).get("route")),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-route", action="store_true")
    args = ap.parse_args()

    fires_payload, which = load_fires()
    assets = json.load(open(os.path.join(ROOT, "data", "work", "assets.json"), encoding="utf-8"))["assets"]

    all_fires = fires_payload["fires"]
    # Gas flares are real heat but not wildfires, and nobody needs an evacuation
    # analysis for Hassi Messaoud. They stay in fires.json, flagged; they just do
    # not belong in an exposure report.
    fires = [f for f in all_fires if f.get("category") != "industrial"]
    skipped = len(all_fires) - len(fires)
    print("fires: %d of %d (from %s, source=%s); %d industrial heat sources excluded"
          % (len(fires), len(all_fires), which, fires_payload.get("source"), skipped))
    print("assets: %s" % ", ".join("%s=%d" % (k, len(v)) for k, v in assets.items()))

    def progress(done, total):
        if done % 5 == 0 or done == total:
            print("  analysed %d/%d" % (done, total), flush=True)

    exps = exposure.analyse(fires, assets, route=not args.no_route, progress=progress)
    agg = exposure.by_wilaya(exps)

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "fires_source": fires_payload.get("source"),
        "rings_km": exposure.RINGS_KM,
        "fires": exps,
        "by_wilaya": agg,
        "totals": totals(exps),
    }

    out = os.path.join(DATA, "exposure.json")
    json.dump(payload, open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print("\nwrote %s (%.0f KB)" % (out, os.path.getsize(out) / 1024))

    tot = payload["totals"]
    print("\nTOTALS  fires=%d growing=%d  people within 5km=%s  within 10km=%s  routed=%d"
          % (tot["fires"], tot["growing"], "{:,}".format(tot["pop_5km"]),
             "{:,}".format(tot["pop_10km"]), tot["routed"]))

    print("\nmost exposed fires:")
    for e in sorted(exps, key=lambda x: x["rings"]["r5"]["pop"], reverse=True)[:8]:
        st = e.get("station") or {}
        route = st.get("route")
        drive = ("%s km / %s min" % (route["km"], route["min"])) if route else "-"
        near = e["rings"]["r5"]["nearest"]
        print("  %s w=%s  %6s people <5km (%d places)  station: %-26s %s"
              % (e["id"], e["wilaya"], "{:,}".format(e["rings"]["r5"]["pop"]),
                 e["rings"]["r5"]["places"], (st.get("name") or "-")[:26], drive))
        if near:
            print("        closest: " + ", ".join("%s (%.1f km)" % (p["name"], p["km"])
                                                  for p in near[:3]))


if __name__ == "__main__":
    main()
