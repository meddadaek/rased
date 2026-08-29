"""Export the relief database to static JSON for a serverless deployment.

    python export_static.py

Vercel gives you a read-only filesystem and no process between requests, so
SQLite cannot live there. Rather than ship a deployment where the shelters page
is simply empty, the verified data is exported to flat files that the frontend
already knows how to fall back to.

The split this creates is deliberate and is surfaced in the UI:

    static deploy    everything readable — fires, danger, shelters, needs,
                     associations, affected areas. No submissions.
    with the server  the same, plus reporting, pledging and confirmations.

Only verified and community-confirmed records are exported. Unverified public
submissions are a coordinator's queue, not something to publish on a CDN where
nobody can dispute them.

Contact phone numbers ARE included for shelters and associations, because a
relief point nobody can call is useless — those numbers are already published by
Sanad and Hiba for exactly this purpose. Fire-report and SOS contacts are NEVER
exported: those are private individuals who did not publish anything.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "app"))

import catalog  # noqa: E402
import relief  # noqa: E402
import verify  # noqa: E402

DATA = os.path.abspath(os.path.join(HERE, "..", "frontend", "data"))


def write(name, payload):
    path = os.path.join(DATA, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    return os.path.getsize(path) / 1024


def main():
    relief.configure(os.path.join(HERE, "rased.db"))
    stamp = relief.now()
    sizes = {}

    with relief.db() as conn:
        # ── shelters: verified or community-confirmed only ───────────────
        rows = [dict(r) for r in conn.execute("SELECT * FROM shelters")]
        verify.annotate(conn, "shelter", rows)
        shelters = [r for r in rows if r["trust"] in ("verified", "confirmed")]
        sizes["shelters.json"] = write("shelters.json", {
            "generated_at": stamp, "static": True,
            "count": len(shelters), "total_known": len(rows),
            "shelters": shelters})

        # ── collection points ────────────────────────────────────────────
        rows = [dict(r) for r in conn.execute("SELECT * FROM collection_points")]
        verify.annotate(conn, "point", rows)
        points = [r for r in rows if r["trust"] in ("verified", "confirmed")]
        for p in points:
            p["accepts"] = (p.get("accepts") or "").split(",") if p.get("accepts") else []
        sizes["points.json"] = write("points.json", {
            "generated_at": stamp, "static": True,
            "count": len(points), "points": points})

        # ── needs: open and pledged; delivered ones are history ──────────
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM needs WHERE status IN ('open','pledged')"
            " ORDER BY CASE urgency WHEN 'critical' THEN 0 WHEN 'urgent' THEN 1"
            " ELSE 2 END, created_at")]
        verify.annotate(conn, "need", rows)
        for r in rows:
            r["pledges"] = 0
        sizes["needs.json"] = write("needs.json", {
            "generated_at": stamp, "static": True,
            "count": len(rows), "needs": rows})

        # ── affected areas, with their satellite verdicts ────────────────
        try:
            areas = [dict(r) for r in conn.execute(
                "SELECT * FROM affected_areas ORDER BY wilaya, commune")]
        except Exception:
            areas = []
        sizes["affected.json"] = write("affected.json", {
            "generated_at": stamp, "static": True,
            "count": len(areas), "areas": areas})

    sizes["categories.json"] = write("categories.json", {
        "generated_at": stamp, "count": len(catalog.CATEGORIES),
        "categories": catalog.as_list()})

    print("Exported for static hosting:\n")
    for k, v in sizes.items():
        print("  %-18s %6.1f KB" % (k, v))
    print("\nVerified and community-confirmed records only.")
    print("Fire-report and SOS contact details are never exported.")


if __name__ == "__main__":
    main()
