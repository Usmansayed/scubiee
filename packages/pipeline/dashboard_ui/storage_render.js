(function (root, factory) {
  const renderer = factory();
  if (typeof module === "object" && module.exports) module.exports = renderer;
  root.CEStorageRender = renderer;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function labelFor(key) {
    return String(key).replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  function displayScalar(value) {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "boolean") return value ? "Yes" : "No";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  function formatBytes(value) {
    const bytes = Number(value);
    if (!Number.isFinite(bytes) || bytes < 0) return displayScalar(value);
    if (bytes < 1024) return `${bytes} B`;
    const units = ["KB", "MB", "GB", "TB"];
    let amount = bytes;
    let unit = -1;
    do {
      amount /= 1024;
      unit += 1;
    } while (amount >= 1024 && unit < units.length - 1);
    const precision = amount >= 10 || Number.isInteger(amount) ? 0 : 1;
    return `${amount.toFixed(precision)} ${units[unit]}`;
  }

  function recordName(record, index) {
    const path = String(
      record.store_dir || record.path || record.primary_path || record.root || ""
    );
    return (
      record.name ||
      record.project_id ||
      record.repository ||
      path.replace(/[\\/]+$/, "").split(/[\\/]/).pop() ||
      `Record ${index + 1}`
    );
  }

  function recordPath(record) {
    return (
      record.store_dir ||
      record.path ||
      record.primary_path ||
      record.root ||
      record.store_path ||
      ""
    );
  }

  function recordState(record, sectionTitle) {
    if (String(sectionTitle).toLowerCase().includes("candidate")) return "candidate";
    if (record.pinned === true) return "pinned";
    if (record.managed === true) return "managed";
    if (record.managed === false) return "unmanaged";
    return "storage";
  }

  function recordSize(record) {
    const keys = [
      "bytes_used",
      "size_bytes",
      "store_bytes",
      "disk_bytes",
      "bytes",
      "size",
    ];
    const key = keys.find((candidate) => record[candidate] !== undefined);
    return key ? formatBytes(record[key]) : "—";
  }

  function stateBadge(state) {
    if (!state) return '<span class="badge">record</span>';
    const cssClass = String(state).toLowerCase().replace(/[^a-z0-9_-]+/g, "-");
    return `<span class="badge ${escapeHtml(cssClass)}">${escapeHtml(state)}</span>`;
  }

  function renderRecords(title, records) {
    return `<article class="data-card">
      <div class="data-card-header">
        <div><h3>${escapeHtml(title)}</h3><p>${records.length} storage record${records.length === 1 ? "" : "s"}</p></div>
      </div>
      <div class="state-list">${records.map((record, index) => {
        const path = recordPath(record);
        return `<div class="state-row">
          <div class="repo-name">
            <strong>${escapeHtml(recordName(record, index))}</strong>
            <small>${escapeHtml(path || "Path unavailable")}</small>
          </div>
          ${stateBadge(recordState(record, title))}
          <strong>${escapeHtml(recordSize(record))}</strong>
        </div>`;
      }).join("")}</div>
    </article>`;
  }

  function renderValuePanel(title, value) {
    const rendered = Array.isArray(value)
      ? value.map(displayScalar).join(", ") || "None"
      : displayScalar(value);
    return `<article class="data-card">
      <div class="data-card-header"><div><h3>${escapeHtml(title)}</h3><p>Storage data reported by Context Engine</p></div></div>
      <div class="key-grid"><div class="key-value"><span>Value</span><strong>${escapeHtml(rendered)}</strong></div></div>
    </article>`;
  }

  function collectSections(value, title, output) {
    if (Array.isArray(value)) {
      if (value.some((item) => item && typeof item === "object")) {
        output.push(renderRecords(title, value.filter((item) => item && typeof item === "object")));
      } else {
        output.push(renderValuePanel(title, value));
      }
      return;
    }
    if (value && typeof value === "object") {
      const entries = Object.entries(value);
      if (!entries.length) {
        output.push(renderValuePanel(title, "No details reported"));
        return;
      }
      entries.forEach(([key, item]) => {
        const childTitle = title ? `${title} · ${labelFor(key)}` : labelFor(key);
        collectSections(item, childTitle, output);
      });
      return;
    }
    output.push(renderValuePanel(title, value));
  }

  function renderStorageSections(payload) {
    const sections = [];
    Object.entries(payload || {})
      .filter(([key]) => key !== "ok")
      .forEach(([key, value]) => collectSections(value, labelFor(key), sections));
    return sections.join("") || renderValuePanel("Storage", "No details reported");
  }

  return { renderStorageSections };
});
