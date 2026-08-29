"""Rased API + static host.

    pip install fastapi uvicorn
    python backend/server.py            # http://127.0.0.1:8080

Serves the frontend and a small public API. The API exists so that other people's
software can consume Rased — specifically Hiba, whose `affected_areas` table has an
`unconfirmed` severity meaning "a social-media report we have not verified". The
/confirm endpoint answers that question mechanically.

Citizen reports live in SQLite. Every report is cross-checked against satellite
detections at write time and stored with that verdict, so a coordinator reading the
queue sees "3 satellite detections within 4 km" rather than an unqualified claim.

Deliberately dependency-light: FastAPI, uvicorn, and the standard library. No ORM,
no migrations, no build step. It has to be runnable by someone who was handed the
repo and has no context.
"""
import datetime as dt
import json
import math
import os
import sqlite3
import sys

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
FRONTEND = os.path.join(ROOT, "frontend")
DATA = os.path.join(FRONTEND, "data")
DB_PATH = os.path.join(HERE, "rased.db")

sys.path.insert(0, os.path.join(HERE, "app"))
import wilayas as wilayas_ref  # noqa: E402

import relief  # noqa: E402

app = FastAPI(
    title="Rased API",
    version="0.1",
    description="Open fire-danger and exposure data for Algeria. "
                "Free to use; attribution appreciated.",
)

