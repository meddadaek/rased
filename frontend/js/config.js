/* ─── data source ─────────────────────────────────────────────────────────
   Where the generated payloads are fetched from.

   Same origin, always. The payloads ship with the site — on GitHub Pages, on
   Vercel, and from `python -m http.server` — so `data/` resolves everywhere
   without a cross-origin request, a CDN dependency, or a CORS failure mode.

   An earlier version pulled these from raw.githubusercontent so that a data
   refresh needed no redeploy. That property is now provided by the scheduled
   GitHub Action instead: it runs the pipeline, commits the payloads, and the
   deploy workflow republishes automatically. Same outcome, one less service in
   the path between a person and a fire map.

   DATA_BASE is deliberately a single constant rather than per-call logic: every
   fetch in the app goes through dataURL(), so redirecting the whole site at a
   mirror is a one-line change here if it is ever needed.
   ───────────────────────────────────────────────────────────────────────── */

const DATA_BASE = "data/";

/* Accepts either "risk.json" or "data/risk.json" so call sites stay readable
   either way. */
function dataURL(path) {
  return DATA_BASE + String(path).replace(/^data\//, "");
}
