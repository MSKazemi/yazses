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

test("emergency stop is never counted as a confirmation or an accept", () => {
  const r = buildReport(FX);
  const stops = FX.scenarios.filter((s) => s.expected.decision === "stop").length;
  assert.equal(r.decisions.stop, stops);
  assert.equal(r.confirmation_burden.denominator, r.scenarios - r.decisions.stop);
});
