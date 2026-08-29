# راصد · Rased

Early-warning system for forest fires across Algeria's 48 wilayas.

Rased answers the question that comes *before* a relief platform can act: **where is
it going to burn, and what is burning right now?** It is built to complement
[هبة الجزائر / Hiba](https://habadz.life) ([source](https://github.com/oussamabenkortbi/najdat-jijel)),
which coordinates in-kind aid *after* a fire — not to duplicate it.

---

## What is real, and what is not

| Layer | Source | Status |
|---|---|---|
| Fire danger forecast (FWI), 48 wilayas × 7 days | Open-Meteo | **Live** — no API key, no account, no card |
| Wilaya boundaries, names, fuel class | geoBoundaries (ODbL) | **Live** — committed to the repo |
| Basemap | OpenStreetMap via OpenFreeMap | **Live** — no key |
| Fire stations, hospitals, villages, reservoirs | OpenStreetMap / Overpass | **Live** — no key |
| Road routing (station → fire) | OSRM | **Live** — no key |
| Active fire hotspots | NASA FIRMS | **Mock** — needs a free MAP_KEY (see below) |

Real ground truth currently loaded: **410 Protection Civile stations, 2,604 hospitals
and clinics, 9,825 populated places, 10,593 schools, 252 reservoirs.**

The UI labels the fire panel as simulated whenever the FIRMS key is absent. An
unlabelled fake fire on a fire map is the one failure this project cannot afford.

### Enabling real fire data

FIRMS needs a MAP_KEY. It is free and asks only for an email address — no card:

    https://firms.modaps.eosdis.nasa.gov/api/map_key/

Then:

```bash
export RASED_FIRMS_KEY=your_key_here
python backend/app/firms.py --days 2
```

That writes `frontend/data/fires.json` and the badge flips to live automatically.

---

## Exposure analysis — the part that is actually operational

A dot on a map saying "fire" is not useful. `backend/app/exposure.py` answers the
questions a coordinator actually has:

- **who is in the way** — populated places within 5 km and 10 km of each front,
  with population totals
- **who can get there** — nearest Protection Civile unit, with the *real road*
  distance and drive time from OSRM, because 5 km across a ravine in Kabylie can
  be a 40 minute drive
- **where casualties go** — nearest hospital or clinic
- **which wilaya to pre-position for** — the same figures aggregated to wilaya level

That last aggregate is the number a relief platform needs *before* the requests
start arriving, which is exactly what Hiba currently learns from manual field
reports.

Selection uses great-circle distance through a bucketed spatial index; only the 25
most powerful fires get a routed answer, to stay polite on OSRM's shared demo server.

Population caveat: OSM carries a `population` tag for only about 9% of Algerian
places. The rest fall back to a conservative estimate by settlement class
(city/town/village/hamlet). These figures are for **ranking**, not for census work,
and the UI says so.

## The science

The danger index is the **Canadian Forest Fire Weather Index System**
(Van Wagner & Pickett 1985, CFS Technical Report 33) — the same equation set EFFIS
and GWIS run across the Mediterranean. `backend/app/fwi.py` reproduces the published
worked example to four decimal places.

```
FFMC  fine fuel moisture    litter, cured grass      ~2/3 day lag
DMC   duff moisture         loose organic layer      ~12 day lag
DC    drought code          deep compact organic     ~52 day lag
ISI   spread index          FFMC + wind
BUI   buildup index         DMC + DC
FWI   fire weather index    ISI + BUI
```

Two things matter more than the equations:

**Spin-up.** The moisture codes carry memory. The drought state on 29 August is a
consequence of June and July, so the chain is integrated across all 72 days of
available history before a single forecast day is emitted. A cold start would report
a rain-soaked forest in the middle of a two-month drought.

**Fuel masking.** FWI is a pure *weather* index. A July day in Adrar scores extreme on
temperature and humidity alone, but the Sahara has nothing to carry a fire. Each
wilaya is classified `forest` / `steppe` / `desert` and the index is scaled
accordingly. Publishing an unmasked FWI map of Algeria would paint the Sahara red and
destroy the product's credibility on first sight.

### Known caveats

- Noon values come from the hourly forecast at 12:00 local. Rainfall is the daily
  midnight-to-midnight total, the standard approximation.
- One sample point per wilaya (the largest ring's centroid). Coarse for the big
  southern wilayas — irrelevant there, since they are fuel-masked anyway, but
  commune-level sampling is the natural next step.
- Values above 50 are all "extreme" on the EFFIS scale; late-August readings of
  90–120 in the north-east reflect a genuine Drought Code near 700.

---

## How it plugs into Hiba

Hiba's `affected_areas` table has a severity called `unconfirmed`, commented in the
migration as *"a report from social media, not yet confirmed"*. They built a hole for
verification and are filling it by hand.

Rased can answer that mechanically: given a reported point, is there a satellite
thermal detection within *n* km in the last *h* hours? Planned endpoints:

```
GET /api/v1/risk?date=              per-wilaya FWI + components
GET /api/v1/fires?hours=            clustered active fire events
GET /api/v1/confirm?lat=&lng=       satellite confirmation of a report
GET /api/v1/affected-candidates     rows shaped like their affected_areas table
```

---

## The site

| Page | What it is |
|---|---|
| `index.html` | Home — live situation, then the way in to everything else |
| `map.html` | The map: fires burning now over the 7-day danger forecast |
| `fires.html` | Every fire still burning, ranked by threat to people |
| `wilayas.html` / `wilaya.html` | The **forecast** — labelled as a prediction, not a fire |
| `report.html` | Citizen fire report, auto-checked against satellites |
| `needs.html` | Needs board — what a place is short of, and pledging to cover it |
| `shelters.html` | Reception centres, with proposed/confirmed clearly separated |
| `aid.html` | Nearest hospital, fire station and association, with drive times |
| `prepare.html` | What to do before, during and after a fire |
| `about.html` | Method and limits |

### Active vs predicted

These are kept strictly apart, because conflating them is the fastest way to lose
trust:

* **Burning now** — a satellite saw it within 6 hours (about two VIIRS passes).
  This is what the map and the fires page show by default. The 48-hour feed holds
  hundreds of fires that are already out; counting those as "active" would be
  false, and an early build did exactly that.
* **Predicted** — the FWI forecast. Every page showing it carries a banner saying
  it is an estimate of ignition probability, not an observed fire.

### New-fire detection

Each FIRMS run is diffed against the previous one. A cluster with no match within
3.5 km is flagged `is_new`, and `first_seen_utc` is carried forward for the rest,
so the site can say *"this has been burning for nine hours"* and *"this one just
started"*. History lives in `backend/app/fire_history.json` and is written
atomically, so a crash mid-write cannot lose it.

### Not everything hot is a wildfire

FIRMS reports thermal anomalies. Algeria's biggest and most persistent are gas
flares — Hassi Messaoud in Ouargla, the Illizi fields — which burn continuously.
On a real run they ranked first and second by detection count while the actual
emergency was in Kabylie. Anomalies in wilayas with no vegetation to burn are
flagged `industrial` and excluded from fire counts, exposure and the map. They are
flagged rather than deleted: the heat is real, it just is not a forest fire.

## Running it

```bash
python backend/build_geo.py          # once - joins metadata onto boundaries
python backend/pipeline.py           # live weather -> live FWI
python backend/app/firms.py          # live hotspots (needs RASED_FIRMS_KEY)
python backend/build_assets.py       # OSM responders + villages (slow, run rarely)
python backend/slim_assets.py        # trim 3.5 MB -> ~1 MB for the browser
python backend/build_exposure.py     # join fires to people and responders
python backend/seed_shelters.py      # candidate shelters from OSM

# then either:
python backend/server.py             # API + site on :8080  (needed for needs/reports)
python -m http.server 5180 --directory frontend   # static only, read-only pages
```

The static mode is a supported deployment, not a degraded one — every read-only
page falls back from the API to the generated JSON files. Only the pages that
accept submissions (reports, needs, shelters) require the server.

No build step, no bundler, no npm install. `frontend/` is plain HTML/CSS/JS and can
be served from anywhere static.

## Layout

```
backend/
  build_geo.py        joins wilaya metadata onto geoBoundaries polygons
  pipeline.py         Open-Meteo -> FWI -> frontend/data/risk.json
  make_mock.py        synthetic payloads in the exact live shape
  app/
    fwi.py            Canadian FWI system (validated against Van Wagner 1987)
    wilayas.py        48 wilayas: codes, ar/fr names, fuel class
    weather.py        Open-Meteo client, batched, keyless
    firms.py          NASA FIRMS ingest, clustering, wilaya lookup
    osm.py            Overpass client, mirror rotation
    exposure.py       fires -> exposed population, nearest responders, routing
  build_assets.py     OSM extract -> assets.json
  slim_assets.py      browser-sized asset payload
  build_exposure.py   exposure.json
frontend/
  index.html          RTL-first, Arabic default, French second
  css/style.css
  js/app.js           map, choropleth, panels
  js/basemap.js       builds a dark style by inverting OpenFreeMap positron
  js/layers.js        responder + settlement map layers
  js/i18n.js          ar / fr strings
  data/               boundaries + generated payloads
```

## Credit where it is owed

The verified Jijel relief data — 7 reception centres, 5 associations and 22
community needs, all with confirmed phone numbers — was **collected on the ground
by the Sanad team (Quanta Club)** at https://sanad-ca736.web.app, and curated into
machine-readable form by **Hiba Algeria** (habadz.life,
[repo](https://github.com/oussamabenkortbi/najdat-jijel), migration 0016).

Rased reproduces it so someone looking at a fire can reach the nearest real
shelter without changing sites. It does not claim the work.

Two of Hiba's curation decisions are preserved deliberately:

* Five associations from the original source carried sequential placeholder phone
  numbers (0550123456, 0661234567, …). They remain excluded. An unverified number
  on a relief platform sends people to a wrong number during an emergency.
* Sanad-sourced records are marked **verified**; OSM-derived shelter candidates
  are marked **candidate**, because nobody has checked those. A page that blurs
  the two is worse than one that shows fewer places.

## Licensing and attribution

Boundaries © geoBoundaries (ODbL). Basemap © OpenStreetMap contributors via
OpenFreeMap. Weather © Open-Meteo (CC BY 4.0). Hotspots courtesy of NASA FIRMS.

## This is not an evacuation order

Rased is a planning and preparation tool. Operational decisions — evacuating,
closing roads, committing resources — belong to the Protection Civile alone.
Emergency: **14** / **1021**.
