#!/usr/bin/env node
"use strict";

const { spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const PKG = JSON.parse(
  fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8")
);

const VENV_DIR = path.join(os.homedir(), ".context-engine", "venv");
const GIT_ORIGIN =
  process.env.CTX_GIT_ORIGIN ||
  "https://github.com/Usmansayed/new-context-engine.git";

function pythonArgs(bin, args) {
  if (bin === "py") return ["-3", ...args];
  return args;
}

function venvPython() {
  if (process.platform === "win32") {
    return path.join(VENV_DIR, "Scripts", "python.exe");
  }
  return path.join(VENV_DIR, "bin", "python");
}

function preferredPython() {
  const venv = venvPython();
  if (fs.existsSync(venv)) return venv;
  if (process.env.CTX_PYTHON) return process.env.CTX_PYTHON;
  return findPython();
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

function findUv() {
  const probe = spawnSync("uv", ["--version"], { encoding: "utf8" });
  return probe.status === 0 ? "uv" : null;
}

function run(bin, args, opts = {}) {
  return spawnSync(bin, args, {
    encoding: "utf8",
    shell: false,
    ...opts,
  });
}

function pipNeedsBreakSystemPackages(output) {
  const text = `${output.stdout || ""}\n${output.stderr || ""}`;
  return (
    text.includes("externally-managed-environment") ||
    text.includes("PEP 668") ||
    text.includes("externally managed")
  );
}

function ensureVenv(basePython) {
  const py = venvPython();
  if (fs.existsSync(py)) return py;
  fs.mkdirSync(path.dirname(VENV_DIR), { recursive: true });
  console.log(`[scubiee] Creating isolated venv at ${VENV_DIR}`);
  const created = run(basePython, pythonArgs(basePython, ["-m", "venv", VENV_DIR]), {
    stdio: "inherit",
  });
  if (created.status !== 0 || !fs.existsSync(py)) {
    console.error("[scubiee] Failed to create Python venv");
    return null;
  }
  run(py, ["-m", "pip", "install", "--upgrade", "pip"], { stdio: "inherit" });
  return py;
}

function pipSpecs(version) {
  if (process.env.CTX_PIP_SPEC) return [process.env.CTX_PIP_SPEC];
  const extra = process.platform === "darwin" ? "[coreml]" : "";
  return [
    `scubiee${extra}==${version}`,
    `scubiee${extra} @ git+${GIT_ORIGIN}@v${version}`,
    `scubiee${extra} @ git+${GIT_ORIGIN}@feat/production-certification`,
  ];
}

function uvToolSpecs(version) {
  if (process.env.CTX_PIP_SPEC) return [process.env.CTX_PIP_SPEC];
  const extra = process.platform === "darwin" ? "[coreml]" : "";
  return [
    `scubiee${extra}==${version}`,
    `scubiee${extra} @ git+${GIT_ORIGIN}@v${version}`,
    `scubiee${extra} @ git+${GIT_ORIGIN}@feat/production-certification`,
  ];
}

function pipInstall(python, spec) {
  const env = {
    ...process.env,
    PIP_PROGRESS_BAR: "off",
    PIP_DISABLE_PIP_VERSION_CHECK: "1",
  };
  return run(
    python,
    pythonArgs(python, ["-m", "pip", "install", "--progress-bar", "off", spec]),
    { env }
  );
}

function uvToolRoot() {
  return path.join(os.homedir(), "AppData", "Roaming", "uv", "tools", "scubiee");
}

function uvToolPython() {
  if (process.platform === "win32") {
    return path.join(uvToolRoot(), "Scripts", "python.exe");
  }
  return path.join(uvToolRoot(), "bin", "python");
}

function verifyUvToolInstall() {
  const py = uvToolPython();
  const pyvenv = path.join(uvToolRoot(), "pyvenv.cfg");
  if (!fs.existsSync(pyvenv)) {
    console.error(
      "[scubiee] uv tool env is broken (missing pyvenv.cfg).\n" +
        "  Quit Cursor, then run:\n" +
        "    powershell -ExecutionPolicy Bypass -File scripts/repair-uv-scubiee.ps1"
    );
    return false;
  }
  if (!fs.existsSync(py)) return true;
  const probe = run(py, ["-c", "import faiss"], { encoding: "utf8" });
  if (probe.status === 0) return true;
  console.log("[scubiee] faiss broken after uv install — repairing from wheel …");
  const whlDir = path.join(os.tmpdir(), "faiss_whl");
  fs.mkdirSync(whlDir, { recursive: true });
  run(py, ["-m", "pip", "download", "faiss-cpu==1.15.0", "-d", whlDir, "--no-deps", "--quiet"], {
    stdio: "inherit",
  });
  const wheels = fs.readdirSync(whlDir).filter((f) => f.startsWith("faiss_cpu-") && f.endsWith(".whl"));
  if (!wheels.length) {
    console.error("[scubiee] faiss wheel repair failed.");
    return false;
  }
  const fix = run("uv", ["pip", "install", "--force-reinstall", path.join(whlDir, wheels[0]), "--python", py], {
    stdio: "inherit",
  });
  return fix.status === 0;
}

function uvToolInstall(spec) {
  console.log(`[scubiee] uv tool install --force ${spec} --index-url https://pypi.org/simple`);
  return run(
    "uv",
    ["tool", "install", "--force", spec, "--index-url", "https://pypi.org/simple"],
    { stdio: "inherit" }
  );
}

function installWithUv(version) {
  let last = null;
  for (const spec of uvToolSpecs(version)) {
    last = uvToolInstall(spec);
    if (last.status === 0) return last;
  }
  return last;
}

function installPackage(python) {
  let last = null;
  for (const spec of pipSpecs(PKG.version)) {
    console.log(`[scubiee] pip install ${spec}`);
    last = pipInstall(python, spec);
    if (last.status === 0) return last;
    if (pipNeedsBreakSystemPackages(last)) break;
  }
  return last;
}

function writePathHint(python) {
  const binDir =
    process.platform === "win32"
      ? path.join(VENV_DIR, "Scripts")
      : path.join(VENV_DIR, "bin");
  if (python === venvPython() && fs.existsSync(binDir)) {
    console.log(
      `[scubiee] Add to your shell profile:\n` +
        `  export PATH="${binDir}:$PATH"\n` +
        `Then run: scubiee setup`
    );
  }
}

function runSetupViaScubiee() {
  const setup = run("scubiee", ["setup"], { stdio: "inherit" });
  if (setup.status === 0 || setup.error == null) return setup.status || 0;
  return setup.status || 1;
}

function runSetupViaPython(python) {
  const setup = run(python, pythonArgs(python, ["-m", "pipeline", "setup"]), {
    stdio: "inherit",
  });
  return setup.status || 0;
}

function main() {
  if (process.env.CTX_SKIP_PIP === "1") {
    console.log("[scubiee] CTX_SKIP_PIP=1 — skipping Python install");
    return 0;
  }

  console.log(
    "This may take a few minutes. Downloading and installing the Scubiee engine."
  );

  const uv = process.env.CTX_USE_UV === "0" ? null : findUv();
  if (uv) {
    const installed = installWithUv(PKG.version);
    if (installed && installed.status === 0) {
      if (!verifyUvToolInstall()) {
        return 1;
      }
      console.log(
        "[scubiee] If `scubiee` is not found, run once: uv tool update-shell (then restart terminal)"
      );
      if (process.env.CTX_SKIP_SETUP === "1") {
        console.log("[scubiee] CTX_SKIP_SETUP=1 — run `scubiee setup` yourself");
        return 0;
      }
      console.log("[scubiee] Installed with uv. Running scubiee setup …");
      return runSetupViaScubiee();
    }
    console.log("[scubiee] uv tool install failed — falling back to pip/venv");
  }

  let python = preferredPython();
  if (!python) {
    console.error(
      "[scubiee] Python 3.10+ not found.\n" +
        "  Recommended: install uv (https://docs.astral.sh/uv/) then\n" +
        "    uv tool install scubiee\n" +
        "    scubiee setup\n" +
        "  macOS: brew install python@3.12\n" +
        "  pip fallback: python3 -m venv ~/.context-engine/venv\n"
    );
    return 1;
  }

  let installed = installPackage(python);
  if (installed && installed.status !== 0 && pipNeedsBreakSystemPackages(installed)) {
    const base = findPython();
    if (!base) return installed.status || 1;
    python = ensureVenv(base);
    if (!python) return 1;
    installed = installPackage(python);
  }

  if (!installed || installed.status !== 0) {
    if (installed?.stdout) process.stdout.write(installed.stdout);
    if (installed?.stderr) process.stderr.write(installed.stderr);
    console.error(
      "[scubiee] pip install failed.\n" +
        "  Recommended:\n" +
        "    uv tool install scubiee\n" +
        "    scubiee setup\n" +
        "  pip fallback:\n" +
        `    python3 -m venv ~/.context-engine/venv\n` +
        `    source ~/.context-engine/venv/bin/activate\n` +
        `    pip install "scubiee[coreml] @ git+${GIT_ORIGIN}@v${PKG.version}"\n` +
        "    python -m pipeline setup"
    );
    return installed?.status || 1;
  }

  writePathHint(python);

  if (process.env.CTX_SKIP_SETUP === "1") {
    console.log("[scubiee] CTX_SKIP_SETUP=1 — run `scubiee setup` yourself");
    return 0;
  }

  return runSetupViaPython(python);
}

if (require.main === module) {
  process.exit(main());
}

module.exports = {
  findPython,
  findUv,
  preferredPython,
  pythonArgs,
  venvPython,
  main,
};
