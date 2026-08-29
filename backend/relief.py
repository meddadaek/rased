"""Relief coordination: shelters, needs, and offers of help.

Monitoring tells you a village is in danger. This is what turns that into help
actually arriving — where displaced people can sleep, what they actually need,
and who has offered to carry it there.

Kept in its own module because it is a different kind of thing from the rest of
Rased: the monitoring side is derived from satellites and physics and is
recomputed from scratch on every run, while this is human-entered data that must
never be silently regenerated or lost.

Design decisions worth stating:

* Nothing is ever deleted. A need moves open -> pledged -> delivered, so the
  record of what a place asked for survives the emergency and can be reviewed
  afterwards.
* Pledging against a need takes it out of the open queue immediately, so two
  donors do not both drive to the same village with the same water.
* Phone numbers here ARE public, unlike the ones on fire reports. A shelter or a
  donation point that nobody can call is useless; a citizen reporting smoke has
  no reason to be contacted by strangers.
* Everything a member of the public submits lands as unverified. Coordinators
  promote it. During the 2021 fires the damage from confidently wrong
  information was its own emergency.
"""
import datetime as dt
import sqlite3

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

import catalog
import verify

router = APIRouter(prefix="/api/v1", tags=["relief"])

URGENCIES = ("critical", "urgent", "normal")
NEED_STATUS = ("open", "pledged", "delivered")
OFFER_KINDS = ("supply", "transport", "volunteer", "shelter")

_DB_PATH = None


def configure(db_path):
    global _DB_PATH
    _DB_PATH = db_path
    init_schema()


def db():
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def init_schema():
    with db() as conn:
        verify.init(conn)
        catalog.init_sos(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shelters (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                name       TEXT NOT NULL,
                wilaya     TEXT,
                commune    TEXT,
                address    TEXT,
                kind       TEXT NOT NULL DEFAULT 'shelter',
                capacity   INTEGER,
                phone      TEXT,
                lat        REAL,
                lon        REAL,
                notes      TEXT,
                status     TEXT NOT NULL DEFAULT 'reported'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS needs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                wilaya     TEXT,
                commune    TEXT,
                place      TEXT,
                item       TEXT NOT NULL,
                quantity   TEXT,
                urgency    TEXT NOT NULL DEFAULT 'normal',
                category   TEXT,
                phone      TEXT,
                notes      TEXT,
                status     TEXT NOT NULL DEFAULT 'open'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS offers (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                kind       TEXT NOT NULL,
                name       TEXT,
                wilaya     TEXT,
                detail     TEXT NOT NULL,
                phone      TEXT,
                need_id    INTEGER REFERENCES needs(id),
                status     TEXT NOT NULL DEFAULT 'open'
            )
        """)
        # Standing aid organisations: associations that receive and distribute
        # donations. Distinct from `offers`, which are one-off pledges.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS collection_points (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                name       TEXT NOT NULL,
                wilaya     TEXT,
                commune    TEXT,
                address    TEXT,
                phone      TEXT,
                accepts    TEXT,
                notes      TEXT,
                lat        REAL,
                lon        REAL,
                source     TEXT,
                status     TEXT NOT NULL DEFAULT 'open',
                verified   INTEGER NOT NULL DEFAULT 0
            )
        """)
        for stmt in (
            "CREATE INDEX IF NOT EXISTS idx_points_wilaya ON collection_points(wilaya)",
            "CREATE INDEX IF NOT EXISTS idx_needs_status ON needs(status)",
            "CREATE INDEX IF NOT EXISTS idx_needs_wilaya ON needs(wilaya)",
            "CREATE INDEX IF NOT EXISTS idx_shelters_wilaya ON shelters(wilaya)",
            "CREATE INDEX IF NOT EXISTS idx_offers_need ON offers(need_id)",
        ):
            conn.execute(stmt)


# ─── models ──────────────────────────────────────────────────────────────

class ShelterIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=160)
    wilaya: str | None = Field(None, max_length=4)
    commune: str | None = Field(None, max_length=120)
    address: str | None = Field(None, max_length=300)
    kind: str = Field("shelter", max_length=32)
    capacity: int | None = Field(None, ge=0, le=100000)
    phone: str | None = Field(None, max_length=60)
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    notes: str | None = Field(None, max_length=600)


class NeedIn(BaseModel):
    item: str = Field(..., min_length=2, max_length=120)
    category: str | None = Field(None, max_length=32)
    wilaya: str | None = Field(None, max_length=4)
    commune: str | None = Field(None, max_length=120)
    place: str | None = Field(None, max_length=160)
    quantity: str | None = Field(None, max_length=80)
    urgency: str = Field("normal", max_length=16)
    phone: str | None = Field(None, max_length=60)
    notes: str | None = Field(None, max_length=600)


