# Deploying Rased

The repository is deploy-ready. `vercel.json` is committed with the output
directory and security headers already set, so no build configuration is needed.

## Vercel (recommended, free, no card)

Vercel's Hobby tier needs only a GitHub sign-in.

1. Go to **https://vercel.com/new**
2. Sign in with GitHub. When prompted, click **Install** / **Configure** to give
   Vercel access to your repositories — this is a one-time authorization.
3. Select **meddadaek/rased** and click **Deploy**.

That is the whole process. `vercel.json` supplies:

- `outputDirectory: frontend` — no build step, the site is plain HTML/CSS/JS
- a Content-Security-Policy limiting network access to the four services the
  site actually uses (OpenFreeMap, OSRM, Open-Meteo, raw.githubusercontent)
- HSTS, `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`
- `Permissions-Policy: geolocation=(self)` — the map asks for position; camera,
  microphone, payment and USB are denied outright

> If you are automating this instead, note that an API token needs the
> **deployment: write** scope. A token without it returns
> `403 forbidden — You don't have permission to create a Production Deployment`,
> and the Git-import path additionally needs the Vercel GitHub App installed on
> the account.

## What the deployed site does and does not do

The deployment is **read-only**, and this is by design rather than a limitation
worked around: Vercel has no persistent filesystem, so SQLite cannot live there.

Working on the static deployment:

- the fire map, active fires, and the seven-day danger forecast
- all 48 wilaya pages with charts
- verified shelters, associations, needs and affected areas
- convoy routing, animal welfare, preparedness guidance
- everything bilingual, with the welcome screen

Requires the API (`python backend/server.py`):

- submitting a fire report, a need, or a shelter
- pledging against a need
- community confirm / dispute
- the emergency SOS channel

The pages detect which mode they are in and hide the submission controls rather
than showing buttons that fail.

## Keeping the data current

Data is **not** baked into the deployment. `frontend/js/config.js` points the
live site at the repository over HTTPS with a five-minute cache, so:

```bash
export RASED_FIRMS_KEY=...        # free, email only: firms.modaps.eosdis.nasa.gov/api/map_key/
python backend/app/firms.py --days 2     # satellite fire detections
python backend/pipeline.py               # weather -> danger index
python backend/build_exposure.py         # who is near which fire
python backend/export_static.py          # relief records -> static JSON
git add frontend/data && git commit -m "data refresh" && git push
```

The live site picks that up within five minutes. **No redeploy.** Run it from a
cron job, a laptop, or a GitHub Action — the site does not care where it ran.

`raw.githubusercontent` is used rather than jsDelivr on purpose: jsDelivr caches
a branch for seven days at the edge, and a half-day-stale answer on a page
headed "burning in the last six hours" is not a caching trade-off, it is wrong.

## Running the full stack

```bash
pip install -r requirements.txt
python backend/server.py          # http://127.0.0.1:8080
```

Set `RASED_FP_SALT` in production. It salts the hash used to stop one source
stacking confirmations; the default is a constant published in this repository,
which would make those hashes reversible by anyone who reads it.

## Static hosting elsewhere

Any static host works — GitHub Pages, Netlify, Cloudflare Pages, or a plain
`nginx`. Serve `frontend/` as the document root. There is no build step and no
bundler; `backend/build_dist.py` produces a trimmed 317 KB bundle if you want
one, but it is not required.
