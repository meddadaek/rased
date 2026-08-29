"""Build the live risk payload: real weather -> real FWI, for all 48 wilayas.

    python pipeline.py            # writes frontend/data/risk.json
    python pipeline.py --dry      # fetch and compute, write nothing

The moisture codes are integrated across the entire returned history before any
output day is emitted. That spin-up is the whole reason the numbers mean
anything: FFMC reacts in under a day, but DMC has a ~12 day memory and DC a ~52
day one, so the drought state on 29 August is a consequence of June and July.
Starting the chain today would report a rain-soaked forest in the middle of a
two-month drought.
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))

import fwi  # noqa: E402
import weather  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
GEO = os.path.join(ROOT, "frontend", "data", "wilayas.geojson")
OUT = os.path.join(ROOT, "frontend", "data", "risk.json")

OUTPUT_DAYS = 7
MIN_SPINUP_DAYS = 30


def load_locations():
    geo = json.load(open(GEO, encoding="utf-8"))
    return [
        {
            "code": f["properties"]["code"],
            "lat": f["properties"]["lat"],
            "lon": f["properties"]["lon"],
            "fuel": f["properties"]["fuel"],
            "name_ar": f["properties"]["name_ar"],
            "name_fr": f["properties"]["name_fr"],
        }
        for f in geo["features"]
    ]


def run_chain(series):
    """Integrate the FWI chain across the full series; return per-day results."""
    state = fwi.START
    days = []
    for rec in series:
        month = int(rec["date"][5:7])
        r = fwi.daily_step(rec["temp"], rec["rh"], rec["wind"], rec["rain"], month, state)
        state = (r["ffmc"], r["dmc"], r["dc"])
        days.append({**r, "date": rec["date"], "weather": rec})
    return days


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="compute but do not write")
    args = ap.parse_args()

    locs = load_locations()
    print("fetching Open-Meteo for %d wilayas (no API key)..." % len(locs))

    def progress(done, total):
        print("  %d/%d" % (done, total), flush=True)

    raw = weather.fetch_all(locs, progress=progress)

    today = dt.date.today().isoformat()
    out, spinups, skipped = {}, [], []

    for loc in locs:
        series = raw.get(loc["code"]) or []
        if len(series) < MIN_SPINUP_DAYS:
            skipped.append(loc["code"])
            continue
        chain = run_chain(series)

        # Emit from today forward. If today is missing (timezone edge), fall back
        # to the last OUTPUT_DAYS available rather than dropping the wilaya.
        start = next((i for i, d in enumerate(chain) if d["date"] >= today), None)
        if start is None:
            start = max(0, len(chain) - OUTPUT_DAYS)
        window = chain[start:start + OUTPUT_DAYS]

        spinups.append(start)
        days = []
        for d in window:
            masked = fwi.apply_fuel_mask(d["fwi"], loc["fuel"])
            days.append({
                "date": d["date"],
                "fwi": round(masked, 1),
                "fwi_raw": round(d["fwi"], 1),
                "class": fwi.danger_class(masked),
                "ffmc": round(d["ffmc"], 1),
                "dmc": round(d["dmc"], 1),
                "dc": round(d["dc"], 1),
                "isi": round(d["isi"], 1),
                "bui": round(d["bui"], 1),
                "weather": {
                    "temp": round(d["weather"]["temp"], 1),
                    "rh": round(d["weather"]["rh"], 1),
                    "wind": round(d["weather"]["wind"], 1),
                    "wind_dir": round(d["weather"]["wind_dir"]),
                    "rain": round(d["weather"]["rain"], 1),
                },
            })
        out[loc["code"]] = {"code": loc["code"], "fuel": loc["fuel"], "days": days}

    if skipped:
        print("WARNING: insufficient history, skipped:", skipped)
    if not out:
        raise SystemExit("no wilaya produced a usable series")

    dates = out[next(iter(out))]["days"]
    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "source": "open-meteo",
        "model": "Canadian FWI (Van Wagner 1987), fuel-masked",
        "spinup_days": min(spinups) if spinups else 0,
        "note": "Noon-local temp/RH/wind, daily precipitation total. Codes integrated "
                "across the full available history before the forecast window.",
        "dates": [d["date"] for d in dates],
        "wilayas": out,
    }

    if args.dry:
        print("[dry run] nothing written")
    else:
        json.dump(payload, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        print("wrote %s (%.0f KB)" % (OUT, os.path.getsize(OUT) / 1024))

    print("\nspin-up: %d days before the first reported day" % payload["spinup_days"])
    print("window : %s -> %s" % (payload["dates"][0], payload["dates"][-1]))

    ranked = sorted(
        ((v["days"][0]["fwi"], k) for k, v in out.items()), reverse=True)[:10]
    by_code = {l["code"]: l for l in locs}
    print("\nhighest fuel-masked FWI today (%s):" % payload["dates"][0])
    for val, code in ranked:
        l = by_code[code]
        d = out[code]["days"][0]
        print("  %s %-20s FWI %5.1f (raw %5.1f) %-10s  T=%4.1f RH=%3.0f%% W=%4.1f DC=%5.1f"
              % (code, l["name_fr"], val, d["fwi_raw"], fwi.danger_class(val),
                 d["weather"]["temp"], d["weather"]["rh"], d["weather"]["wind"], d["dc"]))


if __name__ == "__main__":
    main()
