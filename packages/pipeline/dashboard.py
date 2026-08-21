"""Minimal Context Engine settings dashboard (HTML + JSON API)."""

from __future__ import annotations

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Context Engine — Settings</title>
  <style>
    :root {
      --bg: #0f1419;
      --panel: #1a222c;
      --text: #e7ecf1;
      --muted: #8b9aab;
      --accent: #3d9a6a;
      --border: #2a3542;
      --warn: #c9a227;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", system-ui, sans-serif;
      background: radial-gradient(1200px 600px at 10% -10%, #1a2a22 0%, var(--bg) 55%);
      color: var(--text);
      min-height: 100vh;
      padding: 2rem 1.25rem 3rem;
    }
    main { max-width: 640px; margin: 0 auto; }
    h1 { font-size: 1.6rem; font-weight: 650; letter-spacing: -0.02em; margin: 0 0 0.35rem; }
    .sub { color: var(--muted); margin-bottom: 1.75rem; line-height: 1.45; }
    section {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.25rem 1.35rem;
      margin-bottom: 1rem;
    }
    h2 { font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin: 0 0 1rem; }
    label.option {
      display: flex; gap: 0.75rem; align-items: flex-start;
      padding: 0.85rem 0.9rem; border-radius: 8px; border: 1px solid transparent;
      cursor: pointer; margin-bottom: 0.5rem;
    }
    label.option:hover { background: rgba(255,255,255,0.03); }
    label.option.active { border-color: var(--accent); background: rgba(61,154,106,0.08); }
    label.option input { margin-top: 0.25rem; }
    .title { font-weight: 600; }
    .desc { color: var(--muted); font-size: 0.9rem; margin-top: 0.2rem; line-height: 1.4; }
    .row { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 0.5rem 0; }
    button {
      background: var(--accent); color: #04140c; border: 0; border-radius: 8px;
      padding: 0.65rem 1.1rem; font-weight: 650; cursor: pointer;
    }
    button:disabled { opacity: 0.5; cursor: default; }
    #status { margin-top: 0.75rem; font-size: 0.9rem; color: var(--muted); min-height: 1.2em; }
    #status.ok { color: var(--accent); }
    #status.err { color: #e07070; }
    code { font-size: 0.85em; color: var(--warn); }
  </style>
</head>
<body>
  <main>
    <h1>Context Engine</h1>
    <p class="sub">Choose how projects are registered. Both modes use the same indexing pipeline; only the trigger differs.</p>

    <section>
      <h2>Project registration</h2>
      <label class="option" id="opt-auto">
        <input type="radio" name="mode" value="automatic" />
        <div>
          <div class="title">Automatic</div>
          <div class="desc">When a supported IDE opens a project, Context Engine registers it once, then keeps incremental indexing on.</div>
        </div>
      </label>
      <label class="option" id="opt-mcp">
        <input type="radio" name="mode" value="mcp_cli" />
        <div>
          <div class="title">MCP / CLI</div>
          <div class="desc">Do not auto-initialize. Register only when MCP asks (with always-allow option) or you run <code>scubiee register</code> / <code>scubiee index</code>.</div>
        </div>
      </label>
    </section>

    <section>
      <h2>After registration</h2>
      <div class="row">
        <div>
          <div class="title">Incremental indexing</div>
          <div class="desc">5-minute keeper updates changed files (graph + embed).</div>
        </div>
        <input type="checkbox" id="incremental" />
      </div>
      <div class="row">
        <div>
          <div class="title">File watching</div>
          <div class="desc">Keeper + sync-trigger while the session is open.</div>
        </div>
        <input type="checkbox" id="watching" />
      </div>
    </section>

    <button id="save" type="button">Save settings</button>
    <div id="status"></div>
  </main>
  <script>
    const optAuto = document.getElementById("opt-auto");
    const optMcp = document.getElementById("opt-mcp");
    function syncActive() {
      const v = document.querySelector('input[name="mode"]:checked')?.value;
      optAuto.classList.toggle("active", v === "automatic");
      optMcp.classList.toggle("active", v === "mcp_cli");
    }
    document.querySelectorAll('input[name="mode"]').forEach(el => el.addEventListener("change", syncActive));

    async function load() {
      const r = await fetch("/api/settings");
      const d = await r.json();
      const mode = d.registration_mode === "mcp_cli" ? "mcp_cli" : "automatic";
      document.querySelector(`input[name="mode"][value="${mode}"]`).checked = true;
      document.getElementById("incremental").checked = !!d.incremental_indexing;
      document.getElementById("watching").checked = !!d.file_watching;
      syncActive();
    }
    document.getElementById("save").onclick = async () => {
      const status = document.getElementById("status");
      status.textContent = "Saving…";
      status.className = "";
      const body = {
        registration_mode: document.querySelector('input[name="mode"]:checked').value,
        incremental_indexing: document.getElementById("incremental").checked,
        file_watching: document.getElementById("watching").checked,
      };
      try {
        const r = await fetch("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || "save failed");
        status.textContent = "Saved.";
        status.className = "ok";
      } catch (e) {
        status.textContent = String(e.message || e);
        status.className = "err";
      }
    };
    load().catch(e => {
      document.getElementById("status").textContent = String(e);
      document.getElementById("status").className = "err";
    });
  </script>
</body>
</html>
"""
