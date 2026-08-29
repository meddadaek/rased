"""Exposure analysis: turn a fire into an answer somebody can act on.

A dot on a map saying "fire" is not operationally useful. These are:

    which villages are within 5 km of this front, and how many people live there
    which fire station is closest, and how long is the drive by real roads
    which hospital would receive casualties
    which wilayas have the most people currently near an active fire

That last one is the number a relief platform needs in order to pre-position aid
*before* the requests start arriving — which is precisely what Hiba currently
learns from manual field reports.

Distances are great-circle for selection (fast, and correct for "is it near"),
then real road routing via OSRM for the handful of pairs that matter, because
5 km across a ravine in Kabylie can be a 40 minute drive.
"""
import json
import math
import time
import urllib.request

EARTH_R = 6371.0

# OSRM's public demo server: free, no key, but a shared community resource.
# Only the most significant fires get a routed answer.
OSRM = "https://router.project-osrm.org/route/v1/driving"
MAX_ROUTED_FIRES = 25

RINGS_KM = [5, 10]

# Assumed built-up radius per settlement class, in km.
#
# OpenStreetMap puts a settlement's whole population on a single node at its
# centre. Taken literally, a detection 2 km from the Algiers node "threatens"
# 3.5 million people — but Algiers does not fit inside a 5 km circle, and
# publishing that number would discredit everything else on the page.
#
# So a settlement is treated as a disc of population rather than a point, and
# only the part of that disc inside the fire buffer is counted. For a village
# (radius 0.9 km) this changes almost nothing; for a city it is the difference
# between a plausible figure and a nonsensical one.
# Typical Algerian urban density, people per km². Used to infer how much ground
# a settlement actually covers, since OSM gives us a population but no footprint.
URBAN_DENSITY = 4000.0
MIN_RADIUS_KM = 0.3
MAX_RADIUS_KM = 25.0


def settlement_radius_km(pop):
    """Infer a settlement's built-up radius from its population.

    A fixed radius per class does not work: "city" spans Algiers at 3.5 million
    and a provincial seat at 80 000. Deriving it from population keeps the model
    self-consistent at every size — 3.5 M lands near 17 km, a 3 000-person
    village near 0.5 km, both of which match reality closely enough for ranking.
    """
    if not pop or pop <= 0:
        return MIN_RADIUS_KM
    r = math.sqrt(pop / (math.pi * URBAN_DENSITY))
    return max(MIN_RADIUS_KM, min(MAX_RADIUS_KM, r))


def disc_overlap_fraction(dist_km, settle_r, buffer_r):
    """Fraction of a settlement disc that lies inside the fire buffer."""
    if settle_r <= 0:
        return 1.0 if dist_km <= buffer_r else 0.0
    if dist_km >= settle_r + buffer_r:
        return 0.0
    if dist_km <= abs(buffer_r - settle_r):
        # One disc sits entirely inside the other.
        return 1.0 if settle_r <= buffer_r else (buffer_r ** 2) / (settle_r ** 2)

    # Standard circle-circle lens area.
    d, r, R = dist_km, settle_r, buffer_r
    a1 = r * r * math.acos((d * d + r * r - R * R) / (2 * d * r))
    a2 = R * R * math.acos((d * d + R * R - r * r) / (2 * d * R))
    a3 = 0.5 * math.sqrt(max(0.0, (-d + r + R) * (d + r - R) * (d - r + R) * (d + r + R)))
    return max(0.0, min(1.0, (a1 + a2 - a3) / (math.pi * r * r)))


def people_within(hits, buffer_r):
    """Population inside the buffer, and the places contributing to it."""
    total = 0.0
    contributing = []
    for d, p in hits:
        sr = settlement_radius_km(p.get("pop"))
        frac = disc_overlap_fraction(d, sr, buffer_r)
        if frac <= 0:
            continue
        total += p.get("pop", 0) * frac
        contributing.append((d, p, frac))
    return int(round(total)), contributing



