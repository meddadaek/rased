/* ─── data source ─────────────────────────────────────────────────────────
   Where the generated payloads are fetched from.

   Locally they sit next to the pages. In production they are read straight
   from the public GitHub repository, which has a useful consequence: refreshing
   the data is a `git push`, not a redeploy. The pipeline can run on a schedule
   from anywhere and the live site picks it up, with nothing to rebuild.

   raw.githubusercontent rather than jsDelivr, deliberately. Both are free and
   both send CORS headers, but jsDelivr caches a branch for 7 days at the edge
   (s-maxage 12 h) while raw sends max-age=300. On a site whose headline number
   is "fires burning in the last 6 hours", a twelve-hour-stale payload is not a
   performance trade-off, it is a wrong answer.
   ───────────────────────────────────────────────────────────────────────── */

const DATA_REPO = "meddadaek/rased@main";
const DATA_CDN = "https://raw.githubusercontent.com/" +
  DATA_REPO.replace("@", "/") + "/frontend/data/";

const LOCAL_HOSTS = ["localhost", "127.0.0.1", ""];

const DATA_BASE = LOCAL_HOSTS.includes(location.hostname) ? "data/" : DATA_CDN;

/* Accepts either "risk.json" or "data/risk.json" so call sites can stay
   readable either way. */
function dataURL(path) {
  return DATA_BASE + String(path).replace(/^data\//, "");
}
