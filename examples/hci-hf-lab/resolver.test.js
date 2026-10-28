// Run: node --test examples/hci-hf-lab/resolver.test.js
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const R = require("./resolver.js");

// fixtures.js assigns window.HCI_FIXTURES; evaluate it in an empty sandbox.
const sandbox = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, "fixtures.js"), "utf8"), sandbox);
// Round-trip through JSON so the objects belong to this realm (deepEqual compares prototypes).
const FX = JSON.parse(JSON.stringify(sandbox.window.HCI_FIXTURES));

function scenario(id) {
  return JSON.parse(JSON.stringify(FX.scenarios.find((s) => s.id === id).inputs));
}

test("fixtures load and are marked synthetic", () => {
  assert.equal(FX.synthetic, true);
  assert.equal(FX.schema_version, "1.0");
  assert.ok(FX.scenarios.length >= 21);
});

for (const sc of FX.scenarios) {
  test(`scenario ${sc.id}: resolver matches expected decision`, () => {
    const r = R.resolve(sc.inputs, FX);
    assert.equal(r.decision, sc.expected.decision, r.reasons.join(" "));
    assert.equal(r.target, sc.expected.target, "target candidate");
    assert.equal(r.intent, sc.expected.intent, "intent candidate");
    assert.equal(R.simulatedOutcome(r), sc.expected.outcome, "simulated outcome");
    assert.ok(r.reasons.length > 0);
  });
}

test("resolve is deterministic and does not mutate its input", () => {
  const inputs = scenario("correct_target");
  const frozen = JSON.stringify(inputs);
  const a = R.resolve(inputs, FX);
  const b = R.resolve(inputs, FX);
  assert.deepEqual(a, b);
  assert.equal(JSON.stringify(inputs), frozen);
});

test("stop wins over a fully valid accept", () => {
  const inputs = scenario("correct_target");
  assert.equal(R.resolve(inputs, FX).decision, "accept");
  inputs.emergency_stop = true;
  assert.equal(R.resolve(inputs, FX).decision, "stop");
});

test("stop intent wins even with no activation and low confidence", () => {
  const inputs = scenario("correct_target");
  inputs.voice = { intent: "stop", confidence: 0.1, target_ref: null };
  inputs.activation.kind = "none";
  assert.equal(R.resolve(inputs, FX).decision, "stop");
});

test("no activation abstains", () => {
  const inputs = scenario("correct_target");
  inputs.activation.kind = "none";
  const r = R.resolve(inputs, FX);
  assert.equal(r.decision, "abstain");
  assert.match(r.reasons[0], /No deliberate activation/);
});

test("EMG hold shorter than the minimum abstains; at the minimum it passes", () => {
  const inputs = scenario("emg_switch_activation");
  inputs.activation.hold_ms = FX.thresholds.emg_min_hold_ms - 1;
  const short = R.resolve(inputs, FX);
  assert.equal(short.decision, "abstain");
  assert.match(short.reasons.join(" "), /EMG hold/);
  inputs.activation.hold_ms = FX.thresholds.emg_min_hold_ms;
  assert.equal(R.resolve(inputs, FX).decision, "accept");
});

test("blink repeated inside the refractory window is accidental", () => {
  const inputs = scenario("correct_target");
  inputs.activation.bounce_count = 1;
  inputs.activation.bounce_gap_ms = FX.thresholds.blink_refractory_ms - 1;
  const r = R.resolve(inputs, FX);
  assert.equal(r.decision, "abstain");
  assert.match(r.reasons.join(" "), /accidental/);
  inputs.activation.bounce_gap_ms = FX.thresholds.blink_refractory_ms;
  assert.equal(R.resolve(inputs, FX).decision, "accept");
});

test("stale or low-confidence activation abstains", () => {
  const stale = scenario("correct_target");
  stale.activation.age_ms = FX.thresholds.max_age_ms + 1;
  assert.equal(R.resolve(stale, FX).decision, "abstain");
  const low = scenario("correct_target");
  low.activation.confidence = 0.69;
  assert.equal(R.resolve(low, FX).decision, "abstain");
});

