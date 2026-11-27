#!/usr/bin/env node
// Deterministic replay report for the synthetic multimodal fixtures (issue #700).
//
//   node examples/hci-hf-lab/eval/replay.js          Markdown to stdout
//   node examples/hci-hf-lab/eval/replay.js --json   JSON to stdout
//
// Timing is checked first: a scenario whose timestamps are not monotonic, or whose age_ms does
// not follow from its timeline, is never resolved (only a stop still wins). The report also
// replays the set over a fixed grid of confidence floors (the abstention/error trade-off).
//
// Pure: no network, no clock, no randomness, no operating-system action. Every number is
// computed from hand-authored SYNTHETIC scenarios; it is a regression check on the resolver,
// not a measurement of a device or of people (that is the participant validation in #419).
// Exits 1 when any scenario breaks the timing rules or does not match its expected decision.
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

const CONFIDENCE_FLOORS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(function (n) { return n / 10; });

const TRADEOFF_BASIS =
  "one shared floor replaces the gaze, voice and every activation minimum; every other rule is unchanged";

function isMs(v) {
  return Number.isInteger(v) && v >= 0;
}

// The timing rules of the fixtures, checked by the harness itself. Events are in arrival order;
// t_ms never goes back except on an event flagged out_of_order; and a present stream's age_ms is
// decision_at_ms minus its last sample (gaze) or activation event, so it cannot be hand-waved.
function timingErrors(scenario) {
  const errors = [];
  const at = scenario.decision_at_ms;
  const events = scenario.timeline;
  if (!isMs(at)) errors.push("decision_at_ms must be a non-negative integer");
  if (!Array.isArray(events) || events.length === 0) return errors.concat("timeline is missing or empty");

  let highest = -1;
  events.forEach(function (e, i) {
    if (e.seq !== i + 1) errors.push("event " + (i + 1) + ": seq must follow arrival order");
    if (!isMs(e.t_ms)) {
      errors.push("event " + (i + 1) + ": t_ms must be a non-negative integer");
      return;
    }
    if (isMs(at) && e.t_ms > at) errors.push("event " + (i + 1) + ": later than the decision");
    const late = e.out_of_order === true;
    if (late && e.t_ms >= highest) errors.push("event " + (i + 1) + ": flagged out_of_order but is not late");
    if (!late && e.t_ms < highest) errors.push("event " + (i + 1) + ": timestamp goes back");
    highest = Math.max(highest, e.t_ms);
  });

  const inputs = scenario.inputs || {};
  const gaze = inputs.gaze;
  const activation = inputs.activation;
  [
    { source: "gaze", event: "sample", stream: gaze && gaze.connected ? gaze : null },
    { source: "activation", event: "activation", stream: activation && activation.kind !== "none" ? activation : null },
  ].forEach(function (want) {
    if (!want.stream) return; // a missing signal needs no event; the resolver handles its absence
    const seen = events.filter(function (e) { return e.source === want.source && e.event === want.event; });
    if (seen.length === 0) {
      errors.push(want.source + ": present in inputs but the timeline has no " + want.event + " event");
    } else if (want.stream.age_ms !== at - seen[seen.length - 1].t_ms) {
      errors.push(want.source + ": age_ms does not follow from the timeline");
    }
  });
  return errors;
}

// A scenario with bad timing loses its activation, so nothing can be proposed from it. The stop
// rule runs before the activation rule, so an emergency stop still wins.
function withholdBadTiming(fixtures, violations) {
  return Object.assign({}, fixtures, {
    scenarios: fixtures.scenarios.map(function (sc, i) {
      if (violations[i].length === 0) return sc;
      return Object.assign({}, sc, { inputs: Object.assign({}, sc.inputs, { activation: { kind: "none" } }) });
    }),
  });
}

function tally(fixtures) {
  const rows = R.evaluateAll(fixtures).rows;
  const t = {
    rows: rows, decisions: { accept: 0, abstain: 0, ask_confirmation: 0, stop: 0 },
    matches: 0, wrong_target: 0, wrong_actions: 0, negatives: 0, false_accepted: 0, false_prevented: 0,
    expected_accept: 0, missed_accepts: 0,
  };
  rows.forEach(function (row, i) {
    const negative = fixtures.scenarios[i].negative_example === true;
    const falseActivation = negative && row.actual === "accept";
    t.decisions[row.actual] += 1;
    if (row.match) t.matches += 1;
    if (row.wrong_target) t.wrong_target += 1;
    if (negative) t.negatives += 1;
    if (falseActivation) t.false_accepted += 1;
    if (row.prevented) t.false_prevented += 1;
    // A wrong target and an accepted false activation are both wrong actions; count a scenario once.
    if (row.wrong_target || falseActivation) t.wrong_actions += 1;
    if (row.expected === "accept") {
      t.expected_accept += 1;
      if (row.actual !== "accept") t.missed_accepts += 1;
    }
  });
  return t;
}

