// Theme toggle — light/dark.
// The site always starts dark (the OS's prefers-color-scheme is intentionally ignored);
// only the visitor's explicit toggle sticks, and it's remembered across visits.
// Note: the initial theme is applied by an inline script in <head> to avoid FOUC.
(function () {
  var STORAGE_KEY = "amierge-theme";
  var root = document.documentElement;

  function apply(theme) {
    root.setAttribute("data-theme", theme);
  }

  // Toggle button
  var btn = document.getElementById("theme-toggle");
  if (btn) {
    btn.addEventListener("click", function () {
      var current = root.getAttribute("data-theme") || "dark";
      var next = current === "dark" ? "light" : "dark";
      apply(next);
      try { localStorage.setItem(STORAGE_KEY, next); } catch (e) {}
    });
  }
})();