test("conflicting gaze and voice targets abstain", () => {
  const inputs = scenario("gaze_plus_voice");
  inputs.voice.target_ref = "notes";
  const r = R.resolve(inputs, FX);
  assert.equal(r.decision, "abstain");
  assert.match(r.reasons[0], /Conflicting modalities/);
});

test("a named target is used when gaze is unusable", () => {
  for (const patch of [{ connected: false }, { confidence: 0.1 }, { age_ms: 5000 }]) {
    const inputs = scenario("gaze_plus_voice");
    Object.assign(inputs.gaze, patch);
    inputs.voice.target_ref = "mail";
    const r = R.resolve(inputs, FX);
    assert.equal(r.decision, "accept");
    assert.equal(r.target, "mail");
    assert.equal(r.target_source, "voice-only");
  }
});

test("gaze on no window abstains unless voice names a target", () => {
  const inputs = scenario("correct_target");
  inputs.gaze.x = 50;
  inputs.gaze.y = 59;
  assert.equal(R.windowAt(FX.desktop, 50, 59), null);
  assert.equal(R.resolve(inputs, FX).decision, "abstain");
  inputs.voice.target_ref = "notes";
  const r = R.resolve(inputs, FX);
  assert.equal(r.decision, "accept");
  assert.equal(r.target, "notes");
});

test("low voice confidence abstains", () => {
  const inputs = scenario("correct_target");
  inputs.voice.confidence = 0.59;
  assert.equal(R.resolve(inputs, FX).decision, "abstain");
});

test("destructive intents always ask for confirmation", () => {
  for (const intent of FX.intents.filter((i) => i.destructive).map((i) => i.id)) {
    const inputs = scenario("correct_target");
    inputs.voice.intent = intent;
    inputs.voice.confidence = 1;
    inputs.gaze.confidence = 1;
    inputs.activation.confidence = 1;
    const r = R.resolve(inputs, FX);
    assert.equal(r.decision, "ask_confirmation", intent);
  }
  assert.deepEqual(FX.intents.filter((i) => i.destructive).map((i) => i.id).sort(), ["delete", "send"]);
});

test("EEG/EOG activation never auto-accepts, at any confidence or intent", () => {
  for (const intent of ["open", "close", "copy"]) {
    for (const confidence of [0.9, 0.95, 1]) {
      const inputs = scenario("eeg_eog_experimental");
      inputs.voice.intent = intent;
      inputs.activation.confidence = confidence;
      assert.equal(R.resolve(inputs, FX).decision, "ask_confirmation");
    }
  }
});

test("previewLine always ends with the preview-only sentence", () => {
  for (const sc of FX.scenarios) {
    const line = R.previewLine(R.resolve(sc.inputs, FX), FX);
    assert.ok(line.startsWith("SIMULATED RESULT:"));
    assert.ok(line.endsWith("Preview only — nothing was executed."), line);
  }
});

test("evaluateAll: every shipped scenario matches, and summary counts are consistent", () => {
  const { rows, summary } = R.evaluateAll(FX);
  assert.equal(rows.length, FX.scenarios.length);
  assert.equal(summary.matches, summary.total);
  assert.equal(summary.wrong_target, 0);
  assert.equal(
    summary.abstentions + summary.confirmations_required + summary.stops + rows.filter((r) => r.actual === "accept").length,
    summary.total
  );
  assert.ok(summary.false_activations_prevented >= 2);
});

test("evaluateAll counts a wrong target only when it was accepted", () => {
  const cfg = JSON.parse(JSON.stringify(FX));
  // Same inputs as incorrect_target_selection, but a non-destructive intent: the wrong window is accepted.
  const sc = cfg.scenarios.find((s) => s.id === "incorrect_target_selection");
  sc.inputs.voice.intent = "open";
  const out = R.evaluateAll(cfg);
  assert.equal(out.summary.wrong_target, 1);
  assert.equal(out.rows.find((r) => r.id === sc.id).wrong_target, true);
});

// ---- schema 1.0 rules: unknown confidence, ambiguity, untrusted targets, outcomes -------------

function withGaze(id, patch) {
  const inputs = scenario(id);
  Object.assign(inputs.gaze, patch);
  return inputs;
}

