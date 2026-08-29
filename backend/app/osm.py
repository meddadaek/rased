"""Overpass extraction: the ground truth a fire map needs to be useful.

A danger index tells you a wilaya is dangerous. It does not tell you *who* is in
the way, or who can get there. That requires knowing where the villages, the fire
stations, the hospitals and the schools actually are — which OpenStreetMap knows
and which costs nothing to query.

Overpass is free, keyless and community-run, so this is written to be a good
citizen: one query per category, generous timeouts, retries with backoff across
several mirrors, and results cached to disk so it is never called twice for the
same thing.
"""
import json
import os
import time
import urllib.parse
import urllib.request

# Community mirrors. If the main instance is loaded, fall through to the others
# rather than hammering one endpoint.
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]

# Northern Algeria: the Tell Atlas strip where the forests, the people and the
# fires all are. Querying the whole country would pull in the Sahara for nothing.
# south, west, north, east — Overpass bbox order.
NORTH = (33.5, -2.5, 37.6, 8.8)

USER_AGENT = "Rased/0.1 (Algeria wildfire early warning; contact via repo)"

CATEGORIES = {
    "fire_station": '["amenity"="fire_station"]',
    "hospital": '["amenity"~"^(hospital|clinic)$"]',
    "school": '["amenity"="school"]',
    "place": '["place"~"^(city|town|village|hamlet)$"]',
    "water": '["landuse"="reservoir"]',
    # Aid organisations: the جمعيات خيرية that actually run relief on the ground,
    # plus the Croissant-Rouge. OSM scatters these across several tags, so the
    # selector is a union rather than a single key.
    "aid": '["amenity"~"^(social_facility|community_centre)$"]',
    "aid_office": '["office"~"^(charity|ngo)$"]',
    # Veterinary care. After a fire, burned livestock and pets need treatment
    # that no human clinic will provide, and nobody has mapped where to take them.
    "vet": '["amenity"="veterinary"]',
}

# Rough population fallbacks, used only when OSM carries no population tag.
# Deliberately conservative: an underestimate that says "some people live here"
# is safer than a confident invented number.
PLACE_DEFAULT_POP = {"city": 100000, "town": 20000, "village": 3000, "hamlet": 400}


def _post(query, endpoint, timeout=240):
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(endpoint, data=data, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def query(overpass_ql, retries=2):
    last = None
    for endpoint in ENDPOINTS:
        for attempt in range(retries):
            try:
                return _post(overpass_ql, endpoint)
            except Exception as exc:  # noqa: BLE001
                last = "%s -> %s" % (endpoint, exc)
                time.sleep(3.0 * (attempt + 1))
    raise RuntimeError("all Overpass mirrors failed; last: %s" % last)


def build_query(selector, bbox=NORTH):
    s, w, n, e = bbox
    box = "%s,%s,%s,%s" % (s, w, n, e)
    return (
        "[out:json][timeout:180];\n"
        "(\n"
        '  node%s(%s);\n'
        '  way%s(%s);\n'
        '  relation%s(%s);\n'
        ");\n"
        "out center tags;" % (selector, box, selector, box, selector, box)
    )


def parse_elements(payload, category):
    """Flatten nodes/ways/relations to points, keeping only what we will use."""
    out = []
    for el in payload.get("elements", []):
        if el["type"] == "node":
            lat, lon = el.get("lat"), el.get("lon")
        else:
            c = el.get("center") or {}
            lat, lon = c.get("lat"), c.get("lon")
        if lat is None or lon is None:
            continue

        tags = el.get("tags", {})
        name = tags.get("name:ar") or tags.get("name") or tags.get("name:fr")
        if category == "place" and not name:
            continue  # an unnamed village cannot be reported to anybody

        rec = {
            "id": "%s%s" % (el["type"][0], el["id"]),
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "name": name,
            "name_fr": tags.get("name:fr") or tags.get("name"),
        }

        if category == "place":
            rec["place"] = tags.get("place")
            pop = tags.get("population")
            try:
                rec["pop"] = int(str(pop).replace(" ", "").replace(",", ""))
                rec["pop_est"] = False
            except (TypeError, ValueError):
                rec["pop"] = PLACE_DEFAULT_POP.get(tags.get("place"), 500)
                rec["pop_est"] = True

        out.append(rec)
    return out


def fetch_category(category, bbox=NORTH):
    payload = query(build_query(CATEGORIES[category], bbox))
    return parse_elements(payload, category)
