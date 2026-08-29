"""Generate mock risk + fire payloads in the exact shape the live API will serve.

The frontend is built against these files first, so when the real Open-Meteo and FIRMS
ingestion lands the UI needs no changes - only the fetch URL moves from /data/*.json
to /api/v1/*. Values are synthetic but physically generated: real weather is invented
per wilaya, then pushed through the real FWI chain in fwi.py, so the codes carry
correct day-to-day memory and the map shows a plausible heatwave rather than noise.
"""
import datetime as dt
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))
import fwi  # noqa: E402
import wilayas  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GEO = os.path.join(ROOT, "frontend", "data", "wilayas.geojson")
OUT_RISK = os.path.join(ROOT, "frontend", "data", "mock_risk.json")
OUT_FIRES = os.path.join(ROOT, "frontend", "data", "mock_fires.json")

DAYS = 7
rng = random.Random(1821)  # deterministic: same demo every run

# The 2026 campaign wilayas - fires concentrate here, so the mock should too.
NORTHEAST = {"18", "06", "43", "21", "23", "36", "24", "41", "19", "25"}


def synth_weather(props, day_index, month):
    """Invent a plausible noon observation for one wilaya on one day.

    Aridity rises going south (latitude) and inland (distance from the coast); a
    heatwave ramps across the week so the forecast has a visible trend to look at.
    """
    lat, lon = props["lat"], props["lon"]
    southness = max(0.0, (36.9 - lat) / 12.0)          # 0 at the coast, ~1 deep Sahara
    heatwave = 1.0 + 0.055 * day_index                  # week-long warming ramp

    temp = (29.0 + 17.0 * southness) * heatwave + rng.uniform(-1.6, 1.6)
    rh = max(6.0, (58.0 - 40.0 * southness) / heatwave + rng.uniform(-6.0, 6.0))
    # Sirocco: hot dry southerlies are what turned 2021 and 2023 lethal.
    sirocco = day_index in (3, 4)
    wind = rng.uniform(9.0, 20.0) + (rng.uniform(16.0, 30.0) if sirocco else 0.0)
    wind_dir = rng.uniform(150, 210) if sirocco else rng.uniform(0, 360)
    rain = 0.0 if rng.random() > 0.10 else round(rng.uniform(0.5, 7.0), 1)

    return {
        "temp": round(temp, 1),
        "rh": round(min(rh, 100.0), 1),
        "wind": round(wind, 1),
        "wind_dir": round(wind_dir),
        "rain": rain,
    }


def main():
    geo = json.load(open(GEO, encoding="utf-8"))
    today = dt.date(2026, 8, 29)
    days = [(today + dt.timedelta(days=i)).isoformat() for i in range(DAYS)]
    month = today.month

    out = {}
    for feat in geo["features"]:
        p = feat["properties"]
        # Seed the moisture codes mid-season: it is late August after a long dry spell,
        # so DC in particular starts high. Starting from spring values would understate
        # the drought memory by two months.
        state = (88.0 + rng.uniform(-3, 3), 55.0 + rng.uniform(-15, 25), 480.0 + rng.uniform(-120, 180))
        series = []
        for i in range(DAYS):
            w = synth_weather(p, i, month)
            r = fwi.daily_step(w["temp"], w["rh"], w["wind"], w["rain"], month, state)
            state = (r["ffmc"], r["dmc"], r["dc"])
            masked = fwi.apply_fuel_mask(r["fwi"], p["fuel"])
            series.append({
                "date": days[i],
                "fwi": round(masked, 1),
                "fwi_raw": round(r["fwi"], 1),
                "class": fwi.danger_class(masked),
                "ffmc": round(r["ffmc"], 1),
                "dmc": round(r["dmc"], 1),
                "dc": round(r["dc"], 1),
                "isi": round(r["isi"], 1),
                "bui": round(r["bui"], 1),
                "weather": w,
            })
        out[p["code"]] = {"code": p["code"], "fuel": p["fuel"], "days": series}

    risk = {
        "generated_at": dt.datetime(2026, 8, 29, 6, 0).isoformat() + "Z",
        "source": "MOCK",
        "model": "Canadian FWI (Van Wagner 1987), fuel-masked",
        "dates": days,
        "wilayas": out,
    }
    json.dump(risk, open(OUT_RISK, "w", encoding="utf-8"), ensure_ascii=False)

    # --- fires: clusters of VIIRS-like detections, weighted to the north-east ---
    fires = []
    centres = [f for f in geo["features"] if f["properties"]["code"] in NORTHEAST]
    fid = 0
    for feat in centres:
        p = feat["properties"]
        for _ in range(rng.randint(0, 4)):
            fid += 1
            lat = p["lat"] + rng.uniform(-0.30, 0.30)
            lon = p["lon"] + rng.uniform(-0.45, 0.45)
            det = rng.randint(2, 40)
            hours_old = rng.uniform(0.5, 22.0)
            fires.append({
                "id": "F%04d" % fid,
                "lat": round(lat, 4),
                "lon": round(lon, 4),
                "wilaya": p["code"],
                "detections": det,
                "frp_total": round(det * rng.uniform(3.0, 26.0), 1),
                "frp_max": round(rng.uniform(8.0, 190.0), 1),
                "confidence": rng.choice(["nominal", "nominal", "high", "high", "low"]),
                "satellites": rng.sample(["VIIRS_SNPP", "VIIRS_NOAA20", "VIIRS_NOAA21", "MODIS"],
                                         rng.randint(1, 3)),
                "first_seen_h": round(hours_old, 1),
                "last_seen_h": round(rng.uniform(0.1, min(hours_old, 3.0)), 1),
                "growing": rng.random() < 0.45,
            })

    json.dump({
        "generated_at": dt.datetime(2026, 8, 29, 6, 0).isoformat() + "Z",
        "source": "MOCK",
        "window_hours": 24,
        "fires": fires,
    }, open(OUT_FIRES, "w", encoding="utf-8"), ensure_ascii=False)

    hot = sorted(((v["days"][0]["fwi"], k) for k, v in out.items()), reverse=True)[:6]
    print("risk  -> %s (%d wilayas x %d days)" % (os.path.basename(OUT_RISK), len(out), DAYS))
    print("fires -> %s (%d clusters)" % (os.path.basename(OUT_FIRES), len(fires)))
    print("today's highest fuel-masked FWI:")
    for val, code in hot:
        w = wilayas.BY_CODE[code]
        print("   %s  %-20s %5.1f  %s" % (code, w["name_fr"], val, fwi.danger_class(val)))


if __name__ == "__main__":
    main()
