#!/usr/bin/env node
// Writes, or checks, fixtures.manifest.json: the schema version, the scenario ids and the
// SHA-256 of the two data files (issue #699). The manifest is generated; never edit it by hand.
//
//   node examples/hci-hf-lab/eval/make_manifest.js          write the manifest
//   node examples/hci-hf-lab/eval/make_manifest.js --check  exit 1 if the committed one is stale
//
// Pure and offline: reads two files next to it, writes one.
"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const LAB = path.join(__dirname, "..");
const DATA_FILES = ["fixtures.js", "fixtures.schema.json"];
const MANIFEST = path.join(LAB, "fixtures.manifest.json");

function buildManifest(fixtures) {
  return {
    generated_by: "eval/make_manifest.js; do not edit by hand",
    schema_version: fixtures.schema_version,
    synthetic: fixtures.synthetic,
    license: fixtures.license,
    consent: fixtures.consent,
    scenario_count: fixtures.scenarios.length,
    scenarios: fixtures.scenarios.map((s) => s.id),
    files: DATA_FILES.map((name) => {
      const bytes = fs.readFileSync(path.join(LAB, name));
      return { path: name, bytes: bytes.length, sha256: crypto.createHash("sha256").update(bytes).digest("hex") };
    }),
  };
}

function render(manifest) {
  return JSON.stringify(manifest, null, 2) + "\n";
}

function main(argv) {
  const { loadFixtures } = require("./replay.js");
  const text = render(buildManifest(loadFixtures()));
  if (argv.indexOf("--check") >= 0) {
    const have = fs.existsSync(MANIFEST) ? fs.readFileSync(MANIFEST, "utf8") : null;
    if (have === text) {
      process.stdout.write("fixtures.manifest.json is current\n");
      return 0;
    }
    process.stderr.write("fixtures.manifest.json is stale; run: node examples/hci-hf-lab/eval/make_manifest.js\n");
    return 1;
  }
  fs.writeFileSync(MANIFEST, text, "utf8");
  process.stdout.write("wrote " + path.relative(process.cwd(), MANIFEST) + "\n");
  return 0;
}

if (require.main === module) process.exitCode = main(process.argv.slice(2));

module.exports = { buildManifest: buildManifest, render: render, DATA_FILES: DATA_FILES };
