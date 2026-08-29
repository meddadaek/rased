"""Community verification: confirmations and disputes.

Anyone can add a shelter or a need, which is the point — during an emergency the
people who know are not the people with logins. But that also means anyone can
post something false, and sending displaced families to a place that does not
exist is an active harm, not merely bad data.

So a public submission is never trusted on its own:

    reported    submitted; nobody has checked it
    confirmed   two or more independent sources say it is real
    disputed    somebody says it is wrong — still shown, but flagged
    verified    a coordinator, or a field-verified source like Sanad, vouched

A single dispute pulls an entry straight back out of "confirmed". That asymmetry
is deliberate: the cost of showing a fake shelter is much higher than the cost of
showing a real one as unconfirmed for a few hours.

Nothing is ever auto-promoted to `verified` from public input alone, and nothing
is ever deleted by a dispute — hiding a contested entry would let one bad actor
erase a real shelter just as easily as flag a fake one.
"""
import hashlib
import os
import sqlite3

ENTITIES = ("shelter", "need", "point")
TABLE = {"shelter": "shelters", "need": "needs", "point": "collection_points"}

# Two independent confirmations promote an entry: low enough to be reachable in a
# village where three people have signal, high enough that one person cannot
# quietly promote their own submission.
CONFIRMS_TO_PROMOTE = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS confirmations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    entity      TEXT NOT NULL,
    entity_id   INTEGER NOT NULL,
    verdict     TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    note        TEXT,
    UNIQUE(entity, entity_id, fingerprint)
)
"""


def init(conn):
    conn.execute(SCHEMA)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conf_entity "
                 "ON confirmations(entity, entity_id)")


def fingerprint(request):
    """Salted, truncated hash of the caller's address.

    The address itself is never stored. This exists only to stop one source
    stacking confirmations; a disaster-response database should not double as a
    record of who was where. Set RASED_FP_SALT in production — the default is a
    known constant and would make the hashes reversible by anyone with the repo.
    """
    salt = os.environ.get("RASED_FP_SALT", "rased-local-salt")
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    return hashlib.sha256((salt + "|" + ip).encode("utf-8")).hexdigest()[:32]


def tally(conn, entity, ids):
    """confirm/dispute counts for a batch of entities, in one query."""
    ids = [i for i in ids if i is not None]
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        "SELECT entity_id,"
        " SUM(CASE WHEN verdict='confirm' THEN 1 ELSE 0 END) AS confirms,"
        " SUM(CASE WHEN verdict='dispute' THEN 1 ELSE 0 END) AS disputes"
        " FROM confirmations WHERE entity=? AND entity_id IN (" + marks + ")"
        " GROUP BY entity_id", [entity] + list(ids))
    return {r["entity_id"]: {"confirms": r["confirms"] or 0,
                             "disputes": r["disputes"] or 0} for r in rows}


def trust(row, counts):
    """Displayed trust level. Order matters: a dispute outranks confirmations."""
    confirms = counts.get("confirms", 0)
    disputes = counts.get("disputes", 0)
    if row.get("status") == "open" or row.get("verified"):
        return "verified"
    if disputes:
        return "disputed"
    if confirms >= CONFIRMS_TO_PROMOTE:
        return "confirmed"
    return "reported"


def annotate(conn, entity, rows):
    """Attach confirms/disputes/trust to a list of rows, in place."""
    counts = tally(conn, entity, [r.get("id") for r in rows])
    for r in rows:
        c = counts.get(r.get("id"), {})
        r["confirms"] = c.get("confirms", 0)
        r["disputes"] = c.get("disputes", 0)
        r["trust"] = trust(r, c)
    return rows


def record(conn, entity, entity_id, verdict, fp, note=None, now=None):
    """Register one verdict. Re-submitting from the same source replaces it."""
    if entity not in ENTITIES:
        raise ValueError("entity must be one of %s" % (ENTITIES,))
    if verdict not in ("confirm", "dispute"):
        raise ValueError("verdict must be confirm or dispute")

    exists = conn.execute("SELECT 1 FROM %s WHERE id=?" % TABLE[entity],
                          (entity_id,)).fetchone()
    if not exists:
        raise LookupError("no %s with id %s" % (entity, entity_id))

    try:
        conn.execute(
            "INSERT INTO confirmations (created_at,entity,entity_id,verdict,"
            "fingerprint,note) VALUES (?,?,?,?,?,?)",
            (now, entity, entity_id, verdict, fp, note))
    except sqlite3.IntegrityError:
        # One verdict per source per entity; changing your mind is allowed.
        conn.execute(
            "UPDATE confirmations SET verdict=?, note=?, created_at=?"
            " WHERE entity=? AND entity_id=? AND fingerprint=?",
            (verdict, note, now, entity, entity_id, fp))

    counts = tally(conn, entity, [entity_id]).get(entity_id, {})
    row = dict(conn.execute("SELECT * FROM %s WHERE id=?" % TABLE[entity],
                            (entity_id,)).fetchone())
    return {"entity": entity, "id": entity_id, "verdict": verdict,
            "confirms": counts.get("confirms", 0),
            "disputes": counts.get("disputes", 0),
            "trust": trust(row, counts)}
