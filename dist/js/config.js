/* ─── data source ─────────────────────────────────────────────────────────
   Where the generated payloads are fetched from.

   Locally they sit next to the pages. In production they are served from
   jsDelivr's CDN, pointed at the public GitHub repository — which has a useful
   consequence: refreshing the data is a `git push`, not a redeploy. The
   pipeline can run on a schedule from anywhere and the live site picks it up,
   with no build step and nothing to keep running.

   jsDelivr is free, needs no account, sends CORS headers, and caches at the
   edge. If it were ever unreachable the pages fall back to their own origin,
   which is where a self-hosted copy keeps its data.
   ───────────────────────────────────────────────────────────────────────── */

const DATA_REPO = "meddadaek/rased@main";
const DATA_CDN = "https://cdn.jsdelivr.net/gh/" + DATA_REPO + "/frontend/data/";

const LOCAL_HOSTS = ["localhost", "127.0.0.1", ""];

const DATA_BASE = LOCAL_HOSTS.includes(location.hostname) ? "data/" : DATA_CDN;

/* Accepts either "risk.json" or "data/risk.json" so call sites can stay
   readable either way. */
function dataURL(path) {
  return DATA_BASE + String(path).replace(/^data\//, "");
}
