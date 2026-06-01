// Theme toggle — light/dark, defaults to OS preference (prefers-color-scheme).
// Note: the initial theme is applied by an inline script in <head> to avoid FOUC.
(function () {
  var STORAGE_KEY = "amierge-theme";
  var root = document.documentElement;
  var mql = window.matchMedia("(prefers-color-scheme: dark)");

  function systemTheme() {
    return mql.matches ? "dark" : "light";
  }

  function apply(theme) {
    root.setAttribute("data-theme", theme);
  }

  // Toggle button
  var btn = document.getElementById("theme-toggle");
  if (btn) {
    btn.addEventListener("click", function () {
      var current = root.getAttribute("data-theme") || systemTheme();
      var next = current === "dark" ? "light" : "dark";
      apply(next);
      try { localStorage.setItem(STORAGE_KEY, next); } catch (e) {}
    });
  }

  // Follow OS changes only while the user hasn't made an explicit choice.
  mql.addEventListener("change", function (e) {
    var stored;
    try { stored = localStorage.getItem(STORAGE_KEY); } catch (e2) {}
    if (!stored) apply(e.matches ? "dark" : "light");
  });
})();