class OfferIn(BaseModel):
    kind: str = Field(..., max_length=32)
    detail: str = Field(..., min_length=2, max_length=400)
    name: str | None = Field(None, max_length=120)
    wilaya: str | None = Field(None, max_length=4)
    phone: str | None = Field(None, max_length=60)
    need_id: int | None = None


# ─── community verification ──────────────────────────────────────────────

class ConfirmIn(BaseModel):
    entity: str = Field(..., max_length=16)
    entity_id: int
    verdict: str = Field("confirm", max_length=10)
    note: str | None = Field(None, max_length=300)


@router.post("/confirmations", status_code=201)
def add_confirmation(c: ConfirmIn, request: Request):
    fp = verify.fingerprint(request)
    try:
        with db() as conn:
            return verify.record(conn, c.entity, c.entity_id, c.verdict, fp,
                                 c.note, now())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/confirmations")
def get_confirmations(entity: str, entity_id: int):
    with db() as conn:
        counts = verify.tally(conn, entity, [entity_id]).get(entity_id, {})
    return {"entity": entity, "id": entity_id,
            "confirms": counts.get("confirms", 0),
            "disputes": counts.get("disputes", 0)}


# ─── shelters ────────────────────────────────────────────────────────────

@router.get("/shelters")
def list_shelters(wilaya: str | None = None, include_unverified: bool = False):
    """Verified and community-confirmed entries only, unless explicitly asked.

    An unconfirmed shelter is a lead for a coordinator, not an address to send a
    displaced family to. Showing it by default puts the burden of telling the
    difference on the person least able to carry it, so the default listing is
    the trustworthy set and everything else is opt-in.
    """
    sql, args = "SELECT * FROM shelters", []
    where = []
    if wilaya:
        where.append("wilaya = ?")
        args.append(wilaya)
    if not include_unverified:
        where.append("(status = 'open' OR id IN (SELECT entity_id FROM confirmations"
                     " WHERE entity='shelter' AND verdict='confirm'"
                     " GROUP BY entity_id HAVING COUNT(*) >= %d))" % verify.CONFIRMS_TO_PROMOTE)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY status DESC, created_at DESC"
    with db() as conn:
        rows = [dict(r) for r in conn.execute(sql, args)]
        verify.annotate(conn, "shelter", rows)
        total = conn.execute("SELECT COUNT(*) c FROM shelters").fetchone()["c"]
    # Disputed entries are never presented as usable, whatever their status.
    if not include_unverified:
        rows = [r for r in rows if r["trust"] != "disputed"]
    return {"count": len(rows), "total": total,
            "hidden_unverified": total - len(rows), "shelters": rows}


@router.post("/shelters", status_code=201)
def create_shelter(s: ShelterIn):
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO shelters (created_at,name,wilaya,commune,address,kind,"
            "capacity,phone,lat,lon,notes,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (now(), s.name, s.wilaya, s.commune, s.address, s.kind, s.capacity,
             s.phone, s.lat, s.lon, s.notes, "reported"))
    return {"id": cur.lastrowid, "status": "reported"}


# ─── needs ───────────────────────────────────────────────────────────────

@router.get("/needs")
def list_needs(wilaya: str | None = None, status: str | None = None,
               category: str | None = None,
               limit: int = Query(300, ge=1, le=1000)):
    sql = ("SELECT n.*, (SELECT COUNT(*) FROM offers o WHERE o.need_id = n.id"
           " AND o.status <> 'cancelled') AS pledges FROM needs n")
    where, args = [], []
    if wilaya:
        where.append("n.wilaya = ?")
        args.append(wilaya)
    if status:
        where.append("n.status = ?")
        args.append(status)
    if category:
        where.append("n.category = ?")
        args.append(category)
    if where:
        sql += " WHERE " + " AND ".join(where)
    # Critical first, then oldest: a need that has waited longest outranks a
    # fresher one of the same severity.
    sql += (" ORDER BY CASE n.urgency WHEN 'critical' THEN 0 WHEN 'urgent' THEN 1"
            " ELSE 2 END, n.created_at ASC LIMIT ?")
    args.append(limit)
    with db() as conn:
        rows = [dict(r) for r in conn.execute(sql, args)]
        verify.annotate(conn, "need", rows)
    return {"count": len(rows), "needs": rows}


@router.post("/needs", status_code=201)
def create_need(n: NeedIn):
    urgency = n.urgency if n.urgency in URGENCIES else "normal"
    # Fall back to keyword classification so a need typed in a hurry still lands
    # in a bucket someone can filter on.
    cat = n.category if n.category in catalog.BY_SLUG else catalog.classify(n.item)
    stamp = now()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO needs (created_at,updated_at,wilaya,commune,place,item,"
            "quantity,urgency,phone,notes,status,category)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (stamp, stamp, n.wilaya, n.commune, n.place, n.item, n.quantity,
             urgency, n.phone, n.notes, "open", cat))
    return {"id": cur.lastrowid, "status": "open", "urgency": urgency, "category": cat}


