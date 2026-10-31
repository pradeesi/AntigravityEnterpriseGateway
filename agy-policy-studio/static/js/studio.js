/* ============================================================================
 * FILE HEADER: Interactive Client Controller — Antigravity Policy Studio
 * ============================================================================
 * Purpose:
 *   Powers the responsive Split-Pane Antigravity Admin Policy Studio UI using
 *   progressive multi-select dropdowns (OS -> Surface -> Policy Type & Target
 *   Files), a left-panel File Reference & Manual Lock CLI card, two-way
 *   Form <-> Code synchronization, 1-click Auto-Fix remediation, multi-mode
 *   file import, and BOM-free single-file / `.zip` MDM bundle downloads.
 *
 * Architecture / Context:
 *   Vanilla ES2022 controller loaded by `templates/index.html`. Communicates
 *   with the stateless Flask backend (`app.py`) via `/api/*` JSON and multipart
 *   endpoints. Persists only UI theme (`light`/`dark`) in `localStorage`.
 *
 * Dependencies / Side Effects:
 *   Requires Bootstrap 5.3 `Dropdown`, `Modal`, and `Toast` globals.
 * ============================================================================ */

(function () {
  "use strict";

  const bootstrapNode = document.getElementById("studio-bootstrap-data");
  const BOOTSTRAP = JSON.parse(bootstrapNode.textContent);

  /** @type {Array<Object>} */
  const CATALOG = BOOTSTRAP.catalog;
  /** @type {Object<string, Object>} */
  const CATALOG_BY_ID = {};
  CATALOG.forEach((item) => {
    CATALOG_BY_ID[item.id] = item;
  });

  /** @type {Object<string, Object>} */
  const PRESET_BY_ID = {};
  BOOTSTRAP.presets.forEach((p) => {
    PRESET_BY_ID[p.id] = p;
  });

  const REFERENCE_DATA = BOOTSTRAP.reference || { os_requirements: [], version_requirements: [] };

  const OS_DISPLAY = {
    linux: "Linux",
    macos: "macOS",
    windows: "Windows",
  };

  const OS_LOCK_DISPLAY = {
    linux: "Linux (chmod + chattr +i)",
    macos: "macOS (chmod + chflags schg)",
    windows: "Windows (BOM-free + attrib + icacls)",
  };

  const SURFACE_DISPLAY = {
    cli: "AGY CLI",
    desktop: "AGY Desktop",
    web: "AGY Web Hub",
    ide: "AGY IDE Plugins",
  };

  // Start in clean progressive Step 1 state while keeping default policy values ready
  const initialState = JSON.parse(JSON.stringify(BOOTSTRAP.initial.state));
  initialState.os_list = [];
  initialState.surfaces = [];
  initialState.selected_file_ids = [];

  const AppStore = {
    state: initialState,
    availableFileIds: [],
    activeFileIds: [],
    files: {},
    validation: {
      error_count: 0,
      warn_count: 0,
      fixable_count: 0,
      file_status: {},
      issues_by_file: {},
      all_issues: [],
    },
    perFileCli: {},
    allFilesCli: BOOTSTRAP.initial.all_files_cli || {},
    selectedFileId: "",
    fileLockExpanded: false,
    selectedLockOs: "linux",
    refModalCliOs: "linux",
    refModalSection: "all",
    activePermBucket: "allow",
    permFilterQuery: "",
    showSecrets: false,
    codeSyncTimer: null,
    formSyncTimer: null,
  };

  /**
   * Escape untrusted strings before inserting into HTML templates.
   *
   * @summary Defends against DOM XSS when rendering user-entered values.
   * @param {string|number|boolean|null|undefined} raw - Raw value to escape.
   * @returns {string} HTML-entity-escaped string.
   * @throws {never} Never throws.
   */
  function escapeHtml(raw) {
    return String(raw ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  /**
   * Display a concise non-blocking notification toast in the bottom-right corner.
   *
   * @summary Renders feedback for copy, import, auto-fix, and export actions.
   * @param {string} message - Notification text to display.
   * @param {string} [variant="dark"] - Bootstrap text-bg class suffix.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function showToast(message, variant = "dark") {
    const toastEl = document.getElementById("studio-toast");
    const bodyEl = document.getElementById("studio-toast-body");
    if (!toastEl || !bodyEl) {
      return;
    }
    toastEl.className = `toast align-items-center border-0 text-bg-${variant}`;
    bodyEl.textContent = message;
    const instance = window.bootstrap.Toast.getOrCreateInstance(toastEl, { delay: 2600 });
    instance.show();
  }

  /**
   * Initialize and persist the Light (default) or Dark theme preference.
   *
   * @summary Applies `data-bs-theme` on `<html>` and updates toggle caption.
   * @param {string} theme - Either `"light"` or `"dark"`.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function applyTheme(theme) {
    const normalized = theme === "dark" ? "dark" : "light";
    document.documentElement.setAttribute("data-bs-theme", normalized);
    localStorage.setItem("agy_studio_theme", normalized);
    const label = document.getElementById("theme-toggle-label");
    if (label) {
      label.textContent = normalized === "light" ? "Dark Mode" : "Light Mode";
    }
  }

  /**
   * Send a JSON POST request to a stateless studio API endpoint.
   *
   * @summary Wrapper around `fetch` with defensive error handling.
   * @param {string} url - API endpoint path (e.g., `/api/compile`).
   * @param {Object} payload - Serializable request body object.
   * @returns {Promise<Object>} Parsed JSON response payload.
   * @throws {Error} Throws descriptive Error when HTTP status is non-2xx.
   */
  async function postJson(url, payload) {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(data.error || `Request failed (${resp.status})`);
    }
    return data;
  }

  /**
   * Populate the Policy Type / Starter Preset `<select>` menu in Step 2.
   *
   * @summary Groups core presets and `ADMIN_POLICY_EXAMPLES.md` recipes cleanly.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function initPresetDropdown() {
    const selectEl = document.getElementById("preset-selector");
    if (!selectEl) {
      return;
    }
    const groups = {};
    BOOTSTRAP.presets.forEach((p) => {
      if (!groups[p.category]) {
        groups[p.category] = [];
      }
      groups[p.category].push(p);
    });

    let html = "";
    Object.keys(groups).forEach((cat) => {
      html += `<optgroup label="${escapeHtml(cat)}">`;
      groups[cat].forEach((p) => {
        const sel = p.id === AppStore.state.active_preset ? "selected" : "";
        html += `<option value="${escapeHtml(p.id)}" ${sel}>${escapeHtml(p.label)}</option>`;
      });
      html += "</optgroup>";
    });
    selectEl.innerHTML = html;
    updatePresetDescriptionHint();
  }

  /**
   * Update the concise helper description below `#preset-selector`.
   *
   * @summary Explains what the selected policy preset configures.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function updatePresetDescriptionHint() {
    const hintEl = document.getElementById("preset-description-hint");
    const presetMeta = PRESET_BY_ID[AppStore.state.active_preset];
    if (hintEl) {
      hintEl.textContent = presetMeta ? presetMeta.description : "";
    }
  }

  /**
   * Apply a backend compilation or import payload to `AppStore` and render UI.
   *
   * @summary Synchronizes Step 1/2/3 visibility, dropdown summaries, File
   *   Reference Card, form controls, live code editor, and validation drawer.
   * @param {Object} payload - Compiled payload returned by `/api/*`.
   * @param {Object} [options={}] - Rendering flags (`skipEditor`, `skipForm`, `autoSelectFiles`).
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function applyServerPayload(payload, options = {}) {
    AppStore.state = payload.state;
    AppStore.availableFileIds = payload.available_file_ids || [];
    AppStore.activeFileIds = payload.active_file_ids || [];
    AppStore.files = payload.files || {};
    AppStore.validation = payload.validation || {
      error_count: 0,
      warn_count: 0,
      fixable_count: 0,
      file_status: {},
      issues_by_file: {},
      all_issues: [],
    };
    AppStore.perFileCli = payload.per_file_cli || {};
    if (payload.all_files_cli) {
      AppStore.allFilesCli = payload.all_files_cli;
    }

    if (options.autoSelectFiles || AppStore.state.selected_file_ids === null) {
      AppStore.state.selected_file_ids = [...AppStore.activeFileIds];
    }

    if (AppStore.activeFileIds.length > 0) {
      if (!AppStore.activeFileIds.includes(AppStore.selectedFileId)) {
        AppStore.selectedFileId = AppStore.activeFileIds[0];
      }
    } else {
      AppStore.selectedFileId = "";
    }

    if (
      AppStore.state.os_list.length > 0 &&
      !AppStore.state.os_list.includes(AppStore.selectedLockOs)
    ) {
      AppStore.selectedLockOs = AppStore.state.os_list[0];
    }

    renderAllPanels(options);
  }

  /**
   * Re-render all progressive left-pane and right-pane sections consistently.
   *
   * @summary Coordinates progressive step visibility and individual widgets.
   * @param {Object} [options={}] - Optional `{skipForm, skipEditor}` flags.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function renderAllPanels(options = {}) {
    const hasScope =
      AppStore.state.os_list.length > 0 && AppStore.state.surfaces.length > 0;
    const hasFiles = hasScope && AppStore.activeFileIds.length > 0;

    renderTopActionButtons(hasFiles);
    renderStep1Controls();
    renderStep2Controls(hasScope);
    renderFileReferenceCard(hasFiles);
    renderReferenceGuideModal();

    const formContainer = document.getElementById("form-panel-container");
    if (formContainer) {
      formContainer.classList.toggle("d-none", !hasFiles);
    }
    if (hasFiles && !options.skipForm) {
      renderActiveFormPanel();
    }

    const emptyRight = document.getElementById("right-empty-state");
    const activeRight = document.getElementById("right-editor-workspace");
    if (emptyRight && activeRight) {
      emptyRight.classList.toggle("d-none", hasFiles);
      activeRight.classList.toggle("d-none", !hasFiles);
    }

    if (!hasFiles) {
      renderEmptyGuideProgress(hasScope);
    } else {
      if (!options.skipEditor) {
        renderEditorPane();
      } else {
        renderEditorHeaderOnly();
      }
      renderValidationDrawer();
    }
  }

  /**
   * Populate and synchronize the top-bar Requirements & File Guide Modal.
   *
   * @summary Renders Table 1 (Minimum OS Requirements), Table 2 (Minimum
   *   Antigravity Versions), and Table 3 (All 11 Config Files, Purpose,
   *   Mandatory Status, Admin Permission CLI & Official Public Docs).
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function renderReferenceGuideModal() {
    const secFilter = AppStore.refModalSection || "all";
    const cliOs = AppStore.refModalCliOs || "linux";
    const u = AppStore.state.dev_user || "alice";

    const secOs = document.getElementById("ref-sec-os");
    const secVer = document.getElementById("ref-sec-versions");
    const secFiles = document.getElementById("ref-sec-files");
    if (secOs) {
      secOs.classList.toggle("d-none", secFilter !== "all" && secFilter !== "os");
    }
    if (secVer) {
      secVer.classList.toggle("d-none", secFilter !== "all" && secFilter !== "versions");
    }
    if (secFiles) {
      secFiles.classList.toggle("d-none", secFilter !== "all" && secFilter !== "files");
    }

    const userCap = document.getElementById("ref-files-user-caption");
    if (userCap) {
      userCap.textContent = `Paths & CLI templated for OS: ${OS_DISPLAY[cliOs] || cliOs} · Workstation User: ${u}`;
    }

    // Table 1: Minimum OS Requirements
    const tbodyOs = document.getElementById("tbody-ref-os");
    if (tbodyOs) {
      tbodyOs.innerHTML = (REFERENCE_DATA.os_requirements || [])
        .map(
          (row) => `
          <tr>
            <td class="fw-semibold">${escapeHtml(row.os)}</td>
            <td>${escapeHtml(row.min_version)}</td>
            <td>${escapeHtml(row.architectures)}</td>
            <td>${escapeHtml(row.hardware_runtime)}</td>
            <td class="mono-input" style="font-size: 0.72rem;">${escapeHtml(row.sandbox_lock)}</td>
          </tr>`
        )
        .join("");
    }

    // Table 2: Minimum Antigravity Versions
    const tbodyVer = document.getElementById("tbody-ref-versions");
    if (tbodyVer) {
      tbodyVer.innerHTML = (REFERENCE_DATA.version_requirements || [])
        .map(
          (row) => `
          <tr>
            <td class="fw-semibold">${escapeHtml(row.surface)}</td>
            <td><span class="badge text-bg-light border text-wrap text-start fw-semibold" style="font-size: 0.72rem;">${escapeHtml(row.min_version)}</span></td>
            <td>${escapeHtml(row.platforms_protocols)}</td>
            <td>${escapeHtml(row.notes)}</td>
            <td>
              <a href="${escapeHtml(row.doc_url)}" target="_blank" rel="noopener noreferrer" class="text-decoration-none fw-medium text-nowrap">
                ${escapeHtml(row.doc_label || "Docs")} &#8599;
              </a>
            </td>
          </tr>`
        )
        .join("");
    }

    // Table 3: Canonical Files, Purpose, Is Mandatory, Admin CLI & Public Docs
    const tbodyFiles = document.getElementById("tbody-ref-files");
    if (tbodyFiles) {
      tbodyFiles.innerHTML = CATALOG.map((item) => {
        const rawPath = (item.paths && item.paths[cliOs]) ? item.paths[cliOs].replace(/\{user\}/g, u) : "";
        const primaryPath = rawPath ? rawPath.split("  (")[0].trim() : "";
        const cliBlock = AppStore.allFilesCli?.[item.id]?.[cliOs]?.lock || "";
        const surfacesText = (item.surface_details || item.surfaces).join(", ");
        const badgeVariant = item.mandatory_variant || "secondary";
        const badgeText = item.mandatory_status || "Optional";

        const pathHtml = rawPath
          ? `<div class="mt-1 d-flex align-items-start justify-content-between gap-1">
               <code class="text-break" style="font-size: 0.7rem;">${escapeHtml(rawPath)}</code>
               <button type="button" class="btn btn-sm btn-outline-secondary py-0 px-1 flex-shrink-0" style="font-size: 0.66rem; height: 20px;" data-ref-copy-path="${escapeHtml(primaryPath)}">Copy</button>
             </div>`
          : `<div class="mt-1"><span class="badge text-bg-light border text-body-secondary">Not used on ${escapeHtml(OS_DISPLAY[cliOs] || cliOs)}</span></div>`;

        const cliHtml = cliBlock
          ? `<div>
               <div class="d-flex justify-content-between align-items-center mb-1">
                 <span class="text-body-secondary" style="font-size: 0.69rem;">${escapeHtml(item.permissions_summary?.[cliOs]?.replace(/\{user\}/g, u) || "")}</span>
                 <button type="button" class="btn btn-sm btn-outline-secondary py-0 px-2 flex-shrink-0" style="font-size: 0.67rem; height: 20px;" data-ref-copy-cli="${escapeHtml(item.id)}">Copy CLI</button>
               </div>
               <pre class="ref-table-cli">${escapeHtml(cliBlock)}</pre>
             </div>`
          : `<span class="text-body-secondary small">N/A on ${escapeHtml(OS_DISPLAY[cliOs] || cliOs)}</span>`;

        return `
          <tr>
            <td>
              <div class="fw-semibold mono-input" style="font-size: 0.77rem;">${escapeHtml(item.short_label)}</div>
              ${pathHtml}
            </td>
            <td style="font-size: 0.73rem;">${escapeHtml(surfacesText)}</td>
            <td style="font-size: 0.74rem;">${escapeHtml(item.summary)}</td>
            <td>
              <span class="badge text-bg-${escapeHtml(badgeVariant)} mb-1">${escapeHtml(badgeText)}</span>
              <div class="text-body-secondary" style="font-size: 0.71rem; line-height: 1.3;">${escapeHtml(item.mandatory_note || "")}</div>
            </td>
            <td>${cliHtml}</td>
            <td>
              <a href="${escapeHtml(item.doc_url)}" target="_blank" rel="noopener noreferrer" class="text-decoration-none fw-medium" style="font-size: 0.74rem;">
                Public Docs &#8599;
              </a>
            </td>
          </tr>`;
      }).join("");

      tbodyFiles.querySelectorAll("[data-ref-copy-path]").forEach((btn) => {
        btn.addEventListener("click", () => {
          navigator.clipboard?.writeText(btn.dataset.refCopyPath);
          showToast(`Copied path: ${btn.dataset.refCopyPath}`, "dark");
        });
      });

      tbodyFiles.querySelectorAll("[data-ref-copy-cli]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const fid = btn.dataset.refCopyCli;
          const cmd = AppStore.allFilesCli?.[fid]?.[cliOs]?.lock || "";
          if (cmd) {
            navigator.clipboard?.writeText(cmd);
            showToast(`Copied ${OS_DISPLAY[cliOs]} Admin CLI for ${CATALOG_BY_ID[fid]?.filename || fid}`, "dark");
          }
        });
      });
    }
  }

  /**
   * Update the top header `Download MDM Bundle` button state and file count.
   *
   * @summary Enables ZIP export only when at least one file is selected.
   * @param {boolean} hasFiles - Whether >= 1 target config file is active.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function renderTopActionButtons(hasFiles) {
    const zipBtn = document.getElementById("btn-download-zip");
    if (!zipBtn) {
      return;
    }
    zipBtn.disabled = !hasFiles;
    const count = AppStore.activeFileIds.length;
    zipBtn.textContent = hasFiles
      ? `Download MDM Bundle (${count} ${count === 1 ? "File" : "Files"})`
      : "Download MDM Bundle (.zip)";
  }

  /**
   * Update the 3-step visual indicator inside the Right-Pane empty state.
   *
   * @summary Highlights Step 1 before OS/Surface selection and Step 2 once
   *   OS & Surface are selected.
   * @param {boolean} hasScope - True when >= 1 OS and >= 1 Surface are selected.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function renderEmptyGuideProgress(hasScope) {
    const d1 = document.getElementById("guide-dot-1");
    const d2 = document.getElementById("guide-dot-2");
    const d3 = document.getElementById("guide-dot-3");
    if (d1) {
      d1.className = `guide-step-dot ${hasScope ? "done" : "active"}`;
      d1.textContent = hasScope ? "✓" : "1";
    }
    if (d2) {
      d2.className = `guide-step-dot ${hasScope ? "active" : ""}`;
      d2.textContent = "2";
    }
    if (d3) {
      d3.className = "guide-step-dot";
      d3.textContent = "3";
    }
  }

  /**
   * Render Step 1 OS & Surface multi-select dropdown labels, counts, and checkboxes.
   *
   * @summary Keeps multi-select dropdown buttons crisp with zero overflow.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function renderStep1Controls() {
    const osList = AppStore.state.os_list || [];
    const surfList = AppStore.state.surfaces || [];

    // Sync OS checkboxes and button summary
    document.querySelectorAll("[data-os-value]").forEach((chk) => {
      chk.checked = osList.includes(chk.dataset.osValue);
    });
    const osBtn = document.getElementById("dropdownOsBtn");
    const osLbl = document.getElementById("dropdownOsLabel");
    const osCnt = document.getElementById("dropdownOsCount");
    if (osBtn && osLbl && osCnt) {
      if (osList.length === 0) {
        osBtn.classList.add("is-placeholder");
        osLbl.textContent = "Select Target OS...";
        osCnt.classList.add("d-none");
      } else {
        osBtn.classList.remove("is-placeholder");
        osLbl.textContent =
          osList.length === 3
            ? "All Operating Systems"
            : osList.map((o) => OS_DISPLAY[o] || o).join(", ");
        osCnt.textContent = String(osList.length);
        osCnt.classList.remove("d-none");
      }
    }

    // Sync Surface checkboxes and button summary
    document.querySelectorAll("[data-surface-value]").forEach((chk) => {
      chk.checked = surfList.includes(chk.dataset.surfaceValue);
    });
    const surfBtn = document.getElementById("dropdownSurfaceBtn");
    const surfLbl = document.getElementById("dropdownSurfaceLabel");
    const surfCnt = document.getElementById("dropdownSurfaceCount");
    if (surfBtn && surfLbl && surfCnt) {
      if (surfList.length === 0) {
        surfBtn.classList.add("is-placeholder");
        surfLbl.textContent = "Select Surface(s)...";
        surfCnt.classList.add("d-none");
      } else {
        surfBtn.classList.remove("is-placeholder");
        surfLbl.textContent =
          surfList.length === 4
            ? "All Antigravity Surfaces"
            : surfList.map((s) => SURFACE_DISPLAY[s] || s).join(", ");
        surfCnt.textContent = String(surfList.length);
        surfCnt.classList.remove("d-none");
      }
    }

    const userEl = document.getElementById("input-dev-user");
    if (userEl && document.activeElement !== userEl) {
      userEl.value = AppStore.state.dev_user || "alice";
    }

    const syncSelect = document.getElementById("select-perm-sync");
    if (syncSelect) {
      syncSelect.value = AppStore.state.sync_permissions ? "linked" : "separate";
    }
  }

  /**
   * Render Step 2 Policy Type `<select>`, Target Config Files multi-select, and
   * Active File `<select>`.
   *
   * @summary Revealed right after OS and Surface selection on the Left Panel.
   * @param {boolean} hasScope - Whether >= 1 OS and >= 1 Surface are selected.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function renderStep2Controls(hasScope) {
    const step2Card = document.getElementById("step2-policy-files-card");
    if (!step2Card) {
      return;
    }
    step2Card.classList.toggle("d-none", !hasScope);
    if (!hasScope) {
      return;
    }

    const presetEl = document.getElementById("preset-selector");
    if (presetEl && AppStore.state.active_preset) {
      presetEl.value = AppStore.state.active_preset;
    }
    updatePresetDescriptionHint();

    const avail = AppStore.availableFileIds || [];
    const active = AppStore.activeFileIds || [];
    const statusMap = (AppStore.validation && AppStore.validation.file_status) || {};

    const availCaption = document.getElementById("files-available-caption");
    if (availCaption) {
      availCaption.textContent = `Available Files (${avail.length})`;
    }

    const filesBtn = document.getElementById("dropdownFilesBtn");
    const filesLbl = document.getElementById("dropdownFilesLabel");
    const filesCnt = document.getElementById("dropdownFilesCount");
    if (filesBtn && filesLbl && filesCnt) {
      if (active.length === 0) {
        filesBtn.classList.add("is-placeholder");
        filesLbl.textContent = `Select Config File(s) (${avail.length} available)...`;
        filesCnt.classList.add("d-none");
      } else if (active.length === 1) {
        filesBtn.classList.remove("is-placeholder");
        filesLbl.textContent = CATALOG_BY_ID[active[0]]?.short_label || active[0];
        filesCnt.textContent = "1";
        filesCnt.classList.remove("d-none");
      } else if (active.length === avail.length) {
        filesBtn.classList.remove("is-placeholder");
        filesLbl.textContent = `All Matching Files Selected`;
        filesCnt.textContent = `${active.length}/${avail.length}`;
        filesCnt.classList.remove("d-none");
      } else {
        filesBtn.classList.remove("is-placeholder");
        filesLbl.textContent = active
          .map((fid) => CATALOG_BY_ID[fid]?.filename || fid)
          .join(", ");
        filesCnt.textContent = `${active.length}/${avail.length}`;
        filesCnt.classList.remove("d-none");
      }
    }

    const menuFiles = document.getElementById("menu-files-options");
    if (menuFiles) {
      menuFiles.classList.toggle("ms-options-grid-2col", avail.length > 4);
      menuFiles.innerHTML = avail
        .map((fid) => {
          const meta = CATALOG_BY_ID[fid];
          const isChecked = active.includes(fid);
          const st = (statusMap[fid] || "PASS").toLowerCase();
          const dotHtml = isChecked
            ? `<span class="status-dot ${escapeHtml(st)} ms-1" title="${escapeHtml(st.toUpperCase())}"></span>`
            : "";
          return `
            <label class="ms-check-row" for="chk-file-${escapeHtml(fid)}">
              <input id="chk-file-${escapeHtml(fid)}" type="checkbox" class="form-check-input" data-file-check="${escapeHtml(fid)}" ${isChecked ? "checked" : ""}>
              <div class="flex-grow-1">
                <div class="ms-check-title d-flex align-items-center justify-content-between">
                  <span>${escapeHtml(meta.short_label)}</span>
                  ${dotHtml}
                </div>
                <div class="ms-check-sub">${escapeHtml(meta.group_title)}</div>
              </div>
            </label>`;
        })
        .join("");

      menuFiles.querySelectorAll("[data-file-check]").forEach((chk) => {
        chk.addEventListener("change", () => {
          const fid = chk.dataset.fileCheck;
          const curSet = new Set(AppStore.state.selected_file_ids || []);
          if (chk.checked) {
            curSet.add(fid);
            AppStore.selectedFileId = fid;
          } else {
            curSet.delete(fid);
          }
          AppStore.state.selected_file_ids = avail.filter((id) => curSet.has(id));
          scheduleFormCompile(true);
        });
      });
    }

    // Active File Single-Select Dropdown (visible when 2+ files are checked)
    const activeWrap = document.getElementById("active-file-selector-wrap");
    const activeSelect = document.getElementById("active-file-selector");
    if (activeWrap && activeSelect) {
      const showSwitcher = active.length >= 2;
      activeWrap.classList.toggle("d-none", !showSwitcher);
      if (showSwitcher) {
        activeSelect.innerHTML = active
          .map((fid) => {
            const meta = CATALOG_BY_ID[fid];
            const st = statusMap[fid] || "PASS";
            const sel = fid === AppStore.selectedFileId ? "selected" : "";
            return `<option value="${escapeHtml(fid)}" ${sel}>[${escapeHtml(st)}] ${escapeHtml(meta.short_label)} — ${escapeHtml(meta.group_title)}</option>`;
          })
          .join("");
      }
    }
  }

  /**
   * Render Step 3A: Left-Panel Selected File Reference & Manual Lock CLI Card.
   *
   * @summary Displays Purpose, Used by Surfaces, Official Public Docs link,
   *   Full Target Path(s), and collapsible Per-File Manual Permissions + Lock /
   *   Unlock CLI commands directly on the Left Panel.
   * @param {boolean} hasFiles - True when >= 1 target config file is selected.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function renderFileReferenceCard(hasFiles) {
    const card = document.getElementById("step3-file-ref-card");
    if (!card) {
      return;
    }
    const meta = CATALOG_BY_ID[AppStore.selectedFileId];
    if (!hasFiles || !meta) {
      card.classList.add("d-none");
      return;
    }
    card.classList.remove("d-none");

    const u = AppStore.state.dev_user || "alice";

    const grpBadge = document.getElementById("ref-group-badge");
    const fnLabel = document.getElementById("ref-filename-label");
    const docLink = document.getElementById("ref-doc-link");
    const purposeEl = document.getElementById("ref-file-purpose");
    const surfacesEl = document.getElementById("ref-file-surfaces");
    const pathsEl = document.getElementById("ref-file-paths");

    if (grpBadge) {
      grpBadge.textContent = `Group ${meta.group_code} · ${meta.group_title}`;
    }
    if (fnLabel) {
      fnLabel.textContent = meta.filename;
    }
    if (docLink) {
      docLink.href = meta.doc_url;
      docLink.title = meta.doc_title || "Open Official Public Documentation";
      docLink.innerHTML = `${escapeHtml(meta.doc_title || "Official Public Docs")} &#8599;`;
    }
    if (purposeEl) {
      purposeEl.textContent = meta.summary;
    }
    if (surfacesEl) {
      const details = meta.surface_details || meta.surfaces.map((s) => SURFACE_DISPLAY[s] || s);
      surfacesEl.innerHTML = details
        .map((label) => `<span class="surface-chip">${escapeHtml(label)}</span>`)
        .join("");
    }
    if (pathsEl) {
      const applicableOs = AppStore.state.os_list.filter((osKey) => Boolean(meta.paths[osKey]));
      pathsEl.innerHTML = applicableOs
        .map((osKey) => {
          const fullText = meta.paths[osKey].replace(/\{user\}/g, u);
          const primaryPath = fullText.split("  (")[0].trim();
          return `
            <div class="target-path-row">
              <span class="target-path-os">${escapeHtml(OS_DISPLAY[osKey] || osKey)}</span>
              <code class="target-path-code">${escapeHtml(fullText)}</code>
              <button type="button" class="btn btn-sm btn-outline-secondary py-0 px-2 flex-shrink-0" style="font-size: 0.7rem; height: 22px;" data-copy-target-path="${escapeHtml(primaryPath)}">
                Copy
              </button>
            </div>`;
        })
        .join("");

      pathsEl.querySelectorAll("[data-copy-target-path]").forEach((btn) => {
        btn.addEventListener("click", () => {
          navigator.clipboard?.writeText(btn.dataset.copyTargetPath);
          showToast(`Copied path: ${btn.dataset.copyTargetPath}`, "dark");
        });
      });
    }

    // Per-file manual permissions & lock/unlock commands
    const lockBody = document.getElementById("file-lock-cli-body");
    const toggleBtn = document.getElementById("btn-toggle-file-lock-cli");
    const chevron = document.getElementById("file-lock-chevron");
    if (lockBody && toggleBtn && chevron) {
      lockBody.classList.toggle("d-none", !AppStore.fileLockExpanded);
      toggleBtn.setAttribute("aria-expanded", String(AppStore.fileLockExpanded));
      chevron.innerHTML = AppStore.fileLockExpanded ? "&#9652; Hide" : "&#9662; Show";
    }

    const cliForFile = AppStore.perFileCli[AppStore.selectedFileId] || {};
    const osKeys = Object.keys(cliForFile);
    const osSelect = document.getElementById("select-file-lock-os");
    const permSumEl = document.getElementById("ref-perm-summary");
    const preLock = document.getElementById("pre-file-lock-cmd");
    const preUnlock = document.getElementById("pre-file-unlock-cmd");

    if (osKeys.length > 0) {
      const curOs = cliForFile[AppStore.selectedLockOs] ? AppStore.selectedLockOs : osKeys[0];
      AppStore.selectedLockOs = curOs;
      if (osSelect) {
        osSelect.innerHTML = osKeys
          .map(
            (k) =>
              `<option value="${escapeHtml(k)}" ${k === curOs ? "selected" : ""}>${escapeHtml(OS_LOCK_DISPLAY[k] || k)}</option>`
          )
          .join("");
      }
      if (permSumEl) {
        const rawPerm = (meta.permissions_summary && meta.permissions_summary[curOs]) || "";
        permSumEl.textContent = rawPerm
          ? `Permissions Model: ${rawPerm.replace(/\{user\}/g, u)}`
          : "";
      }
      if (preLock) {
        preLock.textContent = cliForFile[curOs].lock;
      }
      if (preUnlock) {
        preUnlock.textContent = cliForFile[curOs].unlock;
      }
    }
  }

  /**
   * Trigger a debounced `/api/compile` call after left-pane scope or form edits.
   *
   * @summary Compiles structured form state into right-pane raw code + validation.
   * @param {boolean} [reRenderForm=false] - Whether to re-render left form DOM.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function scheduleFormCompile(reRenderForm = false) {
    const syncPill = document.getElementById("sync-status-pill");
    if (syncPill) {
      syncPill.textContent = "Syncing";
    }
    clearTimeout(AppStore.formSyncTimer);
    AppStore.formSyncTimer = setTimeout(async () => {
      try {
        const res = await postJson("/api/compile", { state: AppStore.state });
        applyServerPayload(res, { skipForm: !reRenderForm, skipEditor: false });
        if (syncPill) {
          syncPill.textContent = "Two-Way Synced";
        }
      } catch (err) {
        showToast(err.message, "danger");
      }
    }, 100);
  }

  /**
   * Render the Permission Rule Chip Builder (`allow` / `ask` / `deny`) HTML
   * using clean `<select>` dropdowns instead of horizontal button clusters.
   *
   * @summary Shared component used by CLI `settings.json` and Desktop `config.json`.
   * @param {string} targetScope - Either `"cli"` or `"desktop"`.
   * @param {Object} permsObj - Object containing `allow`, `ask`, and `deny` arrays.
   * @returns {string} HTML string for the permission rule manager.
   * @throws {never} Never throws.
   */
  function buildPermissionsWidgetHtml(targetScope, permsObj) {
    const bucket = AppStore.activePermBucket;
    const allRules = Array.isArray(permsObj[bucket]) ? permsObj[bucket] : [];
    const q = AppStore.permFilterQuery.trim().toLowerCase();
    const filtered = q
      ? allRules.map((r, idx) => ({ r, idx })).filter((item) => item.r.toLowerCase().includes(q))
      : allRules.map((r, idx) => ({ r, idx }));

    const linkedNotice =
      targetScope === "desktop" && AppStore.state.sync_permissions
        ? `<div class="alert alert-info py-1 px-2 small mb-2 d-flex justify-content-between align-items-center">
             <span>Synchronized with CLI <code>settings.json</code> permissions.</span>
             <button type="button" class="btn btn-sm btn-link p-0 text-decoration-none" id="btn-inline-unlink">Edit Separately</button>
           </div>`
        : "";

    const chipsHtml = filtered.length
      ? filtered
          .map(
            (item) => `
          <span class="rule-chip">
            <span>${escapeHtml(item.r)}</span>
            <button type="button" class="rule-chip-remove" data-remove-rule-idx="${item.idx}" title="Remove rule">&times;</button>
          </span>`
          )
          .join("")
      : `<div class="text-body-secondary small p-2">No ${escapeHtml(bucket)} rules match current filter.</div>`;

    const u = escapeHtml(AppStore.state.dev_user || "alice");

    return `
      <div class="section-block" data-perm-scope="${escapeHtml(targetScope)}">
        <div class="d-flex justify-content-between align-items-center mb-1">
          <div class="section-heading mb-0">Permission Grants (Allow / Ask / Deny)</div>
          <span class="text-body-secondary" style="font-size:0.72rem;">Deny &gt; Ask &gt; Allow</span>
        </div>
        <div class="section-desc">Manage command, file, URL, and lazy MCP tool permissions via dropdown controls.</div>
        ${linkedNotice}

        <div class="row g-2 mb-2">
          <div class="col-sm-6">
            <label class="form-label-sm" for="select-perm-bucket">Permission Bucket</label>
            <select id="select-perm-bucket" class="form-select form-select-sm fw-medium">
              <option value="allow" ${bucket === "allow" ? "selected" : ""}>Allow Grants (${(permsObj.allow || []).length})</option>
              <option value="ask" ${bucket === "ask" ? "selected" : ""}>Ask / Review Grants (${(permsObj.ask || []).length})</option>
              <option value="deny" ${bucket === "deny" ? "selected" : ""}>Deny / Block Grants (${(permsObj.deny || []).length})</option>
            </select>
          </div>
          <div class="col-sm-6">
            <label class="form-label-sm" for="input-perm-search">Filter Current Bucket</label>
            <input type="search" id="input-perm-search" class="form-control form-control-sm" placeholder="Filter rules..." value="${escapeHtml(AppStore.permFilterQuery)}">
          </div>
        </div>

        <div class="row g-2 mb-2">
          <div class="col-sm-5">
            <label class="form-label-sm" for="select-rule-template">Syntax Template</label>
            <select id="select-rule-template" class="form-select form-select-sm">
              <option value="">Insert template...</option>
              <option value="command(git status)">command(...) — Literal</option>
              <option value="command(regex:^git\\s+(status|diff)$)">command(regex:...) — Regex</option>
              <option value="read_file(/home/${u}/workspace)">read_file(/path) — Read</option>
              <option value="write_file(/home/${u}/workspace)">write_file(/path) — Write</option>
              <option value="read_url(docs.cloud.google.com)">read_url(domain) — URL</option>
              <option value="mcp(catalog/*)">mcp(server/tool) — MCP</option>
            </select>
          </div>
          <div class="col-sm-7">
            <label class="form-label-sm" for="input-new-perm-rule">New Rule Expression</label>
            <div class="input-group input-group-sm">
              <input type="text" id="input-new-perm-rule" class="form-control mono-input" placeholder="e.g. command(git status)">
              <button type="button" id="btn-add-perm-rule" class="btn btn-outline-primary fw-semibold">Add</button>
            </div>
          </div>
        </div>

        <div class="rule-chip-list">${chipsHtml}</div>
      </div>
    `;
  }

  /**
   * Wire event listeners for the dropdown-driven Permission Rule Chip Builder.
   *
   * @summary Handles bucket dropdown, template dropdown, search, add, and remove.
   * @param {HTMLElement} container - Parent form container DOM element.
   * @param {string} targetScope - `"cli"` or `"desktop"`.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function bindPermissionsWidgetEvents(container, targetScope) {
    const getTargetPerms = () => {
      if (AppStore.state.sync_permissions) {
        return AppStore.state.cli.permissions;
      }
      return targetScope === "cli"
        ? AppStore.state.cli.permissions
        : AppStore.state.desktop.permissions;
    };

    const syncMirrorIfLinked = () => {
      if (AppStore.state.sync_permissions) {
        AppStore.state.desktop.permissions = JSON.parse(
          JSON.stringify(AppStore.state.cli.permissions)
        );
      }
    };

    container.querySelector("#select-perm-bucket")?.addEventListener("change", (e) => {
      AppStore.activePermBucket = e.target.value;
      renderActiveFormPanel();
    });

    const searchInput = container.querySelector("#input-perm-search");
    if (searchInput) {
      searchInput.addEventListener("input", () => {
        AppStore.permFilterQuery = searchInput.value;
        const pos = searchInput.selectionStart;
        renderActiveFormPanel();
        const nextSearch = document.getElementById("input-perm-search");
        if (nextSearch) {
          nextSearch.focus();
          nextSearch.setSelectionRange(pos, pos);
        }
      });
    }

    container.querySelector("#btn-inline-unlink")?.addEventListener("click", () => {
      AppStore.state.sync_permissions = false;
      renderStep1Controls();
      renderActiveFormPanel();
      scheduleFormCompile(false);
    });

    const newRuleInput = container.querySelector("#input-new-perm-rule");
    const tplSelect = container.querySelector("#select-rule-template");
    if (tplSelect && newRuleInput) {
      tplSelect.addEventListener("change", () => {
        if (tplSelect.value) {
          newRuleInput.value = tplSelect.value;
          tplSelect.value = "";
          newRuleInput.focus();
        }
      });
    }

    const addRule = () => {
      if (!newRuleInput) {
        return;
      }
      const val = newRuleInput.value.trim();
      if (!val) {
        return;
      }
      const perms = getTargetPerms();
      const arr = perms[AppStore.activePermBucket];
      if (!arr.includes(val)) {
        arr.unshift(val);
      }
      syncMirrorIfLinked();
      newRuleInput.value = "";
      renderActiveFormPanel();
      scheduleFormCompile(false);
    };

    container.querySelector("#btn-add-perm-rule")?.addEventListener("click", addRule);
    newRuleInput?.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        addRule();
      }
    });

    container.querySelectorAll("[data-remove-rule-idx]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = Number(btn.dataset.removeRuleIdx);
        const perms = getTargetPerms();
        perms[AppStore.activePermBucket].splice(idx, 1);
        syncMirrorIfLinked();
        renderActiveFormPanel();
        scheduleFormCompile(false);
      });
    });
  }

  /**
   * Render Step 3B: Focused visual form controls for `AppStore.selectedFileId`.
   *
   * @summary Renders ONLY the active file's form fields directly below the
   *   File Reference Card on the Left Panel.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function renderActiveFormPanel() {
    const container = document.getElementById("form-panel-container");
    if (!container) {
      return;
    }
    const fid = AppStore.selectedFileId;
    if (!fid || !CATALOG_BY_ID[fid]) {
      container.innerHTML = "";
      return;
    }

    const s = AppStore.state;
    const secretType = AppStore.showSecrets ? "text" : "password";
    const eyeCaption = AppStore.showSecrets ? "Hide" : "Show";
    let html = "";

    if (fid === "admin_settings") {
      const gw = s.gateway;
      const headersRows = (gw.customHeaders || [])
        .map(
          (h, idx) => `
          <div class="row g-2 align-items-center mb-1">
            <div class="col-5">
              <input type="text" class="form-control form-control-sm mono-input" data-gw-hdr-key="${idx}" value="${escapeHtml(h.key)}" placeholder="X-Cost-Center">
            </div>
            <div class="col-6">
              <input type="text" class="form-control form-control-sm mono-input" data-gw-hdr-val="${idx}" value="${escapeHtml(h.value)}" placeholder="CC-9941-SEC">
            </div>
            <div class="col-1 text-end">
              <button type="button" class="btn btn-sm btn-outline-danger py-0 px-1" data-gw-hdr-del="${idx}" title="Remove header">&times;</button>
            </div>
          </div>`
        )
        .join("");

      const modelRows = (gw.models || [])
        .map(
          (m, idx) => `
          <div class="row g-2 align-items-center mb-1">
            <div class="col-6">
              <input type="text" class="form-control form-control-sm mono-input" data-gw-mdl-id="${idx}" value="${escapeHtml(m.modelId)}" placeholder="gemini-3.8-flash">
            </div>
            <div class="col-5">
              <input type="text" class="form-control form-control-sm" data-gw-mdl-name="${idx}" value="${escapeHtml(m.displayName || "")}" placeholder="Display Name (optional)">
            </div>
            <div class="col-1 text-end">
              <button type="button" class="btn btn-sm btn-outline-danger py-0 px-1" data-gw-mdl-del="${idx}" title="Remove model">&times;</button>
            </div>
          </div>`
        )
        .join("");

      html += `
        <div class="section-block">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <div>
              <div class="section-heading mb-0">Enterprise Gateway Connection</div>
              <div class="section-desc mb-0">Activates Gateway auth and suppresses consumer OAuth login.</div>
            </div>
            <div class="form-check form-switch">
              <input class="form-check-input" type="checkbox" id="gw-enabled" ${gw.enabled ? "checked" : ""}>
              <label class="form-check-label small fw-semibold" for="gw-enabled">Enabled</label>
            </div>
          </div>

          <div class="row g-2 mb-2">
            <div class="col-md-7">
              <label class="form-label-sm" for="gw-url">Gateway HTTPS Endpoint URL</label>
              <input id="gw-url" type="url" class="form-control form-control-sm mono-input" value="${escapeHtml(gw.url)}" placeholder="https://gateway.corp.example.com">
            </div>
            <div class="col-md-5">
              <label class="form-label-sm" for="gw-wire">Wire Protocol</label>
              <select id="gw-wire" class="form-select form-select-sm">
                <option value="genai" ${gw.wireProtocol === "genai" ? "selected" : ""}>genai (Default / ACP)</option>
                <option value="openai" ${gw.wireProtocol === "openai" ? "selected" : ""}>openai (/v1/chat/completions)</option>
              </select>
            </div>
          </div>

          <div class="row g-2 mb-2">
            <div class="col-md-7">
              <div class="d-flex justify-content-between align-items-center">
                <label class="form-label-sm" for="gw-apikey">Gateway Bearer API Key</label>
                <div class="form-check mb-0">
                  <input class="form-check-input" type="checkbox" id="gw-omit-key" ${gw.omitApiKeyInMdm ? "checked" : ""}>
                  <label class="form-check-label" style="font-size:0.72rem;" for="gw-omit-key">Omit in MDM (use Tier-2 Env)</label>
                </div>
              </div>
              <div class="input-group input-group-sm">
                <input id="gw-apikey" type="${secretType}" class="form-control mono-input" value="${escapeHtml(gw.apiKey)}" ${gw.omitApiKeyInMdm ? "disabled" : ""} placeholder="REPLACE_WITH_GATEWAY_API_KEY">
                <button type="button" class="btn btn-outline-secondary btn-toggle-secret">${eyeCaption}</button>
              </div>
            </div>
            <div class="col-md-5">
              <label class="form-label-sm" for="gw-cacert">Top-Level CA Bundle Path (POSIX)</label>
              <input id="gw-cacert" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(gw.caCertPath)}" placeholder="/etc/ssl/certs/ca-certificates.crt">
            </div>
          </div>
        </div>

        <div class="section-block">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <div>
              <div class="section-heading mb-0">FinOps &amp; Attribution Headers</div>
              <div class="section-desc mb-0">Pinned in Tier-1 MDM so developers cannot spoof chargeback headers.</div>
            </div>
            <button type="button" id="btn-add-gw-header" class="btn btn-sm btn-outline-primary py-0 px-2" style="font-size:0.75rem;">+ Add Header</button>
          </div>
          ${headersRows || '<div class="text-body-secondary small">No custom headers configured.</div>'}
        </div>

        <div class="section-block">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <div>
              <div class="section-heading mb-0">Approved Model Catalog</div>
              <div class="section-desc mb-0">Top-level GA <code>models.defaultModelId</code> and <code>models.list</code>.</div>
            </div>
            <button type="button" id="btn-add-gw-model" class="btn btn-sm btn-outline-primary py-0 px-2" style="font-size:0.75rem;">+ Add Model</button>
          </div>
          <div class="mb-2" style="max-width: 280px;">
            <label class="form-label-sm" for="gw-default-model">Default Model ID</label>
            <input id="gw-default-model" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(gw.defaultModelId)}">
          </div>
          ${modelRows}
        </div>
      `;
    } else if (fid === "gateway_env") {
      const ge = s.gateway_env;
      html += `
        <div class="section-block">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <div>
              <div class="section-heading mb-0">Tier-2 Environment Variables (AGY_LLM_GATEWAY_*)</div>
              <div class="section-desc mb-0">Ideal for per-user API keys, containers, and headless SSH workspaces.</div>
            </div>
            <div class="form-check form-switch">
              <input class="form-check-input" type="checkbox" id="env-export-prefix" ${ge.exportPrefix ? "checked" : ""}>
              <label class="form-check-label small" for="env-export-prefix">Include <code>export</code></label>
            </div>
          </div>

          <div class="mb-2">
            <label class="form-label-sm" for="env-url">AGY_LLM_GATEWAY_URL</label>
            <input id="env-url" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(ge.url)}">
          </div>
          <div class="row g-2 mb-2">
            <div class="col-md-7">
              <label class="form-label-sm" for="env-apikey">AGY_LLM_GATEWAY_API_KEY</label>
              <div class="input-group input-group-sm">
                <input id="env-apikey" type="${secretType}" class="form-control mono-input" value="${escapeHtml(ge.apiKey)}">
                <button type="button" class="btn btn-outline-secondary btn-toggle-secret">${eyeCaption}</button>
              </div>
            </div>
            <div class="col-md-5">
              <label class="form-label-sm" for="env-wire">AGY_LLM_GATEWAY_WIRE_PROTOCOL</label>
              <select id="env-wire" class="form-select form-select-sm">
                <option value="genai" ${ge.wireProtocol === "genai" ? "selected" : ""}>genai</option>
                <option value="openai" ${ge.wireProtocol === "openai" ? "selected" : ""}>openai</option>
              </select>
            </div>
          </div>
          <div class="mb-2">
            <label class="form-label-sm" for="env-cacert">AGY_LLM_GATEWAY_CA_CERT</label>
            <input id="env-cacert" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(ge.caCert)}">
          </div>
          <div class="mb-2">
            <label class="form-label-sm" for="env-headers">AGY_LLM_GATEWAY_HEADERS (Comma-separated Key: Value pairs)</label>
            <input id="env-headers" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(ge.headers)}">
          </div>
          <div>
            <label class="form-label-sm" for="env-models">AGY_LLM_GATEWAY_MODELS (Comma-separated model IDs)</label>
            <input id="env-models" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(ge.models)}">
          </div>
        </div>
      `;
    } else if (fid === "cli_settings") {
      const c = s.cli;
      html += `
        <div class="section-block">
          <div class="section-heading">CLI &amp; VS Code Execution Sandbox</div>
          <div class="section-desc">Enforced by <code>agy</code> CLI, VS Code, and Visual Studio extensions.</div>
          <div class="row g-2 mb-2">
            <div class="col-sm-6">
              <label class="form-label-sm" for="cli-agent-mode">agentMode</label>
              <select id="cli-agent-mode" class="form-select form-select-sm">
                <option value="plan" ${c.agentMode === "plan" ? "selected" : ""}>plan (Recommended)</option>
                <option value="accept-edits" ${c.agentMode === "accept-edits" ? "selected" : ""}>accept-edits</option>
                <option value="auto" ${c.agentMode === "auto" ? "selected" : ""}>auto</option>
                <option value="" ${c.agentMode === "" ? "selected" : ""}>"" (Client Default)</option>
              </select>
            </div>
            <div class="col-sm-6">
              <label class="form-label-sm" for="cli-tool-perm">toolPermission</label>
              <select id="cli-tool-perm" class="form-select form-select-sm">
                <option value="proceed-in-sandbox" ${c.toolPermission === "proceed-in-sandbox" ? "selected" : ""}>proceed-in-sandbox</option>
                <option value="request-review" ${c.toolPermission === "request-review" ? "selected" : ""}>request-review</option>
                <option value="strict" ${c.toolPermission === "strict" ? "selected" : ""}>strict (Zero Auto-Run)</option>
                <option value="always-proceed" ${c.toolPermission === "always-proceed" ? "selected" : ""}>always-proceed</option>
              </select>
            </div>
            <div class="col-sm-6">
              <label class="form-label-sm" for="cli-artifact-review">artifactReviewPolicy</label>
              <select id="cli-artifact-review" class="form-select form-select-sm">
                <option value="asks-for-review" ${c.artifactReviewPolicy === "asks-for-review" ? "selected" : ""}>asks-for-review</option>
                <option value="agent-decides" ${c.artifactReviewPolicy === "agent-decides" ? "selected" : ""}>agent-decides</option>
                <option value="always-proceed" ${c.artifactReviewPolicy === "always-proceed" ? "selected" : ""}>always-proceed</option>
              </select>
            </div>
            <div class="col-sm-6 ${c.includeOptionalUiKeys ? "" : "d-none"}" id="cli-optional-row">
              <label class="form-label-sm" for="cli-history-size">historySize (0 = Ephemeral)</label>
              <input id="cli-history-size" type="number" min="0" max="500" class="form-control form-control-sm" value="${escapeHtml(c.historySize)}">
            </div>
          </div>

          <div class="d-flex flex-wrap gap-3 mt-2">
            <div class="form-check form-switch">
              <input class="form-check-input" type="checkbox" id="cli-enable-sandbox" ${c.enableTerminalSandbox ? "checked" : ""}>
              <label class="form-check-label small" for="cli-enable-sandbox">enableTerminalSandbox</label>
            </div>
            <div class="form-check form-switch">
              <input class="form-check-input" type="checkbox" id="cli-non-ws" ${c.allowNonWorkspaceAccess ? "checked" : ""}>
              <label class="form-check-label small" for="cli-non-ws">allowNonWorkspaceAccess</label>
            </div>
            <div class="form-check form-switch">
              <input class="form-check-input" type="checkbox" id="cli-opt-ui" ${c.includeOptionalUiKeys ? "checked" : ""}>
              <label class="form-check-label small" for="cli-opt-ui">Include historySize &amp; UI suppression</label>
            </div>
          </div>
        </div>

        <div class="section-block">
          <div class="d-flex justify-content-between align-items-center mb-1">
            <div>
              <div class="section-heading mb-0">Corporate TLS Sandbox Egress Proxy (sandboxProxy.http)</div>
              <div class="section-desc mb-0">Requires a single-certificate PEM file (never a multi-CA bundle).</div>
            </div>
            <div class="form-check form-switch">
              <input class="form-check-input" type="checkbox" id="cli-sbp-enabled" ${c.sandboxProxyEnabled ? "checked" : ""}>
            </div>
          </div>
          <div class="row g-2 mt-1 ${c.sandboxProxyEnabled ? "" : "d-none"}">
            <div class="col-md-6">
              <label class="form-label-sm" for="cli-sbp-addr">Proxy Address</label>
              <input id="cli-sbp-addr" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(c.sandboxProxyAddress)}" placeholder="http://proxy.corp.example.com:3128">
            </div>
            <div class="col-md-6">
              <label class="form-label-sm" for="cli-sbp-cert">Single-Cert Root CA PEM</label>
              <input id="cli-sbp-cert" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(c.sandboxProxyCertFile)}" placeholder="/etc/antigravity/certs/corp-root-ca.pem">
            </div>
          </div>
        </div>

        ${buildPermissionsWidgetHtml("cli", c.permissions)}
      `;
    } else if (fid === "desktop_config") {
      const d = s.desktop;
      const activePerms = s.sync_permissions ? s.cli.permissions : d.permissions;
      html += `
        <div class="section-block">
          <div class="section-heading">Desktop App &amp; Self-Hosted Web Hub (userSettings)</div>
          <div class="section-desc">Enforced by Antigravity Desktop App (2.15.0+) and <code>agy --hub</code> (:4400).</div>
          <div class="row g-2 mb-2">
            <div class="col-md-6">
              <label class="form-label-sm" for="desk-auto-exec">autoExecutionPolicy</label>
              <select id="desk-auto-exec" class="form-select form-select-sm">
                <option value="CASCADE_COMMANDS_AUTO_EXECUTION_PROCEED_IN_SANDBOX" ${d.autoExecutionPolicy === "CASCADE_COMMANDS_AUTO_EXECUTION_PROCEED_IN_SANDBOX" ? "selected" : ""}>PROCEED_IN_SANDBOX</option>
                <option value="CASCADE_COMMANDS_AUTO_EXECUTION_DISABLED" ${d.autoExecutionPolicy === "CASCADE_COMMANDS_AUTO_EXECUTION_DISABLED" ? "selected" : ""}>DISABLED (Require Review)</option>
                <option value="CASCADE_COMMANDS_AUTO_EXECUTION_EAGER" ${d.autoExecutionPolicy === "CASCADE_COMMANDS_AUTO_EXECUTION_EAGER" ? "selected" : ""}>EAGER</option>
              </select>
            </div>
            <div class="col-md-6">
              <label class="form-label-sm" for="desk-artifact">artifactReviewMode</label>
              <select id="desk-artifact" class="form-select form-select-sm">
                <option value="ARTIFACT_REVIEW_MODE_ALWAYS" ${d.artifactReviewMode === "ARTIFACT_REVIEW_MODE_ALWAYS" ? "selected" : ""}>ALWAYS</option>
                <option value="ARTIFACT_REVIEW_MODE_TURBO" ${d.artifactReviewMode === "ARTIFACT_REVIEW_MODE_TURBO" ? "selected" : ""}>TURBO</option>
              </select>
            </div>
          </div>

          <div class="row g-2 mb-2">
            <div class="col-md-6">
              <label class="form-label-sm" for="desk-browser-js">browserJsExecutionPolicy</label>
              <select id="desk-browser-js" class="form-select form-select-sm">
                <option value="BROWSER_JS_EXECUTION_POLICY_DISABLED" ${d.browserJsExecutionPolicy === "BROWSER_JS_EXECUTION_POLICY_DISABLED" ? "selected" : ""}>DISABLED (Hardened)</option>
                <option value="BROWSER_JS_EXECUTION_POLICY_REQUEST_REVIEW" ${d.browserJsExecutionPolicy === "BROWSER_JS_EXECUTION_POLICY_REQUEST_REVIEW" ? "selected" : ""}>REQUEST_REVIEW</option>
                <option value="BROWSER_JS_EXECUTION_POLICY_TURBO" ${d.browserJsExecutionPolicy === "BROWSER_JS_EXECUTION_POLICY_TURBO" ? "selected" : ""}>TURBO</option>
              </select>
            </div>
            <div class="col-md-6 d-flex align-items-end gap-3 pb-1">
              <div class="form-check form-switch">
                <input class="form-check-input" type="checkbox" id="desk-sandbox" ${d.enableTerminalSandbox ? "checked" : ""}>
                <label class="form-check-label small" for="desk-sandbox">enableTerminalSandbox</label>
              </div>
              <div class="form-check form-switch">
                <input class="form-check-input" type="checkbox" id="desk-net" ${d.sandboxAllowNetwork ? "checked" : ""}>
                <label class="form-check-label small" for="desk-net">sandboxAllowNetwork</label>
              </div>
            </div>
          </div>
        </div>

        ${buildPermissionsWidgetHtml("desktop", activePerms)}
      `;
    } else if (fid === "browser_allowlist") {
      const domains = s.browser_domains || [];
      const chips = domains
        .map(
          (dom, idx) => `
          <span class="rule-chip">
            <span>${escapeHtml(dom)}</span>
            <button type="button" class="rule-chip-remove" data-del-domain="${idx}">&times;</button>
          </span>`
        )
        .join("");

      html += `
        <div class="section-block">
          <div class="section-heading">Trusted Browser Subagent Hostnames</div>
          <div class="section-desc">Enter bare hostnames (no <code>https://</code> scheme or path). Lock the file using the commands above so developers cannot click "Always allow".</div>
          <div class="input-group input-group-sm mb-2">
            <input id="input-new-domain" type="text" class="form-control mono-input" placeholder="docs.internal.example.com">
            <button id="btn-add-domain" type="button" class="btn btn-outline-primary fw-semibold">Add Domain</button>
          </div>
          <div class="rule-chip-list">${chips || '<div class="text-body-secondary small">No domains listed.</div>'}</div>
        </div>
      `;
    } else if (fid === "mcp_config") {
      const serversHtml = (s.mcp_servers || [])
        .map(
          (srv, idx) => `
          <div class="border rounded p-2 mb-2 bg-body-tertiary">
            <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">
              <div class="d-flex flex-wrap align-items-center gap-2 flex-grow-1">
                <input type="text" class="form-control form-control-sm mono-input fw-semibold" style="min-width: 155px; max-width: 220px; flex: 1 1 165px;" data-mcp-name="${idx}" value="${escapeHtml(srv.name)}" placeholder="server_name">
                <select class="form-select form-select-sm" style="width: 150px; flex: 0 0 auto;" data-mcp-transport="${idx}">
                  <option value="stdio" ${srv.transport === "stdio" ? "selected" : ""}>Local stdio</option>
                  <option value="http" ${srv.transport === "http" ? "selected" : ""}>Remote HTTP</option>
                </select>
              </div>
              <div class="d-flex align-items-center gap-2">
                <div class="form-check form-switch mb-0">
                  <input class="form-check-input" type="checkbox" data-mcp-enabled="${idx}" ${!srv.disabled ? "checked" : ""}>
                  <label class="form-check-label small">${!srv.disabled ? "Enabled" : "Disabled"}</label>
                </div>
                <button type="button" class="btn btn-sm btn-outline-danger py-0 px-1" data-mcp-del="${idx}">&times;</button>
              </div>
            </div>

            ${
              srv.transport === "http"
                ? `<div class="mb-2">
                     <label class="form-label-sm">serverUrl</label>
                     <input type="text" class="form-control form-control-sm mono-input" data-mcp-url="${idx}" value="${escapeHtml(srv.serverUrl)}" placeholder="https://mcp.internal.example.com/mcp/">
                   </div>`
                : `<div class="row g-2 mb-2">
                     <div class="col-6">
                       <label class="form-label-sm">command</label>
                       <input type="text" class="form-control form-control-sm mono-input" data-mcp-cmd="${idx}" value="${escapeHtml(srv.command)}" placeholder="/usr/local/bin/mcp_server">
                     </div>
                     <div class="col-6">
                       <label class="form-label-sm">args (comma-separated)</label>
                       <input type="text" class="form-control form-control-sm mono-input" data-mcp-args="${idx}" value="${escapeHtml((srv.args || []).join(", "))}">
                     </div>
                   </div>`
            }

            <div class="row g-2">
              <div class="col-6">
                <label class="form-label-sm">enabledTools (comma-separated)</label>
                <input type="text" class="form-control form-control-sm mono-input" data-mcp-allow="${idx}" value="${escapeHtml((srv.enabledTools || []).join(", "))}">
              </div>
              <div class="col-6">
                <label class="form-label-sm">disabledTools (comma-separated)</label>
                <input type="text" class="form-control form-control-sm mono-input" data-mcp-deny="${idx}" value="${escapeHtml((srv.disabledTools || []).join(", "))}">
              </div>
            </div>
          </div>`
        )
        .join("");

      html += `
        <div class="section-block">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <div>
              <div class="section-heading mb-0">MCP Server Definitions</div>
              <div class="section-desc mb-0">Keep lazy loading (default) so <code>permissions.deny</code> <code>mcp(...)</code> rules apply inside <code>call_mcp_tool</code>.</div>
            </div>
            <button type="button" id="btn-add-mcp" class="btn btn-sm btn-outline-primary py-0 px-2" style="font-size:0.75rem;">+ Add Server</button>
          </div>
          ${serversHtml || '<div class="text-body-secondary small">No MCP servers configured.</div>'}
        </div>
      `;
    } else if (fid === "hooks_config") {
      const h = s.hooks;
      html += `
        <div class="section-block">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <div>
              <div class="section-heading mb-0">PreToolUse Synchronous Security Gate</div>
              <div class="section-desc mb-0">Exit code <code>2</code> or JSON <code>{"decision":"deny"}</code> blocks tool execution immediately.</div>
            </div>
            <div class="form-check form-switch">
              <input class="form-check-input" type="checkbox" id="hook-pre-en" ${h.enablePreToolUse ? "checked" : ""}>
            </div>
          </div>
          <div class="row g-2 ${h.enablePreToolUse ? "" : "d-none"}">
            <div class="col-md-5">
              <label class="form-label-sm" for="hook-pre-matcher">Tool Regex Matcher</label>
              <input id="hook-pre-matcher" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(h.preMatcher)}">
            </div>
            <div class="col-md-7">
              <label class="form-label-sm" for="hook-pre-cmd">Guard Command</label>
              <input id="hook-pre-cmd" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(h.preCommand)}">
            </div>
          </div>
        </div>

        <div class="section-block">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <div>
              <div class="section-heading mb-0">PostToolUse SIEM Audit Logger</div>
              <div class="section-desc mb-0">Appends structured JSONL telemetry after tool execution.</div>
            </div>
            <div class="form-check form-switch">
              <input class="form-check-input" type="checkbox" id="hook-post-en" ${h.enablePostToolUse ? "checked" : ""}>
            </div>
          </div>
          <div class="row g-2 ${h.enablePostToolUse ? "" : "d-none"}">
            <div class="col-md-5">
              <label class="form-label-sm" for="hook-post-matcher">Tool Regex Matcher</label>
              <input id="hook-post-matcher" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(h.postMatcher)}">
            </div>
            <div class="col-md-7">
              <label class="form-label-sm" for="hook-post-cmd">Audit Command</label>
              <input id="hook-post-cmd" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(h.postCommand)}">
            </div>
          </div>
        </div>

        <div class="section-block">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <div>
              <div class="section-heading mb-0">SessionStart Ephemeral Compliance Banner</div>
              <div class="section-desc mb-0">Injects an enterprise governance reminder at the start of every agent session.</div>
            </div>
            <div class="form-check form-switch">
              <input class="form-check-input" type="checkbox" id="hook-banner-en" ${h.enableSessionStartBanner ? "checked" : ""}>
            </div>
          </div>
          <div class="${h.enableSessionStartBanner ? "" : "d-none"}">
            <label class="form-label-sm" for="hook-banner-txt">Compliance Banner Text</label>
            <input id="hook-banner-txt" type="text" class="form-control form-control-sm" value="${escapeHtml(h.sessionBannerText)}">
          </div>
        </div>
      `;
    } else if (fid === "guard_sh" || fid === "guard_ps1") {
      const isPs = fid === "guard_ps1";
      html += `
        <div class="section-block">
          <div class="section-heading">${isPs ? "Windows PowerShell" : "Linux / macOS POSIX Bash"} Deterministic Guard</div>
          <div class="section-desc">
            Edit the full guard script directly in the live code editor on the right. Changes round-trip into your single-file download and MDM <code>.zip</code> bundle.
          </div>
          <ul class="small text-body-secondary mb-2 ps-3">
            <li><strong>Exit Code 0</strong>: Permits compliant tool call and records JSONL SIEM event.</li>
            <li><strong>Exit Code 2</strong>: Hard-blocks violating tool call and surfaces stderr policy reason to the agent.</li>
            <li><strong>5 Defense Domains</strong>: File deletion, OS credential stores/keys, lateral movement, privilege/lock bypass, and cloud metadata SSRF.</li>
          </ul>
          <button type="button" id="btn-reset-guard-script" class="btn btn-sm btn-outline-secondary">Reset Script to Canonical Default</button>
        </div>
      `;
    } else if (fid === "acp_json" || fid === "acp_auth") {
      const acp = s.acp;
      html += `
        <div class="section-block">
          <div class="section-heading">JetBrains IDEs &amp; Zed Editor (ACP 1.3.0+)</div>
          <div class="section-desc">
            ACP servers inherit your Gateway URL, headers, and models from Group 01 and require <code>wireProtocol: "genai"</code> plus <code>{"auth": {"type": "gateway"}}</code>.
          </div>
          <div class="row g-2 mb-2">
            <div class="col-md-8">
              <label class="form-label-sm" for="acp-cmd">Antigravity CLI Executable Path</label>
              <input id="acp-cmd" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(acp.command)}">
            </div>
            <div class="col-md-4">
              <label class="form-label-sm" for="acp-auth-type">ACP Auth Type</label>
              <select id="acp-auth-type" class="form-select form-select-sm">
                <option value="gateway" ${acp.authType === "gateway" ? "selected" : ""}>gateway (Required)</option>
              </select>
            </div>
          </div>
        </div>
      `;
    }

    container.innerHTML = html;
    bindActiveFormEvents(container, fid);
  }

  /**
   * Attach input/change listeners to the currently rendered left-pane form.
   *
   * @summary Mutates `AppStore.state` cleanly and triggers `scheduleFormCompile`.
   * @param {HTMLElement} container - Left-pane form container.
   * @param {string} fid - Active `file_id`.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function bindActiveFormEvents(container, fid) {
    const s = AppStore.state;

    container.querySelectorAll(".btn-toggle-secret").forEach((btn) => {
      btn.addEventListener("click", () => {
        AppStore.showSecrets = !AppStore.showSecrets;
        renderActiveFormPanel();
      });
    });

    if (fid === "admin_settings") {
      const gw = s.gateway;
      container.querySelector("#gw-enabled")?.addEventListener("change", (e) => {
        gw.enabled = e.target.checked;
        scheduleFormCompile(false);
      });
      container.querySelector("#gw-url")?.addEventListener("input", (e) => {
        gw.url = e.target.value;
        s.gateway_env.url = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#gw-wire")?.addEventListener("change", (e) => {
        gw.wireProtocol = e.target.value;
        s.gateway_env.wireProtocol = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#gw-omit-key")?.addEventListener("change", (e) => {
        gw.omitApiKeyInMdm = e.target.checked;
        renderActiveFormPanel();
        scheduleFormCompile(false);
      });
      container.querySelector("#gw-apikey")?.addEventListener("input", (e) => {
        gw.apiKey = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#gw-cacert")?.addEventListener("input", (e) => {
        gw.caCertPath = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#gw-default-model")?.addEventListener("input", (e) => {
        gw.defaultModelId = e.target.value;
        scheduleFormCompile(false);
      });

      container.querySelector("#btn-add-gw-header")?.addEventListener("click", () => {
        gw.customHeaders.push({ key: "X-Enterprise-Team", value: "Platform" });
        renderActiveFormPanel();
        scheduleFormCompile(false);
      });
      container.querySelectorAll("[data-gw-hdr-key]").forEach((inp) => {
        inp.addEventListener("input", () => {
          gw.customHeaders[Number(inp.dataset.gwHdrKey)].key = inp.value;
          scheduleFormCompile(false);
        });
      });
      container.querySelectorAll("[data-gw-hdr-val]").forEach((inp) => {
        inp.addEventListener("input", () => {
          gw.customHeaders[Number(inp.dataset.gwHdrVal)].value = inp.value;
          scheduleFormCompile(false);
        });
      });
      container.querySelectorAll("[data-gw-hdr-del]").forEach((btn) => {
        btn.addEventListener("click", () => {
          gw.customHeaders.splice(Number(btn.dataset.gwHdrDel), 1);
          renderActiveFormPanel();
          scheduleFormCompile(false);
        });
      });

      container.querySelector("#btn-add-gw-model")?.addEventListener("click", () => {
        gw.models.push({ modelId: "gemini-3.8-flash", displayName: "Gemini 3.8 Flash" });
        renderActiveFormPanel();
        scheduleFormCompile(false);
      });
      container.querySelectorAll("[data-gw-mdl-id]").forEach((inp) => {
        inp.addEventListener("input", () => {
          gw.models[Number(inp.dataset.gwMdlId)].modelId = inp.value;
          scheduleFormCompile(false);
        });
      });
      container.querySelectorAll("[data-gw-mdl-name]").forEach((inp) => {
        inp.addEventListener("input", () => {
          gw.models[Number(inp.dataset.gwMdlName)].displayName = inp.value;
          scheduleFormCompile(false);
        });
      });
      container.querySelectorAll("[data-gw-mdl-del]").forEach((btn) => {
        btn.addEventListener("click", () => {
          gw.models.splice(Number(btn.dataset.gwMdlDel), 1);
          renderActiveFormPanel();
          scheduleFormCompile(false);
        });
      });
    } else if (fid === "gateway_env") {
      const ge = s.gateway_env;
      container.querySelector("#env-export-prefix")?.addEventListener("change", (e) => {
        ge.exportPrefix = e.target.checked;
        scheduleFormCompile(false);
      });
      container.querySelector("#env-url")?.addEventListener("input", (e) => {
        ge.url = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#env-apikey")?.addEventListener("input", (e) => {
        ge.apiKey = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#env-wire")?.addEventListener("change", (e) => {
        ge.wireProtocol = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#env-cacert")?.addEventListener("input", (e) => {
        ge.caCert = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#env-headers")?.addEventListener("input", (e) => {
        ge.headers = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#env-models")?.addEventListener("input", (e) => {
        ge.models = e.target.value;
        scheduleFormCompile(false);
      });
    } else if (fid === "cli_settings") {
      const c = s.cli;
      container.querySelector("#cli-agent-mode")?.addEventListener("change", (e) => {
        c.agentMode = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#cli-tool-perm")?.addEventListener("change", (e) => {
        c.toolPermission = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#cli-artifact-review")?.addEventListener("change", (e) => {
        c.artifactReviewPolicy = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#cli-enable-sandbox")?.addEventListener("change", (e) => {
        c.enableTerminalSandbox = e.target.checked;
        scheduleFormCompile(false);
      });
      container.querySelector("#cli-non-ws")?.addEventListener("change", (e) => {
        c.allowNonWorkspaceAccess = e.target.checked;
        scheduleFormCompile(false);
      });
      container.querySelector("#cli-opt-ui")?.addEventListener("change", (e) => {
        c.includeOptionalUiKeys = e.target.checked;
        renderActiveFormPanel();
        scheduleFormCompile(false);
      });
      container.querySelector("#cli-history-size")?.addEventListener("input", (e) => {
        c.historySize = Number(e.target.value || 0);
        scheduleFormCompile(false);
      });
      container.querySelector("#cli-sbp-enabled")?.addEventListener("change", (e) => {
        c.sandboxProxyEnabled = e.target.checked;
        if (c.sandboxProxyEnabled && !c.sandboxProxyAddress) {
          c.sandboxProxyAddress = "http://proxy.internal.example.com:3128";
          c.sandboxProxyCertFile = "/etc/antigravity/certs/corp-root-ca.pem";
        }
        renderActiveFormPanel();
        scheduleFormCompile(false);
      });
      container.querySelector("#cli-sbp-addr")?.addEventListener("input", (e) => {
        c.sandboxProxyAddress = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#cli-sbp-cert")?.addEventListener("input", (e) => {
        c.sandboxProxyCertFile = e.target.value;
        scheduleFormCompile(false);
      });
      bindPermissionsWidgetEvents(container, "cli");
    } else if (fid === "desktop_config") {
      const d = s.desktop;
      container.querySelector("#desk-auto-exec")?.addEventListener("change", (e) => {
        d.autoExecutionPolicy = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#desk-artifact")?.addEventListener("change", (e) => {
        d.artifactReviewMode = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#desk-browser-js")?.addEventListener("change", (e) => {
        d.browserJsExecutionPolicy = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#desk-sandbox")?.addEventListener("change", (e) => {
        d.enableTerminalSandbox = e.target.checked;
        scheduleFormCompile(false);
      });
      container.querySelector("#desk-net")?.addEventListener("change", (e) => {
        d.sandboxAllowNetwork = e.target.checked;
        scheduleFormCompile(false);
      });
      bindPermissionsWidgetEvents(container, "desktop");
    } else if (fid === "browser_allowlist") {
      const addDom = () => {
        const inp = container.querySelector("#input-new-domain");
        const val = (inp?.value || "").trim();
        if (!val) {
          return;
        }
        if (!s.browser_domains.includes(val)) {
          s.browser_domains.push(val);
        }
        inp.value = "";
        renderActiveFormPanel();
        scheduleFormCompile(false);
      };
      container.querySelector("#btn-add-domain")?.addEventListener("click", addDom);
      container.querySelector("#input-new-domain")?.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          addDom();
        }
      });
      container.querySelectorAll("[data-del-domain]").forEach((btn) => {
        btn.addEventListener("click", () => {
          s.browser_domains.splice(Number(btn.dataset.delDomain), 1);
          renderActiveFormPanel();
          scheduleFormCompile(false);
        });
      });
    } else if (fid === "mcp_config") {
      container.querySelector("#btn-add-mcp")?.addEventListener("click", () => {
        s.mcp_servers.push({
          name: `corp_server_${s.mcp_servers.length + 1}`,
          transport: "stdio",
          command: "/usr/local/bin/mcp_server",
          args: [],
          serverUrl: "",
          disabled: true,
          timeoutSeconds: 60,
          enabledTools: [],
          disabledTools: [],
          env: {},
        });
        renderActiveFormPanel();
        scheduleFormCompile(false);
      });
      container.querySelectorAll("[data-mcp-name]").forEach((inp) => {
        inp.addEventListener("input", () => {
          s.mcp_servers[Number(inp.dataset.mcpName)].name = inp.value;
          scheduleFormCompile(false);
        });
      });
      container.querySelectorAll("[data-mcp-transport]").forEach((sel) => {
        sel.addEventListener("change", () => {
          s.mcp_servers[Number(sel.dataset.mcpTransport)].transport = sel.value;
          renderActiveFormPanel();
          scheduleFormCompile(false);
        });
      });
      container.querySelectorAll("[data-mcp-enabled]").forEach((chk) => {
        chk.addEventListener("change", () => {
          s.mcp_servers[Number(chk.dataset.mcpEnabled)].disabled = !chk.checked;
          renderActiveFormPanel();
          scheduleFormCompile(false);
        });
      });
      container.querySelectorAll("[data-mcp-del]").forEach((btn) => {
        btn.addEventListener("click", () => {
          s.mcp_servers.splice(Number(btn.dataset.mcpDel), 1);
          renderActiveFormPanel();
          scheduleFormCompile(false);
        });
      });
      container.querySelectorAll("[data-mcp-url]").forEach((inp) => {
        inp.addEventListener("input", () => {
          s.mcp_servers[Number(inp.dataset.mcpUrl)].serverUrl = inp.value;
          scheduleFormCompile(false);
        });
      });
      container.querySelectorAll("[data-mcp-cmd]").forEach((inp) => {
        inp.addEventListener("input", () => {
          s.mcp_servers[Number(inp.dataset.mcpCmd)].command = inp.value;
          scheduleFormCompile(false);
        });
      });
      container.querySelectorAll("[data-mcp-args]").forEach((inp) => {
        inp.addEventListener("input", () => {
          s.mcp_servers[Number(inp.dataset.mcpArgs)].args = inp.value
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean);
          scheduleFormCompile(false);
        });
      });
      container.querySelectorAll("[data-mcp-allow]").forEach((inp) => {
        inp.addEventListener("input", () => {
          s.mcp_servers[Number(inp.dataset.mcpAllow)].enabledTools = inp.value
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean);
          scheduleFormCompile(false);
        });
      });
      container.querySelectorAll("[data-mcp-deny]").forEach((inp) => {
        inp.addEventListener("input", () => {
          s.mcp_servers[Number(inp.dataset.mcpDeny)].disabledTools = inp.value
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean);
          scheduleFormCompile(false);
        });
      });
    } else if (fid === "hooks_config") {
      const h = s.hooks;
      container.querySelector("#hook-pre-en")?.addEventListener("change", (e) => {
        h.enablePreToolUse = e.target.checked;
        renderActiveFormPanel();
        scheduleFormCompile(false);
      });
      container.querySelector("#hook-pre-matcher")?.addEventListener("input", (e) => {
        h.preMatcher = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#hook-pre-cmd")?.addEventListener("input", (e) => {
        h.preCommand = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#hook-post-en")?.addEventListener("change", (e) => {
        h.enablePostToolUse = e.target.checked;
        renderActiveFormPanel();
        scheduleFormCompile(false);
      });
      container.querySelector("#hook-post-matcher")?.addEventListener("input", (e) => {
        h.postMatcher = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#hook-post-cmd")?.addEventListener("input", (e) => {
        h.postCommand = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#hook-banner-en")?.addEventListener("change", (e) => {
        h.enableSessionStartBanner = e.target.checked;
        renderActiveFormPanel();
        scheduleFormCompile(false);
      });
      container.querySelector("#hook-banner-txt")?.addEventListener("input", (e) => {
        h.sessionBannerText = e.target.value;
        scheduleFormCompile(false);
      });
    } else if (fid === "guard_sh" || fid === "guard_ps1") {
      container.querySelector("#btn-reset-guard-script")?.addEventListener("click", async () => {
        try {
          const fresh = await postJson("/api/preset", {
            preset_id: "balanced",
            dev_user: s.dev_user,
          });
          s.scripts[fid] = fresh.state.scripts[fid];
          scheduleFormCompile(false);
          showToast("Guard script restored to canonical default", "success");
        } catch (err) {
          showToast(err.message, "danger");
        }
      });
    } else if (fid === "acp_json" || fid === "acp_auth") {
      container.querySelector("#acp-cmd")?.addEventListener("input", (e) => {
        s.acp.command = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#acp-auth-type")?.addEventListener("change", (e) => {
        s.acp.authType = e.target.value;
        scheduleFormCompile(false);
      });
    }
  }

  /**
   * Update ONLY the right-pane header without resetting cursor focus in `#code-editor`.
   *
   * @summary Updates active filename, validation badge, and Auto-Fix All button.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function renderEditorHeaderOnly() {
    const fid = AppStore.selectedFileId;
    const meta = CATALOG_BY_ID[fid];
    const titleEl = document.getElementById("active-file-title");
    if (titleEl && meta) {
      titleEl.textContent = meta.filename;
    }

    const badge = document.getElementById("global-validation-badge");
    const fixAllBtn = document.getElementById("btn-fix-all");
    const v = AppStore.validation;
    if (badge && v) {
      if (v.error_count > 0) {
        badge.className = "badge rounded-pill status-badge-error px-2 py-1";
        badge.textContent = `ERROR · ${v.error_count} Error(s), ${v.warn_count} Warn`;
      } else if (v.warn_count > 0) {
        badge.className = "badge rounded-pill status-badge-warn px-2 py-1";
        badge.textContent = `WARN · ${v.warn_count} Warning(s)`;
      } else {
        badge.className = "badge rounded-pill status-badge-pass px-2 py-1";
        badge.textContent = "PASS · Valid";
      }
    }
    if (fixAllBtn && v) {
      fixAllBtn.classList.toggle("d-none", !(v.fixable_count > 0));
      fixAllBtn.textContent = `Auto-Fix All (${v.fixable_count})`;
    }
  }

  /**
   * Update line-number gutter to match the current `#code-editor` line count.
   *
   * @summary Keeps line numbers aligned during typing and scrolling.
   * @param {string} text - Raw text inside `#code-editor`.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function updateEditorGutter(text) {
    const gutter = document.getElementById("editor-gutter");
    if (!gutter) {
      return;
    }
    const count = Math.max(1, (text || "").split("\n").length);
    const nums = [];
    for (let i = 1; i <= count; i += 1) {
      nums.push(i);
    }
    gutter.textContent = nums.join("\n");
  }

  /**
   * Render the right-pane header and raw file code editor.
   *
   * @summary Populates `#code-editor` with the active compiled or imported text.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function renderEditorPane() {
    renderEditorHeaderOnly();
    const editor = document.getElementById("code-editor");
    const content = AppStore.files[AppStore.selectedFileId] || "";
    if (editor) {
      editor.value = content;
      updateEditorGutter(content);
    }
  }

  /**
   * Render the Right-Pane Real-Time Validation Drawer.
   *
   * @summary Displays PASS status or actionable per-issue `Auto-Fix` buttons.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function renderValidationDrawer() {
    const countEl = document.getElementById("drawer-issue-count");
    const drawer = document.getElementById("drawer-content");
    if (!drawer) {
      return;
    }

    const showAll = document.getElementById("select-validation-scope")?.value === "all";
    const v = AppStore.validation || { issues_by_file: {}, all_issues: [] };
    const scopedIssues = showAll
      ? v.all_issues || []
      : (v.issues_by_file && v.issues_by_file[AppStore.selectedFileId]) || [];

    if (countEl) {
      countEl.textContent = String(
        scopedIssues.filter((i) => i.severity !== "INFO").length
      );
    }

    if (!scopedIssues.length) {
      drawer.innerHTML = `
        <div class="d-flex align-items-center gap-2 p-2 rounded status-badge-pass">
          <strong>PASS:</strong>
          <span>Zero schema, UTF-8 BOM, sandbox mount, or cross-OS runtime issues detected.</span>
        </div>`;
      return;
    }

    drawer.innerHTML = scopedIssues
      .map((issue) => {
        const fMeta = CATALOG_BY_ID[issue.file_id];
        const fileTag =
          showAll && fMeta
            ? `<span class="badge text-bg-light border me-1">${escapeHtml(fMeta.filename)}</span>`
            : "";
        const lineTag = issue.line
          ? ` <span class="text-body-secondary">(line ${issue.line})</span>`
          : "";
        const fixBtn = issue.fixable
          ? `<button type="button" class="btn btn-sm btn-primary text-nowrap py-1 px-2" style="font-size:0.74rem;" data-autofix-code="${escapeHtml(issue.code)}" data-autofix-fid="${escapeHtml(issue.file_id)}">
               Auto-Fix: ${escapeHtml(issue.fix_label)}
             </button>`
          : "";

        return `
          <div class="issue-row severity-${escapeHtml(issue.severity)}">
            <div>
              <div class="fw-semibold" style="font-size:0.8rem;">
                <span class="badge ${issue.severity === "ERROR" ? "text-bg-danger" : issue.severity === "WARN" ? "text-bg-warning" : "text-bg-info"} me-1">${escapeHtml(issue.severity)}</span>
                ${fileTag}${escapeHtml(issue.title)}${lineTag}
              </div>
              <div class="text-body-secondary mt-1" style="font-size:0.76rem;">${escapeHtml(issue.message)}</div>
            </div>
            ${fixBtn}
          </div>`;
      })
      .join("");

    drawer.querySelectorAll("[data-autofix-code]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const targetFid = btn.dataset.autofixFid;
        const code = btn.dataset.autofixCode;
        try {
          const res = await postJson("/api/autofix", {
            file_id: targetFid,
            issue_code: code,
            content: AppStore.files[targetFid] || "",
            state: AppStore.state,
          });
          AppStore.selectedFileId = targetFid;
          applyServerPayload(res);
          showToast(`Applied Auto-Fix (${code})`, "success");
        } catch (err) {
          showToast(err.message, "danger");
        }
      });
    });
  }

  /**
   * Trigger a browser file download from a `Blob` response.
   *
   * @summary Creates a temporary object URL and clicks a hidden anchor element.
   * @param {Blob} blob - Binary payload to save.
   * @param {string} filename - Suggested download filename.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function triggerBrowserDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  /**
   * Bind all top-level toolbar, multi-select dropdown, reference card, editor,
   * import, and export events.
   *
   * @summary Executed once on DOM startup.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function bindGlobalEvents() {
    // Theme toggle
    const savedTheme = localStorage.getItem("agy_studio_theme") || "light";
    applyTheme(savedTheme);
    document.getElementById("btn-theme-toggle")?.addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-bs-theme");
      applyTheme(current === "dark" ? "light" : "dark");
    });

    // Sync fixed-strategy Popper multi-select dropdown widths & viewport height
    const syncMultiSelectMenuGeometry = (toggleBtn) => {
      if (!toggleBtn) {
        return;
      }
      const menu = toggleBtn.parentElement?.querySelector(".studio-multiselect-menu");
      if (!menu) {
        return;
      }
      const btnRect = toggleBtn.getBoundingClientRect();
      menu.style.width = `${Math.max(Math.round(btnRect.width), 245)}px`;
      const topbarHeight = document.querySelector(".studio-topbar")?.offsetHeight || 56;
      const spaceBelow = window.innerHeight - btnRect.bottom - 16;
      const spaceAbove = btnRect.top - topbarHeight - 12;
      const bestSpace = Math.max(spaceBelow, spaceAbove, 220);
      menu.style.maxHeight = `${Math.round(bestSpace)}px`;
    };

    document.querySelectorAll(".studio-multiselect-btn").forEach((btn) => {
      btn.parentElement?.addEventListener("show.bs.dropdown", () => {
        syncMultiSelectMenuGeometry(btn);
      });
      btn.parentElement?.addEventListener("shown.bs.dropdown", () => {
        syncMultiSelectMenuGeometry(btn);
      });
    });

    window.addEventListener("resize", () => {
      document.querySelectorAll(".studio-multiselect-btn[aria-expanded='true']").forEach((btn) => {
        syncMultiSelectMenuGeometry(btn);
      });
    });

    document.querySelector(".left-scroll-area")?.addEventListener(
      "scroll",
      () => {
        document.querySelectorAll(".studio-multiselect-btn[aria-expanded='true']").forEach((btn) => {
          syncMultiSelectMenuGeometry(btn);
        });
      },
      { passive: true }
    );

    // Reset Scope button
    document.getElementById("btn-reset-scope")?.addEventListener("click", () => {
      AppStore.state.os_list = [];
      AppStore.state.surfaces = [];
      AppStore.state.selected_file_ids = [];
      AppStore.availableFileIds = [];
      AppStore.activeFileIds = [];
      AppStore.selectedFileId = "";
      renderAllPanels();
      showToast("Reset OS, Surface, and File scope", "dark");
    });

    // Step 1: Target OS Multi-Select Checkboxes & Select All / Clear
    const updateOsFromDom = () => {
      const checked = [];
      document.querySelectorAll("[data-os-value]").forEach((chk) => {
        if (chk.checked) {
          checked.push(chk.dataset.osValue);
        }
      });
      AppStore.state.os_list = checked;
      renderStep1Controls();
      scheduleFormCompile(true);
    };
    document.querySelectorAll("[data-os-value]").forEach((chk) => {
      chk.addEventListener("change", updateOsFromDom);
    });
    document.getElementById("btn-os-select-all")?.addEventListener("click", () => {
      document.querySelectorAll("[data-os-value]").forEach((chk) => {
        chk.checked = true;
      });
      updateOsFromDom();
    });
    document.getElementById("btn-os-clear")?.addEventListener("click", () => {
      document.querySelectorAll("[data-os-value]").forEach((chk) => {
        chk.checked = false;
      });
      updateOsFromDom();
    });

    // Step 1: Antigravity Surface Multi-Select Checkboxes & Select All / Clear
    const updateSurfacesFromDom = () => {
      const checked = [];
      document.querySelectorAll("[data-surface-value]").forEach((chk) => {
        if (chk.checked) {
          checked.push(chk.dataset.surfaceValue);
        }
      });
      AppStore.state.surfaces = checked;
      renderStep1Controls();
      scheduleFormCompile(true);
    };
    document.querySelectorAll("[data-surface-value]").forEach((chk) => {
      chk.addEventListener("change", updateSurfacesFromDom);
    });
    document.getElementById("btn-surface-select-all")?.addEventListener("click", () => {
      document.querySelectorAll("[data-surface-value]").forEach((chk) => {
        chk.checked = true;
      });
      updateSurfacesFromDom();
    });
    document.getElementById("btn-surface-clear")?.addEventListener("click", () => {
      document.querySelectorAll("[data-surface-value]").forEach((chk) => {
        chk.checked = false;
      });
      updateSurfacesFromDom();
    });

    // Step 1: Workstation Username & Permission Sync Select
    document.getElementById("input-dev-user")?.addEventListener("input", (e) => {
      const oldUser = AppStore.state.dev_user || "alice";
      const nextUser = e.target.value.trim() || "alice";
      AppStore.state.dev_user = nextUser;
      const swapUserPaths = (arr) =>
        (arr || []).map((r) =>
          r
            .replace(`/home/${oldUser}/`, `/home/${nextUser}/`)
            .replace(`/Users/${oldUser}/`, `/Users/${nextUser}/`)
        );
      ["allow", "ask", "deny"].forEach((b) => {
        AppStore.state.cli.permissions[b] = swapUserPaths(AppStore.state.cli.permissions[b]);
        AppStore.state.desktop.permissions[b] = swapUserPaths(AppStore.state.desktop.permissions[b]);
      });
      scheduleFormCompile(true);
    });

    document.getElementById("select-perm-sync")?.addEventListener("change", (e) => {
      AppStore.state.sync_permissions = e.target.value === "linked";
      if (AppStore.state.sync_permissions) {
        AppStore.state.desktop.permissions = JSON.parse(
          JSON.stringify(AppStore.state.cli.permissions)
        );
      }
      scheduleFormCompile(true);
    });

    // Step 2: Policy Type / Preset Dropdown (placed after Surface selection)
    document.getElementById("preset-selector")?.addEventListener("change", async (e) => {
      const presetId = e.target.value;
      try {
        const res = await postJson("/api/preset", {
          preset_id: presetId,
          dev_user: AppStore.state.dev_user,
          preserve_scope: true,
          os_list: AppStore.state.os_list,
          surfaces: AppStore.state.surfaces,
          selected_file_ids: AppStore.state.selected_file_ids,
        });
        applyServerPayload(res);
        showToast(`Loaded policy preset: ${e.target.selectedOptions[0].text}`, "primary");
      } catch (err) {
        showToast(err.message, "danger");
      }
    });

    // Step 2: Target Config Files Select All / Clear
    document.getElementById("btn-files-select-all")?.addEventListener("click", () => {
      AppStore.state.selected_file_ids = [...AppStore.availableFileIds];
      if (!AppStore.selectedFileId && AppStore.availableFileIds.length > 0) {
        AppStore.selectedFileId = AppStore.availableFileIds[0];
      }
      scheduleFormCompile(true);
    });
    document.getElementById("btn-files-clear")?.addEventListener("click", () => {
      AppStore.state.selected_file_ids = [];
      AppStore.selectedFileId = "";
      scheduleFormCompile(true);
    });

    // Step 2: Currently Editing File single-select dropdown
    document.getElementById("active-file-selector")?.addEventListener("change", (e) => {
      AppStore.selectedFileId = e.target.value;
      renderFileReferenceCard(true);
      renderActiveFormPanel();
      renderEditorPane();
      renderValidationDrawer();
    });

    // Step 3A: Collapsible Per-File Manual Permissions & Lock / Unlock CLI
    document.getElementById("btn-toggle-file-lock-cli")?.addEventListener("click", () => {
      AppStore.fileLockExpanded = !AppStore.fileLockExpanded;
      renderFileReferenceCard(AppStore.activeFileIds.length > 0);
    });

    document.getElementById("select-file-lock-os")?.addEventListener("change", (e) => {
      AppStore.selectedLockOs = e.target.value;
      renderFileReferenceCard(AppStore.activeFileIds.length > 0);
    });

    document.getElementById("btn-copy-file-lock")?.addEventListener("click", () => {
      const cli = AppStore.perFileCli[AppStore.selectedFileId]?.[AppStore.selectedLockOs];
      if (cli?.lock) {
        navigator.clipboard?.writeText(cli.lock);
        showToast("Copied manual permissions & lock commands", "dark");
      }
    });

    document.getElementById("btn-copy-file-unlock")?.addEventListener("click", () => {
      const cli = AppStore.perFileCli[AppStore.selectedFileId]?.[AppStore.selectedLockOs];
      if (cli?.unlock) {
        navigator.clipboard?.writeText(cli.unlock);
        showToast("Copied maintenance unlock command", "dark");
      }
    });

    // Auto-Fix All button
    document.getElementById("btn-fix-all")?.addEventListener("click", async () => {
      try {
        const res = await postJson("/api/autofix", {
          file_id: "ALL_FILES",
          issue_code: "ALL",
          files: AppStore.files,
          state: AppStore.state,
        });
        applyServerPayload(res);
        showToast("Remediated all fixable validation findings", "success");
      } catch (err) {
        showToast(err.message, "danger");
      }
    });

    // Right-Pane Live Code Editor Two-Way Sync
    const editor = document.getElementById("code-editor");
    const gutter = document.getElementById("editor-gutter");
    if (editor) {
      editor.addEventListener("scroll", () => {
        if (gutter) {
          gutter.scrollTop = editor.scrollTop;
        }
      });

      editor.addEventListener("keydown", (ev) => {
        if (ev.key === "Tab") {
          ev.preventDefault();
          const start = editor.selectionStart;
          const end = editor.selectionEnd;
          editor.value = `${editor.value.substring(0, start)}  ${editor.value.substring(end)}`;
          editor.selectionStart = start + 2;
          editor.selectionEnd = start + 2;
          editor.dispatchEvent(new Event("input"));
        }
      });

      editor.addEventListener("input", () => {
        if (!AppStore.selectedFileId) {
          return;
        }
        const raw = editor.value;
        AppStore.files[AppStore.selectedFileId] = raw;
        updateEditorGutter(raw);
        const syncPill = document.getElementById("sync-status-pill");
        if (syncPill) {
          syncPill.textContent = "Parsing";
        }

        clearTimeout(AppStore.codeSyncTimer);
        AppStore.codeSyncTimer = setTimeout(async () => {
          try {
            const res = await postJson("/api/sync-code", {
              file_id: AppStore.selectedFileId,
              content: raw,
              state: AppStore.state,
            });
            applyServerPayload(res, { skipEditor: true, skipForm: false });
            if (syncPill) {
              syncPill.textContent = "Two-Way Synced";
            }
          } catch (err) {
            showToast(err.message, "danger");
          }
        }, 300);
      });
    }

    // Format JSON button
    document.getElementById("btn-format-code")?.addEventListener("click", () => {
      const fid = AppStore.selectedFileId;
      if (!fid || !CATALOG_BY_ID[fid]) {
        return;
      }
      const raw = (AppStore.files[fid] || "").replace(/^\uFEFF/, "");
      if (CATALOG_BY_ID[fid].language === "json") {
        try {
          const pretty = `${JSON.stringify(JSON.parse(raw), null, 2)}\n`;
          AppStore.files[fid] = pretty;
          renderEditorPane();
          editor?.dispatchEvent(new Event("input"));
          showToast("Formatted JSON cleanly", "dark");
        } catch (err) {
          showToast(`Cannot format malformed JSON: ${err.message}`, "warning");
        }
      } else {
        showToast("Line endings normalized", "dark");
      }
    });

    // Copy active file
    document.getElementById("btn-copy-code")?.addEventListener("click", () => {
      const fid = AppStore.selectedFileId;
      if (!fid || !CATALOG_BY_ID[fid]) {
        return;
      }
      const content = AppStore.files[fid] || "";
      navigator.clipboard?.writeText(content);
      showToast(`Copied ${CATALOG_BY_ID[fid].filename} to clipboard`, "dark");
    });

    // Download single BOM-free file
    document.getElementById("btn-download-single")?.addEventListener("click", async () => {
      const fid = AppStore.selectedFileId;
      const meta = CATALOG_BY_ID[fid];
      if (!meta) {
        return;
      }
      try {
        const resp = await fetch("/api/download-file", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ file_id: fid, content: AppStore.files[fid] || "" }),
        });
        if (!resp.ok) {
          throw new Error("Failed to download file");
        }
        const blob = await resp.blob();
        triggerBrowserDownload(blob, meta.filename);
        showToast(`Downloaded BOM-free ${meta.filename}`, "success");
      } catch (err) {
        showToast(err.message, "danger");
      }
    });

    // Download OS-structured MDM `.zip` bundle (includes only selected files)
    document.getElementById("btn-download-zip")?.addEventListener("click", async () => {
      if (!AppStore.activeFileIds.length) {
        return;
      }
      try {
        const resp = await fetch("/api/download-zip", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ state: AppStore.state }),
        });
        if (!resp.ok) {
          throw new Error("Failed to build MDM ZIP bundle");
        }
        const blob = await resp.blob();
        triggerBrowserDownload(blob, "antigravity-mdm-policy-bundle.zip");
        showToast("Downloaded antigravity-mdm-policy-bundle.zip", "success");
      } catch (err) {
        showToast(err.message, "danger");
      }
    });

    // Validation Drawer Scope Dropdown
    document.getElementById("select-validation-scope")?.addEventListener("change", () => {
      renderValidationDrawer();
    });

    // Top-Bar Reference Guide Modal Section & OS Controls
    document.getElementById("select-ref-section")?.addEventListener("change", (e) => {
      AppStore.refModalSection = e.target.value;
      renderReferenceGuideModal();
    });

    document.getElementById("select-ref-cli-os")?.addEventListener("change", (e) => {
      AppStore.refModalCliOs = e.target.value;
      renderReferenceGuideModal();
    });

    document.getElementById("referenceGuideModal")?.addEventListener("show.bs.modal", () => {
      if (AppStore.state.os_list.length === 1) {
        AppStore.refModalCliOs = AppStore.state.os_list[0];
        const osSel = document.getElementById("select-ref-cli-os");
        if (osSel) {
          osSel.value = AppStore.refModalCliOs;
        }
      }
      renderReferenceGuideModal();
    });

    // Import Modal: Drag-and-Drop / File Picker
    const dropzone = document.getElementById("import-dropzone");
    const fileInput = document.getElementById("input-import-files");
    const closeImportModal = () => {
      const modalEl = document.getElementById("importModal");
      if (modalEl) {
        window.bootstrap.Modal.getInstance(modalEl)?.hide();
      }
    };

    const handleFileUploadList = async (fileList) => {
      if (!fileList || !fileList.length) {
        return;
      }
      const fd = new FormData();
      Array.from(fileList).forEach((f) => fd.append("files", f));
      fd.append("state", JSON.stringify(AppStore.state));
      try {
        const resp = await fetch("/api/import", { method: "POST", body: fd });
        const data = await resp.json();
        if (!resp.ok) {
          throw new Error(data.error || "Import failed");
        }
        if (data.imported_files && data.imported_files.length) {
          const firstId = data.imported_files[0].detected_file_id;
          if (CATALOG_BY_ID[firstId]) {
            AppStore.selectedFileId = firstId;
          }
        }
        applyServerPayload(data);
        closeImportModal();
        showToast(`Imported ${data.imported_files.length} file(s) into Studio`, "success");
      } catch (err) {
        showToast(err.message, "danger");
      }
    };

    document.getElementById("btn-browse-files")?.addEventListener("click", (ev) => {
      ev.stopPropagation();
      fileInput?.click();
    });
    dropzone?.addEventListener("click", () => fileInput?.click());
    dropzone?.addEventListener("dragover", (ev) => {
      ev.preventDefault();
      dropzone.classList.add("dragover");
    });
    dropzone?.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
    dropzone?.addEventListener("drop", (ev) => {
      ev.preventDefault();
      dropzone.classList.remove("dragover");
      handleFileUploadList(ev.dataTransfer?.files);
    });
    fileInput?.addEventListener("change", () => {
      handleFileUploadList(fileInput.files);
      fileInput.value = "";
    });

    // Import Modal: Standalone Validate vs Import Paste
    document.getElementById("btn-validate-paste-only")?.addEventListener("click", async () => {
      const rawText = document.getElementById("paste-raw-textarea")?.value || "";
      const explicitType = document.getElementById("paste-file-type")?.value || "";
      const outEl = document.getElementById("standalone-validation-output");
      if (!rawText.trim()) {
        showToast("Paste configuration content first", "warning");
        return;
      }
      try {
        const res = await postJson("/api/validate", {
          file_id: explicitType,
          content: rawText,
          os_list: AppStore.state.os_list.length ? AppStore.state.os_list : ["linux", "macos", "windows"],
          surfaces: AppStore.state.surfaces.length ? AppStore.state.surfaces : ["cli", "desktop", "web", "ide"],
          dev_user: AppStore.state.dev_user,
        });
        const detectedLabel = CATALOG_BY_ID[res.detected_file_id]?.short_label || res.detected_file_id;
        if (!res.issues.length) {
          outEl.innerHTML = `<div class="p-2 rounded status-badge-pass small"><strong>PASS (${escapeHtml(detectedLabel)}):</strong> 0 errors, 0 warnings.</div>`;
        } else {
          outEl.innerHTML =
            `<div class="small fw-semibold mb-1">Detected as ${escapeHtml(detectedLabel)} — ${res.error_count} error(s), ${res.warn_count} warning(s):</div>` +
            res.issues
              .map(
                (i) =>
                  `<div class="issue-row severity-${escapeHtml(i.severity)} py-1 px-2 mb-1 small"><div><strong>[${escapeHtml(i.severity)}] ${escapeHtml(i.title)}:</strong> ${escapeHtml(i.message)}</div></div>`
              )
              .join("");
        }
      } catch (err) {
        showToast(err.message, "danger");
      }
    });

    document.getElementById("btn-import-paste")?.addEventListener("click", async () => {
      const rawText = document.getElementById("paste-raw-textarea")?.value || "";
      const explicitType = document.getElementById("paste-file-type")?.value || "";
      if (!rawText.trim()) {
        showToast("Paste configuration content first", "warning");
        return;
      }
      try {
        const res = await postJson("/api/import", {
          file_id: explicitType,
          raw_text: rawText,
          state: AppStore.state,
        });
        const importedId = res.imported_files?.[0]?.detected_file_id;
        if (importedId && CATALOG_BY_ID[importedId]) {
          AppStore.selectedFileId = importedId;
        }
        applyServerPayload(res);
        closeImportModal();
        showToast(`Imported into ${CATALOG_BY_ID[AppStore.selectedFileId].filename}`, "success");
      } catch (err) {
        showToast(err.message, "danger");
      }
    });

    // Import Modal: Load Sibling Repository Baseline
    document.getElementById("btn-import-repo-baseline")?.addEventListener("click", async () => {
      try {
        const res = await postJson("/api/import", {
          load_repo_baseline: true,
          state: AppStore.state,
        });
        applyServerPayload(res, { autoSelectFiles: true });
        closeImportModal();
        showToast("Loaded full 8-module baseline from ../agy-config/configs/", "success");
      } catch (err) {
        showToast(err.message, "danger");
      }
    });
  }

  // Boot the Studio in clean Step 1 progressive state
  initPresetDropdown();
  bindGlobalEvents();
  renderAllPanels();
})();
