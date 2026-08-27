(() => {
  "use strict";

  const API = "/ce-dashboard/api";
  const pageTitles = {
    overview: "Overview",
    repositories: "Repositories",
    sync: "Index & Sync",
    storage: "Storage",
    health: "Health",
    runtime: "Runtime",
    graph: "Graph",
    settings: "Settings",
  };
  const state = { repositories: [], forgetRepo: null, pathAction: null, graphProjectId: null };
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function displayValue(value) {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "boolean") return value ? "Yes" : "No";
    if (Array.isArray(value)) {
      return value.length
        ? value.map((item) => typeof item === "object" ? JSON.stringify(item) : String(item)).join(", ")
        : "None";
    }
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  function labelFor(key) {
    return String(key).replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  async function api(path, options = {}) {
    const response = await fetch(`${API}/${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const payload = await response.json().catch(() => ({ ok: false, error: "Invalid server response" }));
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || `Request failed (${response.status})`);
    }
    return payload;
  }

  function toast(message, type = "success") {
    const item = document.createElement("div");
    item.className = `toast ${type === "error" ? "error" : ""}`;
    item.textContent = message;
    $("#toast-region").append(item);
    window.setTimeout(() => item.remove(), 4200);
  }

  function refreshIcons() {
    if (globalThis.lucide?.createIcons) globalThis.lucide.createIcons();
  }

  function emptyState(icon, title, copy, { actionLabel = "", goPage = "", openAdd = false } = {}) {
    let action = "";
    if (openAdd) {
      action = `<button class="button primary small" type="button" data-open-add>${escapeHtml(actionLabel || "Add repository")}</button>`;
    } else if (actionLabel && goPage) {
      action = `<button class="button primary small" type="button" data-go="${escapeHtml(goPage)}">${escapeHtml(actionLabel)}</button>`;
    }
    return `<div class="empty-state">
      <div class="empty-icon" data-lucide="${escapeHtml(icon)}"></div>
      <strong>${escapeHtml(title)}</strong>
      <p>${escapeHtml(copy)}</p>
      ${action}
    </div>`;
  }

  function setServiceState(healthy) {
    $("#sidebar-status").textContent = healthy ? "Service online" : "Service unavailable";
    $(".pulse-dot").classList.toggle("offline", !healthy);
  }

  function repoName(repo) {
    const path = String(repo.primary_path || repo.path || repo.root || repo.paths?.[0] || "");
    return repo.name || path.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || repo.project_id || "Repository";
  }

  function repoPath(repo) {
    return repo.primary_path || repo.path || repo.root || repo.paths?.[0] || "Path unavailable";
  }

  function repoPresence(repo) {
    return String(repo.presence || repo.state || "active").toLowerCase();
  }

  function statusBadge(value) {
    const status = String(value || "unknown").toLowerCase();
    return `<span class="badge ${escapeHtml(status)}">${escapeHtml(status)}</span>`;
  }

  function showPage(page, updateHash = true) {
    if (!pageTitles[page]) page = "overview";
    $$(".page").forEach((element) => element.classList.toggle("active", element.id === `page-${page}`));
    $$(".nav-item").forEach((element) => element.classList.toggle("active", element.dataset.page === page));
    $("#page-title").textContent = pageTitles[page];
    document.title = `${pageTitles[page]} · Scubiee`;
    $("#sidebar").classList.remove("open");
    if (updateHash && location.hash !== `#${page}`) history.replaceState(null, "", `#${page}`);
    loadPage(page);
  }

  async function loadOverview() {
    try {
      const payload = await api("overview");
      const repositories = payload.repositories || {};
      const states = repositories.states || {};
      const active = Number(states.active || 0);
      const total = Number(repositories.managed || 0);
      $("#metric-managed").textContent = total;
      $("#metric-active").textContent = active;
      $("#metric-attention").textContent = Math.max(0, total - active);
      $("#metric-managed-detail").textContent = `${Object.keys(states).length || 0} presence state${Object.keys(states).length === 1 ? "" : "s"}`;
      $("#overview-updated").textContent = `Updated ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
      const stateEntries = Object.entries(states);
      $("#overview-repo-list").innerHTML = stateEntries.length
        ? stateEntries.map(([name, count]) => `
          <div class="state-row">
            <div class="repo-name"><strong>${escapeHtml(labelFor(name))}</strong><small>Presence validation</small></div>
            ${statusBadge(name)}
            <strong>${Number(count)}</strong>
          </div>`).join("")
        : emptyState(
            "folder-git-2",
            "No managed repositories yet",
            "Add a repository to start indexing and monitoring presence.",
            { actionLabel: "Add repository", openAdd: true }
          );
      const dashboard = payload.dashboard || {};
      $("#overview-service").innerHTML = `
        <div><dt>Network</dt><dd>Loopback only</dd></div>
        <div><dt>Base path</dt><dd><code>/ce-dashboard</code></dd></div>
        <div><dt>Process</dt><dd>${escapeHtml(dashboard.pid || "Current")}</dd></div>`;
      refreshIcons();
      setServiceState(true);
    } catch (error) {
      setServiceState(false);
      $("#overview-repo-list").innerHTML = errorCard(error);
    }
  }

  async function loadRepositories() {
    try {
      const payload = await api("repos");
      state.repositories = Array.isArray(payload.repositories) ? payload.repositories : [];
      renderRepositories();
      renderSync();
    } catch (error) {
      $("#repositories-body").innerHTML = `<tr><td colspan="5">${errorCard(error)}</td></tr>`;
      $("#sync-list").innerHTML = errorCard(error);
    }
  }

  function renderRepositories() {
    const query = $("#repo-search").value.trim().toLowerCase();
    const repos = state.repositories.filter((repo) =>
      [repoName(repo), repo.project_id, repoPath(repo)].some((value) => String(value || "").toLowerCase().includes(query))
    );
    $("#repo-count").textContent = `${repos.length} repositor${repos.length === 1 ? "y" : "ies"}`;
    $("#repositories-body").innerHTML = repos.length
      ? repos.map((repo) => {
          const projectId = String(repo.project_id || "");
          const presence = repoPresence(repo);
          const paused = Boolean(repo.paused);
          const indexed = repo.indexed ?? repo.index_exists ?? repo.has_index;
          return `<tr>
            <td><div class="repo-name"><strong>${escapeHtml(repoName(repo))}</strong><small>${escapeHtml(projectId)}</small></div></td>
            <td>${statusBadge(presence)}</td>
            <td>${statusBadge(indexed === false ? "empty" : paused ? "paused" : "ready")}</td>
            <td class="path-cell" title="${escapeHtml(repoPath(repo))}">${escapeHtml(repoPath(repo))}</td>
            <td><div class="actions">
              <button class="button quiet small" data-action="${paused ? "resume" : "pause"}" data-id="${escapeHtml(projectId)}">${paused ? "Resume" : "Pause"}</button>
              ${presence === "missing" ? `<button class="button quiet small" data-action="locate" data-id="${escapeHtml(projectId)}">Locate</button>` : ""}
              <button class="button quiet small" data-action="forget" data-id="${escapeHtml(projectId)}" title="Remove this repository from Scubiee. Source files are not deleted.">Forget</button>
            </div></td>
          </tr>`;
        }).join("")
      : `<tr><td colspan="5">${emptyState(
          "search",
          "No repositories match this view",
          state.repositories.length
            ? "Try a different search term."
            : "Add a repository to get started.",
          state.repositories.length
            ? {}
            : { actionLabel: "Add repository", openAdd: true }
        )}</td></tr>`;
    refreshIcons();
  }

  function renderSync() {
    $("#sync-list").innerHTML = state.repositories.length
      ? state.repositories.map((repo) => {
          const projectId = String(repo.project_id || "");
          const paused = Boolean(repo.paused);
          return `<article class="data-card">
            <div class="data-card-header">
              <div><h3>${escapeHtml(repoName(repo))}</h3><p>${escapeHtml(projectId)} · ${escapeHtml(repoPath(repo))}</p></div>
              <div class="data-card-actions">
                <button class="button secondary small" data-action="sync" data-id="${escapeHtml(projectId)}">Sync now</button>
                <button class="button secondary small" data-action="rebuild" data-id="${escapeHtml(projectId)}">Rebuild</button>
                <button class="button quiet small" data-action="${paused ? "resume" : "pause"}" data-id="${escapeHtml(projectId)}">${paused ? "Resume" : "Pause"}</button>
                <button class="button quiet small" data-action="clear-index" data-id="${escapeHtml(projectId)}">Clear index</button>
              </div>
            </div>
            <div class="key-grid">
              <div class="key-value"><span>Presence</span><strong>${escapeHtml(repoPresence(repo))}</strong></div>
              <div class="key-value"><span>Index state</span><strong>${escapeHtml(displayValue(repo.index_state || (repo.indexed === false ? "Empty" : "Ready")))}</strong></div>
              <div class="key-value"><span>Pinned</span><strong>${repo.pinned ? "Yes" : "No"}</strong></div>
            </div>
          </article>`;
        }).join("")
      : `<article class="data-card">${emptyState(
          "refresh-cw",
          "No repositories to index",
          "Add a repository from the Repositories page to sync and rebuild indexes.",
          { actionLabel: "Go to repositories", goPage: "repositories" }
        )}</article>`;
    refreshIcons();
  }

  function flattenObject(value, prefix = "", output = []) {
    if (!value || typeof value !== "object") return output;
    Object.entries(value).forEach(([key, item]) => {
      const label = prefix ? `${prefix} · ${labelFor(key)}` : labelFor(key);
      if (item && typeof item === "object" && !Array.isArray(item)) flattenObject(item, label, output);
      else output.push([label, displayValue(item)]);
    });
    return output;
  }

  function dataPanel(title, subtitle, value) {
    const rows = flattenObject(value).slice(0, 24);
    return `<article class="data-card">
      <div class="data-card-header"><div><h3>${escapeHtml(title)}</h3><p>${escapeHtml(subtitle)}</p></div></div>
      <div class="key-grid">${rows.length
        ? rows.map(([key, item]) => `<div class="key-value"><span>${escapeHtml(key)}</span><strong>${escapeHtml(item)}</strong></div>`).join("")
        : '<div class="key-value"><span>Status</span><strong>No details reported</strong></div>'}
      </div>
    </article>`;
  }

  function renderHealth(payload) {
    const repairs = Array.isArray(payload.repairs) ? payload.repairs : [];
    const safe = repairs.filter((item) => item && item.kind === "safe");
    const manual = repairs.filter((item) => item && item.kind === "manual");
    const repairRows = repairs.length
      ? repairs.map((item) => `<div class="key-value"><span>${escapeHtml(item.kind || "repair")} · ${escapeHtml(item.id || "")}</span><strong>${escapeHtml(item.detail || item.repo || "")}</strong></div>`).join("")
      : '<div class="key-value"><span>Repairs</span><strong>None</strong></div>';
    const repoCards = Array.isArray(payload.repositories)
      ? payload.repositories.map((repo) => dataPanel(repo.project_id || "Repository", repo.repo || "Managed repository", repo)).join("")
      : "";
    $("#health-content").innerHTML = `
      <article class="data-card">
        <div class="data-card-header"><div><h3>Repair plan</h3><p>${safe.length} safe · ${manual.length} manual</p></div></div>
        <div class="key-grid">${repairRows}</div>
      </article>
      ${dataPanel("Dashboard", "Local operator process", {
        identity: payload.dashboard_identity,
        pid: payload.dashboard_pid,
      })}
      ${repoCards}
    `;
  }

  async function loadHealth() {
    try {
      renderHealth(await api("doctor"));
      setServiceState(true);
    } catch (error) {
      $("#health-content").innerHTML = errorCard(error);
      setServiceState(false);
    }
  }

  async function applySafeRepairs() {
    const button = $("#apply-safe-repairs");
    if (button) button.disabled = true;
    try {
      const payload = await api("repair", { method: "POST", body: JSON.stringify({}) });
      toast(payload.ok ? "Safe repairs applied" : "Safe repairs finished with remaining manual actions");
      await loadHealth();
    } catch (error) {
      toast(error.message, "error");
    }
    if (button) button.disabled = false;
  }

  async function loadDataPage(endpoint, target, title) {
    try {
      const payload = await api(endpoint);
      const entries = Object.entries(payload).filter(([key]) => key !== "ok");
      $(target).innerHTML = entries.map(([key, value]) =>
        dataPanel(labelFor(key), `${title} data reported by Scubiee`, value)
      ).join("") || dataPanel(title, "No additional details", {});
      setServiceState(true);
    } catch (error) {
      $(target).innerHTML = errorCard(error);
      setServiceState(false);
    }
  }

  async function loadStorage() {
    try {
      const payload = await api("storage");
      $("#storage-content").innerHTML = globalThis.CEStorageRender.renderStorageSections(payload);
      setServiceState(true);
    } catch (error) {
      $("#storage-content").innerHTML = errorCard(error);
      setServiceState(false);
    }
  }

  async function loadSettings() {
    try {
      const payload = await api("settings");
      const settings = payload.settings || {};
      const mode = settings.admission_mode || settings.registration_mode || "automatic";
      const radio = $(`input[name="admission-mode"][value="${mode}"]`);
      if (radio) radio.checked = true;
      $("#settings-meta").textContent = settings.prefs_path ? `Preferences: ${settings.prefs_path}` : "Preferences are stored locally.";
      $("#settings-status").textContent = mode === "automatic" ? "Automatic admission is active" : "Manual admission is active";
    } catch (error) {
      $("#settings-status").textContent = error.message;
      toast(error.message, "error");
    }
  }

  function graphNodeLabel(node) {
    return String(node.label || node.name || node.id || "Unnamed");
  }

  function renderGraph(payload) {
    const allNodes = Array.isArray(payload.nodes) ? payload.nodes : [];
    const allEdges = Array.isArray(payload.edges) ? payload.edges : [];
    const nodes = allNodes.slice(0, 60);
    const nodeIds = new Set(nodes.map((node) => String(node.id)));
    const edges = allEdges.filter((edge) =>
      nodeIds.has(String(edge.source)) && nodeIds.has(String(edge.target))
    ).slice(0, 100);
    const positions = new Map();
    const centerX = 360;
    const centerY = 235;
    const radius = Math.min(185, 58 + nodes.length * 3.2);
    nodes.forEach((node, index) => {
      const angle = (index / Math.max(nodes.length, 1)) * Math.PI * 2 - Math.PI / 2;
      positions.set(String(node.id), {
        x: centerX + Math.cos(angle) * radius,
        y: centerY + Math.sin(angle) * radius,
      });
    });
    const edgeMarkup = edges.map((edge) => {
      const source = positions.get(String(edge.source));
      const target = positions.get(String(edge.target));
      return `<line x1="${source.x.toFixed(1)}" y1="${source.y.toFixed(1)}" x2="${target.x.toFixed(1)}" y2="${target.y.toFixed(1)}"></line>`;
    }).join("");
    const nodeMarkup = nodes.map((node) => {
      const point = positions.get(String(node.id));
      const label = graphNodeLabel(node);
      const short = label.length > 18 ? `${label.slice(0, 17)}…` : label;
      return `<g class="graph-node" transform="translate(${point.x.toFixed(1)} ${point.y.toFixed(1)})">
        <circle r="8"></circle>
        <text y="22" text-anchor="middle">${escapeHtml(short)}</text>
        <title>${escapeHtml(label)}</title>
      </g>`;
    }).join("");
    $("#graph-canvas").innerHTML = nodes.length
      ? `<svg viewBox="0 0 720 470" role="img" aria-label="Repository graph with ${nodes.length} visible nodes and ${edges.length} visible edges">
          <g class="graph-edges">${edgeMarkup}</g>
          <g>${nodeMarkup}</g>
        </svg>`
      : '<div class="graph-empty"><p>This graph artifact contains no nodes.</p></div>';
    $("#graph-edge-list").innerHTML = edges.length
      ? edges.map((edge) => `
        <div class="graph-edge-row">
          <strong>${escapeHtml(edge.source)}</strong>
          <span>${escapeHtml(edge.type || edge.relationship || "links to")}</span>
          <strong>${escapeHtml(edge.target)}</strong>
        </div>`).join("")
      : '<p class="empty-cell">This graph has no links.</p>';
    $("#graph-node-count").textContent = allNodes.length;
    $("#graph-edge-count").textContent = allEdges.length;
    $("#graph-status").textContent = [
      `Showing ${nodes.length} of ${allNodes.length} nodes`,
      `Showing ${edges.length} of ${allEdges.length} links`,
    ].join("; ") + ".";
  }

  async function loadGraph() {
    const select = $("#graph-repository");
    try {
      const reposPayload = await api("repos");
      state.repositories = Array.isArray(reposPayload.repositories) ? reposPayload.repositories : [];
      const available = state.repositories.filter((repo) => repo.project_id);
      if (!available.length) {
        select.innerHTML = '<option value="">No repositories</option>';
        select.disabled = true;
        $("#graph-canvas").innerHTML = '<div class="graph-empty"><p>Add and index a repository to view its graph.</p></div>';
        $("#graph-edge-list").innerHTML = '<p class="empty-cell">No links loaded.</p>';
        $("#graph-status").textContent = "No managed repositories are available.";
        return;
      }
      select.disabled = false;
      const selected = available.some((repo) => String(repo.project_id) === state.graphProjectId)
        ? state.graphProjectId
        : String(available[0].project_id);
      state.graphProjectId = selected;
      select.innerHTML = available.map((repo) =>
        `<option value="${escapeHtml(repo.project_id)}" ${String(repo.project_id) === selected ? "selected" : ""}>${escapeHtml(repoName(repo))}</option>`
      ).join("");
      $("#graph-status").textContent = "Loading graph artifact…";
      renderGraph(await api(`graph/${encodeURIComponent(selected)}`));
      setServiceState(true);
    } catch (error) {
      $("#graph-canvas").innerHTML = errorCard(error);
      $("#graph-edge-list").innerHTML = '<p class="empty-cell">No links available.</p>';
      $("#graph-node-count").textContent = "—";
      $("#graph-edge-count").textContent = "—";
      $("#graph-status").textContent = error.message;
    }
  }

  function loadPage(page) {
    if (page === "overview") loadOverview();
    else if (page === "repositories" || page === "sync") loadRepositories();
    else if (page === "storage") loadStorage();
    else if (page === "health") loadHealth();
    else if (page === "runtime") loadDataPage("runtime", "#runtime-content", "Runtime");
    else if (page === "graph") loadGraph();
    else if (page === "settings") loadSettings();
  }

  function errorCard(error) {
    return `<article class="data-card error-card"><h3>Data unavailable</h3><p>${escapeHtml(error.message || error)}</p></article>`;
  }

  async function runRepoAction(projectId, action, body = {}) {
    try {
      const payload = await api(`repos/${encodeURIComponent(projectId)}/${action}`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      toast(payload.message || `${labelFor(action)} completed`);
      await loadRepositories();
      return true;
    } catch (error) {
      toast(error.message, "error");
      return false;
    }
  }

  function findRepo(projectId) {
    return state.repositories.find((repo) => String(repo.project_id) === String(projectId));
  }

  function openForget(projectId) {
    const repo = findRepo(projectId);
    if (!repo) {
      toast("Repository is no longer listed.", "error");
      return;
    }
    state.forgetRepo = repo;
    $("#forget-required-value").textContent = projectId;
    $("#forget-confirmation").value = "";
    $("#confirm-forget-button").disabled = true;
    $("#forget-dialog").showModal();
    $("#forget-confirmation").focus();
  }

  function openPathDialog(action, projectId = null) {
    state.pathAction = { action, projectId };
    const locate = action === "locate";
    $("#path-dialog-title").textContent = locate ? "Locate repository" : "Add repository";
    $("#path-dialog-copy").textContent = locate
      ? "Choose the repository's new absolute path. Its stored identity must match."
      : "Enter an absolute path on this machine. Scubiee will initialize and index it.";
    $("#repository-path").value = "";
    $("#path-dialog").showModal();
    $("#repository-path").focus();
  }

  document.addEventListener("click", async (event) => {
    if (event.target.closest("[data-open-add]")) {
      openPathDialog("initialize");
      return;
    }
    const nav = event.target.closest("[data-page]");
    if (nav) showPage(nav.dataset.page);
    const go = event.target.closest("[data-go]");
    if (go) showPage(go.dataset.go);

    const button = event.target.closest("[data-action]");
    if (!button || button.disabled) return;
    const { action, id } = button.dataset;
    if (action === "forget") return openForget(id);
    if (action === "locate") return openPathDialog("locate", id);
    if (action === "clear-index" && !window.confirm("Clear this repository's local index? Its managed identity will be kept.")) return;
    if (action === "rebuild" && !window.confirm("Rebuild this repository's index now?")) return;
    button.disabled = true;
    await runRepoAction(id, action);
    button.disabled = false;
  });

  $("#repo-search").addEventListener("input", renderRepositories);
  $("#menu-button").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
  $("#add-repository-button").addEventListener("click", () => openPathDialog("initialize"));
  $("#refresh-button").addEventListener("click", () => loadPage(location.hash.slice(1) || "overview"));
  $("#apply-safe-repairs").addEventListener("click", () => applySafeRepairs());
  $("#graph-repository").addEventListener("change", (event) => {
    state.graphProjectId = event.target.value;
    loadGraph();
  });
  window.addEventListener("hashchange", () => showPage(location.hash.slice(1), false));

  $("#forget-confirmation").addEventListener("input", (event) => {
    const required = String(state.forgetRepo?.project_id || "");
    $("#confirm-forget-button").disabled = event.target.value.trim() !== required;
  });
  $("#forget-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (event.submitter?.value !== "confirm") return $("#forget-dialog").close();
    const projectId = String(state.forgetRepo?.project_id || "");
    const confirmation = $("#forget-confirmation").value.trim();
    if (!projectId || confirmation !== projectId) return;
    $("#forget-dialog").close();
    await runRepoAction(projectId, "forget", { confirm: confirmation });
  });

  $("#path-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (event.submitter?.value !== "confirm") return $("#path-dialog").close();
    const path = $("#repository-path").value.trim();
    if (!path) return;
    const action = state.pathAction;
    $("#path-dialog").close();
    if (action?.action === "locate") await runRepoAction(action.projectId, "locate", { path });
    else {
      try {
        await api("repos/initialize", { method: "POST", body: JSON.stringify({ path, index: true }) });
        toast("Repository added");
        await loadRepositories();
      } catch (error) {
        toast(error.message, "error");
      }
    }
  });

  $("#save-settings-button").addEventListener("click", async () => {
    const selected = $('input[name="admission-mode"]:checked');
    if (!selected) return toast("Choose an admission mode.", "error");
    const button = $("#save-settings-button");
    button.disabled = true;
    try {
      await api("settings", {
        method: "POST",
        body: JSON.stringify({ admission_mode: selected.value }),
      });
      $("#settings-status").textContent = selected.value === "automatic"
        ? "Automatic admission is active"
        : "Manual admission is active";
      toast("Settings saved");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });

  window.addEventListener("load", () => refreshIcons());
  refreshIcons();
  showPage(location.hash.slice(1) || "overview", false);
})();
