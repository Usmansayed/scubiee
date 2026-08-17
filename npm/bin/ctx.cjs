#!/usr/bin/env node
"use strict";

const { spawn } = require("child_process");
const { findPython, pythonArgs } = require("../scripts/install-python.cjs");

const python = findPython();
if (!python) {
  console.error(
    "scubiee: Python 3.10+ is required. Install Python, then: pip install scubiee && ctx setup"
  );
  process.exit(1);
}

const child = spawn(python, pythonArgs(python, ["-m", "pipeline", ...process.argv.slice(2)]), {
  stdio: "inherit",
  env: process.env,
});
child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code === null ? 1 : code);
});
