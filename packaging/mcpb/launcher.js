#!/usr/bin/env node
// Launcher inside the YazSes .mcpb bundle (ADR-032 section 1, #638).
//
// The bundle contains no YazSes. This file runs the `yazses mcp-server` command that is
// already installed on the machine, passing stdin/stdout/stderr straight through (the MCP
// protocol speaks over stdio). If `yazses` cannot be found it says how to install it, on
// stderr, and exits 127 (the shell's "command not found" status) instead of leaving the
// client with a bare spawn error.
//
// On Windows the .exe installer (which winget and Chocolatey run too) puts no
// yazses.exe on PATH: `yazses` there is the yazses.cmd shim, which spawn()
// without a shell does not find. The program behind that shim, yazses-cli.exe,
// is in the same PATH directory, so it is tried second.
//
// Node built-ins only; no network.
"use strict";

const { spawn } = require("node:child_process");

const INSTALL_URL = "https://mskazemi.com/yazses/get-started.html";
const NOT_FOUND_STATUS = 127;

// Names the installed command goes by, tried in order.
const COMMANDS = process.platform === "win32" ? ["yazses", "yazses-cli"] : ["yazses"];

let child;

function start(index) {
  const command = COMMANDS[index];
  const attempt = spawn(command, ["mcp-server", ...process.argv.slice(2)], {
    stdio: "inherit",
  });
  child = attempt;

  attempt.on("error", (err) => {
    if (err && err.code === "ENOENT") {
      if (index + 1 < COMMANDS.length) {
        start(index + 1);
        return;
      }
      process.stderr.write(
        "YazSes is not installed, or the `yazses` command is not on your PATH.\n" +
          "This bundle does not contain YazSes: it runs the copy installed on this machine.\n" +
          `Install YazSes first: ${INSTALL_URL}\n` +
          "Then make sure `yazses` is on your PATH and restart this client.\n",
      );
      process.exit(NOT_FOUND_STATUS);
    }
    process.stderr.write(`could not start \`${command} mcp-server\`: ${err}\n`);
    process.exit(1);
  });

  attempt.on("exit", (code, signal) => {
    // A process that never started has no pid; its "error" handler decides.
    if (attempt.pid === undefined) {
      return;
    }
    if (signal) {
      process.exit(128 + (require("node:os").constants.signals[signal] || 0));
    }
    process.exit(code === null ? 1 : code);
  });
}

start(0);

for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => child.kill(sig));
}