def haversine(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 2 * EARTH_R * math.asin(math.sqrt(a))


class Grid:
    """Coarse lat/lon bucket index.

    With ~10k places and a few dozen fires a brute-force scan would also work,
    but this keeps the cost flat if the place list grows to the whole country or
    the fire count spikes during a bad week.
    """

    def __init__(self, items, cell_deg=0.1):
        self.cell = cell_deg
        self.buckets = {}
        for it in items:
            key = (int(it["lat"] / cell_deg), int(it["lon"] / cell_deg))
            self.buckets.setdefault(key, []).append(it)

    def near(self, lat, lon, radius_km):
        # Longitude degrees shrink with latitude; widen the search accordingly so
        # the box never clips candidates near its edges.
        dlat = radius_km / 111.0
        coslat = max(math.cos(lat * math.pi / 180), 0.2)
        dlon = radius_km / (111.0 * coslat)

        y0, y1 = int((lat - dlat) / self.cell), int((lat + dlat) / self.cell)
        x0, x1 = int((lon - dlon) / self.cell), int((lon + dlon) / self.cell)

        out = []
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                for it in self.buckets.get((y, x), ()):
                    d = haversine(lat, lon, it["lat"], it["lon"])
                    if d <= radius_km:
                        out.append((d, it))
        out.sort(key=lambda t: t[0])
        return out


def osrm_route(from_lat, from_lon, to_lat, to_lon, timeout=20):
    """Real road distance/time. Returns None if OSRM cannot answer."""
    url = "%s/%f,%f;%f,%f?overview=false" % (OSRM, from_lon, from_lat, to_lon, to_lat)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Rased/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        if data.get("code") != "Ok" or not data.get("routes"):
            return None
        route = data["routes"][0]
        return {"km": round(route["distance"] / 1000.0, 1),
                "min": round(route["duration"] / 60.0)}
    except Exception:  # noqa: BLE001 - routing is an enhancement, never a blocker
        return None


def analyse(fires, assets, route=True, progress=None):
    places = Grid(assets.get("place", []))
    stations = Grid(assets.get("fire_station", []), cell_deg=0.25)
    hospitals = Grid(assets.get("hospital", []), cell_deg=0.25)

    # Route only for the fires that actually matter, ranked by radiative power.
    ranked = sorted(fires, key=lambda f: f.get("frp_total", 0), reverse=True)
    routable = {f["id"] for f in ranked[:MAX_ROUTED_FIRES]} if route else set()

    out = []
    for n, f in enumerate(fires):
        rec = {"id": f["id"], "lat": f["lat"], "lon": f["lon"],
               "wilaya": f.get("wilaya"), "frp_total": f.get("frp_total", 0),
               "growing": f.get("growing", False), "rings": {}}

        for km in RINGS_KM:
            # Search a little beyond the ring: a city centred just outside it
            # still puts population inside, and ignoring that would undercount.
            hits = places.near(f["lat"], f["lon"], km + MAX_RADIUS_KM)
            pop, contributing = people_within(hits, km)
            inside = [(d, p) for d, p in hits if d <= km]

            rec["rings"]["r%d" % km] = {
                "places": len(inside),
                "pop": pop,
                "place_ids": [p["id"] for _, p, _ in contributing if p.get("id")],
                # Estimated populations are flagged so the UI can hedge the number.
                "pop_estimated": all(p.get("pop_est") for _, p in inside) if inside else False,
                "nearest": [
                    {"name": p["name"], "km": round(d, 1), "pop": p["pop"],
                     "lat": p["lat"], "lon": p["lon"], "type": p.get("place")}
                    for d, p in inside[:8]
                ],
            }

        st = stations.near(f["lat"], f["lon"], 60)
        if st:
            d, s = st[0]
            rec["station"] = {"name": s["name"] or s["name_fr"], "km_direct": round(d, 1),
                              "lat": s["lat"], "lon": s["lon"]}
            if f["id"] in routable:
                r = osrm_route(s["lat"], s["lon"], f["lat"], f["lon"])
                if r:
                    rec["station"]["route"] = r
                time.sleep(0.35)  # courtesy pacing on a shared demo server

        hp = hospitals.near(f["lat"], f["lon"], 80)
        if hp:
            d, h = hp[0]
            rec["hospital"] = {"name": h["name"] or h["name_fr"], "km_direct": round(d, 1),
                               "lat": h["lat"], "lon": h["lon"]}

        out.append(rec)
        if progress:
            progress(n + 1, len(fires))

    return out


def by_wilaya(exposures):
    """Aggregate to the level a relief coordinator actually plans at."""
    agg = {}
    for e in exposures:
        w = e.get("wilaya")
        if not w:
            continue
        a = agg.setdefault(w, {"fires": 0, "growing": 0, "frp": 0.0,
                               "pop_5km": 0, "pop_10km": 0, "places_10km": 0})
        a["fires"] += 1
        a["growing"] += 1 if e.get("growing") else 0
        a["frp"] += e.get("frp_total", 0)
        a["pop_5km"] += e["rings"]["r5"]["pop"]
        a["pop_10km"] += e["rings"]["r10"]["pop"]
        a["places_10km"] += e["rings"]["r10"]["places"]
    for a in agg.values():
        a["frp"] = round(a["frp"], 1)
    return agg
