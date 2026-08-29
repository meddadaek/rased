"""NASA FIRMS active-fire ingestion: hotspots -> tracked fire clusters.

FIRMS requires a MAP_KEY. It is free and needs only an email address — no card,
no billing relationship — from:

    https://firms.modaps.eosdis.nasa.gov/api/map_key/

Supply it as the RASED_FIRMS_KEY environment variable, or with --key.

A satellite hotspot is a single ~375 m pixel that was hot when the satellite
passed. One wildfire produces dozens of them across several overpasses and
several satellites. Reporting raw pixels would claim forty fires where there is
one, so detections are clustered by proximity into fire *events*, and each event
carries the total radiative power, how long it has been burning, and whether it
grew on the most recent pass.
"""
import argparse
import csv
import datetime as dt
import io
import json
import math
import os
import sys
import urllib.request

BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

# Algeria, generous bounding box: west, south, east, north.
BBOX = "-8.9,18.8,12.1,37.4"

SOURCES = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "MODIS_NRT"]

# Two detections within this distance are treated as the same fire. VIIRS pixels
# are ~375 m, so ~2 km links neighbouring pixels of one front without merging
# genuinely separate fires on adjacent ridges.
CLUSTER_KM = 2.0

EARTH_R = 6371.0


def haversine(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def fetch(map_key, source, days=1):
    url = "%s/%s/%s/%s/%d" % (BASE, map_key, source, BBOX, days)
    req = urllib.request.Request(url, headers={"User-Agent": "Rased/0.1"})
    with urllib.request.urlopen(req, timeout=90) as r:
        body = r.read().decode("utf-8", errors="replace")

    # FIRMS answers errors with HTTP 200 and a plain-text body, so the status
    # code cannot be trusted — inspect the payload itself.
    head = body.lstrip()[:200].lower()
    if not head.startswith("latitude"):
        raise RuntimeError("FIRMS returned no CSV for %s: %s" % (source, body.strip()[:200]))

    rows = list(csv.DictReader(io.StringIO(body)))
    for row in rows:
        row["_source"] = source
    return rows


def normalise(row):
    """One detection, with the per-instrument column differences smoothed out."""
    conf = (row.get("confidence") or "").strip()
    if conf.isdigit():                       # MODIS reports 0-100
        n = int(conf)
        conf = "low" if n < 30 else ("high" if n >= 80 else "nominal")
    else:                                    # VIIRS reports l / n / h
        conf = {"l": "low", "n": "nominal", "h": "high"}.get(conf.lower(), "nominal")

    acq_date = row["acq_date"]
    acq_time = (row.get("acq_time") or "0000").zfill(4)
    when = dt.datetime.strptime(acq_date + acq_time, "%Y-%m-%d%H%M").replace(
        tzinfo=dt.timezone.utc)

    try:
        frp = float(row.get("frp") or 0.0)
    except ValueError:
        frp = 0.0

    return {
        "lat": float(row["latitude"]),
        "lon": float(row["longitude"]),
        "frp": frp,
        "conf": conf,
        "when": when,
        "sat": row["_source"],
        "daynight": row.get("daynight", ""),
    }


# Two detections at the same place separated by more than this are treated as
# separate fire events, not one long one.
#
# Clustering on distance alone merged everything that ever burned at a location
# across the whole 48h window, so the site reported fires "burning for 45 hours"
# that were really yesterday's fire and today's fire counted as one. Satellites
# revisit every few hours, so a genuinely continuous fire produces detections
# throughout; a gap this long means it stopped, and whatever came later is a new
# event (or a re-ignition, which responders also need to see as new).
MAX_GAP_H = 12.0


def cluster(dets, eps_km=CLUSTER_KM, max_gap_h=MAX_GAP_H):
    """Single-linkage clustering in space AND time, via union-find.

    A grid index keeps this near-linear: only detections in the neighbouring
    cells can be within eps, so it does not degrade to comparing every pair.
    """
    n = len(dets)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    cell = eps_km / 111.0  # degrees latitude per eps; longitude is handled by the check
    grid = {}
    for i, d in enumerate(dets):
        key = (int(d["lat"] / cell), int(d["lon"] / cell))
        grid.setdefault(key, []).append(i)

    for (gy, gx), members in grid.items():
        neighbours = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                neighbours.extend(grid.get((gy + dy, gx + dx), ()))
        for i in members:
            for j in neighbours:
                if j <= i:
                    continue
                if haversine(dets[i]["lat"], dets[i]["lon"],
                             dets[j]["lat"], dets[j]["lon"]) > eps_km:
                    continue
                gap = abs((dets[i]["when"] - dets[j]["when"]).total_seconds()) / 3600.0
                if gap <= max_gap_h:
                    union(i, j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


# ─── point in polygon ────────────────────────────────────────────────────

def _in_ring(lat, lon, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            x_at = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_at:
                inside = not inside
        j = i
    return inside


def _in_polygon(lat, lon, poly):
    """poly is a GeoJSON Polygon coordinate array: [outer, hole, hole, ...]."""
    if not _in_ring(lat, lon, poly[0]):
        return False
    return not any(_in_ring(lat, lon, hole) for hole in poly[1:])


def build_locator(geojson):
    """Return locate(lat, lon) -> wilaya code, with a bbox prefilter."""
    entries = []
    for f in geojson["features"]:
        g, p = f["geometry"], f["properties"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        entries.append((p["bbox"], p["code"], polys))

    def locate(lat, lon):
        for bbox, code, polys in entries:
            if not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
                continue
            if any(_in_polygon(lat, lon, poly) for poly in polys):
                return code
        return None

    return locate


# ─── assembly ────────────────────────────────────────────────────────────

# A fire is "active" if a satellite saw it within this many hours. Two VIIRS
# passes happen in roughly that window, so a fire not seen in 6 hours has most
# likely been put out or burnt itself out — and listing it as still burning
# would send people to an emergency that is over.
ACTIVE_HOURS = 6.0

# Distance within which a cluster on this run is considered the same fire as one
# from a previous run. Larger than the clustering epsilon because a front moves
# between passes and its power-weighted centre moves with it.
MATCH_KM = 3.5

HISTORY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fire_history.json")
HISTORY_MAX_AGE_H = 24 * 14


def load_history():
    """Previously seen fires, so we can tell a new ignition from an ongoing one."""
    try:
        with open(HISTORY_PATH, encoding="utf-8") as fh:
            return json.load(fh).get("fires", [])
    except (OSError, ValueError):
        return []


def save_history(entries, now):
    """Persist first-seen times, dropping anything too old to still match."""
    cutoff = now - dt.timedelta(hours=HISTORY_MAX_AGE_H)
    keep = []
    for e in entries:
        try:
            last = dt.datetime.fromisoformat(e["last_seen_utc"])
        except (KeyError, ValueError):
            continue
        if last >= cutoff:
            keep.append(e)
    tmp = HISTORY_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"updated_at": now.replace(microsecond=0).isoformat(),
                   "fires": keep}, fh)
    os.replace(tmp, HISTORY_PATH)   # atomic: a crash mid-write must not lose history
    return len(keep)


def match_history(lat, lon, first_seen, history, max_gap_h=None):
    """Nearest previously-seen fire that is plausibly the SAME fire.

    Proximity alone is not enough. A location that burned two days ago and is
    burning again now is a new ignition, not a fire that has been going for two
    days — and carrying the old first_seen forward is exactly how the site came
    to claim fires "burning for 45 hours" that had started that morning.

    So the same temporal rule used for clustering within a run applies across
    runs: the previous sighting must be recent enough to be continuous with this
    one, or this is a new event.
    """
    if max_gap_h is None:
        max_gap_h = MAX_GAP_H
    best, best_d = None, MATCH_KM
    for e in history:
        d = haversine(lat, lon, e["lat"], e["lon"])
        if d >= best_d:
            continue
        try:
            last = dt.datetime.fromisoformat(e["last_seen_utc"])
        except (KeyError, ValueError):
            continue
        gap = (first_seen - last).total_seconds() / 3600.0
        if gap > max_gap_h:
            continue          # too long quiet; treat as a fresh ignition
        best, best_d = e, d
    return best


def classify(code, wilayas_ref):
    """Separate vegetation fires from persistent industrial heat.

    FIRMS reports thermal anomalies, not wildfires. In Algeria the largest and
    most persistent anomalies are gas flares — Hassi Messaoud in Ouargla, the
    Illizi gas fields — which burn continuously and would otherwise dominate the
    fire list every single day. Ouargla and Illizi ranked first and second by
    detection count on a day when the actual emergency was in Kabylie.

    The same fuel classification that keeps the Sahara off the danger map
    resolves this: a thermal anomaly in a wilaya with no vegetation to burn is
    not a forest fire. They are flagged rather than deleted, because they are
    real heat and hiding them would be its own kind of dishonesty.
    """
    if not code:
        return "unknown"
    meta = wilayas_ref.BY_CODE.get(code)
    if not meta:
        return "unknown"
    return "industrial" if meta["fuel"] == "desert" else "vegetation"


def build(map_key, geojson, days=1, sources=None):
    now = dt.datetime.now(dt.timezone.utc)
    dets, used, failed = [], [], []

    for src in (sources or SOURCES):
        try:
            rows = fetch(map_key, src, days)
            dets.extend(normalise(r) for r in rows)
            used.append(src)
        except Exception as exc:  # one dead satellite feed must not sink the run
            failed.append("%s: %s" % (src, exc))

    if not used:
        raise RuntimeError("every FIRMS source failed:\n  " + "\n  ".join(failed))

    locate = build_locator(geojson)
    import wilayas as wilayas_ref  # noqa: PLC0415 - avoids a circular import at module load
    history = load_history()
    fires, next_history = [], []

    for n, idx in enumerate(cluster(dets), start=1):
        members = [dets[i] for i in idx]
        total_frp = sum(m["frp"] for m in members)

        # Weight the centre by radiative power so it lands on the active front
        # rather than the geometric middle of a long, mostly burnt-out scar.
        w = total_frp or len(members)
        if total_frp > 0:
            lat = sum(m["lat"] * m["frp"] for m in members) / w
            lon = sum(m["lon"] * m["frp"] for m in members) / w
        else:
            lat = sum(m["lat"] for m in members) / len(members)
            lon = sum(m["lon"] for m in members) / len(members)

        first = min(m["when"] for m in members)
        last = max(m["when"] for m in members)

        # "Growing" = more than a third of detections landed in the most recent
        # six hours, i.e. the fire is still producing new hot pixels.
        recent = sum(1 for m in members if (now - m["when"]).total_seconds() <= 6 * 3600)
        growing = len(members) >= 3 and recent >= max(2, len(members) / 3)

        order = {"low": 0, "nominal": 1, "high": 2}
        code = locate(lat, lon)

        last_h = (now - last).total_seconds() / 3600.0
        active = last_h <= ACTIVE_HOURS

        # Was this burning last time we looked? If not, it started since.
        prior = match_history(lat, lon, first, history)
        first_seen_utc = prior["first_seen_utc"] if prior else first.isoformat()
        is_new = prior is None
        try:
            burning_h = (now - dt.datetime.fromisoformat(first_seen_utc)).total_seconds() / 3600.0
        except ValueError:
            burning_h = (now - first).total_seconds() / 3600.0

        next_history.append({
            "lat": round(lat, 4), "lon": round(lon, 4),
            "first_seen_utc": first_seen_utc,
            "last_seen_utc": last.isoformat(),
        })

        fires.append({
            "active": active,
            "is_new": is_new,
            "first_seen_utc": first_seen_utc,
            "burning_hours": round(burning_h, 1),
            "id": "F%04d" % n,
            "category": classify(code, wilayas_ref),
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "wilaya": code,
            "detections": len(members),
            "frp_total": round(total_frp, 1),
            "frp_max": round(max(m["frp"] for m in members), 1),
            "confidence": max((m["conf"] for m in members), key=lambda c: order[c]),
            "satellites": sorted({m["sat"] for m in members}),
            "first_seen_h": round((now - first).total_seconds() / 3600, 1),
            "last_seen_h": round((now - last).total_seconds() / 3600, 1),
            "growing": growing,
        })

    # Drop anything that fell outside every wilaya: the bbox overlaps Tunisia,
    # Morocco and the sea, and nobody using this site can act on those.
    fires = [f for f in fires if f["wilaya"]]

    fires.sort(key=lambda f: f["frp_total"], reverse=True)
    kept = save_history(next_history, now)
    veg = [f for f in fires if f["category"] == "vegetation"]
    active_veg = [f for f in veg if f["active"]]
    return {
        "active_hours": ACTIVE_HOURS,
        "had_history": bool(history),
        "history_entries": kept,
        "vegetation_fires": len(veg),
        "active_vegetation_fires": len(active_veg),
        "new_fires": sum(1 for f in active_veg if f["is_new"]),
        "industrial_flagged": sum(1 for f in fires if f["category"] == "industrial"),
        "generated_at": now.replace(microsecond=0).isoformat(),
        "source": "nasa-firms",
        "window_hours": days * 24,
        "sources_used": used,
        "sources_failed": failed,
        "raw_detections": len(dets),
        "fires": fires,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("RASED_FIRMS_KEY"))
    ap.add_argument("--days", type=int, default=1)
    args = ap.parse_args()

    if not args.key:
        raise SystemExit(
            "No FIRMS MAP_KEY.\n"
            "Get one free (email only, no card) at:\n"
            "  https://firms.modaps.eosdis.nasa.gov/api/map_key/\n"
            "then: set RASED_FIRMS_KEY=...  or  python firms.py --key YOURKEY")

    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    geo = json.load(open(os.path.join(root, "frontend", "data", "wilayas.geojson"),
                        encoding="utf-8"))
    out = build(args.key, geo, days=args.days)

    path = os.path.join(root, "frontend", "data", "fires.json")
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False)

    located = sum(1 for f in out["fires"] if f["wilaya"])
    print("vegetation fires: %d (%d still active within %.0fh) | industrial heat flagged: %d"
          % (out["vegetation_fires"], out["active_vegetation_fires"],
             out["active_hours"], out["industrial_flagged"]))
    if out["had_history"]:
        print("newly started since last run: %d" % out["new_fires"])
    else:
        print("no prior history - new-fire detection starts from the next run")
    print("sources: %s" % ", ".join(out["sources_used"]))
    for f in out["sources_failed"]:
        print("  failed: %s" % f)
    print("detections: %d -> %d fire clusters (%d inside a wilaya)"
          % (out["raw_detections"], len(out["fires"]), located))
    print("wrote %s" % path)
    for f in out["fires"][:10]:
        print("  %s w=%s %5d det  FRP %8.1f MW  %s%s"
              % (f["id"], f["wilaya"] or "--", f["detections"], f["frp_total"],
                 f["confidence"], "  GROWING" if f["growing"] else ""))


if __name__ == "__main__":
    main()
