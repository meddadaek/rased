/* ─── charts ──────────────────────────────────────────────────────────────
   Inline SVG, no library. A charting bundle is 60-200 KB before it draws
   anything, and this site has to open on a phone on rural Algerian mobile data
   during an emergency. These four forms cover everything the data needs.

   Colour follows the dataviz method rather than taste:

   * The danger ramp is an ordered severity scale, validated with
     scripts/validate_palette.js for CVD separation and normal-vision floor.
     Its steps are never reused to mean anything else.
   * Single-series charts use one ink colour and carry no legend — the title
     names the series.
   * Every value is also available as text (axis labels, direct labels, or the
     table beneath), so nothing is encoded by colour alone.
   ───────────────────────────────────────────────────────────────────────── */

const CHART_INK = "#E4572E";
const CHART_HOPE = "#12A594";
const CHART_GRID = "rgba(20,55,45,0.10)";
const CHART_TEXT = "#4E635C";
const CHART_FAINT = "#7C8F88";

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/* ─── vertical bars: a value per day ──────────────────────────────────── */

function barChart(opts) {
  const data = opts.data || [];
  if (!data.length) return "";

  const w = opts.width || 640, h = opts.height || 190;
  const padT = 22, padB = 34, padS = 6;
  const plotH = h - padT - padB;
  const max = Math.max(opts.max || 0, ...data.map((d) => d.value)) || 1;
  const bw = (w - padS * 2) / data.length;
  // 2px of surface between bars, per the mark spec, so adjacent days read as
  // separate quantities rather than one continuous block.
  const gap = Math.min(10, bw * 0.22);

  let svg = '<svg viewBox="0 0 ' + w + " " + h + '" class="chart" ' +
    'role="img" aria-label="' + esc(opts.title || "") + '">';

  // Recessive gridlines: present enough to read a value against, quiet enough
  // that they never compete with the bars.
  for (let i = 0; i <= 2; i++) {
    const y = padT + (plotH * i) / 2;
    svg += '<line x1="' + padS + '" y1="' + y.toFixed(1) + '" x2="' + (w - padS) +
      '" y2="' + y.toFixed(1) + '" stroke="' + CHART_GRID + '" stroke-width="1"/>';
  }

  data.forEach((d, i) => {
    const bh = Math.max(2, (d.value / max) * plotH);
    const x = padS + i * bw + gap / 2;
    const y = padT + plotH - bh;
    const bwid = bw - gap;
    const r = Math.min(4, bwid / 2);
    svg +=
      '<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + bwid.toFixed(1) +
      '" height="' + bh.toFixed(1) + '" rx="' + r + '" fill="' + (d.color || CHART_INK) + '">' +
      "<title>" + esc(d.label + ": " + d.value) + "</title></rect>" +
      '<text x="' + (x + bwid / 2).toFixed(1) + '" y="' + (y - 5).toFixed(1) +
      '" text-anchor="middle" font-size="10.5" font-weight="600" fill="' + CHART_TEXT +
      '">' + esc(d.display !== undefined ? d.display : d.value) + "</text>" +
      '<text x="' + (x + bwid / 2).toFixed(1) + '" y="' + (h - 12) +
      '" text-anchor="middle" font-size="9.5" fill="' + CHART_FAINT + '">' +
      esc(d.label) + "</text>";
    if (d.sub) {
      svg += '<text x="' + (x + bwid / 2).toFixed(1) + '" y="' + (h - 2) +
        '" text-anchor="middle" font-size="8" fill="' + CHART_FAINT + '">' +
        esc(d.sub) + "</text>";
    }
  });

  return svg + "</svg>";
}

/* ─── horizontal bars: ranked categories ──────────────────────────────── */

function rowChart(opts) {
  const data = (opts.data || []).slice(0, opts.limit || 10);
  if (!data.length) return "";
  const max = Math.max(...data.map((d) => d.value)) || 1;

  return '<div class="rowchart" role="img" aria-label="' + esc(opts.title || "") + '">' +
    data.map((d) =>
      '<div class="rc-row">' +
        '<span class="rc-label">' + esc(d.label) + "</span>" +
        '<span class="rc-track"><i style="width:' +
          Math.max(2, (d.value / max) * 100).toFixed(1) + "%;background:" +
          (d.color || CHART_INK) + '"></i></span>' +
        '<span class="rc-value">' + esc(d.display !== undefined ? d.display : d.value) + "</span>" +
      "</div>").join("") +
    "</div>";
}

/* ─── stacked proportion bar ──────────────────────────────────────────── */

function stackBar(opts) {
  const data = (opts.data || []).filter((d) => d.value > 0);
  const total = data.reduce((a, d) => a + d.value, 0);
  if (!total) return "";

  return '<div class="stackbar" role="img" aria-label="' + esc(opts.title || "") + '">' +
    '<div class="sb-track">' +
      data.map((d) =>
        '<i style="width:' + ((d.value / total) * 100).toFixed(2) + "%;background:" +
        (d.color || CHART_INK) + '" title="' + esc(d.label + ": " + d.value) + '"></i>').join("") +
    "</div>" +
    // Legend is always present for >= 2 series, and each entry carries its own
    // number, so identity never depends on the colour alone.
    '<div class="sb-legend">' +
      data.map((d) =>
        '<span><i style="background:' + (d.color || CHART_INK) + '"></i>' +
        esc(d.label) + " <b>" + esc(d.display !== undefined ? d.display : d.value) +
        "</b></span>").join("") +
    "</div></div>";
}

/* ─── sparkline: shape of a short series ──────────────────────────────── */

function sparkline(values, opts) {
  const v = values || [];
  if (v.length < 2) return "";
  const o = opts || {};
  const w = o.width || 120, h = o.height || 30;
  const max = Math.max(...v), min = Math.min(...v);
  const span = max - min || 1;
  const pts = v.map((y, i) =>
    (i / (v.length - 1) * w).toFixed(1) + "," +
    (h - ((y - min) / span) * (h - 4) - 2).toFixed(1)).join(" ");

  return '<svg viewBox="0 0 ' + w + " " + h + '" class="spark" aria-hidden="true">' +
    '<polyline points="' + pts + '" fill="none" stroke="' + (o.color || CHART_INK) +
    '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>' +
    "</svg>";
}
