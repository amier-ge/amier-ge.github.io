// Blog search + category filter (dependency-free).
//
// Security note: this is a fully static site (no server, no database), so there
// is no SQL/command-injection surface here. The query is used ONLY for in-memory
// string matching (indexOf) and is never written back into the DOM as HTML — no
// innerHTML / insertAdjacentHTML / document.write — so there is no XSS sink.
// The query length is also clamped defensively below.
(function () {
  var MAX_QUERY = 80;
  var listEl = document.getElementById("post-list");
  if (!listEl) return;

  var searchInput = document.getElementById("blog-search");
  var catButtons = Array.prototype.slice.call(document.querySelectorAll(".cat-btn"));
  var noResults = document.getElementById("no-results");
  var cards = Array.prototype.slice.call(listEl.querySelectorAll(".post-card"));

  var state = { q: "", cat: "ALL" };

  function normalize(s) {
    return (s || "").toLowerCase().normalize("NFKD");
  }

  function matches(card) {
    // category
    var cats = (card.getAttribute("data-categories") || "").split("|");
    if (state.cat !== "ALL" && cats.indexOf(state.cat) === -1) return false;
    // query
    if (!state.q) return true;
    var haystack = normalize(card.getAttribute("data-search"));
    var terms = normalize(state.q).split(/\s+/).filter(Boolean);
    return terms.every(function (t) { return haystack.indexOf(t) !== -1; });
  }

  function render() {
    var shown = 0;
    cards.forEach(function (card) {
      var ok = matches(card);
      card.style.display = ok ? "" : "none";
      if (ok) shown++;
    });
    if (noResults) noResults.style.display = shown === 0 ? "block" : "none";
  }

  if (searchInput) {
    searchInput.addEventListener("input", function () {
      state.q = (searchInput.value || "").slice(0, MAX_QUERY);
      render();
    });
  }

  catButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      catButtons.forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      state.cat = btn.getAttribute("data-category") || "ALL";
      render();
    });
  });

  render();
})();
