/*
 * HciResolver - pure, deterministic decision logic for the synthetic HCI lab.
 *
 * No DOM, no clock, no randomness, no I/O. Works in a browser (window.HciResolver)
 * and in Node (module.exports). Every number it reads is a SIMULATED input.
 *
 * resolve(inputs, config) -> { decision, target, intent, reasons[], stages{...} }
 *
 *   inputs.emergency_stop            boolean
 *   inputs.gaze       { connected, x, y, confidence, age_ms }   x, y in 0..100 (% of desktop)
 *   inputs.voice      { intent, confidence, target_ref }        target_ref: window id or null
 *   inputs.activation { kind, confidence, age_ms, hold_ms, bounce_count, bounce_gap_ms }
 *   config            the fixtures object: thresholds, desktop.windows, intents
 *
 * A confidence of null means UNKNOWN (not zero): the stream is treated as unusable and the
 * reason says so. A `quality` annotation on a stream is data for evaluators; the resolver
 * decides from confidence and age only.
 *
 * Order of evaluation. The first rule that fires decides; later rules never override it.
 *   1  stop intent or emergency stop          -> stop           (always wins)
 *   2  no activation (kind "none")            -> abstain
 *   3  activation invalid                     -> abstain        (low confidence, stale,
 *        EMG hold shorter than emg_min_hold_ms, blink repeated inside blink_refractory_ms)
 *   4  target resolution
 *        voice names a target, gaze unusable          -> use the named target (voice-only)
 *        voice names a target, gaze on another window -> abstain (conflicting modalities)
 *        voice names a target, gaze on no window      -> use the named target
 *        no named target, gaze unusable               -> abstain (use keyboard/voice fallback)
 *        no named target, gaze on no window           -> abstain
 *        no named target, gaze usable                 -> the gazed window
 *        target window has trusted:false              -> abstain (untrusted target)
 *        target came from gaze alone and the gaze point is within
 *          ambiguity_margin_pct of another window     -> abstain (ambiguous target)
 *      "Gaze unusable" = sensor not connected, confidence unknown or < gaze_min_confidence,
 *      or age > max_age_ms.
 *   5  voice intent missing or confidence < voice_min_confidence -> abstain
 *   6  risk: destructive intents (delete, send) and eeg_eog activation -> ask_confirmation
 *   7  otherwise                              -> accept         (a proposal; nothing runs)
 *
 * "accept" never executes anything: the lab only renders a preview.
 */
