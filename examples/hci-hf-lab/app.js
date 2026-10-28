/* UI wiring only. All decisions come from HciResolver (resolver.js); all data from fixtures.js. */
(function () {
  "use strict";

  var FX = window.HCI_FIXTURES;
  var R = window.HciResolver;
  var $ = function (id) { return document.getElementById(id); };

  var ICON = { pass: "✓", fail: "✗", abstain: "–", pending: "…" };
  var DECISION_ICON = { accept: "✓", ask_confirmation: "?", abstain: "–", stop: "■" };
  var STAGE_ORDER = ["gaze", "voice", "activation", "resolver", "proposed"];

  var state = { scenarioId: null, inputs: null, fired: false, outcome: null, result: null };

  // ---- helpers -------------------------------------------------------------------------

  function clone(o) { return JSON.parse(JSON.stringify(o)); }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function chip(kind, text, icon) {
    var c = el("span", "chip chip-" + kind);
    var i = el("span", "chip-icon", icon);
    i.setAttribute("aria-hidden", "true");
    c.appendChild(i);
    c.appendChild(document.createTextNode(" " + text));
    return c;
  }

  function decisionChip(decision) {
    var kind = { accept: "pass", ask_confirmation: "abstain", abstain: "abstain", stop: "fail" }[decision] || "abstain";
    return chip(kind, decision, DECISION_ICON[decision] || "?");
  }

  function label(id) { return R.windowLabel(FX.desktop, id); }

  function fill(select, items) {
    select.textContent = "";
    items.forEach(function (it) {
      var o = el("option", "", it.text);
      o.value = it.value;
      select.appendChild(o);
    });
  }

  function intVal(input, fallback) {
    var n = parseInt(input.value, 10);
    if (isNaN(n)) n = fallback;
    var min = input.min === "" ? -Infinity : Number(input.min);
    var max = input.max === "" ? Infinity : Number(input.max);
    return Math.max(min, Math.min(max, n));
  }

  // ---- controls <-> state --------------------------------------------------------------

  function writeControls() {
    var i = state.inputs;
    $("gaze-connected").checked = !!i.gaze.connected;
    $("gaze-x").value = i.gaze.x;
    $("gaze-y").value = i.gaze.y;
    $("gaze-conf").value = i.gaze.confidence;
    $("gaze-age").value = i.gaze.age_ms;
    $("voice-intent").value = i.voice.intent || "";
    $("voice-conf").value = i.voice.confidence;
    $("voice-target").value = i.voice.target_ref || "";
    $("act-kind").value = i.activation.kind;
    $("act-conf").value = i.activation.confidence;
    $("act-age").value = i.activation.age_ms;
    $("act-hold").value = i.activation.hold_ms;
    $("act-bounce").value = i.activation.bounce_count;
    $("act-bounce-gap").value = i.activation.bounce_gap_ms === null ? 0 : i.activation.bounce_gap_ms;
  }

  function readControls() {
    var i = state.inputs;
    i.gaze.connected = $("gaze-connected").checked;
    i.gaze.x = Number($("gaze-x").value);
    i.gaze.y = Number($("gaze-y").value);
    i.gaze.confidence = Number($("gaze-conf").value);
    i.gaze.age_ms = intVal($("gaze-age"), 0);
    i.voice.intent = $("voice-intent").value || null;
    i.voice.confidence = Number($("voice-conf").value);
    i.voice.target_ref = $("voice-target").value || null;
    i.activation.kind = $("act-kind").value;
    i.activation.confidence = Number($("act-conf").value);
    i.activation.age_ms = intVal($("act-age"), 0);
    i.activation.hold_ms = intVal($("act-hold"), 0);
    i.activation.bounce_count = intVal($("act-bounce"), 0);
    i.activation.bounce_gap_ms = i.activation.bounce_count > 0 ? intVal($("act-bounce-gap"), 0) : null;
  }

  function invalidate() {
    state.fired = false;
    state.outcome = null;
    state.result = null;
  }

  function onControlChange() {
    readControls();
    invalidate();
    render();
  }

  // ---- actions -------------------------------------------------------------------------

  function loadScenario(id) {
    var sc = FX.scenarios.filter(function (s) { return s.id === id; })[0];
    if (!sc) return;
    state.scenarioId = id;
    state.inputs = clone(sc.inputs);
    invalidate();
    $("scenario").value = id;
    writeControls();
    render();
  }

  function fire() {
    state.fired = true;
    state.outcome = null;
    state.result = R.resolve(state.inputs, FX);
    render();
    if (state.result.decision === "ask_confirmation") $("btn-confirm").focus();
  }

  function emergencyStop() {
    state.inputs.emergency_stop = true;
    fire();
  }

  function reset() {
    var sc = FX.scenarios.filter(function (s) { return s.id === state.scenarioId; })[0];
    state.inputs = clone(sc.inputs);
    state.inputs.emergency_stop = false;
    invalidate();
    writeControls();
    render();
    $("btn-activate").focus();
  }

  function settle(outcome) {
    state.outcome = outcome;
    render();
    $("btn-activate").focus();
  }

  // ---- rendering -----------------------------------------------------------------------

  function setVisibleRows() {
    var kind = $("act-kind").value;
    $("row-act-conf").hidden = kind === "none";
    $("row-act-age").hidden = kind === "none";
    $("row-act-hold").hidden = kind !== "emg_hold";
    $("row-act-bounce").hidden = kind !== "blink";
    $("row-act-bounce-gap").hidden = kind !== "blink" || Number($("act-bounce").value) < 1;
  }

  function renderOutputs() {
    [["gaze-conf", 2], ["voice-conf", 2], ["act-conf", 2], ["gaze-x", 0], ["gaze-y", 0]].forEach(function (p) {
      $(p[0] + "-out").textContent = Number($(p[0]).value).toFixed(p[1]);
    });
  }

  function renderDesktop(live) {
    var g = state.inputs.gaze;
    var gazed = g.connected && live.stages.gaze.status !== "fail" ? R.windowAt(FX.desktop, g.x, g.y) : null;
    var target = state.fired && state.result ? state.result.target : null;
    FX.desktop.windows.forEach(function (w) {
      var node = $("win-" + w.id);
      node.classList.toggle("is-gaze", w.id === gazed);
      node.classList.toggle("is-target", w.id === target);
      var b = node.querySelector(".win-tags");
      b.textContent = (w.id === gazed ? "gaze here " : "") + (w.id === target ? "target " : "");
    });
    var dot = $("gaze-dot");
    dot.style.left = g.x + "%";
    dot.style.top = g.y + "%";
    dot.hidden = !g.connected;
    dot.classList.toggle("is-unusable", live.stages.gaze.status === "fail");
    $("desktop").classList.toggle("is-disconnected", !g.connected);
    $("desktop-offline").hidden = g.connected;

    var desc;
    if (!g.connected) desc = "Gaze sensor disconnected.";
    else desc = "Gaze at (" + g.x + ", " + g.y + ") over " + (R.windowAt(FX.desktop, g.x, g.y) ? label(R.windowAt(FX.desktop, g.x, g.y)) : "no window") +
      ", confidence " + g.confidence.toFixed(2) + ", age " + g.age_ms + " ms" +
      (live.stages.gaze.status === "fail" ? " (unusable: " + live.stages.gaze.note + ")" : "") + ".";
    $("gaze-readout").textContent = desc;
    $("desktop").setAttribute("aria-label", "Simulated desktop with Notes, Terminal and Mail windows. " + desc);
  }

  function stageMeta(s) {
    var parts = [];
    parts.push("Confidence: " + (s.confidence === null ? "n/a" : s.confidence.toFixed(2)));
    parts.push("Freshness: " + (s.freshness === "n/a" ? "n/a" : s.freshness + " (" + s.age_ms + " ms)"));
    return parts.join(" · ");
  }

  function renderPipeline(live) {
    var ol = $("pipeline");
    ol.textContent = "";
    STAGE_ORDER.forEach(function (key) {
      var s = live.stages[key];
      var pending = !state.fired && (key === "resolver" || key === "proposed");
      var li = el("li", "stage stage-" + (pending ? "pending" : s.status));
      var head = el("div", "stage-head");
      head.appendChild(el("h3", "", s.label));
      head.appendChild(pending ? chip("pending", "pending", ICON.pending) : chip(s.status, s.status, ICON[s.status]));
      li.appendChild(head);
      li.appendChild(el("p", "stage-value", pending ? "waiting for Activate" : s.value));
      if (key === "gaze" || key === "voice" || key === "activation") li.appendChild(el("p", "stage-meta", stageMeta(s)));
      if (!pending && s.note && key !== "proposed" && key !== "resolver") li.appendChild(el("p", "stage-note", s.note));
      ol.appendChild(li);
    });
  }

  function renderResult() {
    var status = $("decision-status");
    var sim = $("sim-result");
    var reasons = $("reasons");
    var confirmRow = $("confirm-row");
    reasons.textContent = "";
    sim.hidden = true;
    confirmRow.hidden = true;
    sim.textContent = "";

    if (!state.fired) {
      status.textContent = "Press Activate to run the resolver.";
      return;
    }
    var r = state.result;
    var what = r.intent ? R.windowLabel(FX.desktop, r.target) : "";
    if (r.decision === "accept") status.textContent = "Decision: accept. Proposed: " + r.intent + " " + what + ".";
    else if (r.decision === "ask_confirmation") {
      status.textContent = state.outcome === "cancelled"
        ? "Decision: ask_confirmation. You cancelled."
        : state.outcome === "confirmed"
          ? "Decision: ask_confirmation. You confirmed."
          : "Decision: ask_confirmation. Confirm or cancel: " + r.intent + " " + what + ".";
    } else if (r.decision === "abstain") status.textContent = "Decision: abstain. No action proposed.";
    else status.textContent = "Decision: stop. Everything halted.";

    r.reasons.forEach(function (t) { reasons.appendChild(el("li", "", t)); });

    if (r.decision === "ask_confirmation" && state.outcome === null) confirmRow.hidden = false;
    var line = null;
    if (r.decision !== "ask_confirmation") line = R.previewLine(r, FX);
    else if (state.outcome === "confirmed") line = R.previewLine(r, FX);
    else if (state.outcome === "cancelled") line = "SIMULATED RESULT: cancelled by you, no action. " + R.PREVIEW_ONLY;
    if (line) {
      sim.textContent = line;
      sim.hidden = false;
    }
  }

  function renderMeta() {
    var sc = FX.scenarios.filter(function (s) { return s.id === state.scenarioId; })[0];
    $("scenario-desc").textContent = sc.description;
    var tl = sc.timeline.map(function (e) { return "+" + e.t_ms + " " + e.source + ":" + e.event; }).join(", ");
    $("scenario-meta").textContent =
      "Modalities: " + sc.modality.join(", ") + ". Simulated conditions: " + sc.simulated_conditions.lighting + "; " +
      sc.simulated_conditions.device + ". Intended target: " + (sc.intended_target ? label(sc.intended_target) : "none") +
      ". Timeline (relative ms): " + tl + ". Decision at +" + sc.decision_at_ms + " ms. Controls below may be changed after loading.";
  }

  function render() {
    setVisibleRows();
    renderOutputs();
    var live = R.resolve(state.inputs, FX);
    $("stop-state").textContent = state.inputs.emergency_stop
      ? "Emergency stop is latched: every Activate returns stop. Reset releases it."
      : "Emergency stop is not latched. Escape also stops.";
    renderMeta();
    renderDesktop(live);
    renderPipeline(state.fired && state.result ? state.result : live);
    renderResult();
  }

  // ---- evaluation table ----------------------------------------------------------------

  function renderEvaluation(announce) {
    var out = R.evaluateAll(FX);
    var tbody = document.querySelector("#eval-table tbody");
    tbody.textContent = "";
    out.rows.forEach(function (row) {
      var tr = el("tr");
      var th = el("th", "", row.title);
      th.scope = "row";
      var sc = FX.scenarios.filter(function (s) { return s.id === row.id; })[0];
      if (sc.negative_example) th.appendChild(el("span", "tag", "negative example"));
      tr.appendChild(th);
      var e = el("td");
      e.setAttribute("data-label", "Expected");
      e.appendChild(decisionChip(row.expected));
      var a = el("td");
      a.setAttribute("data-label", "Actual");
      a.appendChild(decisionChip(row.actual));
      var m = el("td");
      m.setAttribute("data-label", "Match");
      m.appendChild(row.match ? chip("pass", "match", ICON.pass) : chip("fail", "mismatch", ICON.fail));
      tr.appendChild(e); tr.appendChild(a); tr.appendChild(m);
      tbody.appendChild(tr);
    });

    var s = out.summary;
    var dl = $("summary");
    dl.textContent = "";
    [
      ["Scenarios matching expected", s.matches + " of " + s.total],
      ["Wrong-target accepts", String(s.wrong_target)],
      ["Abstentions", String(s.abstentions)],
      ["False activations prevented", String(s.false_activations_prevented)],
      ["Confirmations required", String(s.confirmations_required)],
      ["Emergency stops", String(s.stops)],
    ].forEach(function (p) {
      var box = el("div", "stat");
      box.appendChild(el("dt", "", p[0]));
      box.appendChild(el("dd", "", p[1]));
      dl.appendChild(box);
    });
    $("eval-status").textContent = announce
      ? "Replayed " + s.total + " scenarios: " + s.matches + " match the expected decision."
      : "";
  }

  // ---- setup ---------------------------------------------------------------------------

  function buildDesktop() {
    var d = $("desktop");
    FX.desktop.windows.forEach(function (w) {
      var win = el("div", "win");
      win.id = "win-" + w.id;
      win.style.left = w.rect.x + "%";
      win.style.top = w.rect.y + "%";
      win.style.width = w.rect.w + "%";
      win.style.height = w.rect.h + "%";
      var title = el("div", "win-title");
      title.appendChild(el("span", "", w.label));
      title.appendChild(el("span", "win-tags"));
      win.appendChild(title);
      win.appendChild(el("div", "win-body"));
      d.appendChild(win);
    });
    var dot = el("div", "gaze-dot");
    dot.id = "gaze-dot";
    d.appendChild(dot);
    var off = el("div", "desktop-offline", "Gaze sensor disconnected");
    off.id = "desktop-offline";
    off.hidden = true;
    d.appendChild(off);
  }

  function init() {
    fill($("scenario"), FX.scenarios.map(function (s) { return { value: s.id, text: s.title + (s.negative_example ? " (negative example)" : "") }; }));
    fill($("voice-intent"), FX.intents.map(function (i) { return { value: i.id, text: i.label + (i.destructive ? " (destructive)" : "") }; }));
    fill($("voice-target"), [{ value: "", text: "None named (\"this\")" }].concat(
      FX.desktop.windows.map(function (w) { return { value: w.id, text: w.label }; })));
    fill($("act-kind"), FX.activation_kinds.map(function (k) { return { value: k.id, text: k.label }; }));
    buildDesktop();

    $("scenario").addEventListener("change", function () { loadScenario($("scenario").value); });
    ["gaze-connected", "gaze-x", "gaze-y", "gaze-conf", "gaze-age", "voice-intent", "voice-conf", "voice-target",
      "act-kind", "act-conf", "act-age", "act-hold", "act-bounce", "act-bounce-gap"].forEach(function (id) {
      $(id).addEventListener("input", onControlChange);
      $(id).addEventListener("change", onControlChange);
    });
    $("btn-activate").addEventListener("click", fire);
    $("btn-stop").addEventListener("click", emergencyStop);
    $("btn-reset").addEventListener("click", reset);
    $("btn-confirm").addEventListener("click", function () { settle("confirmed"); });
    $("btn-cancel").addEventListener("click", function () { settle("cancelled"); });
    $("btn-replay").addEventListener("click", function () { renderEvaluation(true); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        e.preventDefault();
        emergencyStop();
      }
    });

    renderEvaluation(false);
    loadScenario(FX.scenarios[0].id);
  }

  init();
})();