@router.post("/needs/{need_id}/status")
def set_need_status(need_id: int, status: str = Query(..., max_length=16)):
    if status not in NEED_STATUS:
        raise HTTPException(400, "status must be one of %s" % (NEED_STATUS,))
    with db() as conn:
        cur = conn.execute("UPDATE needs SET status = ?, updated_at = ? WHERE id = ?",
                           (status, now(), need_id))
        if not cur.rowcount:
            raise HTTPException(404, "no need with id %d" % need_id)
    return {"id": need_id, "status": status}


# ─── offers ──────────────────────────────────────────────────────────────

@router.get("/offers")
def list_offers(kind: str | None = None, wilaya: str | None = None):
    sql, where, args = "SELECT * FROM offers", [], []
    if kind:
        where.append("kind = ?")
        args.append(kind)
    if wilaya:
        where.append("wilaya = ?")
        args.append(wilaya)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT 400"
    with db() as conn:
        rows = [dict(r) for r in conn.execute(sql, args)]
    return {"count": len(rows), "offers": rows}


@router.post("/offers", status_code=201)
def create_offer(o: OfferIn):
    kind = o.kind if o.kind in OFFER_KINDS else "supply"
    stamp = now()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO offers (created_at,kind,name,wilaya,detail,phone,need_id,status)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (stamp, kind, o.name, o.wilaya, o.detail, o.phone, o.need_id, "open"))
        # Claiming a specific need closes it to further pledges straight away.
        if o.need_id:
            conn.execute("UPDATE needs SET status='pledged', updated_at=? "
                         "WHERE id=? AND status='open'", (stamp, o.need_id))
    return {"id": cur.lastrowid, "status": "open", "kind": kind}


@router.get("/collection-points")
def list_points(wilaya: str | None = None, include_unverified: bool = False):
    sql, args = "SELECT * FROM collection_points", []
    where = []
    if wilaya:
        where.append("wilaya = ?")
        args.append(wilaya)
    if not include_unverified:
        where.append("(verified = 1 OR id IN (SELECT entity_id FROM confirmations"
                     " WHERE entity='point' AND verdict='confirm'"
                     " GROUP BY entity_id HAVING COUNT(*) >= %d))" % verify.CONFIRMS_TO_PROMOTE)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY verified DESC, name"
    with db() as conn:
        rows = [dict(r) for r in conn.execute(sql, args)]
        verify.annotate(conn, "point", rows)
    for r in rows:
        r["accepts"] = (r.get("accepts") or "").split(",") if r.get("accepts") else []
    if not include_unverified:
        rows = [r for r in rows if r["trust"] != "disputed"]
    return {"count": len(rows), "points": rows}


@router.get("/categories")
def list_categories():
    """Need taxonomy, aligned with Hiba's so records stay exchangeable."""
    return {"count": len(catalog.CATEGORIES), "categories": catalog.as_list()}


class SosIn(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=120)
    phone: str = Field(..., min_length=5, max_length=40)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    people: int | None = Field(None, ge=1, le=500)
    note: str | None = Field(None, max_length=400)


@router.post("/sos", status_code=201)
def create_sos(s: SosIn):
    """An SOS from someone in immediate danger.

    Open to anyone without an account: a person cut off by fire is not going to
    register first. Deliberately NOT readable through the public API — this is a
    named person's live position during a disaster, which is exactly the data
    that must not be browsable. Coordinators read it from the database directly.
    """
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO emergency_sos (created_at,full_name,phone,lat,lon,people,"
            "note,status) VALUES (?,?,?,?,?,?,?,'open')",
            (catalog.now(), s.full_name, s.phone, s.lat, s.lon, s.people, s.note))
    return {"id": cur.lastrowid, "received": True,
            "reminder": "اتصل بالحماية المدنية 14 أو 1021 — هذا النموذج لا يستدعي النجدة"}


def counts():
    """Aggregates for the home page, in one round trip."""
    with db() as conn:
        row = conn.execute("""
            SELECT
              (SELECT COUNT(*) FROM needs WHERE status='open') AS needs_open,
              (SELECT COUNT(*) FROM needs WHERE status='open' AND urgency='critical')
                  AS needs_critical,
              (SELECT COUNT(*) FROM needs WHERE status='delivered') AS needs_delivered,
              (SELECT COUNT(*) FROM shelters) AS shelters,
              (SELECT COUNT(*) FROM offers WHERE status='open') AS offers_open,
              (SELECT COUNT(*) FROM collection_points) AS points,
              (SELECT COUNT(*) FROM shelters WHERE status='open') AS shelters_open
        """).fetchone()
    return dict(row)
