"""Orbital elements for the satellites that actually detect these fires.

Every hotspot on this map was seen by one of five spacecraft. Four carry the
instruments FIRMS publishes from — VIIRS on Suomi NPP, NOAA-20 and NOAA-21,
and MODIS on Terra and Aqua — and between them they give Algeria roughly eight
overpasses a day. That cadence is the single most important thing to understand
about the data: a fire is invisible to this system until a satellite next flies
over it, so "no detection" means "nothing seen on the last pass", not "no fire".

Tracking them on the globe makes that legible. You can see which satellite is
overhead, and how long until the next one arrives to take another look.

The elements come from Celestrak, which is free, keyless, and sends
`Access-Control-Allow-Origin: *`. The browser could therefore fetch them
directly, but they are snapshotted here anyway: a two-line element set stays
accurate for a week or more, so a committed copy means the globe still tracks
correctly if Celestrak is briefly unreachable, and the page loads one fewer
third-party request on the critical path.

Usage:  python backend/build_tle.py
"""

import datetime as dt
import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "frontend", "data", "satellites.json")

GROUPS = ("weather", "resource")
CELESTRAK = "https://celestrak.org/NORAD/elements/gp.php?GROUP=%s&FORMAT=tle"

# Matched on the start of the Celestrak name, which carries suffixes such as
# "NOAA 20 (JPSS-1)". Order here is the order they are drawn and listed.
WANTED = [
    ("SUOMI NPP", {
        "short": "Suomi NPP", "sensor": "VIIRS",
        "ar": "سومي إن بي بي", "fr": "Suomi NPP",
    }),
    ("NOAA 20", {
        "short": "NOAA-20", "sensor": "VIIRS",
        "ar": "نوا-20", "fr": "NOAA-20",
    }),
    ("NOAA 21", {
        "short": "NOAA-21", "sensor": "VIIRS",
        "ar": "نوا-21", "fr": "NOAA-21",
    }),
    ("TERRA", {
        "short": "Terra", "sensor": "MODIS",
        "ar": "تيرا", "fr": "Terra",
    }),
    ("AQUA", {
        "short": "Aqua", "sensor": "MODIS",
        "ar": "أكوا", "fr": "Aqua",
    }),
]

# Swath width on the ground, in km. VIIRS sweeps 3060 km, MODIS 2330 km. This is
# why the revisit time is hours rather than days, and it is what the footprint
# drawn under each satellite represents.
SWATH_KM = {"VIIRS": 3060, "MODIS": 2330}


def fetch(group):
    url = CELESTRAK % group
    req = urllib.request.Request(url, headers={"User-Agent": "rased/1.0"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", "replace")


def parse(text):
    """Celestrak TLE format: name line, then the two element lines."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    out = {}
    for i in range(0, len(lines) - 2, 3):
        name, l1, l2 = lines[i].strip(), lines[i + 1], lines[i + 2]
        if l1.startswith("1 ") and l2.startswith("2 "):
            out[name.upper()] = (name, l1, l2)
    return out


def main():
    catalogue = {}
    for g in GROUPS:
        try:
            catalogue.update(parse(fetch(g)))
        except Exception as exc:
            print("  %s group failed: %s" % (g, exc))

    if not catalogue:
        raise SystemExit("Celestrak unreachable; keeping the existing snapshot")

    sats, missing = [], []
    for prefix, meta in WANTED:
        hit = next((v for k, v in catalogue.items() if k.startswith(prefix)), None)
        if not hit:
            missing.append(prefix)
            continue
        name, l1, l2 = hit
        sats.append({
            "name": name.strip(),
            "short": meta["short"],
            "sensor": meta["sensor"],
            "name_ar": meta["ar"],
            "name_fr": meta["fr"],
            "swath_km": SWATH_KM[meta["sensor"]],
            "tle1": l1,
            "tle2": l2,
        })

    if missing:
        print("  not found in catalogue: " + ", ".join(missing))
    if not sats:
        raise SystemExit("no target satellites found; refusing to write an empty set")

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": "celestrak",
        "note": "Two-line element sets stay usable for roughly a week; "
                "refreshed on the same schedule as the fire data.",
        "satellites": sats,
    }

    out = os.path.abspath(OUT)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)

    print("wrote %s" % out)
    for s in sats:
        # Epoch is the day-of-year the elements were computed for; a set more
        # than a couple of weeks old has drifted enough to be worth noticing.
        print("  %-12s %-6s epoch %s" % (s["short"], s["sensor"], s["tle1"][18:32]))


if __name__ == "__main__":
    main()
