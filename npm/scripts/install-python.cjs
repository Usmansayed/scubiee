#!/usr/bin/env node
"use strict";

const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const PKG = JSON.parse(
  fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8")
);

function pythonArgs(bin, args) {
  if (bin === "py") return ["-3", ...args];
  return args;
}

function findPython() {
  const candidates = [];
  if (process.env.CTX_PYTHON) candidates.push(process.env.CTX_PYTHON);
  if (process.platform === "win32") candidates.push("py", "python", "python3");
  else candidates.push("python3", "python");
  const snippet =
    "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)";
  for (const bin of candidates) {
    const probe = spawnSync(bin, pythonArgs(bin, ["-c", snippet]), {
      encoding: "utf8",
    });
    if (probe.status === 0) return bin;
  }
  return null;
}

function main() {
  if (process.env.CTX_SKIP_PIP === "1") {
    console.log("[context-engine] CTX_SKIP_PIP=1 — skipping Python install");
    return 0;
  }
  const python = findPython();
  if (!python) {
    console.error(
      "[context-engine] Python 3.10+ not found. Install Python, then:\n" +
        "  pip install scubiee && ctx setup"
    );
    return 1;
  }
  const spec = process.env.CTX_PIP_SPEC || `scubiee==${PKG.version}`;
  const env = {
    ...process.env,
    PIP_PROGRESS_BAR: "off",
    PIP_DISABLE_PIP_VERSION_CHECK: "1",
  };
  const pip = pythonArgs(python, [
    "-m",
    "pip",
    "install",
    "--progress-bar",
    "off",
    spec,
  ]);
  console.log(
    "This may take a few minutes. Downloading and installing the Scubiee engine."
  );
  const installed = spawnSync(python, pip, {
    encoding: "utf8",
    env,
    shell: false,
  });
  if (installed.status !== 0) {
    if (installed.stdout) process.stdout.write(installed.stdout);
    if (installed.stderr) process.stderr.write(installed.stderr);
    console.error("[scubiee] pip install failed");
    return installed.status || 1;
  }
  if (process.env.CTX_SKIP_SETUP === "1") {
    console.log("[context-engine] CTX_SKIP_SETUP=1 — run `ctx setup` yourself");
    return 0;
  }
  const setup = spawnSync(
    python,
    pythonArgs(python, ["-m", "pipeline", "setup"]),
    { stdio: "inherit", shell: false }
  );
  return setup.status || 0;
}

if (require.main === module) {
  process.exit(main());
}

module.exports = { findPython, pythonArgs, main };
