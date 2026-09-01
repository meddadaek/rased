"""How much ground actually burned, per wilaya.

This is the question a fire map exists to answer and the one a list of hotspots
does not: not "where is there a fire" but "what did Jijel lose this week".

Method. Every FIRMS detection is a sensor pixel with a known ground footprint —
FIRMS reports it per detection, because a VIIRS pixel is 375 m at nadir and
close to 800 m at the edge of the swath. Burned area is therefore the area of
ground covered by at least one detection. The pixels overlap heavily, since the
same fire is seen repeatedly across several passes and by several satellites,
so they are snapped onto a fixed 375 m grid and the unique cells counted. Adding
raw footprints instead would overstate a well-observed fire by a factor of ten.

What this number is and is not. It is the area where a satellite positively saw
active fire. That makes it a *lower bound* on burned area, and it is important
to say so: the sensors only look every few hours, a fire that starts and dies
between passes leaves no trace here, and thick smoke or cloud hides the ground.
It also is not a damage assessment — it says nothing about whether what burned
was forest, scrub or stubble. Official post-fire surveys by the Direction
Générale des Forêts remain the authority. This is the fast, independent,
same-day estimate that exists while those surveys are still being done.

Usage:  python backend/burned.py
"""

import datetime as dt
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "app"))

ROOT = os.path.abspath(os.path.join(HERE, ".."))
FIRES = os.path.join(ROOT, "frontend", "data", "fires.json")
GEO = os.path.join(ROOT, "frontend", "data", "wilayas.geojson")
OUT = os.path.join(ROOT, "frontend", "data", "burned.json")

# Grid resolution, in metres. Matched to the VIIRS I-band pixel: finer would
# invent precision the sensor does not have, coarser would merge distinct fires.
CELL_M = 375.0

M_PER_DEG_LAT = 110540.0

# Reporting windows, in hours.
WINDOWS = (24, 48, 120)


def cells_for(lat, lon, scan_km, track_km):
    """The grid cells a single detection's footprint covers.

    Footprints are axis-aligned here. A real VIIRS pixel is a rotated
    parallelogram, but at 375 m the difference is well under one cell and the
    error cancels across the hundreds of detections that make up a fire.
    """
    m_per_deg_lon = M_PER_DEG_LAT * math.cos(math.radians(lat))
    if m_per_deg_lon < 1.0:
        return []

    half_lat = (track_km * 1000.0) / 2.0 / M_PER_DEG_LAT
    half_lon = (scan_km * 1000.0) / 2.0 / m_per_deg_lon
    step_lat = CELL_M / M_PER_DEG_LAT
    step_lon = CELL_M / m_per_deg_lon

    out = []
    i0 = int(math.floor((lat - half_lat) / step_lat))
    i1 = int(math.floor((lat + half_lat) / step_lat))
    j0 = int(math.floor((lon - half_lon) / step_lon))
    j1 = int(math.floor((lon + half_lon) / step_lon))
    for i in range(i0, i1 + 1):
        for j in range(j0, j1 + 1):
            out.append((i, j))
    return out


def cell_area_ha(i):
    """Area of one grid cell at the latitude of row `i`, in hectares.

    Cells shrink towards the poles, so this is computed per row rather than
    assumed constant — over Algeria's 19 degrees of latitude the difference is
    about six per cent.
    """
    lat = (i + 0.5) * (CELL_M / M_PER_DEG_LAT)
    m_per_deg_lon = M_PER_DEG_LAT * math.cos(math.radians(lat))
    width_m = (CELL_M / m_per_deg_lon) * m_per_deg_lon   # = CELL_M by construction
    return (CELL_M * width_m) / 10000.0


def main():
    fires = json.load(open(FIRES, encoding="utf-8"))
    geo = json.load(open(GEO, encoding="utf-8"))

    names = {}
    for f in geo["features"]:
        p = f["properties"]
        names[p["code"]] = {
            "name_ar": p.get("name_ar", ""),
            "name_fr": p.get("name_fr", ""),
            "fuel": p.get("fuel", ""),
        }

    now = dt.datetime.now(dt.timezone.utc)
    veg = [f for f in fires["fires"] if f.get("category") != "industrial"]

    # cells[window][wilaya] -> set of (i, j)
    cells = {w: {} for w in WINDOWS}
    det_count = {w: {} for w in WINDOWS}
    fire_ha = {}
    per_wilaya_fires = {w: {} for w in WINDOWS}

    for f in veg:
        code = f.get("wilaya")
        if not code:
            continue
        own = set()
        for p in f.get("points", []):
            got = cells_for(p["lat"], p["lon"], p.get("scan", 0.375), p.get("track", 0.375))
            own.update(got)
            for w in WINDOWS:
                if p["age_h"] <= w:
                    cells[w].setdefault(code, set()).update(got)
                    det_count[w][code] = det_count[w].get(code, 0) + 1
                    per_wilaya_fires[w].setdefault(code, set()).add(f["id"])
        if own:
            fire_ha[f["id"]] = round(sum(cell_area_ha(i) for i, _ in own), 1)

    out_wilayas = {}
    for code in cells[max(WINDOWS)]:
        entry = dict(names.get(code, {"name_ar": "", "name_fr": "", "fuel": ""}))
        entry["code"] = code
        for w in WINDOWS:
            got = cells[w].get(code, set())
            entry["ha_%dh" % w] = round(sum(cell_area_ha(i) for i, _ in got), 1)
            entry["fires_%dh" % w] = len(per_wilaya_fires[w].get(code, ()))
            entry["detections_%dh" % w] = det_count[w].get(code, 0)
        out_wilayas[code] = entry

    totals = {}
    for w in WINDOWS:
        allc = set()
        for s in cells[w].values():
            allc |= s
        totals["ha_%dh" % w] = round(sum(cell_area_ha(i) for i, _ in allc), 1)

    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "source": fires.get("source"),
        "fires_generated_at": fires.get("generated_at"),
        "cell_m": CELL_M,
        "windows_h": list(WINDOWS),
        "totals": totals,
        "method": "Unique 375 m grid cells covered by at least one satellite "
                  "fire detection. A lower bound: fires that start and end "
                  "between overpasses, or that burn under cloud or smoke, are "
                  "not counted.",
        "wilayas": out_wilayas,
        "fires": fire_ha,
    }

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print("wrote %s" % OUT)
    for w in WINDOWS:
        print("  last %3dh: %9s ha burned" % (w, "{:,.0f}".format(totals["ha_%dh" % w])))
    print("\nmost affected wilayas (last %dh):" % max(WINDOWS))
    ranked = sorted(out_wilayas.values(),
                    key=lambda x: -x["ha_%dh" % max(WINDOWS)])[:12]
    for r in ranked:
        print("  %-22s %9s ha   %2d fires  %4d detections  [%s]" % (
            r["name_fr"] or r["code"],
            "{:,.0f}".format(r["ha_%dh" % max(WINDOWS)]),
            r["fires_%dh" % max(WINDOWS)],
            r["detections_%dh" % max(WINDOWS)],
            r["fuel"]))


if __name__ == "__main__":
    main()
