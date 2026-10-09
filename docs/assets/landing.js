/* YazSes landing page behaviour (overrides/home.html).
 *
 * Loaded on every page via extra_javascript, and a no-op on every page except the
 * landing. Material's instant navigation swaps the page without a reload, so the
 * entry point is `document$` (re-emitted on each navigation) rather than
 * DOMContentLoaded, and every timer/observer is torn down before the next run.
 * First-party only: no network request is made from here.
 */
(function () {
  "use strict";

  var cleanups = [];
  function teardown() {
    while (cleanups.length) {
      try { cleanups.pop()(); } catch (e) { /* a stale node is fine */ }
    }
  }

  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function later(fn, ms) {
    var id = window.setTimeout(fn, ms);
    cleanups.push(function () { window.clearTimeout(id); });
    return id;
  }

  /* ---- Scroll reveal + counters + roadmap progress -------------------- */
  function reveal(root) {
    var nodes = root.querySelectorAll(".yzl-reveal, [data-yzl-eras]");
    if (reduced || !("IntersectionObserver" in window)) {
      nodes.forEach(function (n) { n.classList.add("is-in"); });
      return;
    }
    document.documentElement.classList.add("yzl-js");
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        e.target.classList.add("is-in");
        e.target.querySelectorAll("[data-yzl-count]").forEach(count);
        io.unobserve(e.target);
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.12 });
    nodes.forEach(function (n) { io.observe(n); });
    cleanups.push(function () { io.disconnect(); document.documentElement.classList.remove("yzl-js"); });
  }

  function count(el) {
    var target = parseFloat(el.getAttribute("data-yzl-count"));
    var dec = parseInt(el.getAttribute("data-dec") || "0", 10);
    if (!isFinite(target) || reduced) return;
    var start = performance.now(), dur = 1400, raf;
    function step(t) {
      var p = Math.min(1, (t - start) / dur);
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = (target * eased).toFixed(dec);
      if (p < 1) raf = requestAnimationFrame(step);
    }
    raf = requestAnimationFrame(step);
    cleanups.push(function () { cancelAnimationFrame(raf); el.textContent = target.toFixed(dec); });
  }

  /* ---- Install switcher ---------------------------------------------- */
  function install(root) {
    var box = root.querySelector("[data-yzl-install]");
    if (!box) return;
    var tabs = box.querySelectorAll("[data-os]");
    function select(os) {
      tabs.forEach(function (t) { t.setAttribute("aria-selected", String(t.getAttribute("data-os") === os)); });
      box.querySelectorAll("[data-cmd]").forEach(function (c) { c.hidden = c.getAttribute("data-cmd") !== os; });
    }
    tabs.forEach(function (t) {
      t.addEventListener("click", function () { select(t.getAttribute("data-os")); });
    });
    // Pre-select the visitor's own OS. Read locally from the user agent; nothing is sent.
    var ua = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || navigator.userAgent || "";
    if (/mac/i.test(ua) && !/iphone|ipad/i.test(navigator.userAgent)) select("mac");
    else if (/win/i.test(ua)) select("win");

    var copy = box.querySelector("[data-yzl-copy]");
    if (copy) {
      copy.addEventListener("click", function () {
        var visible = box.querySelector("[data-cmd]:not([hidden])");
        if (!visible || !navigator.clipboard) return;
        navigator.clipboard.writeText(visible.textContent.trim()).then(function () {
          var label = copy.querySelector("span");
          copy.classList.add("is-done");
          if (label) label.textContent = "Copied";
          later(function () { copy.classList.remove("is-done"); if (label) label.textContent = "Copy"; }, 1800);
        });
      });
    }
  }

  /* ---- Hero demo: hold → speak → release → typed ---------------------- */
  var SCRIPT = [
    { app: "notes.md — Editor", text: "Hold a key, speak, release. The words land wherever your cursor is." },
    { app: "Terminal — ssh build-box", cmd: "go to line 42" },
    { app: "Mail — Draft", text: "Thanks for the review. I'll push the fix this afternoon." },
    { app: "main.py — VS Code Remote-SSH", cmd: "save file" },
    { app: "Chat", text: "Nothing I just said left this laptop." },
  ];

  function demo(root) {
    var fig = root.querySelector(".yzl-demo");
    if (!fig) return;
    var typed = fig.querySelector("[data-yzl-typed]");
    var key = fig.querySelector("[data-yzl-key]");
    var tray = fig.querySelector("[data-yzl-state]");
    var status = fig.querySelector("[data-yzl-status]");
    var app = fig.querySelector("[data-yzl-app]");
    var i = 0;

    function setState(state, label) {
      tray.setAttribute("data-yzl-state", state);
      status.textContent = label;
      fig.classList.toggle("is-rec", state === "recording");
      fig.classList.toggle("is-think", state === "transcribing");
      key.classList.toggle("is-down", state === "recording");
    }

    if (reduced) {
      typed.textContent = SCRIPT[0].text;
      return;
    }

    function typeOut(str, done) {
      var n = 0;
      (function tick() {
        typed.textContent = str.slice(0, ++n);
        if (n < str.length) later(tick, 22 + Math.random() * 30);
        else done();
      })();
    }

    function run() {
      var step = SCRIPT[i % SCRIPT.length];
      i += 1;
      app.textContent = step.app;
      typed.textContent = "";
      setState("idle", "Idle — hold the key");
      later(function () {
        setState("recording", "Recording… speak");
        later(function () {
          setState("transcribing", "Decoding on your CPU");
          later(function () {
            if (step.cmd) {
              setState("command", "Command → key sequence");
              typed.innerHTML = "";
              var chip = document.createElement("span");
              chip.className = "is-cmd";
              chip.textContent = "⌘ " + step.cmd;
              typed.appendChild(chip);
              later(run, 2600);
            } else {
              setState("idle", "Typed into the focused app");
              typeOut(step.text, function () { later(run, 2600); });
            }
          }, 900);
        }, 1700);
      }, 900);
    }
    run();
  }

  /* ---- Pipeline: auto-advance, hover/tap to inspect -------------------- */
  function pipeline(root) {
    var pipe = root.querySelector("[data-yzl-pipe]");
    if (!pipe) return;
    var stages = Array.prototype.slice.call(pipe.querySelectorAll(".yzl-stage"));
    var desc = root.querySelector("[data-yzl-desc]");
    var src = root.querySelector("[data-yzl-src]");
    var idx = 0, paused = false, timer;

    function show(n) {
      idx = n;
      stages.forEach(function (s, k) { s.classList.toggle("is-active", k === n); });
      desc.textContent = stages[n].getAttribute("data-desc");
      src.textContent = stages[n].getAttribute("data-src");
    }
    function loop() {
      if (!paused) show((idx + 1) % stages.length);
      // the decode stage holds longest, as it does in a real burst
      timer = later(loop, stages[idx].classList.contains("yzl-stage--hot") ? 3200 : 1600);
    }
    stages.forEach(function (s, k) {
      function pick() { paused = true; show(k); }
      s.addEventListener("mouseenter", pick);
      s.addEventListener("focus", pick);
      s.addEventListener("click", pick);
    });
    pipe.addEventListener("mouseleave", function () { paused = false; });
    show(0);
    if (!reduced) timer = later(loop, 1600);
  }

  function init() {
    teardown();
    var root = document.querySelector(".yz-landing");
    if (!root) return;
    reveal(root);
    var final = document.querySelector(".yzl-final");
    if (final) reveal(final);
    install(root);
    demo(root);
    pipeline(root);
  }

  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(init);
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