# Public, read-mostly, humanitarian data — any origin may read it. That is the
# whole point of publishing an API rather than only a website.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ─── storage ─────────────────────────────────────────────────────────────

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT    NOT NULL,
                lat         REAL    NOT NULL,
                lon         REAL    NOT NULL,
                wilaya      TEXT,
                commune     TEXT,
                kind        TEXT    NOT NULL,
                note        TEXT,
                contact     TEXT,
                -- satellite cross-check, computed once at write time
                sat_checked INTEGER NOT NULL DEFAULT 0,
                sat_hits    INTEGER NOT NULL DEFAULT 0,
                sat_km      REAL,
                status      TEXT    NOT NULL DEFAULT 'new'
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_created ON reports(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_wilaya  ON reports(wilaya)")
    relief.configure(DB_PATH)


# ─── payload cache ───────────────────────────────────────────────────────

_cache = {}


def payload(name, required=True):
    """Read a generated JSON payload, re-reading only when the file changes.

    The pipelines rewrite these files on a schedule; the server must pick that up
    without a restart, but must not re-parse a megabyte on every request.
    """
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        if required:
            raise HTTPException(503, "%s not generated yet - run the pipeline" % name)
        return None
    mtime = os.path.getmtime(path)
    hit = _cache.get(name)
    if hit and hit[0] == mtime:
        return hit[1]
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    _cache[name] = (mtime, data)
    return data


def fires_payload():
    for name in ("fires.json", "mock_fires.json"):
        p = payload(name, required=False)
        if p:
            return p
    raise HTTPException(503, "no fire data available")


EARTH_R = 6371.0


def haversine(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 2 * EARTH_R * math.asin(math.sqrt(a))


# ─── models ──────────────────────────────────────────────────────────────

class ReportIn(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    kind: str = Field(..., min_length=2, max_length=32)
    note: str | None = Field(None, max_length=1000)
    commune: str | None = Field(None, max_length=120)
    contact: str | None = Field(None, max_length=120)


# ─── api ─────────────────────────────────────────────────────────────────

@app.get("/api/v1/wilayas")
def get_wilayas():
    """Reference table: codes, Arabic/French names, fuel class."""
    return {"count": 48, "wilayas": wilayas_ref.as_dicts()}


@app.get("/api/v1/risk")
def get_risk(code: str | None = Query(None, description="wilaya code, e.g. 18"),
             date: str | None = Query(None, description="ISO date within the window")):
    data = payload("risk.json", required=False) or payload("mock_risk.json")
    if code:
        w = data["wilayas"].get(code)
        if not w:
            raise HTTPException(404, "unknown wilaya code %r" % code)
        days = w["days"]
        if date:
            days = [d for d in days if d["date"] == date]
            if not days:
                raise HTTPException(404, "no data for %s" % date)
        meta = wilayas_ref.BY_CODE.get(code, {})
        return {"generated_at": data["generated_at"], "source": data["source"],
                "wilaya": {**meta, "days": days}}
    if date:
        out = {c: {**v, "days": [d for d in v["days"] if d["date"] == date]}
               for c, v in data["wilayas"].items()}
        return {**data, "wilayas": out}
    return data


@app.get("/api/v1/fires")
def get_fires(wilaya: str | None = None, growing: bool | None = None):
    data = fires_payload()
    fires = data["fires"]
    if wilaya:
        fires = [f for f in fires if f.get("wilaya") == wilaya]
    if growing is not None:
        fires = [f for f in fires if bool(f.get("growing")) == growing]
    return {**data, "fires": fires}


@app.get("/api/v1/exposure")
def get_exposure(wilaya: str | None = None):
    data = payload("exposure.json")
    if wilaya:
        return {**data, "fires": [f for f in data["fires"] if f.get("wilaya") == wilaya]}
    return data


@app.get("/api/v1/assets")
def get_assets(kind: str | None = None, wilaya: str | None = None):
    data = payload("assets_map.json")
    assets = data["assets"]
    if kind:
        if kind not in assets:
            raise HTTPException(404, "unknown asset kind %r; have %s"
                                % (kind, ", ".join(assets)))
        assets = {kind: assets[kind]}
    if wilaya:
        assets = {k: [a for a in v if a.get("wilaya") == wilaya] for k, v in assets.items()}
    return {**data, "assets": assets}


@app.get("/api/v1/confirm")
def confirm(lat: float = Query(..., ge=-90, le=90),
            lon: float = Query(..., ge=-180, le=180),
            radius_km: float = Query(5.0, gt=0, le=50),
            hours: float = Query(24.0, gt=0, le=168)):
    """Is there satellite evidence of fire near this point?

    Built for Hiba's `unconfirmed` reports. Returns the matching detections and an
    explicit verdict, never a bare boolean — a coordinator needs to see how far
    away and how recent the evidence is before acting on it.
    """
    data = fires_payload()
    hits = []
    for f in data["fires"]:
        d = haversine(lat, lon, f["lat"], f["lon"])
        if d <= radius_km and f.get("last_seen_h", 0) <= hours:
            hits.append({"id": f["id"], "km": round(d, 2),
                         "frp_total": f.get("frp_total"),
                         "detections": f.get("detections"),
                         "last_seen_h": f.get("last_seen_h"),
                         "growing": f.get("growing")})
    hits.sort(key=lambda h: h["km"])
    return {
        "query": {"lat": lat, "lon": lon, "radius_km": radius_km, "hours": hours},
        "source": data.get("source"),
        # Callers must be able to tell a real negative from a simulated one.
        "is_simulated": data.get("source") == "MOCK",
        "confirmed": bool(hits),
        "match_count": len(hits),
        "nearest_km": hits[0]["km"] if hits else None,
        "matches": hits,
    }


@app.get("/api/v1/affected-candidates")
def affected_candidates():
    """Rows shaped like Hiba's `affected_areas` table, ready for review.

    Deliberately not auto-inserted anywhere: these are candidates for a human
    coordinator to accept or reject. Severity is always `burning`, never
    `ravaged` or `evacuated` — a satellite sees heat, not damage or casualties,
    and claiming otherwise from orbit would be a lie.
    """
    expo = payload("exposure.json")
    rows = []
    for e in expo["fires"]:
        code = e.get("wilaya")
        meta = wilayas_ref.BY_CODE.get(code, {}) if code else {}
        near = e["rings"]["r5"]["nearest"]
        rows.append({
            "wilaya": meta.get("name_ar"),
            "wilaya_fr": meta.get("name_fr"),
            "commune": near[0]["name"] if near else None,
            "spot": near[0]["name"] if near else None,
            "severity": "burning",
            "lat": e["lat"],
            "lng": e["lon"],
            "source": "Rased / NASA FIRMS",
            "notes": "%s MW radiative power, %d people within 5 km, %d within 10 km"
                     % (e.get("frp_total"), e["rings"]["r5"]["pop"],
                        e["rings"]["r10"]["pop"]),
            "_rased": {"fire_id": e["id"], "pop_5km": e["rings"]["r5"]["pop"],
                       "pop_10km": e["rings"]["r10"]["pop"],
                       "station": e.get("station"), "hospital": e.get("hospital")},
        })
    return {"generated_at": expo["generated_at"],
            "fires_source": expo.get("fires_source"),
            "is_simulated": expo.get("fires_source") == "MOCK",
            "count": len(rows), "candidates": rows}


@app.post("/api/v1/reports", status_code=201)
def create_report(r: ReportIn):
    """Accept a citizen report and cross-check it against satellites immediately."""
    check = confirm(lat=r.lat, lon=r.lon, radius_km=5.0, hours=24.0)

    code = None
    try:
        expo_geo = payload("wilayas.geojson", required=False)
        if expo_geo:
            sys.path.insert(0, os.path.join(HERE, "app"))
            import firms  # noqa: PLC0415 - optional, only needed here
            code = firms.build_locator(expo_geo)(r.lat, r.lon)
    except Exception:  # noqa: BLE001 - locating is a nicety, not a requirement
        code = None

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO reports (created_at, lat, lon, wilaya, commune, kind, note,"
            " contact, sat_checked, sat_hits, sat_km, status)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (now, r.lat, r.lon, code, r.commune, r.kind, r.note, r.contact,
             0 if check["is_simulated"] else 1,
             check["match_count"], check["nearest_km"], "new"))
        rid = cur.lastrowid

    return {"id": rid, "created_at": now, "wilaya": code,
            "satellite": {"confirmed": check["confirmed"],
                          "match_count": check["match_count"],
                          "nearest_km": check["nearest_km"],
                          "is_simulated": check["is_simulated"]}}


@app.get("/api/v1/reports")
def list_reports(wilaya: str | None = None, limit: int = Query(100, ge=1, le=500)):
    """Public queue. Contact details are never returned — they are for coordinators."""
    sql = ("SELECT id, created_at, lat, lon, wilaya, commune, kind, note,"
           " sat_checked, sat_hits, sat_km, status FROM reports")
    args = []
    if wilaya:
        sql += " WHERE wilaya = ?"
        args.append(wilaya)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with db() as conn:
        rows = [dict(r) for r in conn.execute(sql, args)]
    return {"count": len(rows), "reports": rows}


@app.get("/api/v1/summary")
def summary():
    """Everything the home page needs, in one request."""
    fires = fires_payload()
    veg = [f for f in fires["fires"] if f.get("category") != "industrial"]
    active = [f for f in veg if f.get("active")]
    return {
        "fires": {
            "source": fires.get("source"),
            "is_simulated": fires.get("source") == "MOCK",
            "active": len(active),
            "new": sum(1 for f in active if f.get("is_new")),
            "seen_48h": len(veg),
            "active_hours": fires.get("active_hours", 6),
            "generated_at": fires.get("generated_at"),
        },
        "relief": relief.counts(),
    }


@app.get("/api/v1/health")
def health():
    present = {n: os.path.exists(os.path.join(DATA, n)) for n in
               ("risk.json", "fires.json", "exposure.json", "assets_map.json")}
    risk = payload("risk.json", required=False)
    fires = payload("fires.json", required=False)
    return {
        "ok": True,
        "payloads": present,
        "risk_source": risk.get("source") if risk else None,
        "risk_generated_at": risk.get("generated_at") if risk else None,
        "fires_source": fires.get("source") if fires else "MOCK (no FIRMS key)",
    }


# ─── static site ─────────────────────────────────────────────────────────

@app.get("/api", response_class=PlainTextResponse)
def api_index():
    return "\n".join(
        r.path for r in app.routes if getattr(r, "path", "").startswith("/api/"))


app.include_router(relief.router)

# Mounted last: StaticFiles at "/" would otherwise shadow every API route.
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    init_db()
    print("Rased on http://127.0.0.1:8080   (API under /api/v1)")
    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="info")
else:
    init_db()
