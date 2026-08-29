"""Reference table for Algeria's 48 wilayas.

`fuel` classifies each wilaya by what is actually available to burn:

    forest  Tell Atlas - cork oak, Aleppo pine, maquis. Where the deadly fires happen.
    steppe  High plains - alfa grass and cereal. Fast-moving harvest fires, low intensity.
    desert  Sahara - negligible continuous fuel.

This matters because the Fire Weather Index is a pure *weather* index. A July day in
Adrar scores extreme on temperature and humidity alone, but there is nothing there to
carry a fire. Publishing an unmasked FWI map of Algeria would paint the Sahara red and
destroy the credibility of the whole product. See fwi.apply_fuel_mask().
"""

# code, latin name as it appears in geoBoundaries, arabic, french, fuel class
WILAYAS = [
    ("01", "Adrar",            "أدرار",          "Adrar",            "desert"),
    ("02", "Chlef",            "الشلف",          "Chlef",            "forest"),
    ("03", "Laghouat",         "الأغواط",        "Laghouat",         "steppe"),
    ("04", "Oum El Bouaghi",   "أم البواقي",     "Oum El Bouaghi",   "forest"),
    ("05", "Batna",            "باتنة",          "Batna",            "forest"),
    ("06", "Bejaia",           "بجاية",          "Béjaïa",           "forest"),
    ("07", "Biskra",           "بسكرة",          "Biskra",           "steppe"),
    ("08", "Béchar",           "بشار",           "Béchar",           "desert"),
    ("09", "Blida",            "البليدة",        "Blida",            "forest"),
    ("10", "Bouira",           "البويرة",        "Bouira",           "forest"),
    ("11", "Tamanrasset",      "تمنراست",        "Tamanrasset",      "desert"),
    ("12", "Tébessa",          "تبسة",           "Tébessa",          "forest"),
    ("13", "Tlemcen",          "تلمسان",         "Tlemcen",          "forest"),
    ("14", "Tiaret",           "تيارت",          "Tiaret",           "forest"),
    ("15", "Tizi Ouzou",       "تيزي وزو",       "Tizi Ouzou",       "forest"),
    ("16", "Algiers",          "الجزائر",        "Alger",            "forest"),
    ("17", "Djelfa",           "الجلفة",         "Djelfa",           "steppe"),
    ("18", "Jijel",            "جيجل",           "Jijel",            "forest"),
    ("19", "Sétif",            "سطيف",           "Sétif",            "forest"),
    ("20", "Saïda",            "سعيدة",          "Saïda",            "forest"),
    ("21", "Skikda",           "سكيكدة",         "Skikda",           "forest"),
    ("22", "Sidi Bel Abbès",   "سيدي بلعباس",    "Sidi Bel Abbès",   "forest"),
    ("23", "Annaba",           "عنابة",          "Annaba",           "forest"),
    ("24", "Guelma",           "قالمة",          "Guelma",           "forest"),
    ("25", "Constantine",      "قسنطينة",        "Constantine",      "forest"),
    ("26", "Médéa",            "المدية",         "Médéa",            "forest"),
    ("27", "Mostaganem",       "مستغانم",        "Mostaganem",       "forest"),
    ("28", "M'Sila",           "المسيلة",        "M'Sila",           "steppe"),
    ("29", "Mascara",          "معسكر",          "Mascara",          "forest"),
    ("30", "Ouargla",          "ورقلة",          "Ouargla",          "desert"),
    ("31", "Oran",             "وهران",          "Oran",             "forest"),
    ("32", "El Bayadh",        "البيض",          "El Bayadh",        "steppe"),
    ("33", "Illizi",           "إليزي",          "Illizi",           "desert"),
    ("34", "Bordj Bou Arreridj","برج بوعريريج",  "Bordj Bou Arréridj","forest"),
    ("35", "Boumerdès",        "بومرداس",        "Boumerdès",        "forest"),
    ("36", "El Tarf",          "الطارف",         "El Tarf",          "forest"),
    ("37", "Tindouf",          "تندوف",          "Tindouf",          "desert"),
    ("38", "Tissemsilt",       "تيسمسيلت",       "Tissemsilt",       "forest"),
    ("39", "El Oued",          "الوادي",         "El Oued",          "desert"),
    ("40", "Khenchela",        "خنشلة",          "Khenchela",        "forest"),
    ("41", "Souk Ahras",       "سوق أهراس",      "Souk Ahras",       "forest"),
    ("42", "Tipaza",           "تيبازة",         "Tipaza",           "forest"),
    ("43", "Mila",             "ميلة",           "Mila",             "forest"),
    ("44", "Aïn Defla",        "عين الدفلى",     "Aïn Defla",        "forest"),
    ("45", "Naâma",            "النعامة",        "Naâma",            "steppe"),
    ("46", "Aïn Témouchent",   "عين تموشنت",     "Aïn Témouchent",   "forest"),
    ("47", "Ghardaia",         "غرداية",         "Ghardaïa",         "desert"),
    ("48", "Relizane",         "غليزان",         "Relizane",         "forest"),
]

FIELDS = ("code", "name_latin", "name_ar", "name_fr", "fuel")


def as_dicts():
    return [dict(zip(FIELDS, row)) for row in WILAYAS]


def _key(s: str) -> str:
    """Normalise a wilaya name for matching.

    geoBoundaries ships some names with stray bidi control characters
    (Bordj Bou Arreridj carries a trailing U+200E LEFT-TO-RIGHT MARK), so a plain
    string comparison silently fails on exactly one wilaya. Strip the invisibles.
    """
    return "".join(c for c in s if c not in "‎‏‪‫‬").strip().lower()


BY_LATIN = {_key(row[1]): dict(zip(FIELDS, row)) for row in WILAYAS}
BY_CODE = {row[0]: dict(zip(FIELDS, row)) for row in WILAYAS}


def lookup(name_latin: str):
    return BY_LATIN.get(_key(name_latin))
