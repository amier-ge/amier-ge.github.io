// Hero wordmark typewriter — types the brand out like terminal output of `whoami`.
//
// Sequence: empty line with the cursor blinking twice → text types out (cursor held
// solid) → cursor resumes blinking.
//
// The text is present in the HTML (for SEO / no-JS); CSS hides it only when JS is
// available (`.js` class, set before paint in head.html), so there's no flash of the
// full word before typing starts. Respects prefers-reduced-motion.
(function () {
  var el = document.querySelector(".hero h1 .typed");
  if (!el) return;

  var h1 = el.parentNode;
  var full = el.textContent;

  el.style.visibility = "visible";

  var reduce = false;
  try {
    reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch (e) {}

  if (reduce) return; // leave the full text as-is

  var BLINK_MS = 1500; // keep in sync with @keyframes blink in main.css
  var CHAR_MS = 95;

  el.textContent = ""; // cursor blinks on its own until typing starts

  var i = 0;
  function step() {
    el.textContent = full.slice(0, ++i);
    if (i < full.length) {
      setTimeout(step, CHAR_MS);
    } else {
      h1.classList.remove("typing"); // done → cursor resumes blinking
    }
  }

  setTimeout(function () {
    h1.classList.add("typing"); // hold the cursor solid while typing
    step();
  }, BLINK_MS); // let the cursor blink once first
})();
