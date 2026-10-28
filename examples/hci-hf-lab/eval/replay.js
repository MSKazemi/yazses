#!/usr/bin/env node
// Deterministic replay report for the synthetic multimodal fixtures (issue #700).
//
//   node examples/hci-hf-lab/eval/replay.js          Markdown to stdout
//   node examples/hci-hf-lab/eval/replay.js --json   JSON to stdout
//
// Pure: no network, no clock, no randomness, no operating-system action. Every number is
// computed from hand-authored SYNTHETIC scenarios; it is a regression check on the resolver,
// not a measurement of a device or of people (that is the participant validation in #419).
// Exits 1 when any scenario does not match its expected decision.
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const R = require("../resolver.js");

const NOTICE =
  "SYNTHETIC DATA. These are hand-authored scenarios replayed through a pure resolver. " +
  "They are not measurements of any device or person, and no rate here is an accuracy figure. " +
  "Real participant validation is a separate study (issue #419).";

function loadFixtures() {
  const sandbox = { window: {} };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "..", "fixtures.js"), "utf8"), sandbox);
  // Round-trip through JSON so the objects belong to this realm.
  return JSON.parse(JSON.stringify(sandbox.window.HCI_FIXTURES));
}

function ratio(numerator, denominator) {
  return { numerator: numerator, denominator: denominator, value: denominator === 0 ? null : numerator / denominator };
}

function median(values) {
  if (values.length === 0) return null;
  const sorted = values.slice().sort(function (a, b) { return a - b; });
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function lastEventMs(scenario) {
  return scenario.timeline.reduce(function (latest, e) { return Math.max(latest, e.t_ms); }, 0);
}

function buildReport(fixtures) {
  const evaluation = R.evaluateAll(fixtures);
  const byId = {};
  fixtures.scenarios.forEach(function (sc) { byId[sc.id] = sc; });

  const decisions = { accept: 0, abstain: 0, ask_confirmation: 0, stop: 0 };
  let wrongActions = 0;
  let falseActivationsAccepted = 0;
  let expectedAccept = 0;
  let missedAccepts = 0;
  const latencies = [];

  evaluation.rows.forEach(function (row) {
    const sc = byId[row.id];
    decisions[row.actual] += 1;
    const falseActivation = sc.negative_example === true && row.actual === "accept";
    if (falseActivation) falseActivationsAccepted += 1;
    // A wrong target and an accepted false activation are both wrong actions; count a scenario once.
    if (row.wrong_target || falseActivation) wrongActions += 1;
    if (row.expected === "accept") {
      expectedAccept += 1;
      if (row.actual !== "accept") missedAccepts += 1;
    }
    latencies.push(sc.decision_at_ms - lastEventMs(sc));
  });

  const total = evaluation.summary.total;
  const negatives = fixtures.scenarios.filter(function (s) { return s.negative_example === true; }).length;
  const simulatedMs = fixtures.scenarios.reduce(function (sum, s) { return sum + s.decision_at_ms; }, 0);

  return {
    synthetic: true,
    notice: NOTICE,
    schema_version: fixtures.schema_version,
    scenarios: total,
    decisions: decisions,
    decision_matches_expected: ratio(evaluation.summary.matches, total),
    wrong_actions: ratio(wrongActions, total),
    wrong_target_accepted: ratio(evaluation.summary.wrong_target, total),
    false_activations_accepted: ratio(falseActivationsAccepted, negatives),
    false_activations_prevented: ratio(evaluation.summary.false_activations_prevented, negatives),
    abstention_rate: ratio(decisions.abstain, total),
    missed_accepts: ratio(missedAccepts, expectedAccept),
    confirmation_burden: ratio(decisions.ask_confirmation, total - decisions.stop),
    emergency_stops: ratio(decisions.stop, total),
    decision_latency_ms: {
      basis: "simulated: decision_at_ms minus the last timeline event in each fixture",
      min: Math.min.apply(null, latencies),
      median: median(latencies),
      max: Math.max.apply(null, latencies),
    },
    simulated_duration_s: simulatedMs / 1000,
    false_activations_per_hour: {
      value: null,
      note:
        "The scenarios cover " + simulatedMs / 1000 +
        " simulated seconds in total, and an hourly rate extrapolated from that would be an invented number.",
    },
    mismatches: evaluation.rows
      .filter(function (r) { return !r.match; })
      .map(function (r) { return { id: r.id, expected: r.expected, actual: r.actual }; }),
  };
}

function fmt(r) {
  const pct = r.value === null ? "n/a" : (100 * r.value).toFixed(1) + "%";
  return r.numerator + " / " + r.denominator + " (" + pct + ")";
}

function renderMarkdown(report) {
  const lines = [
    "# Synthetic replay report",
    "",
    "> " + report.notice,
    "",
    "Schema `" + report.schema_version + "`; " + report.scenarios + " scenarios.",
    "",
    "| Metric | Count / denominator |",
    "|---|---|",
    "| Decision matches the expected one | " + fmt(report.decision_matches_expected) + " |",
    "| Wrong actions (accepted wrong target, or accepted false activation) | " + fmt(report.wrong_actions) + " |",
    "| Accepted with a wrong target | " + fmt(report.wrong_target_accepted) + " |",
    "| False activations accepted (of negative examples) | " + fmt(report.false_activations_accepted) + " |",
    "| False activations prevented (of negative examples) | " + fmt(report.false_activations_prevented) + " |",
    "| Abstentions | " + fmt(report.abstention_rate) + " |",
    "| Missed accepts (expected accept, did not accept) | " + fmt(report.missed_accepts) + " |",
    "| Confirmation burden (confirmations, excluding stops) | " + fmt(report.confirmation_burden) + " |",
    "| Emergency stops | " + fmt(report.emergency_stops) + " |",
    "",
    "Decisions: accept " + report.decisions.accept + ", abstain " + report.decisions.abstain +
      ", ask confirmation " + report.decisions.ask_confirmation + ", stop " + report.decisions.stop + ".",
    "",
    "Decision latency (" + report.decision_latency_ms.basis + "): min " + report.decision_latency_ms.min +
      " ms, median " + report.decision_latency_ms.median + " ms, max " + report.decision_latency_ms.max + " ms.",
    "",
    "False activations per hour: not computed. " + report.false_activations_per_hour.note,
    "",
  ];
  if (report.mismatches.length) {
    lines.push("## Mismatches", "");
    report.mismatches.forEach(function (m) {
      lines.push("- `" + m.id + "`: expected " + m.expected + ", got " + m.actual);
    });
    lines.push("");
  }
  return lines.join("\n");
}

function main(argv) {
  const report = buildReport(loadFixtures());
  process.stdout.write(argv.indexOf("--json") >= 0 ? JSON.stringify(report, null, 2) + "\n" : renderMarkdown(report));
  return report.mismatches.length === 0 ? 0 : 1;
}

if (require.main === module) process.exitCode = main(process.argv.slice(2));

module.exports = { buildReport: buildReport, renderMarkdown: renderMarkdown, loadFixtures: loadFixtures, NOTICE: NOTICE };
