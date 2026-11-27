// Run: node --test examples/hci-hf-lab/eval/replay.test.js
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");

const { buildReport, renderMarkdown, loadFixtures, timingErrors, NOTICE } = require("./replay.js");

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

// Make a stream older in a way the timeline agrees with, so the harness's timing check passes and
// the resolver's own freshness rule is what has to refuse it.
function age(s, source, ms) {
  const event = source === "gaze" ? "sample" : "activation";
  const found = s.timeline.filter((e) => e.source === source && e.event === event).pop();
  found.t_ms = s.decision_at_ms - ms;
  found.out_of_order = true;
  s.inputs[source].age_ms = ms;
}

test("#700 C1: no simulated action is emitted on stale, low-confidence or contradictory signals", () => {
  // Each variant degrades the one signal the base decision depends on. The base scenario
  // (gaze-targeted, blink-activated, no named target) is accepted when nothing is degraded.
  const degrade = {
    gaze_stale: (s) => { age(s, "gaze", FX.thresholds.max_age_ms + 1); },
    gaze_low_confidence: (s) => { s.inputs.gaze.confidence = FX.thresholds.gaze_min_confidence - 0.01; },
    gaze_unknown_confidence: (s) => { s.inputs.gaze.confidence = null; },
    activation_stale: (s) => { age(s, "activation", FX.thresholds.max_age_ms + 1); },
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
    assert.deepEqual(r.timing_violations, [], intent);
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
  noEmg.inputs.activation.age_ms = base.inputs.activation.age_ms; // keep this scenario's timeline

  const noEeg = clone(base); // EEG is never required: no accepting path reads it
  noEeg.id = "no_eeg_adapter";
  noEeg.inputs.eeg = undefined;

  const r = buildReport(only(base, noCameraAtAll, noEmg, noEeg));
  assert.deepEqual(r.mismatches, []);
  assert.deepEqual(r.timing_violations, []);
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

// ---------------------------------------------------------------------------------------
// Timing enforcement (issue #700 step 1) and the abstention/error trade-off (step 5).
// ---------------------------------------------------------------------------------------

const gazeEvent = (s) => s.timeline.find((e) => e.source === "gaze" && e.event === "sample");

const BROKEN_TIMING = {
  timestamp_goes_back: (s) => { gazeEvent(s).t_ms = 10; },
  late_flag_on_an_event_that_is_not_late: (s) => { gazeEvent(s).out_of_order = true; },
  negative_timestamp: (s) => { s.timeline[0].t_ms = -1; },
  fractional_timestamp: (s) => { s.timeline[0].t_ms = 0.5; },
  event_after_the_decision: (s) => { s.timeline[s.timeline.length - 1].t_ms = s.decision_at_ms + 1; },
  broken_sequence: (s) => { s.timeline[1].seq = 7; },
  empty_timeline: (s) => { s.timeline = []; },
  no_timeline: (s) => { delete s.timeline; },
  no_decision_time: (s) => { delete s.decision_at_ms; },
  // The dangerous one: a stale sample relabelled as fresh in the inputs only.
  gaze_age_understated: (s) => { gazeEvent(s).t_ms = 100; gazeEvent(s).out_of_order = true; },
  gaze_age_missing: (s) => { delete s.inputs.gaze.age_ms; },
  activation_age_understated: (s) => { s.inputs.activation.age_ms = 0; },
  gaze_present_without_a_sample: (s) => { gazeEvent(s).event = "reconnect"; },
};

test("every shipped scenario satisfies the harness's timing rules", () => {
  for (const sc of FX.scenarios) assert.deepEqual(timingErrors(sc), [], sc.id);
  assert.deepEqual(buildReport(FX).timing_violations, []);
});

for (const [name, apply] of Object.entries(BROKEN_TIMING)) {
  test(`timing: ${name} is reported and nothing is proposed from the scenario`, () => {
    const s = scenario("correct_target"); // accepted when its timing is sound
    apply(s);
    const r = buildReport(only(s));
    assert.equal(r.timing_violations.length, 1);
    assert.equal(r.timing_violations[0].id, "correct_target");
    assert.equal(r.decisions.abstain, 1);
    assert.equal(r.missed_accepts.numerator, 1);
    assert.ok(r.abstention_tradeoff.points.every((p) => p.abstention_rate.numerator === 1));
    assert.equal(r.decision_latency_ms.min, null); // no latency is read from an unsound timeline
    assert.match(renderMarkdown(r), /## Timing violations/);
    assert.match(renderMarkdown(r), /Decision latency .*: not computed/);
  });
}

test("timing: an emergency stop still wins over a broken timeline", () => {
  const s = scenario("correct_target");
  s.timeline = [];
  s.inputs.emergency_stop = true;
  const r = buildReport(only(s));
  assert.equal(r.timing_violations.length, 1);
  assert.equal(r.decisions.stop, 1);
});

test("trade-off: the grid runs from 0 to 1 and every count has a denominator", () => {
  const points = buildReport(FX).abstention_tradeoff.points;
  assert.deepEqual(points.map((p) => p.confidence_floor), [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1]);
  for (const p of points) {
    for (const key of ["wrong_actions", "abstention_rate", "missed_accepts", "confirmations"]) {
      assert.ok(p[key].denominator > 0, key);
      assert.ok(p[key].numerator <= p[key].denominator, key);
    }
  }
});

test("trade-off: a lower floor lets the weak activation through, a higher one misses accepts", () => {
  const points = buildReport(FX).abstention_tradeoff.points;
  const lowest = points[0];
  const highest = points[points.length - 1];
  assert.ok(lowest.wrong_actions.numerator >= 1, "false_activation is accepted with no confidence floor");
  assert.equal(highest.wrong_actions.numerator, 0);
  assert.equal(highest.missed_accepts.numerator, highest.missed_accepts.denominator);
  for (let i = 1; i < points.length; i++) {
    assert.ok(points[i].abstention_rate.numerator >= points[i - 1].abstention_rate.numerator, "abstentions");
    assert.ok(points[i].wrong_actions.numerator <= points[i - 1].wrong_actions.numerator, "wrong actions");
  }
});

test("trade-off: the sweep leaves the shipped thresholds and the headline numbers alone", () => {
  const fx = clone(FX);
  const before = JSON.stringify(fx);
  const r = buildReport(fx);
  assert.equal(JSON.stringify(fx), before);
  assert.equal(r.wrong_actions.numerator, 0);
  assert.match(renderMarkdown(r), /## Abstention\/error trade-off/);
  assert.match(renderMarkdown(r), /does not recommend a threshold/);
});
