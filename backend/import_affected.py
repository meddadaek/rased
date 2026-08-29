"""Import the documented affected-areas list, geocode it, and check it against satellites.

    python import_affected.py

Source: a coordination-team document (August 2026), transcribed into the Hiba
Algeria repository (migration 0018). 55 locations across Jijel, Béjaïa, Mila and
Skikda, each with a severity:

    ravaged      heavy damage / casualties
    evacuated    residents moved out
    threatened   homes at risk
    burning      active fire reported
    unconfirmed  seen on social media, never verified

That last category is the interesting one, and the reason this import exists.
Hiba's schema has the status but no mechanism to resolve it — somebody has to go
and look. Rased can answer it from orbit: was there a thermal detection near this
point in the last 48 hours?

The answer is recorded, never overwritten. A satellite that saw nothing does not
mean nothing happened — it may have passed under cloud, or the fire may have been
small and brief. So the verdict is stored as evidence_for / no_evidence, not as
true / false.
"""
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "app"))

import relief  # noqa: E402
import wilayas as wilayas_ref  # noqa: E402

DATA = os.path.abspath(os.path.join(HERE, "..", "frontend", "data"))
WORK = os.path.abspath(os.path.join(HERE, "..", "data", "work"))
SRC_SQL = os.path.abspath(os.path.join(HERE, "..", "data", "external", "affected_areas.sql"))

SOURCE = "قائمة موثقة من فريق التنسيق — أوت 2026 (عبر هبة الجزائر)"

# Confirmation window. Wider than the 6h "still burning" test on purpose: here we
# are asking "did this place burn at all recently", not "is it burning now".
CONFIRM_KM = 6.0
CONFIRM_HOURS = 48.0

WILAYA_CODE = {"جيجل": "18", "بجاية": "06", "ميلة": "43", "سكيكدة": "21"}

EARTH_R = 6371.0