(function () {
  "use strict";

  var DECISIONS = ["accept", "ask_confirmation", "abstain", "stop"];

  function num(v, fallback) {
    return typeof v === "number" && isFinite(v) ? v : fallback;
  }

  function windowAt(desktop, x, y) {
    var list = (desktop && desktop.windows) || [];
    for (var i = 0; i < list.length; i++) {
      var r = list[i].rect;
      if (x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h) return list[i].id;
    }
    return null;
  }

  function windowLabel(desktop, id) {
    var list = (desktop && desktop.windows) || [];
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i].label;
    return id || "none";
  }

  function intentInfo(intents, id) {
    for (var i = 0; i < (intents || []).length; i++) if (intents[i].id === id) return intents[i];
    return null;
  }

  function windowById(desktop, id) {
    var ws = desktop.windows || [];
    for (var i = 0; i < ws.length; i++) if (ws[i].id === id) return ws[i];
    return null;
  }

  // Distance, in percent of the desktop, from a point to a rectangle (0 when inside it).
  function rectDistance(r, x, y) {
    var dx = Math.max(r.x - x, 0, x - (r.x + r.w));
    var dy = Math.max(r.y - y, 0, y - (r.y + r.h));
    return Math.sqrt(dx * dx + dy * dy);
  }

  // The closest window other than `exceptId` that lies within `margin` of the point, or null.
  function nearOther(desktop, x, y, exceptId, margin) {
    var best = null;
    var bestD = Infinity;
    (desktop.windows || []).forEach(function (w) {
      if (w.id === exceptId) return;
      var d = rectDistance(w.rect, x, y);
      if (d <= margin && d < bestD) {
        best = w;
        bestD = d;
      }
    });
    return best;
  }

  function gazeState(g, th, desktop) {
    g = g || {};
    var conf = num(g.confidence, 0);
    var age = num(g.age_ms, 0);
    var state = { usable: false, target: null, code: "ok", reason: "", confidence: conf, age_ms: age };
    if (!g.connected) {
      state.code = "disconnected";
      state.reason = "Gaze sensor is not connected.";
    } else if (g.confidence === null) {
      state.code = "unknown_confidence";
      state.reason = "Gaze confidence is unknown.";
    } else if (conf < th.gaze_min_confidence) {
      state.code = "low_confidence";
      state.reason = "Gaze confidence " + conf.toFixed(2) + " is below " + th.gaze_min_confidence + ".";
    } else if (age > th.max_age_ms) {
      state.code = "stale";
      state.reason = "Gaze sample is " + age + " ms old (limit " + th.max_age_ms + " ms).";
    } else {
      state.usable = true;
      state.target = windowAt(desktop, num(g.x, -1), num(g.y, -1));
    }
    return state;
  }

  function activationState(a, th) {
    a = a || {};
    var kind = a.kind || "none";
    var out = { valid: false, missing: kind === "none", kind: kind, reasons: [] };
    if (out.missing) {
      out.reasons.push("No deliberate activation.");
      return out;
    }
    var conf = num(a.confidence, 0);
    var min = (th.activation_min_confidence || {})[kind];
    if (typeof min !== "number") min = 1;
    if (a.confidence === null) {
      out.reasons.push("Activation confidence is unknown.");
    } else if (conf < min) {
      out.reasons.push("Activation confidence " + conf.toFixed(2) + " is below " + min + " for " + kind + ".");
    }
    if (num(a.age_ms, 0) > th.max_age_ms) {
      out.reasons.push("Activation is " + num(a.age_ms, 0) + " ms old (limit " + th.max_age_ms + " ms).");
    }
    if (kind === "emg_hold" && num(a.hold_ms, 0) < th.emg_min_hold_ms) {
      out.reasons.push("EMG hold lasted " + num(a.hold_ms, 0) + " ms; at least " + th.emg_min_hold_ms + " ms is required.");
    }
    if (kind === "blink" && num(a.bounce_count, 0) > 0 && num(a.bounce_gap_ms, Infinity) < th.blink_refractory_ms) {
      out.reasons.push(
        "Repeated blink " + num(a.bounce_gap_ms, 0) + " ms after the first (inside the " +
        th.blink_refractory_ms + " ms refractory window): treated as accidental."
      );
    }
    out.valid = out.reasons.length === 0;
    return out;
  }

  function resolve(inputs, config) {
    inputs = inputs || {};
    var th = config.thresholds;
    var desktop = config.desktop;
    var voice = inputs.voice || {};
    var intent = voice.intent || null;
    var info = intentInfo(config.intents, intent);
    var gaze = gazeState(inputs.gaze, th, desktop);
    var act = activationState(inputs.activation, th);
    var named = voice.target_ref || null;
    var voiceConf = num(voice.confidence, 0);
    var voiceOk = intent !== null && voiceConf >= th.voice_min_confidence;

    var targetSource = "none";
    var result = { decision: "abstain", target: null, intent: intent, reasons: [] };

    function done(decision, target, reasons) {
      result.decision = decision;
      result.target = target;
      result.reasons = reasons;
      result.target_source = target ? targetSource : "none";
      result.stages = describeStages(inputs, config, gaze, act, voiceOk, result);
      return result;
    }

    if (intent === "stop" || inputs.emergency_stop) {
      return done("stop", null, [
        inputs.emergency_stop ? "Emergency stop requested; it overrides every other input." : "Voice intent 'stop' overrides every other input.",
      ]);
    }
    if (!act.valid) return done("abstain", null, act.reasons);

    var target = null;
    if (named && !gaze.usable) {
      target = named;
      targetSource = "voice-only";
    } else if (named && gaze.target && gaze.target !== named) {
      return done("abstain", null, [
        "Conflicting modalities: gaze is on " + windowLabel(desktop, gaze.target) + " but voice named " +
          windowLabel(desktop, named) + ". Say or look at one target.",
      ]);
    } else if (named) {
      target = named;
      targetSource = gaze.target === named ? "gaze+voice" : "voice-only";
    } else if (!gaze.usable) {
      return done("abstain", null, [gaze.reason, "No target named by voice. Use the keyboard or name a target by voice."]);
    } else if (!gaze.target) {
      return done("abstain", null, ["Gaze point is not on any window."]);
    } else {
      target = gaze.target;
      targetSource = "gaze";
    }

    var targetWindow = windowById(desktop, target);
    if (targetWindow && targetWindow.trusted === false) {
      return done("abstain", null, [
        windowLabel(desktop, target) + " is not a trusted window, so no action is proposed on it.",
      ]);
    }
    if (targetSource === "gaze" && typeof th.ambiguity_margin_pct === "number") {
      var near = nearOther(desktop, num(inputs.gaze.x, -1), num(inputs.gaze.y, -1), target, th.ambiguity_margin_pct);
      if (near) {
        return done("abstain", null, [
          "Ambiguous target: the gaze point is on " + windowLabel(desktop, target) + " but within " +
            th.ambiguity_margin_pct + "% of " + windowLabel(desktop, near.id) + ". Name the target by voice.",
        ]);
      }
    }

    if (!voiceOk) {
      return done("abstain", null, [
        intent === null
          ? "No voice intent."
          : "Voice confidence " + voiceConf.toFixed(2) + " is below " + th.voice_min_confidence + ".",
      ]);
    }
    if (!info) return done("abstain", null, ["Unknown voice intent '" + intent + "'."]);

    var reasons = [];
    if (info.destructive) reasons.push("'" + info.label + "' is destructive; it always needs explicit confirmation.");
    if (act.kind === "eeg_eog") {
      reasons.push("EEG/EOG activation is experimental; it never auto-accepts and always needs confirmation.");
    }
    if (reasons.length) return done("ask_confirmation", target, reasons);

    var how = {
      "gaze": "Target from gaze.",
      "gaze+voice": "Gaze and voice agree on the target.",
      "voice-only": "Target named by voice (gaze not used).",
    }[targetSource];
    return done("accept", target, [how, "Activation passed all checks."]);
  }

  function freshness(age, th) {
    return age > th.max_age_ms ? "stale" : "fresh";
  }

  function describeStages(inputs, config, gaze, act, voiceOk, result) {
    var th = config.thresholds;
    var desktop = config.desktop;
    var g = inputs.gaze || {};
    var v = inputs.voice || {};
    var a = inputs.activation || {};
    var stages = {};

    var gStatus = "pass";
    var gValue;
    if (!gaze.usable) {
      gStatus = "fail";
      gValue = gaze.code === "disconnected" ? "disconnected" : "unusable (" + gaze.code.replace("_", " ") + ")";
    } else if (!gaze.target) {
      gStatus = "abstain";
      gValue = "no window at (" + num(g.x, 0) + ", " + num(g.y, 0) + ")";
    } else {
      gValue = windowLabel(desktop, gaze.target) + " at (" + num(g.x, 0) + ", " + num(g.y, 0) + ")";
    }
    stages.gaze = {
      label: "Gaze",
      status: gStatus,
      value: gValue,
      confidence: g.connected ? num(g.confidence, 0) : null,
      age_ms: g.connected ? num(g.age_ms, 0) : null,
      freshness: g.connected ? freshness(num(g.age_ms, 0), th) : "n/a",
      note: gaze.reason,
    };

    var vStatus = !v.intent ? "abstain" : voiceOk ? "pass" : "fail";
    var vTarget = v.target_ref ? " -> " + windowLabel(desktop, v.target_ref) : " (no target named)";
    stages.voice = {
      label: "Voice",
      status: vStatus,
      value: v.intent ? "'" + v.intent + "'" + vTarget : "no intent",
      confidence: num(v.confidence, 0),
      age_ms: null,
      freshness: "n/a",
      note: "",
    };

    var aStatus = act.missing ? "abstain" : act.valid ? "pass" : "fail";
    stages.activation = {
      label: "Activation",
      status: aStatus,
      value: act.kind,
      confidence: act.missing ? null : num(a.confidence, 0),
      age_ms: act.missing ? null : num(a.age_ms, 0),
      freshness: act.missing ? "n/a" : freshness(num(a.age_ms, 0), th),
      note: act.missing || act.valid ? "" : act.reasons.join(" "),
    };

    var rStatus = { accept: "pass", ask_confirmation: "abstain", abstain: "abstain", stop: "fail" }[result.decision];
    stages.resolver = {
      label: "Resolver",
      status: rStatus,
      value: result.decision,
      confidence: null,
      age_ms: null,
      freshness: "n/a",
      note: result.reasons.join(" "),
    };

    var proposal = "no action";
    if (result.decision === "accept") proposal = (result.intent || "?") + " -> " + windowLabel(desktop, result.target);
    if (result.decision === "ask_confirmation") {
      proposal = "awaiting confirmation: " + (result.intent || "?") + " -> " + windowLabel(desktop, result.target);
    }
    stages.proposed = {
      label: "Proposed action",
      status: result.decision === "accept" ? "pass" : result.decision === "ask_confirmation" ? "abstain" : "fail",
      value: proposal,
      confidence: null,
      age_ms: null,
      freshness: "n/a",
      note: "Preview only.",
    };
    return stages;
  }

  // The simulated, verified outcome of a decision. Nothing is ever executed.
  var OUTCOMES = ["previewed", "awaiting_confirmation", "nothing_proposed", "stopped"];

  function simulatedOutcome(result) {
    return { accept: "previewed", ask_confirmation: "awaiting_confirmation", abstain: "nothing_proposed", stop: "stopped" }[
      result.decision
    ];
  }

  // Wording is fixed here so the UI and the tests agree on the closing sentence.
  var PREVIEW_ONLY = "Preview only — nothing was executed.";

  function previewLine(result, config) {
    if (result.decision === "stop") return "SIMULATED RESULT: stopped, nothing proposed. " + PREVIEW_ONLY;
    if (result.decision === "abstain") return "SIMULATED RESULT: no action proposed. " + PREVIEW_ONLY;
    var label = result.intent;
    var info = intentInfo(config.intents, result.intent);
    if (info) label = info.label.toLowerCase();
    return "SIMULATED RESULT: would " + label + " " + windowLabel(config.desktop, result.target) + ". " + PREVIEW_ONLY;
  }

  // Replays every fixture scenario. wrong_target counts only an ACCEPTED action whose target
  // differs from intended_target; a wrong target held behind ask_confirmation is not counted.
  function evaluateAll(config) {
    var rows = [];
    var summary = {
      total: 0, matches: 0, wrong_target: 0, abstentions: 0,
      false_activations_prevented: 0, confirmations_required: 0, stops: 0,
    };
    config.scenarios.forEach(function (sc) {
      var r = resolve(sc.inputs, config);
      var exp = sc.expected || {};
      var match = r.decision === exp.decision && (exp.target === undefined || exp.target === r.target);
      var wrong = r.decision === "accept" && sc.intended_target !== null && r.target !== sc.intended_target;
      var prevented = sc.negative_example === true && (r.decision === "abstain" || r.decision === "stop");
      summary.total++;
      if (match) summary.matches++;
      if (wrong) summary.wrong_target++;
      if (r.decision === "abstain") summary.abstentions++;
      if (r.decision === "ask_confirmation") summary.confirmations_required++;
      if (r.decision === "stop") summary.stops++;
      if (prevented) summary.false_activations_prevented++;
      rows.push({
        id: sc.id, title: sc.title, expected: exp.decision, expected_target: exp.target === undefined ? null : exp.target,
        actual: r.decision, actual_target: r.target, match: match, wrong_target: wrong, prevented: prevented,
        reasons: r.reasons,
      });
    });
    return { rows: rows, summary: summary };
  }

  var api = {
    DECISIONS: DECISIONS,
    OUTCOMES: OUTCOMES,
    simulatedOutcome: simulatedOutcome,
    PREVIEW_ONLY: PREVIEW_ONLY,
    resolve: resolve,
    previewLine: previewLine,
    evaluateAll: evaluateAll,
    windowAt: windowAt,
    windowLabel: windowLabel,
  };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof window !== "undefined") window.HciResolver = api;
})();
