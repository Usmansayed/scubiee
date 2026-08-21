#!/usr/bin/env node
"use strict";

const { spawn } = require("child_process");
const { preferredPython, pythonArgs } = require("../scripts/install-python.cjs");

const python = preferredPython();
if (!python) {
  console.error(
    "scubiee: Python 3.10+ is required.\n" +
      "  macOS manual install:\n" +
      "    python3 -m venv ~/.context-engine/venv\n" +
      "    source ~/.context-engine/venv/bin/activate\n" +
      "    pip install \"scubiee[coreml] @ git+https://github.com/Usmansayed/new-context-engine.git@v0.2.5\"\n" +
      "    python -m pipeline setup"
  );
  process.exit(1);
}

const child = spawn(
  python,
  pythonArgs(python, ["-m", "pipeline", ...process.argv.slice(2)]),
  {
    stdio: "inherit",
    env: process.env,
  }
);
child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code === null ? 1 : code);
});