def haversine(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def parse_sql(path):
    """Pull the VALUES tuples out of the migration.

    Ten single-quoted fields per row, with '' as an escaped quote (Bordj T''har,
    Tizi N''Berber). Parsing the SQL rather than re-typing 55 rows keeps this
    honest: re-running against an updated upstream file picks up their changes
    instead of drifting from the source.
    """
    text = open(path, encoding="utf-8").read()
    field = r"'((?:[^']|'')*)'"
    row_re = re.compile(r"\(\s*" + r"\s*,\s*".join([field] * 10) + r"\s*\)")
    rows = []
    for m in row_re.finditer(text):
        vals = [g.replace("''", "'") for g in m.groups()]
        rows.append({
            "wilaya": vals[0], "wilaya_fr": vals[1],
            "daira": vals[2], "daira_fr": vals[3],
            "commune": vals[4], "commune_fr": vals[5],
            "spot": vals[6], "spot_fr": vals[7],
            "status_raw": vals[8], "severity": vals[9],
        })
    return rows


def build_geocoder():
    """Match a commune/spot name to coordinates using OSM place names."""
    with open(os.path.join(WORK, "assets.json"), encoding="utf-8") as fh:
        places = json.load(fh)["assets"].get("place", [])

    index = {}
    for p in places:
        for key in (p.get("name"), p.get("name_fr")):
            if not key:
                continue
            k = key.strip().lower()
            # Prefer the larger settlement when names collide.
            if k not in index or (p.get("pop", 0) > index[k].get("pop", 0)):
                index[k] = p

    def locate(*names):
        for nm in names:
            if not nm:
                continue
            hit = index.get(nm.strip().lower())
            if hit:
                return hit["lat"], hit["lon"], nm
        return None, None, None

    return locate


def main():
    rows = parse_sql(SRC_SQL)
    print("parsed %d affected areas from the coordination list" % len(rows))
    if not rows:
        raise SystemExit("nothing parsed - has the upstream format changed?")

    locate = build_geocoder()

    fires_path = os.path.join(DATA, "fires.json")
    fires = []
    if os.path.exists(fires_path):
        with open(fires_path, encoding="utf-8") as fh:
            payload = json.load(fh)
        # Industrial heat must not be used to "confirm" a village fire report.
        fires = [f for f in payload["fires"] if f.get("category") != "industrial"]
    print("cross-checking against %d satellite fire clusters" % len(fires))

    relief.configure(os.path.join(HERE, "rased.db"))
    with relief.db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS affected_areas (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT NOT NULL,
                wilaya      TEXT,
                wilaya_ar   TEXT,
                daira       TEXT,
                commune     TEXT,
                commune_fr  TEXT,
                spot        TEXT,
                spot_fr     TEXT,
                status_raw  TEXT,
                severity    TEXT NOT NULL,
                lat         REAL,
                lon         REAL,
                geocoded_on TEXT,
                sat_matches INTEGER NOT NULL DEFAULT 0,
                sat_km      REAL,
                sat_frp     REAL,
                verdict     TEXT,
                source      TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_aa_wilaya ON affected_areas(wilaya)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_aa_sev ON affected_areas(severity)")

    stamp = relief.now()
    stats = {"geocoded": 0, "checked": 0, "evidence": 0, "added": 0, "updated": 0}
    unconfirmed_resolved = []

    with relief.db() as conn:
        for r in rows:
            code = WILAYA_CODE.get(r["wilaya"])
            lat, lon, matched = locate(r["spot"], r["commune"], r["spot_fr"], r["commune_fr"])
            if lat:
                stats["geocoded"] += 1

            matches, nearest_km, best_frp, verdict = 0, None, None, None
            if lat and fires:
                stats["checked"] += 1
                near = []
                for f in fires:
                    d = haversine(lat, lon, f["lat"], f["lon"])
                    if d <= CONFIRM_KM and f.get("last_seen_h", 1e9) <= CONFIRM_HOURS:
                        near.append((d, f))
                near.sort(key=lambda t: t[0])
                matches = len(near)
                if near:
                    nearest_km = round(near[0][0], 2)
                    best_frp = max(f["frp_total"] for _, f in near)
                    verdict = "evidence_for"
                    stats["evidence"] += 1
                    if r["severity"] == "unconfirmed":
                        unconfirmed_resolved.append((r, nearest_km, best_frp))
                else:
                    # Absence of a detection is not absence of a fire.
                    verdict = "no_evidence"

            existing = conn.execute(
                "SELECT id FROM affected_areas WHERE commune=? AND spot=? AND wilaya=?",
                (r["commune"], r["spot"], code)).fetchone()

            fields = (code, r["wilaya"], r["daira"], r["commune"], r["commune_fr"],
                      r["spot"], r["spot_fr"], r["status_raw"], r["severity"],
                      lat, lon, matched, matches, nearest_km, best_frp, verdict, SOURCE)
            if existing:
                conn.execute(
                    "UPDATE affected_areas SET wilaya=?,wilaya_ar=?,daira=?,commune=?,"
                    "commune_fr=?,spot=?,spot_fr=?,status_raw=?,severity=?,lat=?,lon=?,"
                    "geocoded_on=?,sat_matches=?,sat_km=?,sat_frp=?,verdict=?,source=? "
                    "WHERE id=?", fields + (existing["id"],))
                stats["updated"] += 1
            else:
                conn.execute(
                    "INSERT INTO affected_areas (created_at,wilaya,wilaya_ar,daira,commune,"
                    "commune_fr,spot,spot_fr,status_raw,severity,lat,lon,geocoded_on,"
                    "sat_matches,sat_km,sat_frp,verdict,source)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (stamp,) + fields)
                stats["added"] += 1

    print("\n%d added, %d updated" % (stats["added"], stats["updated"]))
    print("geocoded %d/%d  ·  satellite-checked %d  ·  found evidence for %d"
          % (stats["geocoded"], len(rows), stats["checked"], stats["evidence"]))

    if unconfirmed_resolved:
        print("\nSocial-media reports now backed by satellite evidence:")
        for r, km, frp in unconfirmed_resolved:
            print("  %s / %s — detection %.1f km away, %.0f MW"
                  % (r["commune"], r["spot"], km, frp))
    else:
        print("\nNo previously-unconfirmed report found satellite evidence in this run.")
        print("That is not a refutation: satellites pass every few hours and miss")
        print("small or short fires, and cloud hides them entirely.")


if __name__ == "__main__":
    main()