function withConfidenceFloor(fixtures, floor) {
  const activation = {};
  Object.keys(fixtures.thresholds.activation_min_confidence).forEach(function (kind) { activation[kind] = floor; });
  return Object.assign({}, fixtures, {
    thresholds: Object.assign({}, fixtures.thresholds, {
      gaze_min_confidence: floor, voice_min_confidence: floor, activation_min_confidence: activation,
    }),
  });
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
  const violations = fixtures.scenarios.map(timingErrors);
  const gated = withholdBadTiming(fixtures, violations);
  const result = tally(gated);
  // Latency and duration are read from the timeline, so only well-timed scenarios contribute.
  const timed = fixtures.scenarios.filter(function (sc, i) { return violations[i].length === 0; });
  const latencies = timed.map(function (sc) { return sc.decision_at_ms - lastEventMs(sc); });

  const decisions = result.decisions;
  const total = result.rows.length;
  const simulatedMs = timed.reduce(function (sum, s) { return sum + s.decision_at_ms; }, 0);

  return {
    synthetic: true,
    notice: NOTICE,
    schema_version: fixtures.schema_version,
    scenarios: total,
    decisions: decisions,
    decision_matches_expected: ratio(result.matches, total),
    wrong_actions: ratio(result.wrong_actions, total),
    wrong_target_accepted: ratio(result.wrong_target, total),
    false_activations_accepted: ratio(result.false_accepted, result.negatives),
    false_activations_prevented: ratio(result.false_prevented, result.negatives),
    abstention_rate: ratio(decisions.abstain, total),
    missed_accepts: ratio(result.missed_accepts, result.expected_accept),
    confirmation_burden: ratio(decisions.ask_confirmation, total - decisions.stop),
    emergency_stops: ratio(decisions.stop, total),
    decision_latency_ms: {
      basis: "simulated: decision_at_ms minus the last timeline event in each fixture",
      min: latencies.length ? Math.min.apply(null, latencies) : null,
      median: median(latencies),
      max: latencies.length ? Math.max.apply(null, latencies) : null,
    },
    simulated_duration_s: simulatedMs / 1000,
    false_activations_per_hour: {
      value: null,
      note:
        "The scenarios cover " + simulatedMs / 1000 +
        " simulated seconds in total, and an hourly rate extrapolated from that would be an invented number.",
    },
    abstention_tradeoff: {
      basis: TRADEOFF_BASIS,
      points: CONFIDENCE_FLOORS.map(function (floor) {
        const at = tally(withConfidenceFloor(gated, floor));
        return {
          confidence_floor: floor,
          wrong_actions: ratio(at.wrong_actions, total),
          abstention_rate: ratio(at.decisions.abstain, total),
          missed_accepts: ratio(at.missed_accepts, at.expected_accept),
          confirmations: ratio(at.decisions.ask_confirmation, total - at.decisions.stop),
        };
      }),
    },
    timing_violations: fixtures.scenarios
      .map(function (sc, i) { return { id: sc.id, errors: violations[i] }; })
      .filter(function (v) { return v.errors.length > 0; }),
    mismatches: result.rows
      .filter(function (r) { return !r.match; })
      .map(function (r) { return { id: r.id, expected: r.expected, actual: r.actual }; }),
  };
}

function fmt(r) {
  const pct = r.value === null ? "n/a" : (100 * r.value).toFixed(1) + "%";
  return r.numerator + " / " + r.denominator + " (" + pct + ")";
}

function fmtLatency(l) {
  if (l.min === null) return "not computed: no scenario passed the timing check.";
  return "min " + l.min + " ms, median " + l.median + " ms, max " + l.max + " ms.";
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
    "Decision latency (" + report.decision_latency_ms.basis + "): " + fmtLatency(report.decision_latency_ms),
    "",
    "False activations per hour: not computed. " + report.false_activations_per_hour.note,
    "",
    "## Abstention/error trade-off",
    "",
    "Synthetic sweep: " + report.abstention_tradeoff.basis + ". It does not recommend a threshold.",
    "",
    "| Confidence floor | Wrong actions | Abstentions | Missed accepts | Confirmations (excluding stops) |",
    "|---|---|---|---|---|",
  ];
  report.abstention_tradeoff.points.forEach(function (p) {
    lines.push("| " + p.confidence_floor.toFixed(1) + " | " + fmt(p.wrong_actions) + " | " + fmt(p.abstention_rate) +
      " | " + fmt(p.missed_accepts) + " | " + fmt(p.confirmations) + " |");
  });
  lines.push("");
  if (report.timing_violations.length) {
    lines.push("## Timing violations (nothing was proposed from these scenarios)", "");
    report.timing_violations.forEach(function (v) {
      lines.push("- `" + v.id + "`: " + v.errors.join("; "));
    });
    lines.push("");
  }
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
  return report.mismatches.length === 0 && report.timing_violations.length === 0 ? 0 : 1;
}

if (require.main === module) process.exitCode = main(process.argv.slice(2));

module.exports = {
  buildReport: buildReport, renderMarkdown: renderMarkdown, loadFixtures: loadFixtures, timingErrors: timingErrors,
  NOTICE: NOTICE,
};
