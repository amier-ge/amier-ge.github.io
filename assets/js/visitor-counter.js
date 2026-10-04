// Visitor counter (TODAY / TOTAL) for a static site.
//
// GitHub Pages has no backend, so counts are kept by a free, no-signup hit-counter
// API (Abacus, https://abacus.jasoncameron.dev). Count a new entry to the site,
// including a return in the same browser. Internal page changes and reloads
// only read the current counts.
// If the service is unavailable the placeholder is left untouched.
(function () {
  var todayEl = document.getElementById("visit-today");
  var totalEl = document.getElementById("visit-total");
  if (!todayEl || !totalEl) return;

  var NS = "amier-ge-blog";
  var BASE = "https://abacus.jasoncameron.dev";
  var VISIT_KEY = "amierge-visit-active";
  var LAST_PAGE_KEY = "amierge-last-page";

  function pad(n) { return n < 10 ? "0" + n : "" + n; }

  var activeVisit = false;
  try { activeVisit = sessionStorage.getItem(VISIT_KEY) === "1"; } catch (e) {}

  var internalReferrer = false;
  try { internalReferrer = new URL(document.referrer).origin === location.origin; } catch (e) {}

  var navigation = performance.getEntriesByType("navigation")[0];
  var isReload = navigation && navigation.type === "reload";
  var returnedFromOutside = false;
  try {
    returnedFromOutside = navigation && navigation.type === "back_forward" &&
      sessionStorage.getItem(LAST_PAGE_KEY) === location.href;
  } catch (e) {}
  var newVisit = !isReload && (!activeVisit || !internalReferrer || returnedFromOutside);

  function show(el, n) {
    try { el.textContent = Number(n).toLocaleString(); } catch (e) { el.textContent = String(n); }
  }

  function load(key, el, verb) {
    fetch(BASE + "/" + verb + "/" + NS + "/" + key, { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (j) { if (j && typeof j.value === "number") show(el, j.value); })
      .catch(function () { /* counter service unavailable — keep placeholder */ });
  }

  function updateCounts(countVisit) {
    var verb = countVisit ? "hit" : "get";
    var d = new Date();
    var dayKey = "d-" + d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
    load(dayKey, todayEl, verb);
    load("total", totalEl, verb);
  }

  updateCounts(newVisit);

  try { sessionStorage.setItem(VISIT_KEY, "1"); } catch (e) {}

  window.addEventListener("pagehide", function () {
    try { sessionStorage.setItem(LAST_PAGE_KEY, location.href); } catch (e) {}
  });

  // A back navigation can restore the page from cache without rerunning this script.
  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) return;
    var lastPage = null;
    try { lastPage = sessionStorage.getItem(LAST_PAGE_KEY); } catch (e) {}
    updateCounts(lastPage === location.href);
  });
})();
