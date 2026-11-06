// Run: node --test examples/hci-hf-lab/eval/replay.test.js
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");

const { buildReport, renderMarkdown, loadFixtures, NOTICE } = require("./replay.js");

const FX = loadFixtures();
const clone = (v) => JSON.parse(JSON.stringify(v));

function scenario(id) {
  return clone(FX.scenarios.find((s) => s.id === id));
}

test("the report is deterministic", () => {
  assert.equal(JSON.stringify(buildReport(clone(FX))), JSON.stringify(buildReport(clone(FX))));
  assert.equal(renderMarkdown(buildReport(FX)), renderMarkdown(buildReport(FX)));
});

test("the shipped scenarios all match and nothing wrong gets through", () => {
  const r = buildReport(FX);
  assert.equal(r.scenarios, FX.scenarios.length);
  assert.equal(r.decision_matches_expected.numerator, r.decision_matches_expected.denominator);
  assert.deepEqual(r.mismatches, []);
  assert.equal(r.wrong_actions.numerator, 0);
  assert.equal(r.false_activations_accepted.numerator, 0);
});

test("every rate carries its numerator and denominator", () => {
  const r = buildReport(FX);
  for (const key of [
    "decision_matches_expected", "wrong_actions", "wrong_target_accepted", "false_activations_accepted",
    "false_activations_prevented", "abstention_rate", "missed_accepts", "confirmation_burden", "emergency_stops",
  ]) {
    assert.equal(typeof r[key].numerator, "number", key);
    assert.equal(typeof r[key].denominator, "number", key);
    assert.ok(r[key].numerator <= r[key].denominator, key);
  }
});

test("decision counts add up to the scenarios", () => {
  const r = buildReport(FX);
  const sum = Object.values(r.decisions).reduce((a, b) => a + b, 0);
  assert.equal(sum, r.scenarios);
});

test("the synthetic-data warning is in both outputs and the hourly rate is not invented", () => {
  const r = buildReport(FX);
  assert.equal(r.synthetic, true);
  assert.equal(r.notice, NOTICE);
  assert.ok(renderMarkdown(r).includes(NOTICE));
  assert.equal(r.false_activations_per_hour.value, null);
  assert.match(renderMarkdown(r), /False activations per hour: not computed/);
});

test("an accepted false activation is counted as a wrong action", () => {
  const fx = clone(FX);
  const bad = scenario("correct_target");
  bad.id = "forced_false_activation";
  bad.negative_example = true; // the resolver still accepts these inputs
  fx.scenarios.push(bad);
  const r = buildReport(fx);
  assert.equal(r.false_activations_accepted.numerator, 1);
  assert.equal(r.wrong_actions.numerator, 1);
  // The cloned fixture still expects "accept", so it matches: a wrong action is counted
  // independently of whether the fixture author expected it.
  assert.equal(r.mismatches.length, 0);
  assert.equal(r.false_activations_prevented.numerator, FX.scenarios.filter((s) => s.negative_example).length);
});

test("an accepted wrong target is counted once, not twice", () => {
  const fx = clone(FX);
  const bad = scenario("correct_target");
  bad.id = "forced_wrong_target";
  bad.intended_target = "some-other-window"; // the resolver accepts Notes
  bad.negative_example = true; // also a false activation: still one wrong action
  fx.scenarios.push(bad);
  const r = buildReport(fx);
  assert.equal(r.wrong_target_accepted.numerator, 1);
  assert.equal(r.wrong_actions.numerator, 1);
});

test("a missed accept is counted when an expected accept does not happen", () => {
  const fx = clone(FX);
  const weak = scenario("correct_target");
  weak.id = "forced_missed_accept";
  weak.inputs.activation.confidence = 0; // the resolver now abstains; the fixture still expects accept
  fx.scenarios.push(weak);
  const r = buildReport(fx);
  assert.equal(r.missed_accepts.numerator, 1);
  assert.equal(r.mismatches[0].id, "forced_missed_accept");
});

// ---------------------------------------------------------------------------------------
// #700 acceptance criteria, one sweep each, judged on the REPORT (what the harness exports)
// rather than on single resolver calls. resolver.test.js covers the rules one at a time.
// ---------------------------------------------------------------------------------------

function only(...scenarios) {
  const fx = clone(FX);
  fx.scenarios = scenarios;
  return fx;
}

const DESTRUCTIVE = FX.intents.filter((i) => i.destructive).map((i) => i.id);

