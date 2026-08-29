"""Import the field data published on habadz.life that is not in their repo.

    python import_habadz_live.py

The Hiba Algeria repository carries migration 0016 (the original Sanad hand-off).
Everything added since has gone in through their admin console, so it lives only
on the live site. This transcribes that delta:

    6 collection / reception points, including 4 schools opened as sorting hubs
    3 critical needs from قاوس that post-date the migration
    2 need categories they use and we did not have: cooking gas, and manpower

Verification status is copied from their site exactly. المركب الرياضي الجواري
الشقفة is marked غير موثق there, so it is unverified here too — silently
promoting somebody else's unverified record would defeat the point of showing
the distinction at all.

Credit: field collection by Sanad (Quanta Club) and the Hiba Algeria team.
Re-running is safe; records match on name + wilaya and update in place.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "app"))

import catalog  # noqa: E402
import relief  # noqa: E402

SOURCE = "هبة الجزائر (habadz.life) — جمع ميداني: سند / Quanta Club"
JIJEL = "18"

# name, commune, address, phone, accepts, verified, note
POINTS = [
    ("المركب الرياضي الجواري الشقفة", "الشقفة", "المركب الرياضي الجواري، الشقفة",
     None, "مواد إغاثة", 0, "نقطة تجميع — لم تُوثَّق بعد على المنصة المصدر"),
    ("ثانوية ناصري رمضان", "الطاهير", "الطاهير، ولاية جيجل",
     None, "مواد إغاثة,غذاء", 1, "ثانوية مفتوحة كنقطة تجميع وفرز"),
    ("المركب الرياضي الجواري بلغيموز", "بلغيموز", "المركب الرياضي الجواري بلغيموز",
     "0770397770", "مواد إغاثة,غذاء", 1, "نقطة تجميع بمركب رياضي"),
    ("متوسطة لبيض محمد", "أولاد سويسي", "أولاد سويسي",
     None, "مواد إغاثة", 1, "متوسطة مفتوحة كنقطة تجميع"),
    ("ثانوية لعبني أحمد", "بوشرقة", "بوشرقة",
     None, "مواد إغاثة", 1, "ثانوية مفتوحة كنقطة تجميع"),
    ("الميناء الجاف — قاوس (Port Sec)", "قاوس",
     "الميناء الجاف، بلدية قاوس — Plus Code: 8F87PRR4+8F",
     None, "مواد إغاثة,نقل", 1, "مركز استقبال وفرز القوافل الكبيرة"),
]

# item, commune, category, urgency
NEEDS = [
    ("طابونات للطبخ", "قاوس", "kitchenware", "critical"),
    ("قارورات غاز للطبخ", "قاوس", "cooking_gas", "critical"),
    ("يد عاملة / متطوعون", "قاوس", "manpower", "critical"),
]

NEED_NOTE = ("احتياج ميداني منشور على منصة هبة الجزائر — تأكّد بالاتصال "
             "بالجهة المنسّقة قبل التحرك. | المصدر: " + SOURCE)


def main():
    relief.configure(os.path.join(HERE, "rased.db"))
    stamp = relief.now()
    added = {"points": 0, "needs": 0}
    updated = {"points": 0, "needs": 0}

    with relief.db() as conn:
        for name, commune, address, phone, accepts, verified, note in POINTS:
            row = conn.execute(
                "SELECT id FROM collection_points WHERE name=? AND wilaya=?",
                (name, JIJEL)).fetchone()
            notes = note + " | المصدر: " + SOURCE
            if row:
                conn.execute(
                    "UPDATE collection_points SET commune=?,address=?,phone=?,"
                    "accepts=?,notes=?,source=?,verified=? WHERE id=?",
                    (commune, address, phone, accepts, notes, SOURCE, verified, row["id"]))
                updated["points"] += 1
            else:
                conn.execute(
                    "INSERT INTO collection_points (created_at,name,wilaya,commune,"
                    "address,phone,accepts,notes,source,status,verified)"
                    " VALUES (?,?,?,?,?,?,?,?,?,'open',?)",
                    (stamp, name, JIJEL, commune, address, phone, accepts,
                     notes, SOURCE, verified))
                added["points"] += 1

        for item, commune, cat, urgency in NEEDS:
            row = conn.execute(
                "SELECT id FROM needs WHERE item=? AND commune=? AND wilaya=?",
                (item, commune, JIJEL)).fetchone()
            if row:
                conn.execute("UPDATE needs SET urgency=?,category=?,notes=?,updated_at=?"
                             " WHERE id=?", (urgency, cat, NEED_NOTE, stamp, row["id"]))
                updated["needs"] += 1
            else:
                conn.execute(
                    "INSERT INTO needs (created_at,updated_at,wilaya,commune,place,"
                    "item,quantity,urgency,phone,notes,status,category)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,'open',?)",
                    (stamp, stamp, JIJEL, commune, commune, item, None,
                     urgency, None, NEED_NOTE, cat))
                added["needs"] += 1

    print("Imported from habadz.life (credit: %s)\n" % SOURCE)
    print("  points  +%d new, %d updated" % (added["points"], updated["points"]))
    print("  needs   +%d new, %d updated" % (added["needs"], updated["needs"]))

    unverified = [p[0] for p in POINTS if not p[5]]
    if unverified:
        print("\nCarried over as UNVERIFIED, exactly as the source marks them:")
        for u in unverified:
            print("   -", u)


if __name__ == "__main__":
    main()
