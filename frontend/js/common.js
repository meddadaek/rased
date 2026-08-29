/* ─── shared page runtime ─────────────────────────────────────────────────
   Nav, language switching, formatting and data access for every page except
   the map. Kept framework-free on purpose: the site has to be servable as
   plain files from anywhere, including offline from a USB stick if it comes
   to that.
   ───────────────────────────────────────────────────────────────────────── */

const NAV = [
  { href: "index.html",   ar: "الرئيسية",         fr: "Accueil" },
  { href: "map.html",     ar: "الخريطة",          fr: "Carte" },
  { href: "fires.html",   ar: "الحرائق النشطة",   fr: "Foyers actifs" },
  { href: "wilayas.html", ar: "الولايات",         fr: "Wilayas" },
  { href: "report.html",  ar: "بلّغ عن حريق",     fr: "Signaler" },
  { href: "prepare.html", ar: "كيف تحمي نفسك",    fr: "Se protéger" },
  { href: "needs.html",   ar: "الاحتياجات",       fr: "Besoins" },
  { href: "shelters.html",ar: "مراكز الإيواء",    fr: "Hébergement" },
  { href: "routes.html",  ar: "القوافل والطرق",  fr: "Convois" },
  { href: "animals.html", ar: "الحيوانات",        fr: "Animaux" },
  { href: "aid.html",     ar: "الجمعيات",         fr: "Associations" },
  { href: "about.html",   ar: "كيف يعمل",         fr: "Méthode" },
];

const CLASS_COLORS = {
  very_low: "#177A55", low: "#8FBF3F", moderate: "#F7D01E",
  high: "#EF7A1A", very_high: "#C01818", extreme: "#5E1030",
};
const CLASS_SEQ = ["very_low", "low", "moderate", "high", "very_high", "extreme"];

const LANG_KEY = "rased.lang";

/* Language is a per-visitor preference, so it belongs in the browser rather
   than the URL. Reads are wrapped because private-mode browsers throw on
   access rather than returning null. */
function savedLang() {
  try {
    return localStorage.getItem(LANG_KEY) === "fr" ? "fr" : "ar";
  } catch (e) {
    return "ar";
  }
}

function saveLang(lang) {
  try { localStorage.setItem(LANG_KEY, lang); } catch (e) { /* nothing to do */ }
}

let LANG = savedLang();
const T = () => I18N[LANG];
const isAr = () => LANG === "ar";

function n(v) { return String(v); }   // Western digits in both languages

function nInt(v) {
  return n(Math.round(v).toLocaleString(isAr() ? "en-US" : "fr-FR"));
}

function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}

/* ─── nav ─────────────────────────────────────────────────────────────── */

const FLAME_SVG =
  '<svg viewBox="0 0 32 32" width="22" height="22">' +
  '<path d="M16 3c1.6 5.2-3.1 6.9-3.1 11.4 0 2 1.2 3.4 2.5 4.1-.6-2 .4-4.3 2.2-5.4-.4 2.6 1.1 3.4 2.4 5 1.9 2.4 1 6.2-1.6 7.6 4.8-.7 8-4.4 8-9.1C26.4 10 20.6 6.2 16 3z" fill="#ff6b35"/>' +
  '<path d="M13.4 20.6c-1.3 1.3-1.5 3.6-.2 5.1-2.3-.7-3.9-2.9-3.9-5.4 0-1.7.7-3 1.7-4.2.2 2 1.3 3.6 2.4 4.5z" fill="#ffb347"/></svg>';

function renderNav(current) {
  const nav = document.getElementById("nav");
  if (!nav) return;
  const L = T();

  nav.innerHTML =
    '<a class="nav-brand" href="index.html">' +
      '<span class="mark" style="display:grid;place-items:center">' + FLAME_SVG + "</span>" +
      "<span><b>" + L.brand + "</b><span>" + L.tagline + "</span></span>" +
    "</a>" +
    '<div class="nav-links">' +
      NAV.map((item) =>
        '<a href="' + item.href + '"' +
        (item.href === current ? ' class="on"' : "") + ">" +
        item[LANG] + "</a>").join("") +
    "</div>" +
    '<div class="langsel">' +
      '<button class="lang' + (isAr() ? " active" : "") + '" data-lang="ar">ع</button>' +
      '<button class="lang' + (!isAr() ? " active" : "") + '" data-lang="fr">FR</button>' +
    "</div>";

  nav.querySelectorAll(".lang").forEach((b) =>
    b.addEventListener("click", () => setPageLang(b.dataset.lang)));
}

function applyDir() {
  const L = T();
  document.documentElement.lang = L.lang;
  document.documentElement.dir = L.dir;
}

/* Pages register a redraw callback; switching language re-runs it rather than
   reloading, so scroll position and any in-progress form input survive. */
let REDRAW = () => {};

function onLangChange(fn) { REDRAW = fn; }

function setPageLang(lang) {
  LANG = lang;
  saveLang(lang);
  applyDir();
  renderNav(currentPage());
  document.querySelectorAll("[data-i18n]").forEach((e) => {
    const v = T()[e.dataset.i18n];
    if (v) e.textContent = v;
  });
  document.querySelectorAll("[data-ar]").forEach((e) => {
    e.innerHTML = isAr() ? e.dataset.ar : e.dataset.fr;
  });
  REDRAW();
}

function currentPage() {
  const p = location.pathname.split("/").pop();
  return p === "" ? "index.html" : p;
}

/* ─── data ────────────────────────────────────────────────────────────── */

/* Try the live API first, fall back to the generated file. This is what lets
   every page work both under the FastAPI server and as plain static files —
   the static deployment is not a degraded mode, it is a supported one. */
async function getJSON(apiPath, filePath) {
  if (apiPath) {
    try {
      const r = await fetch(apiPath, { cache: "no-store" });
      if (r.ok) return await r.json();
    } catch (e) { /* fall through to the file */ }
  }
  const r = await fetch(filePath, { cache: "no-store" });
  if (!r.ok) throw new Error(filePath + " -> HTTP " + r.status);
  return r.json();
}

async function loadRisk() {
  try {
    return await getJSON("/api/v1/risk", "data/risk.json");
  } catch (e) {
    return getJSON(null, "data/mock_risk.json");
  }
}

async function loadFires() {
  try {
    return await getJSON("/api/v1/fires", "data/fires.json");
  } catch (e) {
    return getJSON(null, "data/mock_fires.json");
  }
}

const loadExposure = () => getJSON("/api/v1/exposure", "data/exposure.json");
const loadAssets = () => getJSON("/api/v1/assets", "data/assets_map.json");
const loadWilayaGeo = () => getJSON(null, "data/wilayas.geojson");

/* ─── shared bits ─────────────────────────────────────────────────────── */

function wilayaName(meta) {
  return isAr() ? meta.name_ar : meta.name_fr;
}

function classPill(cls) {
  return '<span class="cls-dot" style="background:' + CLASS_COLORS[cls] + '"></span>' +
         T().cls[cls];
}

/* A banner shown wherever fire data is displayed, so a simulated fire can
   never be mistaken for a real one just because the reader landed on an
   inner page rather than the map. */
function simulatedNotice(source) {
  if (source && source !== "MOCK") return "";
  return '<div class="notice"><b>' + T().simTitle + "</b> " + T().simBody + "</div>";
}

function initPage(opts) {
  applyDir();
  renderNav(currentPage());
  if (opts && opts.redraw) onLangChange(opts.redraw);
  document.querySelectorAll("[data-ar]").forEach((e) => {
    e.innerHTML = isAr() ? e.dataset.ar : e.dataset.fr;
  });
}
