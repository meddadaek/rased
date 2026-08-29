"""Import the field-verified Jijel relief data collected by Sanad.

    python import_sanad.py

Source: منصة سند (Quanta Club) — https://sanad-ca736.web.app
Route:  transcribed from the Hiba Algeria repository, which curated it
        (https://github.com/oussamabenkortbi/najdat-jijel, migration 0016).

Credit for gathering this belongs to the Sanad team, who did it on the ground.
Rased reproduces it so that a person looking at a fire on the map can reach the
nearest real shelter without changing sites — not to claim the work.

Two decisions inherited from Hiba's curation, both worth keeping:

* Five associations in the original source carried obviously sequential phone
  numbers (0550123456, 0661234567, 0558765432, 0799887766, 0771892345). Those
  are placeholders, not contacts. They stay excluded. Publishing an unverified
  number on a relief platform sends people to a wrong number during an emergency.
* Everything here is marked verified, because a field team actually confirmed it.
  That is the opposite of the OSM-derived shelter candidates, which are marked
  'candidate' precisely because nobody has checked them.

Re-running is safe: records are matched by name and wilaya and updated in place.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "app"))

import relief  # noqa: E402

SOURCE = "منصة سند (Quanta Club) — sanad-ca736.web.app"
JIJEL = "18"

# ─── reception centres ───────────────────────────────────────────────────
# name, commune, address, lat, lon, phone, is_shelter, capacity note
HUBS = [
    ("مركز التكوين المهني بوهراوة أحمد (CFPA)", "الشقفة",
     "الشقفة مركز، محاذاة الطريق الرئيسي", 36.77237, 5.95213, "034 56 21 52", True,
     "مجهز لاستقبال العائلات • دورات مياه وأفرشة"),
    ("دار الشباب الشهيد بوناب الرشيد", "جيجل",
     "حي الفرسان، بن شعبان", 36.8120, 5.7720, "034 47 43 75", True,
     "استقبال وفرز القوافل الوطنية وتوجيهها"),
    ("مركب الشباب الشهيد شاطر عبد القادر", "جيجل",
     "حي 1000 مسكن، جيجل", 36.8180, 5.7650, "030 49 08 22", True,
     "مجمع شبابي مجهز للإيواء المؤقت والرعاية"),
    ("ديوان مؤسسات الشباب (ODEJ)", "جيجل",
     "وسط مدينة جيجل", 36.8120, 5.7660, "034 47 43 75", False,
     "خلية التنسيق الولائية للمؤسسات الشبانية"),
    ("مركز استقبال ومأوى تاكسنة", "تاكسنة",
     "بلدية تاكسنة مركز", 36.6667, 5.7833, "034 49 10 20", True,
     "استقبال 65+ حالة وإسعاف الأسر المتضررة"),
    ("مركز إيواء العرايب", "الميلية",
     "منطقة العرايب، طريق برج العنصر", 36.7500, 6.2667, "034 52 11 22", True,
     "مخيم استقبال وإيواء للأسر المُجلية من تنفدور"),
    ("مقر بلدية بوراوي بلهادف (APC)", "بوراوي بلهادف",
     "مقر المجلس الشعبي البلدي", 36.6167, 5.9500, "034 46 51 68", False,
     "نقطة استقبال وتوجيه المساعدات للمداشر الجبلية"),
]

# ─── associations / collection points ────────────────────────────────────
# name, commune, address, phone, accepts, note
POINTS = [
    ("جمعية خاوة فالخير – جيجل", "جيجل", "حي الكريط، قرب صيدلية نخول", "0744160656",
     "غذاء,ماء,مواد إغاثة",
     "خلية أزمة وإمداد غذائي — جمع التبرعات العينية والغذائية وتوجيهها للقرى الجبلية"),
    ("جمعية الياقوت الأزرق الثقافية", "جيجل", "حي الفرسان – بن شعبان", "034 47 43 75",
     "غذاء,ملابس,أغطية,نظافة,مواد إغاثة",
     "نقطة استقبال وفرز — استقبال مساهمات المواطنين وتنسيق توزيعها"),
    ("جمعية نور للناس – جيجل", "جيجل", "فوبور، وسط جيجل", "0770999153",
     "مستلزمات طبية,غذاء",
     "مستلزمات طبية وأدوية — شراء واستقبال المستلزمات الطبية والأدوية العاجلة"),
    ("جمعية نجدة الإنسانية للصحة والإغاثة", "جيجل", "فرع ولاية جيجل", "0541600236",
     "مستلزمات طبية",
     "إغاثة صحية وإسعافات — قوافل طبية ورعاية صحية ميدانية"),
    ("جمعية قوافل الخير (بني حبيبي)", "الجمعة بني حبيبي", "شارع عوار حسين، بني حبيبي",
     "0551444192", "غذاء,أغطية,مواد إغاثة",
     "تنسيق ريفي وتوزيع مباشر — شبكة تواصل مع عائلات المشاتي والقرى المتضررة"),
]

# ─── needs by commune ────────────────────────────────────────────────────
# Sanad's priority scale maps onto ours: critical stays critical, high becomes
# urgent, medium becomes normal.
PRIORITY = {"critical": "critical", "high": "urgent", "medium": "normal"}

NEEDS = [
    ("الجمعة بني حبيبي", "critical",
     "المناطق السكنية، مشاتي الشارع الرئيسي والمحيط الغابي",
     "أولوية إنسانية قصوى؛ تأكد من احتياج الأسر المسجلة محليًا قبل إرسال الشحنات.",
     ["مياه معقمة", "حليب وحفاضات أطفال", "أفرشة وبطانيات", "طرود غذائية"]),
    ("تاكسنة", "high",
     "بوخلف، بوزنطار، الرازيانج، الغريانة، أم ثلاثين، الكلم 14",
     "مسالك جبلية وعرة؛ تتطلب مركبات دفع رباعي وشاحنات صغيرة محلية (توزيع آخر ميل).",
     ["مركبات 4x4 للتوزيع وأعلاف للمواشي", "خيام وقياطين", "أدوات تنظيف ومجارف"]),
    ("زيامة منصورية", "high",
     "أولاد علي، الشريعية، محيط تازة والكهوف العجيبة",
     "تضاريس ومنعطفات وعرة؛ لا تعتمد على الشاحنات الكبيرة وحدها لدخول القرى.",
     ["مياه صالحة للشرب", "أواني وأدوات طبخ", "أفرشة", "مواد تعقيم"]),
    ("الشقفة", "high",
     "منطقة السبت، محيط الشقفة وبرج الطهر، المداشر الغابية",
     "الأفرشة والبطانيات وأدوات التنظيف ومياه الشرب أهم حاليًا من تكرار المواد الغذائية.",
     ["أفرشة وبطانيات", "أدوات تنظيف ومكانس", "خراطيم ودلاء", "مياه نقية"]),
    ("الميلية", "high",
     "مشاط، بوعقبة والمناطق الغابية المحيطة",
     "مركز استقبال رئيسي للقوافل الشرقية؛ التوجيه للمداشر الغابية عبر شاحنات صغيرة.",
     ["أدوات سباكة وكهرباء", "مضخات مياه", "طرود غذائية", "دعم صحي"]),
    ("العنصر", "medium",
     "مناطق متفرقة ظهرت في عمليات الإجلاء الميداني",
     "بيانات مجمّعة — يجب التأكد بالتواصل مع الجهة المُنسّقة قبل التحرك.",
     ["أفرشة", "طرود غذائية", "أدوات تنظيف"]),
]


def main():
    relief.configure(os.path.join(HERE, "rased.db"))
    stamp = relief.now()
    added = {"hubs": 0, "points": 0, "needs": 0}
    updated = {"hubs": 0, "points": 0, "needs": 0}

    with relief.db() as conn:
        # ── reception centres ────────────────────────────────────────────
        for name, commune, address, lat, lon, phone, is_shelter, note in HUBS:
            kind = "shelter" if is_shelter else "coordination"
            row = conn.execute(
                "SELECT id FROM shelters WHERE name=? AND wilaya=?", (name, JIJEL)
            ).fetchone()
            notes = note + " | المصدر: " + SOURCE
            if row:
                conn.execute(
                    "UPDATE shelters SET commune=?,address=?,kind=?,phone=?,lat=?,"
                    "lon=?,notes=?,status='open' WHERE id=?",
                    (commune, address, kind, phone, lat, lon, notes, row["id"]))
                updated["hubs"] += 1
            else:
                conn.execute(
                    "INSERT INTO shelters (created_at,name,wilaya,commune,address,"
                    "kind,capacity,phone,lat,lon,notes,status)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,'open')",
                    (stamp, name, JIJEL, commune, address, kind, None, phone,
                     lat, lon, notes))
                added["hubs"] += 1

        # ── associations ─────────────────────────────────────────────────
        for name, commune, address, phone, accepts, note in POINTS:
            row = conn.execute(
                "SELECT id FROM collection_points WHERE name=? AND wilaya=?",
                (name, JIJEL)).fetchone()
            if row:
                conn.execute(
                    "UPDATE collection_points SET commune=?,address=?,phone=?,"
                    "accepts=?,notes=?,source=?,verified=1 WHERE id=?",
                    (commune, address, phone, accepts, note, SOURCE, row["id"]))
                updated["points"] += 1
            else:
                conn.execute(
                    "INSERT INTO collection_points (created_at,name,wilaya,commune,"
                    "address,phone,accepts,notes,source,status,verified)"
                    " VALUES (?,?,?,?,?,?,?,?,?,'open',1)",
                    (stamp, name, JIJEL, commune, address, phone, accepts,
                     note, SOURCE))
                added["points"] += 1

        # ── needs ────────────────────────────────────────────────────────
        for commune, prio, places, advice, items in NEEDS:
            urgency = PRIORITY.get(prio, "normal")
            notes = places + " — " + advice + " | المصدر: " + SOURCE
            for item in items:
                row = conn.execute(
                    "SELECT id FROM needs WHERE item=? AND commune=? AND wilaya=?",
                    (item, commune, JIJEL)).fetchone()
                if row:
                    conn.execute("UPDATE needs SET urgency=?,notes=?,updated_at=? "
                                 "WHERE id=?", (urgency, notes, stamp, row["id"]))
                    updated["needs"] += 1
                else:
                    conn.execute(
                        "INSERT INTO needs (created_at,updated_at,wilaya,commune,"
                        "place,item,quantity,urgency,phone,notes,status)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,'open')",
                        (stamp, stamp, JIJEL, commune, places, item, None,
                         urgency, None, notes))
                    added["needs"] += 1

    print("Sanad field data imported (credit: %s)\n" % SOURCE)
    for k in ("hubs", "points", "needs"):
        print("  %-7s +%d new, %d updated" % (k, added[k], updated[k]))
    print("\n5 associations from the source remain excluded: their phone numbers")
    print("were sequential placeholders, not real contacts.")


if __name__ == "__main__":
    main()