test("#700 C1: no simulated action is emitted on stale, low-confidence or contradictory signals", () => {
  // Each variant degrades the one signal the base decision depends on. The base scenario
  // (gaze-targeted, blink-activated, no named target) is accepted when nothing is degraded.
  const degrade = {
    gaze_stale: (s) => { s.inputs.gaze.age_ms = FX.thresholds.max_age_ms + 1; },
    gaze_low_confidence: (s) => { s.inputs.gaze.confidence = FX.thresholds.gaze_min_confidence - 0.01; },
    gaze_unknown_confidence: (s) => { s.inputs.gaze.confidence = null; },
    activation_stale: (s) => { s.inputs.activation.age_ms = FX.thresholds.max_age_ms + 1; },
    activation_low_confidence: (s) => { s.inputs.activation.confidence = 0.01; },
    activation_unknown_confidence: (s) => { s.inputs.activation.confidence = null; },
    voice_low_confidence: (s) => { s.inputs.voice.confidence = FX.thresholds.voice_min_confidence - 0.01; },
    contradictory_targets: (s) => { s.inputs.voice.target_ref = "mail"; }, // gaze is on notes
  };
  for (const intent of ["open", ...DESTRUCTIVE]) {
    const variants = Object.entries(degrade).map(([name, apply]) => {
      const s = scenario("correct_target");
      s.id = `${name}_${intent}`;
      s.inputs.voice.intent = intent;
      s.expected = { decision: "abstain" };
      apply(s);
      return s;
    });
    const r = buildReport(only(...variants));
    assert.deepEqual(r.mismatches, [], intent);
    assert.equal(r.decisions.accept, 0, intent);
    assert.equal(r.decisions.ask_confirmation, 0, intent); // not even a proposal awaiting confirmation
    assert.equal(r.decisions.abstain, variants.length, intent);
  }
});

test("#700 C2: a destructive intent is never accepted, whatever the other inputs", () => {
  assert.ok(DESTRUCTIVE.length > 0, "the fixtures must define at least one destructive intent");
  for (const intent of DESTRUCTIVE) {
    const swept = FX.scenarios.map((sc) => {
      const s = clone(sc);
      s.inputs.voice.intent = intent;
      return s;
    });
    const r = buildReport(only(...swept));
    assert.equal(r.decisions.accept, 0, intent);
    // Every scenario that was accepted with a harmless intent now waits for confirmation.
    const acceptedBefore = buildReport(FX).decisions.accept;
    assert.ok(r.decisions.ask_confirmation >= acceptedBefore, intent);
  }
});

test("#700 C3: emergency stop wins over every competing modality in every shipped scenario", () => {
  for (const how of ["emergency_stop", "voice_stop"]) {
    const swept = FX.scenarios.map((sc) => {
      const s = clone(sc);
      if (how === "emergency_stop") s.inputs.emergency_stop = true;
      else s.inputs.voice.intent = "stop";
      return s;
    });
    const r = buildReport(only(...swept));
    assert.equal(r.decisions.stop, swept.length, how);
    assert.equal(r.decisions.accept + r.decisions.ask_confirmation + r.decisions.abstain, 0, how);
    assert.equal(r.confirmation_burden.denominator, 0, how);
    assert.equal(r.confirmation_burden.value, null, how);
  }
});

test("#700 C4: a missing camera, EMG or EEG adapter does not block a voice-named action", () => {
  const base = scenario("voice_only"); // gaze disconnected, EMG hold, voice names the terminal
  assert.equal(base.inputs.voice.target_ref, "terminal");

  const noCameraAtAll = clone(base); // the gaze stream is absent, not merely disconnected
  noCameraAtAll.id = "no_camera_adapter";
  delete noCameraAtAll.inputs.gaze;

  const noEmg = clone(base); // EMG absent: a camera blink is the activation, gaze still absent
  noEmg.id = "no_emg_adapter";
  delete noEmg.inputs.gaze;
  noEmg.inputs.activation = scenario("correct_target").inputs.activation;

  const noEeg = clone(base); // EEG is never required: no accepting path reads it
  noEeg.id = "no_eeg_adapter";
  noEeg.inputs.eeg = undefined;

  const r = buildReport(only(base, noCameraAtAll, noEmg, noEeg));
  assert.deepEqual(r.mismatches, []);
  assert.equal(r.decisions.accept, 4);

  // No shipped scenario needs an EEG/EOG activation to be accepted.
  for (const sc of FX.scenarios.filter((s) => s.expected.decision === "accept")) {
    assert.notEqual(sc.inputs.activation.kind, "eeg_eog", sc.id);
  }

  // An absent gaze stream with no spoken target abstains with a reason; it does not throw.
  const unnamed = clone(noCameraAtAll);
  unnamed.id = "no_camera_no_named_target";
  unnamed.inputs.voice.target_ref = null;
  unnamed.expected = { decision: "abstain" };
  assert.deepEqual(buildReport(only(unnamed)).mismatches, []);
});

test("#700 C5/C7: the notice separates this benchmark from participant validation (#419)", () => {
  const r = buildReport(FX);
  assert.match(r.notice, /^SYNTHETIC DATA\./);
  assert.match(r.notice, /#419/);
  assert.match(r.notice, /no rate here is an accuracy figure/);
  assert.ok(JSON.stringify(r).includes(NOTICE));
});

test("emergency stop is never counted as a confirmation or an accept", () => {
  const r = buildReport(FX);
  const stops = FX.scenarios.filter((s) => s.expected.decision === "stop").length;
  assert.equal(r.decisions.stop, stops);
  assert.equal(r.confirmation_burden.denominator, r.scenarios - r.decisions.stop);
});
