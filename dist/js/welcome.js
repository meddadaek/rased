/* ─── first-visit welcome ─────────────────────────────────────────────────
   Shown once, then never again unless the visitor clears their browser.

   Somebody arriving here for the first time during an emergency has no idea
   what this site is, and the map alone does not explain itself. Three things
   have to land before anything else: the emergency number, what the colours
   mean, and that this is not an evacuation order. The language choice comes
   first because the whole interface depends on it.

   It is dismissible immediately and never blocks the emergency numbers, which
   are visible inside the overlay itself.
   ───────────────────────────────────────────────────────────────────────── */

const WELCOME_KEY = "rased.welcomed.v1";

function welcomeSeen() {
  try {
    return localStorage.getItem(WELCOME_KEY) === "1";
  } catch (e) {
    // Private browsing throws on access. Better to show the welcome again than
    // to crash the page over a preference.
    return false;
  }
}

function markWelcomeSeen() {
  try { localStorage.setItem(WELCOME_KEY, "1"); } catch (e) { /* nothing to do */ }
}

const WELCOME_COPY = {
  ar: {
    title: "راصد",
    sub: "الإنذار المبكر لحرائق الغابات في الجزائر",
    lead: "نحسب خطر اندلاع الحريق قبل وقوعه، ونتابع البؤر المشتعلة الآن بالأقمار الاصطناعية، ونصل بين من يحتاج المساعدة ومن يستطيع تقديمها.",
    steps: [
      ["🔥", "ما يشتعل الآن", "بؤر مرصودة بالأقمار خلال آخر 6 ساعات فقط — لا حرائق قديمة انطفأت."],
      ["📊", "ما قد يشتعل غدًا", "مؤشر خطر لكل ولاية إلى سبعة أيام، محسوب من طقس حقيقي."],
      ["🤝", "من يساعد ومن يحتاج", "مراكز إيواء وجمعيات موثّقة بأرقامها، ولوحة احتياجات مفتوحة."],
    ],
    colors: "ألوان الخريطة تعني احتمال انتشار النار لو اندلعت — لا وجود حريق الآن.",
    emergency: "عند رؤية حريق، اتصل فورًا",
    warn: "راصد أداة توعية وتخطيط. لا يصدر أوامر إخلاء — القرار الميداني للحماية المدنية وحدها.",
    forests: "محافظة الغابات — للتبليغ عن حريق غابي",
    start: "ابدأ",
    lang: "اللغة",
  },
  fr: {
    title: "Rased",
    sub: "Alerte précoce aux feux de forêt en Algérie",
    lead: "Nous calculons le danger d'incendie avant qu'il ne se déclare, suivons par satellite les foyers en cours, et relions ceux qui ont besoin d'aide à ceux qui peuvent en apporter.",
    steps: [
      ["🔥", "Ce qui brûle maintenant", "Foyers vus par satellite dans les 6 dernières heures uniquement — pas d'anciens feux éteints."],
      ["📊", "Ce qui peut brûler demain", "Un indice de danger par wilaya à sept jours, calculé sur des données météo réelles."],
      ["🤝", "Qui aide, qui a besoin", "Centres et associations vérifiés avec leurs numéros, et un tableau des besoins ouvert."],
    ],
    colors: "Les couleurs indiquent la vitesse de propagation d'un feu s'il démarrait — pas la présence d'un feu.",
    emergency: "Si vous voyez un feu, appelez immédiatement",
    warn: "Rased est un outil de sensibilisation et de planification. Il n'émet pas d'ordre d'évacuation — cette décision relève de la seule Protection civile.",
    forests: "Conservation des forêts — signaler un feu de forêt",
    start: "Commencer",
    lang: "Langue",
  },
};

function renderWelcome(lang, onChoose, onStart) {
  const C = WELCOME_COPY[lang];
  const scale = CLASS_SEQ.map((c) =>
    '<i style="background:' + CLASS_COLORS[c] + '"></i>').join("");

  return '' +
    '<div class="wel-inner" role="dialog" aria-modal="true" aria-label="' + C.title + '">' +
      '<div class="wel-langs">' +
        '<span>' + C.lang + '</span>' +
        '<button class="wel-lang' + (lang === "ar" ? " on" : "") + '" data-l="ar">العربية</button>' +
        '<button class="wel-lang' + (lang === "fr" ? " on" : "") + '" data-l="fr">Français</button>' +
      "</div>" +

      '<div class="wel-brand">' +
        '<span class="wel-mark">' + FLAME_SVG + "</span>" +
        "<div><h2>" + C.title + "</h2><p>" + C.sub + "</p></div>" +
      "</div>" +

      '<p class="wel-lead">' + C.lead + "</p>" +

      '<div class="wel-steps">' +
        C.steps.map(([icon, t, d]) =>
          '<div class="wel-step"><span class="wel-ic">' + icon + "</span>" +
          "<b>" + t + "</b><p>" + d + "</p></div>").join("") +
      "</div>" +

      '<div class="wel-scale"><div class="wel-scale-bar">' + scale + "</div>" +
        "<p>" + C.colors + "</p></div>" +

      '<div class="wel-em"><span>' + C.emergency + "</span>" +
        '<a href="tel:14">14</a><a href="tel:1021">1021</a>' +
        '<a href="tel:1070" title="' + C.forests + '">1070</a>' +
      "</div>" +

      '<p class="wel-warn">' + C.warn + "</p>" +
      '<button class="btn wel-start">' + C.start + "</button>" +
    "</div>";
}

function showWelcome(currentLang, setLang) {
  const host = document.createElement("div");
  host.className = "welcome";
  host.id = "welcome";
  document.body.appendChild(host);

  let lang = currentLang;

  function paint() {
    host.innerHTML = renderWelcome(lang);
    host.querySelectorAll(".wel-lang").forEach((b) =>
      b.addEventListener("click", () => {
        lang = b.dataset.l;
        setLang(lang);       // flip the page behind the overlay too
        paint();
      }));
    host.querySelector(".wel-start").addEventListener("click", close);
  }

  function close() {
    markWelcomeSeen();
    host.classList.add("gone");
    setTimeout(() => host.remove(), 320);
  }

  // Escape closes it: never trap somebody who needs the page underneath.
  document.addEventListener("keydown", function esc(e) {
    if (e.key !== "Escape") return;
    document.removeEventListener("keydown", esc);
    if (document.getElementById("welcome")) close();
  });
  host.addEventListener("click", (e) => { if (e.target === host) close(); });

  paint();
}

function maybeShowWelcome(currentLang, setLang) {
  if (welcomeSeen()) return;
  showWelcome(currentLang, setLang);
}