test("an unknown (null) confidence is unusable and is reported as unknown, not as low", () => {
  const gaze = R.resolve(withGaze("correct_target", { confidence: null }), FX);
  assert.equal(gaze.decision, "abstain");
  assert.match(gaze.reasons.join(" "), /Gaze confidence is unknown/);
  assert.doesNotMatch(gaze.reasons.join(" "), /below/);

  const inputs = scenario("correct_target");
  inputs.activation.confidence = null;
  const act = R.resolve(inputs, FX);
  assert.equal(act.decision, "abstain");
  assert.match(act.reasons.join(" "), /Activation confidence is unknown/);
});

test("a gaze-only target within the ambiguity margin abstains; just outside it is accepted", () => {
  const margin = FX.thresholds.ambiguity_margin_pct;
  const terminal = FX.desktop.windows.find((w) => w.id === "terminal").rect;
  const inside = R.resolve(withGaze("correct_target", { x: terminal.x - margin, y: 30 }), FX);
  assert.equal(inside.decision, "abstain", "a point exactly at the margin is ambiguous");
  assert.match(inside.reasons.join(" "), /Ambiguous target/);
  const outside = R.resolve(withGaze("correct_target", { x: terminal.x - margin - 0.5, y: 30 }), FX);
  assert.equal(outside.decision, "accept");
  assert.equal(outside.target, "notes");
});

test("a spoken target settles an ambiguous gaze point", () => {
  const inputs = withGaze("ambiguous_gaze_edge", {});
  inputs.voice.target_ref = "notes";
  const r = R.resolve(inputs, FX);
  assert.equal(r.decision, "accept");
  assert.equal(r.target, "notes");
});

test("the ambiguity rule is skipped when the margin is not configured", () => {
  const cfg = JSON.parse(JSON.stringify(FX));
  delete cfg.thresholds.ambiguity_margin_pct;
  assert.equal(R.resolve(scenario("ambiguous_gaze_edge"), cfg).decision, "accept");
});

test("an untrusted window is never a target, whichever modality names it", () => {
  const viaVoiceAndGaze = R.resolve(scenario("untrusted_target"), FX);
  assert.equal(viaVoiceAndGaze.decision, "abstain");
  assert.match(viaVoiceAndGaze.reasons.join(" "), /not a trusted window/);

  const viaGazeAlone = scenario("untrusted_target");
  viaGazeAlone.voice.target_ref = null;
  assert.equal(R.resolve(viaGazeAlone, FX).decision, "abstain");

  const viaVoiceAlone = scenario("untrusted_target");
  viaVoiceAlone.gaze.connected = false;
  assert.equal(R.resolve(viaVoiceAlone, FX).decision, "abstain");

  const cfg = JSON.parse(JSON.stringify(FX));
  cfg.desktop.windows.find((w) => w.id === "browser").trusted = true;
  assert.equal(R.resolve(scenario("untrusted_target"), cfg).decision, "accept");
});

test("emergency stop still wins over an untrusted or ambiguous target", () => {
  for (const id of ["untrusted_target", "ambiguous_gaze_edge"]) {
    const inputs = scenario(id);
    inputs.emergency_stop = true;
    assert.equal(R.resolve(inputs, FX).decision, "stop", id);
  }
});

test("simulatedOutcome follows the decision and nothing is ever executed", () => {
  assert.deepEqual(R.OUTCOMES.slice().sort(), ["awaiting_confirmation", "nothing_proposed", "previewed", "stopped"]);
  for (const decision of R.DECISIONS) assert.ok(R.OUTCOMES.includes(R.simulatedOutcome({ decision })));
  assert.equal(R.simulatedOutcome({ decision: "accept" }), "previewed");
  assert.equal(R.simulatedOutcome({ decision: "stop" }), "stopped");
});

test("an out-of-order sample is stale by its own timestamp", () => {
  const sc = FX.scenarios.find((s) => s.id === "out_of_order_sample");
  const late = sc.timeline.find((e) => e.out_of_order);
  assert.equal(sc.inputs.gaze.age_ms, sc.decision_at_ms - late.t_ms);
  assert.ok(sc.inputs.gaze.age_ms > FX.thresholds.max_age_ms);
  assert.equal(R.resolve(sc.inputs, FX).decision, "abstain");
});
