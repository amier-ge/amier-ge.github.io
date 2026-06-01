// Visitor counter (TODAY / TOTAL) for a static site.
//
// GitHub Pages has no backend, so counts are kept by a free, no-signup hit-counter
// API (Abacus, https://abacus.jasoncameron.dev). To approximate "unique visitors",
// each browser is counted at most once per day via localStorage:
//   - first visit of the day  -> "hit"  (increments TODAY's key and TOTAL)
//   - later views same day    -> "get"  (read-only, no increment)
// If the service is unavailable the placeholder is left untouched.
(function () {
  var todayEl = document.getElementById("visit-today");
  var totalEl = document.getElementById("visit-total");
  if (!todayEl || !totalEl) return;

  var NS = "amier-ge-blog";
  var BASE = "https://abacus.jasoncameron.dev";
  var VISIT_KEY = "amierge-last-visit-day";

  function pad(n) { return n < 10 ? "0" + n : "" + n; }
  var d = new Date();
  var dayKey = "d-" + d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());

  var last = null;
  try { last = localStorage.getItem(VISIT_KEY); } catch (e) {}
  var firstVisitToday = last !== dayKey;
  var verb = firstVisitToday ? "hit" : "get";

  function show(el, n) {
    try { el.textContent = Number(n).toLocaleString(); } catch (e) { el.textContent = String(n); }
  }

  function load(key, el) {
    fetch(BASE + "/" + verb + "/" + NS + "/" + key, { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (j) { if (j && typeof j.value === "number") show(el, j.value); })
      .catch(function () { /* counter service unavailable — keep placeholder */ });
  }

  load(dayKey, todayEl);
  load("total", totalEl);

  if (firstVisitToday) {
    try { localStorage.setItem(VISIT_KEY, dayKey); } catch (e) {}
  }
})();
