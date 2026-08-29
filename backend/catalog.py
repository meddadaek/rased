"""Need categories and the emergency SOS channel.

The category list starts from the taxonomy Hiba Algeria uses (migration 0009) so
that a need written here means the same thing as a need written there, and the
two systems could exchange records without translation.

Two additions on top of theirs:

* `animal_feed` — livestock. Both Hiba and Sanad file fodder under "other", but
  in Kabylie and the Tell a family's animals are its income, and after a fire the
  grazing is gone before the houses are. Sanad's own Texenna entry asked for
  "مركبات 4x4 للتوزيع وأعلاف للمواشي" — the need was already being expressed and
  had nowhere to go. A category makes it countable, and therefore fundable.
* `animal_care` — veterinary treatment for burned animals, which is a different
  request from feed and arrives on a different truck.
"""
import datetime as dt

# slug, Arabic, French, default unit, icon
CATEGORIES = [
    ("water",                  "ماء",                      "Eau",                    "لتر",    "💧"),
    ("food",                   "غذاء",                     "Nourriture",             "حصة",    "🥫"),
    ("baby_supplies",          "مستلزمات أطفال",           "Fournitures bébé",       "علبة",   "🍼"),
    ("blankets",               "أغطية وبطانيات",           "Couvertures",            "قطعة",   "🛏️"),
    ("clothing",               "ملابس",                    "Vêtements",              "قطعة",   "👕"),
    ("hygiene",                "مواد نظافة",               "Hygiène",                "علبة",   "🧼"),
    ("medical",                "أدوية ومستلزمات طبية",     "Médicaments",            "علبة",   "💊"),
    ("kitchenware",            "أدوات طبخ",                "Ustensiles de cuisine",  "قطعة",   "🍳"),
    # Both from Hiba's live board: bottled cooking gas is its own logistics
    # problem (heavy, regulated, and the single most requested item in Gaous),
    # and manpower is a need that no amount of donated goods substitutes for.
    ("cooking_gas",            "قارورات غاز",              "Bouteilles de gaz",      "قارورة", "🔥"),
    ("manpower",               "يد عاملة ومتطوعون",        "Main-d'œuvre, bénévoles", "شخص",   "🧑‍🤝‍🧑"),
    ("shelter",                "مأوى وخيام",               "Abri et tentes",         "قطعة",   "⛺"),
    ("animal_feed",            "أعلاف للمواشي",            "Fourrage pour bétail",   "قنطار",  "🐑"),
    ("animal_care",            "رعاية بيطرية",             "Soins vétérinaires",     "حالة",   "🐕"),
    ("construction_materials", "مواد بناء",                "Matériaux de construction", "طن",  "🧱"),
    ("relief_materials",       "مواد إغاثة متنوعة",        "Matériel de secours",    "كرتون",  "📦"),
    ("transport",              "نقل ومركبات",              "Transport et véhicules", "مركبة",  "🚚"),
    ("other",                  "أخرى",                     "Autre",                  "قطعة",   "•"),
]

BY_SLUG = {c[0]: {"slug": c[0], "name_ar": c[1], "name_fr": c[2],
                  "unit": c[3], "icon": c[4]} for c in CATEGORIES}


def as_list():
    return [BY_SLUG[c[0]] for c in CATEGORIES]


# Keyword hints used to file free-text needs into a category. Deliberately
# conservative: an unmatched need becomes "other" rather than being guessed into
# the wrong truck.
HINTS = {
    "water": ["ماء", "مياه", "eau", "شرب"],
    "food": ["غذائ", "طرود", "أكل", "nourriture", "alimentaire", "حليب"],
    "baby_supplies": ["حفاض", "أطفال", "رضع", "bébé", "couches"],
    "blankets": ["أفرشة", "بطاني", "أغطية", "couverture", "matelas"],
    "clothing": ["ملابس", "لباس", "vêtement"],
    "hygiene": ["تنظيف", "نظافة", "تعقيم", "مكانس", "hygiène", "savon"],
    "medical": ["دواء", "أدوية", "طبي", "صحي", "إسعاف", "médic", "santé"],
    "kitchenware": ["أواني", "طبخ", "cuisine", "ustensile"],
    "shelter": ["خيام", "خيمة", "قياطين", "مأوى", "tente", "abri"],
    "animal_feed": ["أعلاف", "علف", "مواشي", "ماشية", "بهائم", "fourrage", "bétail",
                    "cheptel", "دواجن", "أغنام", "أبقار"],
    "animal_care": ["بيطر", "vétérin", "حيوان"],
    "construction_materials": ["بناء", "سباك", "كهرباء", "مضخات", "construction"],
    "transport": ["مركبات", "شاحن", "نقل", "4x4", "camion", "véhicule"],
    "cooking_gas": ["قارورات غاز", "قارورة غاز", "غاز", "بوتان", "gaz", "butane"],
    "manpower": ["يد عاملة", "متطوع", "عمال", "سواعد", "bénévole", "main-d'œuvre"],
}


def classify(text):
    """Best-effort category for a free-text need."""
    if not text:
        return "other"
    low = text.lower()
    for slug, words in HINTS.items():
        for w in words:
            if w.lower() in low:
                return slug
    return "other"


# ─── emergency SOS ───────────────────────────────────────────────────────

SOS_SCHEMA = """
CREATE TABLE IF NOT EXISTS emergency_sos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    full_name   TEXT NOT NULL,
    phone       TEXT NOT NULL,
    lat         REAL NOT NULL,
    lon         REAL NOT NULL,
    people      INTEGER,
    note        TEXT,
    wilaya      TEXT,
    status      TEXT NOT NULL DEFAULT 'open'
)
"""


def init_sos(conn):
    conn.execute(SOS_SCHEMA)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sos_created ON emergency_sos(created_at)")


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
