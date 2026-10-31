/* ============================================================================
 * FILE HEADER: Interactive Client Controller — Antigravity Policy Studio
 * ============================================================================
 * Purpose:
 *   Powers the responsive Split-Pane Antigravity Admin Policy Studio UI using
 *   progressive multi-select dropdowns (OS -> Surface -> Policy Type & Target
 *   Files), a left-panel File Reference & Manual Lock CLI card, race-free
 *   two-way Form <-> Code synchronization, 1-click Auto-Fix remediation,
 *   multi-mode file import, and BOM-free single-file / `.zip` MDM downloads.
 *
 * Architecture / Context:
 *   Vanilla ES2022 controller loaded by `templates/index.html`. Communicates
 *   with the stateless Flask backend (`app.py`) via `/api/*` JSON and multipart
 *   endpoints using monotonic sequence IDs (`syncSeq`) and `AbortController`
 *   cancellation so out-of-order HTTP responses never clobber active typing.
 *   Persists only UI theme (`light`/`dark`) in `localStorage`.
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

  const UNSET_USER_TOKEN = "__DEV_USER__";
  const VALID_DEV_USER_RE = /^[A-Za-z0-9._][A-Za-z0-9._-]{0,63}$/;
  const PLACEHOLDER_DEV_USER_SET = new Set([
    "__dev_user__",
    "{user}",
    "<user>",
    "replace_with_user",
    "replace_with_username",
  ]);

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
    fileDetailsExpanded: false,
    fileLockExpanded: false,
    selectedLockOs: "linux",
    refModalCliOs: "linux",
    refModalSection: "all",
    refFilterQuery: "",
    activePermBucket: "allow",
    permFilterQuery: "",
    domainFilterQuery: "",
    mcpFilterQuery: "",
    mcpExpandedIndices: null,
    showSecrets: false,
    lastDevUser: initialState.dev_user || "",
    syncSeq: 0,
    activeAbortController: null,
    codeSyncTimer: null,
    formSyncTimer: null,
    pendingCodeSync: null,
    pendingFormSync: null,
    unparsedCodeFiles: {},
    isPointerDownInForm: false,
    deferredFormRender: false,
  };

  /**
   * Validate a workstation username string on the client.
   *
   * @summary Mirrors backend `validate_workstation_username` rules so Step 1 UI
   *   feedback, inline warnings, and download guards give instant feedback.
   * @param {string} rawUser - Candidate workstation username.
   * @returns {string|null} Human-readable error message when invalid, or `null` when valid.
   * @throws {never} Never throws.
   */
  function validateWorkstationUsernameClient(rawUser) {
    const cleaned = String(rawUser ?? "").trim();
    if (!cleaned) {
      return "Workstation Username is required for user-scoped policy files.";
    }
    if (PLACEHOLDER_DEV_USER_SET.has(cleaned.toLowerCase())) {
      return `Replace placeholder '${cleaned}' with the real workstation username.`;
    }
    if (!VALID_DEV_USER_RE.test(cleaned)) {
      return "Username may only contain letters, digits, '.', '_', or '-' (no spaces or slashes).";
    }
    return null;
  }

  /**
   * Compute mandatory workstation username status across currently selected files.
   *
   * @summary Distinguishes machine-wide files (`admin_settings.json`, `antigravity-gateway.env`,
   *   `agy_security_guard.*`) from user-scoped home-directory files (`requires_user === true`).
   * @returns {{required: boolean, devUser: string, userScopedFiles: Array<Object>, isMissing: boolean, isInvalid: boolean, errorMessage: string, isBlocking: boolean}}
   *   Structured username validation state.
   * @throws {never} Never throws.
   */
  function getWorkstationUserState() {
    const devUser = String(AppStore.state.dev_user ?? "").trim();
    const activeIds = AppStore.activeFileIds || [];
    const userScopedFiles = activeIds
      .map((fid) => CATALOG_BY_ID[fid])
      .filter((meta) => Boolean(meta && meta.requires_user));
    const required = userScopedFiles.length > 0;
    const syntaxErr = devUser ? validateWorkstationUsernameClient(devUser) : null;
    const isMissing = !devUser;
    const isInvalid = Boolean(syntaxErr);
    let errorMessage = "";

    if (isInvalid) {
      errorMessage = syntaxErr;
    } else if (required && isMissing) {
      const sampleNames = userScopedFiles.slice(0, 2).map((m) => m.filename);
      const extraCount = userScopedFiles.length - sampleNames.length;
      const suffix = extraCount > 0 ? ` (+${extraCount} more)` : "";
      errorMessage = `Required for ${sampleNames.join(", ")}${suffix}.`;
    }

    return {
      required,
      devUser,
      userScopedFiles,
      isMissing,
      isInvalid,
      errorMessage,
      isBlocking: (required && (isMissing || isInvalid)) || (!required && isInvalid),
    };
  }

  /**
   * Synchronize Step 1 Workstation Username `Required` badge, `.is-invalid` border,
   * and inline `#dev-user-feedback` helper message.
   *
   * @summary Highlights `#input-dev-user` whenever user-scoped files are active
   *   and the username is missing or malformed, while staying neutral for system-only files.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function renderWorkstationUserStatus() {
    const userEl = document.getElementById("input-dev-user");
    const reqBadge = document.getElementById("dev-user-req-badge");
    const feedbackEl = document.getElementById("dev-user-feedback");
    const uState = getWorkstationUserState();

    if (reqBadge) {
      reqBadge.classList.toggle("d-none", !uState.required);
    }
    if (userEl) {
      userEl.required = uState.required;
      userEl.classList.toggle("is-invalid", uState.isBlocking);
    }
    if (feedbackEl) {
      if (uState.isBlocking && uState.errorMessage) {
        feedbackEl.textContent = uState.errorMessage;
        feedbackEl.classList.remove("d-none");
      } else {
        feedbackEl.textContent = "";
        feedbackEl.classList.add("d-none");
      }
    }
  }

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
   * Build `<option>` tags for a `<select>`, preserving unexpected values edited in raw code.
   *
   * @summary Ensures Code -> Form two-way sync always displays custom or invalid enum
   *   values typed in `#code-editor` rather than silently showing the first option.
   * @param {Array<{value: string, label: string}>} options - Standard selectable options.
   * @param {string} currentValue - Current value stored in `AppStore.state`.
   * @returns {string} Joined `<option>` HTML markup.
   * @throws {never} Never throws.
   */
  function renderSelectOptions(options, currentValue) {
    const cur = String(currentValue ?? "");
    const hasMatch = options.some((opt) => opt.value === cur);
    const list = hasMatch
      ? options
      : [...options, { value: cur, label: `${cur || '""'} (Custom in Code)` }];
    return list
      .map(
        (opt) =>
          `<option value="${escapeHtml(opt.value)}" ${opt.value === cur ? "selected" : ""}>${escapeHtml(opt.label)}</option>`
      )
      .join("");
  }

  /**
   * Render a standardized search/filter input box with leading magnifying-glass icon
   * and conditional `×` clear button.
   *
   * @summary Visually distinguishes read-only list search controls from record-creation inputs.
   * @param {string} inputId - DOM `id` attribute for the `<input type="search">` element.
   * @param {string} clearBtnId - DOM `id` attribute for the clear `<button>` element.
   * @param {string} currentValue - Active search query string.
   * @param {string} placeholder - Concise placeholder describing what list is filtered.
   * @returns {string} HTML markup for `.studio-search-wrap`.
   * @throws {never} Never throws.
   */
  function buildSearchBoxHtml(inputId, clearBtnId, currentValue, placeholder) {
    const val = String(currentValue ?? "");
    const hideClear = val ? "" : "d-none";
    return `
      <div class="studio-search-wrap">
        <svg class="studio-search-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true">
          <circle cx="7" cy="7" r="4.75"></circle>
          <line x1="10.5" y1="10.5" x2="14" y2="14"></line>
        </svg>
        <input type="search" id="${escapeHtml(inputId)}" class="form-control form-control-sm studio-search-input" placeholder="${escapeHtml(placeholder)}" value="${escapeHtml(val)}">
        <button type="button" id="${escapeHtml(clearBtnId)}" class="studio-search-clear ${hideClear}" aria-label="Clear search" title="Clear search">&times;</button>
      </div>`;
  }

  /**
   * Generate a guaranteed-unique key or identifier for dictionary/catalog rows.
   *
   * @summary Prevents `+ Add Header`, `+ Add Model`, and `+ Add Server` from
   *   pushing duplicate keys that collapse into a single property inside
   *   Right-Pane JSON objects (`gateway.customHeaders`, `mcpServers`).
   * @param {Array<string>} existingValues - Existing keys or IDs currently in the list.
   * @param {string} preferredFirst - Clean initial key used when not yet present.
   * @param {string} numberedPrefix - Prefix for numbered keys (`X-Custom-Header-`, `corp_server_`).
   * @returns {string} Guaranteed-unique key not present in `existingValues`.
   * @throws {never} Never throws.
   */
  function nextUniqueIdentifier(existingValues, preferredFirst, numberedPrefix) {
    const used = new Set(
      (existingValues || [])
        .map((v) => String(v ?? "").trim().toLowerCase())
        .filter(Boolean)
    );
    if (preferredFirst && !used.has(preferredFirst.toLowerCase())) {
      return preferredFirst;
    }
    let counter = 1;
    while (used.has(`${numberedPrefix}${counter}`.toLowerCase())) {
      counter += 1;
    }
    return `${numberedPrefix}${counter}`;
  }

  /**
   * Highlight duplicate or blank keys in dictionary-backed Left-Pane form rows without re-rendering DOM.
   *
   * @summary Explains immediately why two rows sharing the same key collapse into
   *   one property in JSON objects (`gateway.customHeaders` or `mcpServers`).
   * @param {HTMLElement} container - Left-pane form container.
   * @param {string} inputSelector - CSS selector for key/ID inputs (e.g. `[data-gw-hdr-key]`).
   * @param {string} feedbackId - Element ID of the inline warning box.
   * @param {string} jsonObjectLabel - Human-readable JSON path (e.g. `gateway.customHeaders`).
   * @param {boolean} [caseInsensitive=false] - Whether collisions are case-insensitive (true for HTTP headers).
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function refreshUniqueKeyFeedback(
    container,
    inputSelector,
    feedbackId,
    jsonObjectLabel,
    caseInsensitive = false
  ) {
    const inputs = Array.from(container.querySelectorAll(inputSelector));
    const feedbackEl = container.querySelector(`#${feedbackId}`);
    if (!feedbackEl) {
      return;
    }
    const counts = new Map();
    const displayDupes = [];
    let hasBlank = false;

    inputs.forEach((inp) => {
      const raw = inp.value.trim();
      if (!raw) {
        hasBlank = true;
        return;
      }
      const norm = caseInsensitive ? raw.toLowerCase() : raw;
      counts.set(norm, (counts.get(norm) || 0) + 1);
    });

    const seenDupeNorm = new Set();
    inputs.forEach((inp) => {
      const raw = inp.value.trim();
      const norm = caseInsensitive ? raw.toLowerCase() : raw;
      const isDupe = Boolean(raw) && (counts.get(norm) || 0) > 1;
      const isInvalid = !raw || isDupe;
      inp.classList.toggle("is-invalid", isInvalid);
      const parentMcpCard = inp.closest(".mcp-server-card");
      if (parentMcpCard) {
        parentMcpCard.classList.toggle("has-dup-error", isInvalid);
      }
      if (isDupe && !seenDupeNorm.has(norm)) {
        seenDupeNorm.add(norm);
        displayDupes.push(raw);
      }
    });

    if (displayDupes.length > 0) {
      feedbackEl.textContent = `Duplicate key (${displayDupes.join(", ")}) — JSON "${jsonObjectLabel}" keys must be unique, so duplicate names overwrite earlier rows on the right.`;
      feedbackEl.classList.remove("d-none");
    } else if (hasBlank) {
      feedbackEl.textContent = `Blank key — enter a non-empty name so the row is emitted into "${jsonObjectLabel}" on the right.`;
      feedbackEl.classList.remove("d-none");
    } else {
      feedbackEl.textContent = "";
      feedbackEl.classList.add("d-none");
    }
  }

  /**
   * Resolve and prune the set of expanded MCP server card indices.
   *
   * @summary Defaults to expanded when only 1 MCP server exists, and collapsed
   *   summary rows when 2+ MCP servers exist so admins can scan all servers at a glance.
   * @param {number} totalCount - Total number of MCP servers in `AppStore.state.mcp_servers`.
   * @returns {Set<number>} Mutable set of expanded 0-based server indices.
   * @throws {never} Never throws.
   */
  function getMcpExpandedSet(totalCount) {
    if (!(AppStore.mcpExpandedIndices instanceof Set)) {
      AppStore.mcpExpandedIndices = totalCount === 1 ? new Set([0]) : new Set();
    }
    Array.from(AppStore.mcpExpandedIndices).forEach((idx) => {
      if (!Number.isInteger(idx) || idx < 0 || idx >= totalCount) {
        AppStore.mcpExpandedIndices.delete(idx);
      }
    });
    return AppStore.mcpExpandedIndices;
  }

  /**
   * Format a compact one-line endpoint or executable summary for an MCP server card header.
   *
   * @summary Shows `serverUrl` for Remote HTTP servers or `command args...` for Local stdio servers.
   * @param {Object} srv - MCP server state object.
   * @returns {string} Human-readable summary text for `.mcp-card-summary`.
   * @throws {never} Never throws.
   */
  function formatMcpEndpointSummary(srv) {
    if (!srv) {
      return "";
    }
    if (srv.transport === "http") {
      return String(srv.serverUrl || "").trim() || "(no serverUrl)";
    }
    const cmd = String(srv.command || "").trim() || "(no command)";
    const argsStr = Array.isArray(srv.args) && srv.args.length ? ` ${srv.args.join(" ")}` : "";
    return `${cmd}${argsStr}`;
  }

  /**
   * Compute a compact tool-governance badge summary for an MCP server card header.
   *
   * @summary Surfaces wildcard blocks (`Blocked: *`) or allowed/blocked tool counts even when collapsed.
   * @param {Object} srv - MCP server state object.
   * @returns {{text: string, tone: string}} Pill label and tone (`"warn"`, `"ok"`, `"neutral"`, or `""`).
   * @throws {never} Never throws.
   */
  function formatMcpToolsBadge(srv) {
    const allowLen = Array.isArray(srv?.enabledTools) ? srv.enabledTools.length : 0;
    const denyList = Array.isArray(srv?.disabledTools) ? srv.disabledTools : [];
    if (denyList.includes("*")) {
      return { text: "Blocked: *", tone: "warn" };
    }
    if (allowLen > 0 && denyList.length > 0) {
      return { text: `${allowLen} allow · ${denyList.length} block`, tone: "neutral" };
    }
    if (allowLen > 0) {
      return { text: `${allowLen} allowed`, tone: "ok" };
    }
    if (denyList.length > 0) {
      return { text: `${denyList.length} blocked`, tone: "warn" };
    }
    return { text: "", tone: "" };
  }

  /**
   * Update an MCP server card's header title, endpoint summary, and tool badge in place.
   *
   * @summary Keeps the card header synchronized on every keystroke inside an expanded card
   *   without replacing DOM inputs or losing cursor focus.
   * @param {HTMLElement} container - Left-pane form container element.
   * @param {number} idx - 0-based MCP server index.
   * @param {Object} srv - Updated MCP server state object.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function syncMcpCardHeaderDom(container, idx, srv) {
    if (!container || !srv) {
      return;
    }
    const titleEl = container.querySelector(`[data-mcp-hdr-name="${idx}"]`);
    if (titleEl) {
      titleEl.textContent = String(srv.name || "").trim() || "(unnamed)";
    }
    const summaryEl = container.querySelector(`[data-mcp-hdr-summary="${idx}"]`);
    if (summaryEl) {
      summaryEl.textContent = formatMcpEndpointSummary(srv);
    }
    const toolsEl = container.querySelector(`[data-mcp-hdr-tools="${idx}"]`);
    if (toolsEl) {
      const badge = formatMcpToolsBadge(srv);
      toolsEl.textContent = badge.text;
      toolsEl.className = `mcp-card-tools-pill ${badge.tone ? `tone-${badge.tone}` : "d-none"}`;
    }
  }

  /**
   * Check whether an error came from an intentional `AbortController.abort()` call.
   *
   * @summary Prevents superseded network requests from triggering error toasts.
   * @param {unknown} err - Caught exception object.
   * @returns {boolean} True when the error represents an aborted fetch.
   * @throws {never} Never throws.
   */
  function isAbortError(err) {
    if (!err || typeof err !== "object") {
      return false;
    }
    return err.name === "AbortError" || String(err.message || "").toLowerCase().includes("aborted");
  }

  /**
   * Update the `#sync-status-pill` badge in the Right-Pane editor header.
   *
   * @summary Communicates live synchronization state (`synced`, `syncing`,
   *   `parsing`, or `syntax_error`) accurately to the administrator.
   * @param {"synced"|"syncing"|"parsing"|"syntax_error"} mode - Sync badge mode.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function setSyncPillState(mode) {
    const syncPill = document.getElementById("sync-status-pill");
    if (!syncPill) {
      return;
    }
    if (mode === "syntax_error") {
      syncPill.className = "badge status-badge-warn fw-semibold";
      syncPill.textContent = "Syntax Error — Fix JSON to Sync";
      return;
    }
    syncPill.className = "badge studio-badge-neutral fw-normal";
    if (mode === "syncing") {
      syncPill.textContent = "Syncing...";
    } else if (mode === "parsing") {
      syncPill.textContent = "Parsing...";
    } else {
      syncPill.textContent = "Two-Way Synced";
    }
  }

  /**
   * Refresh `#sync-status-pill` according to whether the selected file has unparsed JSON.
   *
   * @summary Keeps the sync badge accurate when switching between valid and malformed files.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function refreshSyncPillForSelectedFile() {
    if (
      AppStore.selectedFileId &&
      Object.prototype.hasOwnProperty.call(AppStore.unparsedCodeFiles, AppStore.selectedFileId)
    ) {
      setSyncPillState("syntax_error");
    } else {
      setSyncPillState("synced");
    }
  }

  /**
   * Display a concise, theme-consistent notification toast in the bottom-right corner.
   *
   * @summary Uses `.studio-toast` surface tokens with a semantic accent border instead
   *   of hardcoded dark Bootstrap backgrounds so Light and Dark modes stay cohesive.
   * @param {string} message - Notification text to display.
   * @param {string} [variant="info"] - Semantic variant (`"info"`, `"primary"`, `"dark"`, `"success"`, `"warning"`, `"danger"`).
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function showToast(message, variant = "info") {
    const toastEl = document.getElementById("studio-toast");
    const bodyEl = document.getElementById("studio-toast-body");
    if (!toastEl || !bodyEl) {
      return;
    }
    const tone =
      variant === "success" || variant === "warning" || variant === "danger"
        ? variant
        : "info";
    toastEl.className = `toast studio-toast toast-${tone} align-items-center`;
    bodyEl.textContent = message;
    const instance = window.bootstrap.Toast.getOrCreateInstance(toastEl, { delay: 2600 });
    instance.show();
  }

  /**
   * Synchronize Popper fixed-strategy dropdown menu width and max-height with its trigger button.
   *
   * @summary Keeps both `.studio-multiselect-menu` and `.studio-singleselect-menu`
   *   flush with the trigger width (with a readable minimum width on compact controls)
   *   and prevents viewport clipping.
   * @param {HTMLElement|null} toggleBtn - Dropdown trigger button element.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function syncDropdownMenuGeometry(toggleBtn) {
    if (!toggleBtn) {
      return;
    }
    const menu = toggleBtn.parentElement?.querySelector(
      ".studio-multiselect-menu, .studio-singleselect-menu"
    );
    if (!menu) {
      return;
    }
    const isMulti = menu.classList.contains("studio-multiselect-menu");
    const minMenuWidth = isMulti ? 245 : 210;
    const btnRect = toggleBtn.getBoundingClientRect();
    menu.style.width = `${Math.max(Math.round(btnRect.width), minMenuWidth)}px`;
    const topbarHeight = document.querySelector(".studio-topbar")?.offsetHeight || 56;
    const spaceBelow = window.innerHeight - btnRect.bottom - 16;
    const spaceAbove = btnRect.top - topbarHeight - 12;
    const bestSpace = Math.max(spaceBelow, spaceAbove, 220);
    menu.style.maxHeight = `${Math.round(bestSpace)}px`;
  }

  /**
   * Split an option label on `" — "` into primary title and secondary subtitle text.
   *
   * @summary Renders descriptive options cleanly on two lines inside `.studio-singleselect-menu`,
   *   matching the visual hierarchy of `.studio-multiselect-menu`.
   * @param {string} rawText - Full option display text.
   * @returns {{title: string, sub: string}} Parsed title and optional subtitle.
   * @throws {never} Never throws.
   */
  function splitOptionTitleAndSub(rawText) {
    const clean = String(rawText || "").trim();
    const sepIdx = clean.indexOf(" — ");
    if (sepIdx > 0) {
      return {
        title: clean.slice(0, sepIdx).trim(),
        sub: clean.slice(sepIdx + 3).trim(),
      };
    }
    return { title: clean, sub: "" };
  }

  /**
   * Refresh the visible `.studio-singleselect-btn` label, placeholder styling, and active row state.
   *
   * @summary Synchronizes the custom button with `selectEl.selectedIndex` and `selectEl.disabled`.
   * @param {HTMLSelectElement} selectEl - Underlying `<select>` element.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function refreshSingleSelectDisplay(selectEl) {
    const wrap = selectEl?._studioDropdownWrap;
    if (!wrap) {
      return;
    }
    const btn = wrap.querySelector(".studio-singleselect-btn");
    const labelSpan = btn?.querySelector(".ss-label");
    const menu = wrap.querySelector(".studio-singleselect-menu");
    if (!btn || !labelSpan) {
      return;
    }

    btn.disabled = Boolean(selectEl.disabled);
    const selIdx = selectEl.selectedIndex;
    const selOpt = selIdx >= 0 ? selectEl.options[selIdx] : selectEl.options[0];
    const text = selOpt ? selOpt.textContent.trim() : "";
    labelSpan.textContent = text;

    const isPlaceholderOpt =
      Boolean(selOpt) && selOpt.value === "" && text.endsWith("...");
    btn.classList.toggle("is-placeholder", isPlaceholderOpt);

    if (menu) {
      menu.querySelectorAll(".ss-option-row").forEach((row) => {
        const idx = Number(row.dataset.optionIndex);
        const active = idx === selIdx;
        row.classList.toggle("is-selected", active);
        row.setAttribute("aria-selected", String(active));
      });
    }
  }

  /**
   * Populate `<optgroup>` section headers and `.ss-option-row` items inside a custom single-select menu.
   *
   * @summary Mirrors `selectEl` children (`<optgroup>` and `<option>`) into theme-consistent
   *   Bootstrap dropdown DOM rows with zero native OS popup rendering.
   * @param {HTMLSelectElement} selectEl - Underlying `<select>` element.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function buildSingleSelectMenuItems(selectEl) {
    const wrap = selectEl?._studioDropdownWrap;
    if (!wrap) {
      return;
    }
    const btn = wrap.querySelector(".studio-singleselect-btn");
    const menu = wrap.querySelector(".studio-singleselect-menu");
    if (!btn || !menu) {
      return;
    }

    const allOptions = Array.from(selectEl.options);
    const selIdx = selectEl.selectedIndex;
    let html = "";
    let renderedAnyGroup = false;

    const renderOptionButton = (optEl) => {
      const optIndex = allOptions.indexOf(optEl);
      const isSelected = optIndex === selIdx;
      const parsed = splitOptionTitleAndSub(optEl.textContent);
      const title = parsed.title;
      const sub = (optEl.dataset.optionSub || parsed.sub || "").trim();
      const subHtml = sub ? `<div class="ss-option-sub">${escapeHtml(sub)}</div>` : "";
      return `
        <button type="button" class="ss-option-row ${isSelected ? "is-selected" : ""}" role="option" aria-selected="${isSelected}" data-option-index="${optIndex}" ${optEl.disabled ? "disabled" : ""}>
          <div class="ss-option-text-wrap">
            <div class="ss-option-title">${escapeHtml(title)}</div>
            ${subHtml}
          </div>
          <span class="ss-check-icon" aria-hidden="true">&#10003;</span>
        </button>`;
    };

    Array.from(selectEl.children).forEach((child) => {
      if (child.tagName === "OPTGROUP") {
        if (renderedAnyGroup) {
          html += `<div class="ss-group-divider" role="separator"></div>`;
        }
        renderedAnyGroup = true;
        const grpLabel = child.getAttribute("label") || "";
        if (grpLabel) {
          html += `<div class="ss-group-header">${escapeHtml(grpLabel)}</div>`;
        }
        Array.from(child.children).forEach((opt) => {
          if (opt.tagName === "OPTION") {
            html += renderOptionButton(opt);
          }
        });
      } else if (child.tagName === "OPTION") {
        html += renderOptionButton(child);
      }
    });

    menu.innerHTML = html;
    menu.querySelectorAll(".ss-option-row").forEach((row) => {
      row.addEventListener("click", (ev) => {
        ev.preventDefault();
        const optIndex = Number(row.dataset.optionIndex);
        if (Number.isNaN(optIndex) || optIndex < 0 || optIndex >= selectEl.options.length) {
          return;
        }
        try {
          window.bootstrap.Dropdown.getOrCreateInstance(btn).hide();
        } catch {
          // Safe guard if dropdown instance was already disposed
        }
        if (selectEl.selectedIndex !== optIndex) {
          selectEl.selectedIndex = optIndex;
          selectEl.dispatchEvent(new Event("change", { bubbles: true }));
        }
        if (selectEl.isConnected) {
          refreshSingleSelectDisplay(selectEl);
        }
      });
    });
  }

  /**
   * Upgrade all `<select class="form-select">` elements within `root` into custom
   * white-surface `.dropdown.studio-singleselect` components.
   *
   * @summary Eliminates native macOS/Windows dark OS `<select>` popups while keeping
   *   every `<select>` ID, `.value`, and `change` listener 100% compatible.
   * @param {Document|HTMLElement} [root=document] - Container scope to scan and sync.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function syncStudioSingleSelects(root = document) {
    if (!root) {
      return;
    }
    const selects = [];
    if (root instanceof HTMLSelectElement && root.classList.contains("form-select")) {
      selects.push(root);
    } else if (typeof root.querySelectorAll === "function") {
      root.querySelectorAll("select.form-select").forEach((el) => selects.push(el));
    }

    selects.forEach((selectEl) => {
      selectEl.classList.add("studio-native-select-hidden");

      if (!selectEl._studioDropdownWrap || !selectEl._studioDropdownWrap.isConnected) {
        const wrap = document.createElement("div");
        wrap.className = "dropdown studio-singleselect";
        ["width", "minWidth", "maxWidth", "flex"].forEach((prop) => {
          if (selectEl.style[prop]) {
            wrap.style[prop] = selectEl.style[prop];
          }
        });

        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "studio-singleselect-btn dropdown-toggle";
        if (selectEl.classList.contains("studio-select-compact")) {
          btn.classList.add("is-compact");
        }
        if (selectEl.classList.contains("mono-input")) {
          btn.classList.add("mono-input");
        }
        if (selectEl.id) {
          btn.id = `${selectEl.id}DropdownBtn`;
          btn.dataset.singleSelectFor = selectEl.id;
        }
        if (selectEl.hasAttribute("data-mcp-transport")) {
          btn.dataset.mcpTransportBtn = selectEl.getAttribute("data-mcp-transport");
        }
        btn.setAttribute("data-bs-toggle", "dropdown");
        btn.setAttribute("data-bs-popper-config", '{"strategy":"fixed"}');
        btn.setAttribute("aria-expanded", "false");
        btn.setAttribute("aria-haspopup", "listbox");
        btn.innerHTML = '<span class="ss-label"></span>';

        const menu = document.createElement("div");
        menu.className = "dropdown-menu studio-singleselect-menu";
        menu.setAttribute("role", "listbox");
        if (btn.id) {
          menu.setAttribute("aria-labelledby", btn.id);
        }

        wrap.appendChild(btn);
        wrap.appendChild(menu);
        selectEl.insertAdjacentElement("afterend", wrap);
        selectEl._studioDropdownWrap = wrap;

        wrap.addEventListener("show.bs.dropdown", () => {
          buildSingleSelectMenuItems(selectEl);
          refreshSingleSelectDisplay(selectEl);
          syncDropdownMenuGeometry(btn);
        });
        wrap.addEventListener("shown.bs.dropdown", () => {
          syncDropdownMenuGeometry(btn);
          const activeRow = menu.querySelector(".ss-option-row.is-selected");
          activeRow?.scrollIntoView({ block: "nearest" });
        });

        if (!selectEl._studioChangeSynced) {
          selectEl._studioChangeSynced = true;
          selectEl.addEventListener("change", () => {
            refreshSingleSelectDisplay(selectEl);
          });
        }

        if (selectEl.id) {
          const assocLabel = document.querySelector(`label[for="${CSS.escape(selectEl.id)}"]`);
          if (assocLabel && !assocLabel.dataset.ssLabelBound) {
            assocLabel.dataset.ssLabelBound = "1";
            assocLabel.addEventListener("click", (ev) => {
              const curBtn = selectEl._studioDropdownWrap?.querySelector(".studio-singleselect-btn");
              if (curBtn && !curBtn.disabled) {
                ev.preventDefault();
                curBtn.focus();
                window.bootstrap.Dropdown.getOrCreateInstance(curBtn).toggle();
              }
            });
          }
        }
      }

      buildSingleSelectMenuItems(selectEl);
      refreshSingleSelectDisplay(selectEl);
    });
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
   * @summary Wrapper around `fetch` supporting `AbortSignal` and structured error messages.
   * @param {string} url - API endpoint path (e.g., `/api/compile`).
   * @param {Object} payload - Serializable request body object.
   * @param {Object} [fetchOptions={}] - Optional fetch overrides such as `{ signal }`.
   * @returns {Promise<Object>} Parsed JSON response payload.
   * @throws {Error} Throws descriptive Error when HTTP status is non-2xx or aborted.
   */
  async function postJson(url, payload, fetchOptions = {}) {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      ...fetchOptions,
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
        html += `<option value="${escapeHtml(p.id)}" data-option-sub="${escapeHtml(p.description || "")}" ${sel}>${escapeHtml(p.label)}</option>`;
      });
      html += "</optgroup>";
    });
    selectEl.innerHTML = html;
    syncStudioSingleSelects(selectEl);
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
   *   Reference Card, form controls, live code editor, and validation drawer
   *   while preserving any other file's unparsed raw JSON edits.
   * @param {Object} payload - Compiled payload returned by `/api/*`.
   * @param {Object} [options={}] - Rendering flags (`skipEditor`, `skipForm`,
   *   `autoSelectFiles`, `preserveFormFocus`, `resetUnparsed`).
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function applyServerPayload(payload, options = {}) {
    if (options.resetUnparsed) {
      AppStore.unparsedCodeFiles = {};
      AppStore.mcpExpandedIndices = null;
    }

    AppStore.state = payload.state;
    AppStore.lastDevUser = (payload.state && payload.state.dev_user) || "";
    AppStore.availableFileIds = payload.available_file_ids || [];
    AppStore.activeFileIds = payload.active_file_ids || [];

    const nextFiles = { ...(payload.files || {}) };
    Object.keys(AppStore.unparsedCodeFiles).forEach((dirtyFid) => {
      if (Object.prototype.hasOwnProperty.call(nextFiles, dirtyFid)) {
        nextFiles[dirtyFid] = AppStore.unparsedCodeFiles[dirtyFid];
      } else {
        delete AppStore.unparsedCodeFiles[dirtyFid];
      }
    });
    AppStore.files = nextFiles;

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
   * @param {Object} [options={}] - Optional `{skipForm, skipEditor, preserveFormFocus}` flags.
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
      if (options.deferFormIfPointerDown && AppStore.isPointerDownInForm) {
        // Defer innerHTML replacement while mouse/pointer is pressed inside the form
        // so mousedown -> mouseup -> click on [x] or + Add buttons is never aborted.
        AppStore.deferredFormRender = true;
      } else {
        renderActiveFormPanel(Boolean(options.preserveFormFocus));
      }
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
    const q = String(AppStore.refFilterQuery ?? "").trim().toLowerCase();
    const rawUser = String(AppStore.state.dev_user ?? "").trim();
    const u = rawUser || UNSET_USER_TOKEN;
    const userCaptionVal = rawUser || "<unset>";

    const secOs = document.getElementById("ref-sec-os");
    const secVer = document.getElementById("ref-sec-versions");
    const secFiles = document.getElementById("ref-sec-files");
    const cliOsWrap = document.getElementById("ref-cli-os-wrap");
    const refSearchInput = document.getElementById("input-ref-search");
    const refClearBtn = document.getElementById("btn-clear-ref-search");

    const showTable3 = secFilter === "all" || secFilter === "files";
    if (secOs) {
      secOs.classList.toggle("d-none", secFilter !== "all" && secFilter !== "os");
    }
    if (secVer) {
      secVer.classList.toggle("d-none", secFilter !== "all" && secFilter !== "versions");
    }
    if (secFiles) {
      secFiles.classList.toggle("d-none", !showTable3);
    }
    if (cliOsWrap) {
      cliOsWrap.classList.toggle("d-none", !showTable3);
    }
    if (refSearchInput && document.activeElement !== refSearchInput) {
      refSearchInput.value = AppStore.refFilterQuery || "";
    }
    if (refClearBtn) {
      refClearBtn.classList.toggle("d-none", !q);
    }

    const userCap = document.getElementById("ref-files-user-caption");
    if (userCap) {
      userCap.textContent = `Paths & CLI templated for OS: ${OS_DISPLAY[cliOs] || cliOs} · Workstation User: ${userCaptionVal}`;
    }

    // Table 1: Minimum OS Requirements
    const tbodyOs = document.getElementById("tbody-ref-os");
    if (tbodyOs) {
      const osRows = (REFERENCE_DATA.os_requirements || []).filter((row) => {
        if (!q) {
          return true;
        }
        const hay = `${row.os} ${row.min_version} ${row.architectures} ${row.hardware_runtime} ${row.sandbox_lock}`.toLowerCase();
        return hay.includes(q);
      });
      tbodyOs.innerHTML = osRows.length
        ? osRows
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
            .join("")
        : `<tr><td colspan="5" class="text-body-secondary small py-2 text-center">No OS requirement rows match "${escapeHtml(AppStore.refFilterQuery)}".</td></tr>`;
    }

    // Table 2: Minimum Antigravity Versions
    const tbodyVer = document.getElementById("tbody-ref-versions");
    if (tbodyVer) {
      const verRows = (REFERENCE_DATA.version_requirements || []).filter((row) => {
        if (!q) {
          return true;
        }
        const hay = `${row.surface} ${row.min_version} ${row.platforms_protocols} ${row.notes}`.toLowerCase();
        return hay.includes(q);
      });
      tbodyVer.innerHTML = verRows.length
        ? verRows
            .map(
              (row) => `
              <tr>
                <td class="fw-semibold">${escapeHtml(row.surface)}</td>
                <td><span class="badge studio-badge-neutral text-wrap text-start fw-semibold" style="font-size: 0.72rem;">${escapeHtml(row.min_version)}</span></td>
                <td>${escapeHtml(row.platforms_protocols)}</td>
                <td>${escapeHtml(row.notes)}</td>
                <td>
                  <a href="${escapeHtml(row.doc_url)}" target="_blank" rel="noopener noreferrer" class="text-decoration-none fw-medium text-nowrap">
                    ${escapeHtml(row.doc_label || "Docs")} &#8599;
                  </a>
                </td>
              </tr>`
            )
            .join("")
        : `<tr><td colspan="5" class="text-body-secondary small py-2 text-center">No surface version rows match "${escapeHtml(AppStore.refFilterQuery)}".</td></tr>`;
    }

    // Table 3: Canonical Files, Purpose, Is Mandatory, Admin CLI & Public Docs
    const tbodyFiles = document.getElementById("tbody-ref-files");
    if (tbodyFiles) {
      const fileItems = CATALOG.filter((item) => {
        if (!q) {
          return true;
        }
        const rawPath = item.paths && item.paths[cliOs] ? item.paths[cliOs].replace(/\{user\}/g, u) : "";
        const surfacesText = (item.surface_details || item.surfaces).join(" ");
        const hay = `${item.short_label} ${item.filename} ${item.group_title} ${rawPath} ${surfacesText} ${item.summary} ${item.mandatory_status || ""} ${item.mandatory_note || ""}`.toLowerCase();
        return hay.includes(q);
      });

      tbodyFiles.innerHTML = fileItems.length
        ? fileItems
            .map((item) => {
              const rawPath = item.paths && item.paths[cliOs] ? item.paths[cliOs].replace(/\{user\}/g, u) : "";
              const primaryPath = rawPath ? rawPath.split("  (")[0].trim() : "";
              const cliBlock = AppStore.allFilesCli?.[item.id]?.[cliOs]?.lock || "";
              const surfacesText = (item.surface_details || item.surfaces).join(", ");
              const badgeVariant = item.mandatory_variant || "secondary";
              const badgeClass =
                badgeVariant === "secondary"
                  ? "studio-badge-neutral"
                  : badgeVariant === "primary"
                    ? "studio-badge-primary"
                    : `text-bg-${escapeHtml(badgeVariant)}`;
              const badgeText = item.mandatory_status || "Optional";

              const pathHtml = rawPath
                ? `<div class="mt-1 d-flex align-items-start justify-content-between gap-1">
                     <code class="text-break" style="font-size: 0.7rem;">${escapeHtml(rawPath)}</code>
                     <button type="button" class="btn btn-sm btn-outline-secondary py-0 px-1 flex-shrink-0" style="font-size: 0.66rem; height: 20px;" data-ref-copy-path="${escapeHtml(primaryPath)}">Copy</button>
                   </div>`
                : `<div class="mt-1"><span class="badge studio-badge-neutral">Not used on ${escapeHtml(OS_DISPLAY[cliOs] || cliOs)}</span></div>`;

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
                    <span class="badge ${badgeClass} mb-1">${escapeHtml(badgeText)}</span>
                    <div class="text-body-secondary" style="font-size: 0.71rem; line-height: 1.3;">${escapeHtml(item.mandatory_note || "")}</div>
                  </td>
                  <td>${cliHtml}</td>
                  <td>
                    <a href="${escapeHtml(item.doc_url)}" target="_blank" rel="noopener noreferrer" class="text-decoration-none fw-medium" style="font-size: 0.74rem;">
                      Public Docs &#8599;
                    </a>
                  </td>
                </tr>`;
            })
            .join("")
        : `<tr><td colspan="6" class="text-body-secondary small py-2 text-center">No configuration file rows match "${escapeHtml(AppStore.refFilterQuery)}".</td></tr>`;

      tbodyFiles.querySelectorAll("[data-ref-copy-path]").forEach((btn) => {
        btn.addEventListener("click", () => {
          navigator.clipboard?.writeText(btn.dataset.refCopyPath);
          showToast(`Copied path: ${btn.dataset.refCopyPath}`, "info");
        });
      });

      tbodyFiles.querySelectorAll("[data-ref-copy-cli]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const fid = btn.dataset.refCopyCli;
          const cmd = AppStore.allFilesCli?.[fid]?.[cliOs]?.lock || "";
          if (cmd) {
            navigator.clipboard?.writeText(cmd);
            showToast(`Copied ${OS_DISPLAY[cliOs]} Admin CLI for ${CATALOG_BY_ID[fid]?.filename || fid}`, "info");
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
      userEl.value = AppStore.state.dev_user || "";
    }
    renderWorkstationUserStatus();

    const syncSelect = document.getElementById("select-perm-sync");
    if (syncSelect) {
      syncSelect.value = AppStore.state.sync_permissions ? "linked" : "separate";
      syncStudioSingleSelects(syncSelect);
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
      renderWorkstationUserStatus();
      return;
    }

    const presetEl = document.getElementById("preset-selector");
    if (presetEl && AppStore.state.active_preset) {
      presetEl.value = AppStore.state.active_preset;
      syncStudioSingleSelects(presetEl);
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
        filesLbl.textContent = "All Matching Files Selected";
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
        chk.addEventListener("change", async () => {
          const fid = chk.dataset.fileCheck;
          const isNowChecked = chk.checked;
          await flushPendingSync();
          const curAvail = AppStore.availableFileIds || [];
          const curSet = new Set(AppStore.state.selected_file_ids || []);
          if (isNowChecked) {
            curSet.add(fid);
            AppStore.selectedFileId = fid;
          } else {
            curSet.delete(fid);
            delete AppStore.unparsedCodeFiles[fid];
          }
          AppStore.state.selected_file_ids = curAvail.filter((id) => curSet.has(id));
          scheduleFormCompile(true, { keepCurrentUnparsed: true });
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
        syncStudioSingleSelects(activeSelect);
      }
    }
    renderWorkstationUserStatus();
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

    const u = String(AppStore.state.dev_user ?? "").trim() || UNSET_USER_TOKEN;

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
          showToast(`Copied path: ${btn.dataset.copyTargetPath}`, "info");
        });
      });
    }

    // Collapsible File Details (Purpose, Used by Surfaces & Target Paths)
    const detailsBox = document.getElementById("section-box-file-details");
    const detailsBody = document.getElementById("file-details-body");
    const detailsToggleBtn = document.getElementById("btn-toggle-file-details");
    const detailsChevron = document.getElementById("file-details-chevron");
    if (detailsBody && detailsToggleBtn && detailsChevron) {
      detailsBody.classList.toggle("d-none", !AppStore.fileDetailsExpanded);
      detailsToggleBtn.setAttribute("aria-expanded", String(AppStore.fileDetailsExpanded));
      detailsChevron.innerHTML = AppStore.fileDetailsExpanded ? "&#9652; Hide" : "&#9662; Show";
      detailsBox?.classList.toggle("is-expanded", AppStore.fileDetailsExpanded);
    }

    // Collapsible Per-File Manual Permissions & Lock / Unlock Commands
    const lockBox = document.getElementById("section-box-file-lock");
    const lockBody = document.getElementById("file-lock-cli-body");
    const toggleBtn = document.getElementById("btn-toggle-file-lock-cli");
    const chevron = document.getElementById("file-lock-chevron");
    if (lockBody && toggleBtn && chevron) {
      lockBody.classList.toggle("d-none", !AppStore.fileLockExpanded);
      toggleBtn.setAttribute("aria-expanded", String(AppStore.fileLockExpanded));
      chevron.innerHTML = AppStore.fileLockExpanded ? "&#9652; Hide" : "&#9662; Show";
      lockBox?.classList.toggle("is-expanded", AppStore.fileLockExpanded);
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
        syncStudioSingleSelects(osSelect);
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
   * Execute an ordered `/api/compile` call and discard stale out-of-order responses.
   *
   * @summary Sends structured `AppStore.state` to `/api/compile` under `reqSeq`
   *   and `AbortController` protection so rapid form edits never overwrite newer input.
   * @param {boolean} reRenderForm - Whether to re-render the left form container.
   * @param {number} reqSeq - Monotonic sequence token captured when scheduled.
   * @returns {Promise<void>} Resolves once compilation finishes or is superseded.
   * @throws {never} Errors are surfaced via toast unless aborted.
   */
  async function executeFormCompile(reRenderForm, reqSeq) {
    if (reqSeq !== AppStore.syncSeq) {
      return;
    }
    AppStore.activeAbortController?.abort();
    const controller = new AbortController();
    AppStore.activeAbortController = controller;
    const stateSnapshot = JSON.parse(JSON.stringify(AppStore.state));

    try {
      const res = await postJson(
        "/api/compile",
        { state: stateSnapshot },
        { signal: controller.signal }
      );
      // Drop out-of-order response if user typed newer characters while in flight
      if (reqSeq !== AppStore.syncSeq) {
        return;
      }
      applyServerPayload(res, {
        skipForm: !reRenderForm,
        skipEditor: false,
        preserveFormFocus: true,
        deferFormIfPointerDown: true,
      });
      refreshSyncPillForSelectedFile();
    } catch (err) {
      if (!isAbortError(err)) {
        showToast(err.message, "danger");
      }
    }
  }

  /**
   * Trigger a debounced `/api/compile` call after left-pane scope or form edits.
   *
   * @summary Cancels any pending code-sync timer, increments `AppStore.syncSeq`,
   *   and compiles structured form state into right-pane raw code + validation.
   * @param {boolean} [reRenderForm=false] - Whether to re-render left form DOM.
   * @param {Object} [opts={}] - Optional `{ keepCurrentUnparsed }` flag when only scope changed.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function scheduleFormCompile(reRenderForm = false, opts = {}) {
    clearTimeout(AppStore.codeSyncTimer);
    AppStore.codeSyncTimer = null;
    AppStore.pendingCodeSync = null;

    if (!opts.keepCurrentUnparsed && AppStore.selectedFileId) {
      delete AppStore.unparsedCodeFiles[AppStore.selectedFileId];
    }

    AppStore.activeAbortController?.abort();
    const reqSeq = ++AppStore.syncSeq;
    AppStore.pendingFormSync = { reRenderForm: Boolean(reRenderForm), seq: reqSeq };
    setSyncPillState("syncing");

    clearTimeout(AppStore.formSyncTimer);
    AppStore.formSyncTimer = setTimeout(async () => {
      AppStore.formSyncTimer = null;
      AppStore.pendingFormSync = null;
      await executeFormCompile(reRenderForm, reqSeq);
    }, 80);
  }

  /**
   * Detect which permission grant bucket (`allow`, `ask`, or `deny`) changed during a raw code edit.
   *
   * @summary Auto-switches `AppStore.activePermBucket` when a user edits a non-active
   *   permission array in `#code-editor` so the Left Form immediately displays the change.
   * @param {Object} prevPerms - Previous `{allow, ask, deny}` arrays.
   * @param {Object} nextPerms - Newly parsed `{allow, ask, deny}` arrays.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function syncActivePermBucketOnCodeEdit(prevPerms, nextPerms) {
    if (!prevPerms || !nextPerms) {
      return;
    }
    const cur = AppStore.activePermBucket || "allow";
    const sameBucket = (b) =>
      JSON.stringify(prevPerms[b] || []) === JSON.stringify(nextPerms[b] || []);

    let targetBucket = cur;
    if (sameBucket(cur)) {
      const changed = ["allow", "ask", "deny"].find((b) => !sameBucket(b));
      if (changed) {
        targetBucket = changed;
        AppStore.activePermBucket = changed;
      }
    }

    if (AppStore.permFilterQuery.trim()) {
      const q = AppStore.permFilterQuery.trim().toLowerCase();
      const bucketRules = Array.isArray(nextPerms[targetBucket]) ? nextPerms[targetBucket] : [];
      if (bucketRules.length > 0 && !bucketRules.some((r) => String(r).toLowerCase().includes(q))) {
        AppStore.permFilterQuery = "";
      }
    }
  }

  /**
   * Execute an ordered `/api/sync-code` request for a specific `editedFileId` and `rawContent`.
   *
   * @summary Parses raw right-pane edits into `AppStore.state`, updates left-pane
   *   form controls, and marks mid-edit JSON syntax errors explicitly without
   *   clobbering active typing or falsely reporting `"Two-Way Synced"`.
   * @param {string} editedFileId - File ID captured at the exact moment of the edit.
   * @param {string} rawContent - Raw text content captured from `#code-editor`.
   * @param {number} reqSeq - Monotonic sequence token captured when scheduled.
   * @returns {Promise<void>} Resolves once synchronization completes or is superseded.
   * @throws {never} Errors are surfaced via toast unless aborted.
   */
  async function executeCodeSync(editedFileId, rawContent, reqSeq) {
    if (!editedFileId || reqSeq !== AppStore.syncSeq) {
      return;
    }
    AppStore.activeAbortController?.abort();
    const controller = new AbortController();
    AppStore.activeAbortController = controller;

    const prevCliPerms = JSON.parse(JSON.stringify(AppStore.state.cli?.permissions || {}));
    const prevDeskPerms = JSON.parse(JSON.stringify(AppStore.state.desktop?.permissions || {}));

    try {
      const res = await postJson(
        "/api/sync-code",
        {
          file_id: editedFileId,
          content: rawContent,
          state: AppStore.state,
        },
        { signal: controller.signal }
      );
      if (reqSeq !== AppStore.syncSeq) {
        return;
      }

      if (res.code_synced === false) {
        AppStore.unparsedCodeFiles[editedFileId] = rawContent;
        applyServerPayload(res, { skipEditor: true, skipForm: true });
        refreshSyncPillForSelectedFile();
        return;
      }

      delete AppStore.unparsedCodeFiles[editedFileId];
      if (editedFileId === "cli_settings") {
        syncActivePermBucketOnCodeEdit(prevCliPerms, res.state?.cli?.permissions);
      } else if (editedFileId === "desktop_config") {
        const nextDeskPerms = res.state?.sync_permissions
          ? res.state?.cli?.permissions
          : res.state?.desktop?.permissions;
        syncActivePermBucketOnCodeEdit(prevDeskPerms, nextDeskPerms);
      }

      const stillViewingEditedFile = AppStore.selectedFileId === editedFileId;
      applyServerPayload(res, {
        skipEditor: stillViewingEditedFile,
        skipForm: false,
        preserveFormFocus: true,
        deferFormIfPointerDown: true,
      });
      refreshSyncPillForSelectedFile();
    } catch (err) {
      if (!isAbortError(err)) {
        showToast(err.message, "danger");
      }
    }
  }

  /**
   * Schedule a debounced `/api/sync-code` call after typing in `#code-editor`.
   *
   * @summary Captures `editedFileId` and `rawContent` eagerly at keystroke time so
   *   switching files within the debounce window never cross-contaminates files.
   * @param {string} editedFileId - Active file ID being edited in `#code-editor`.
   * @param {string} rawContent - Updated text value of `#code-editor`.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function scheduleCodeSync(editedFileId, rawContent) {
    if (!editedFileId) {
      return;
    }
    clearTimeout(AppStore.formSyncTimer);
    AppStore.formSyncTimer = null;
    AppStore.pendingFormSync = null;

    AppStore.activeAbortController?.abort();
    const reqSeq = ++AppStore.syncSeq;
    AppStore.pendingCodeSync = {
      fileId: editedFileId,
      content: rawContent,
      seq: reqSeq,
    };
    setSyncPillState("parsing");

    clearTimeout(AppStore.codeSyncTimer);
    AppStore.codeSyncTimer = setTimeout(async () => {
      AppStore.codeSyncTimer = null;
      AppStore.pendingCodeSync = null;
      await executeCodeSync(editedFileId, rawContent, reqSeq);
    }, 160);
  }

  /**
   * Immediately flush any debounced code-sync or form-compile operation before
   * switching files, running Auto-Fix, or exporting bundles.
   *
   * @summary Guarantees zero lost edits when the user acts faster than the debounce timer.
   * @returns {Promise<void>} Resolves once any pending sync request finishes.
   * @throws {never} Never throws.
   */
  async function flushPendingSync() {
    if (AppStore.codeSyncTimer) {
      clearTimeout(AppStore.codeSyncTimer);
      AppStore.codeSyncTimer = null;
    }
    if (AppStore.pendingCodeSync) {
      const pending = AppStore.pendingCodeSync;
      AppStore.pendingCodeSync = null;
      await executeCodeSync(pending.fileId, pending.content, pending.seq);
    }

    if (AppStore.formSyncTimer) {
      clearTimeout(AppStore.formSyncTimer);
      AppStore.formSyncTimer = null;
    }
    if (AppStore.pendingFormSync) {
      const pendingForm = AppStore.pendingFormSync;
      AppStore.pendingFormSync = null;
      await executeFormCompile(pendingForm.reRenderForm, pendingForm.seq);
    }
  }

  /**
   * Capture focus and text-cursor selection inside `#form-panel-container` prior to re-render.
   *
   * @summary Prevents left-pane DOM refreshes from dropping keyboard focus or cursor offset.
   * @param {HTMLElement} container - Left-pane form container element.
   * @returns {Object|null} Snapshot of focused control selector and selection range, or null.
   * @throws {never} Never throws.
   */
  function captureFormFocus(container) {
    const active = document.activeElement;
    if (!active || !container.contains(active)) {
      return null;
    }
    let selector = null;
    if (active.id) {
      selector = `#${CSS.escape(active.id)}`;
    } else {
      const dataAttrs = [
        "data-gw-hdr-key",
        "data-gw-hdr-val",
        "data-gw-mdl-id",
        "data-gw-mdl-name",
        "data-mcp-name",
        "data-mcp-transport",
        "data-mcp-url",
        "data-mcp-cmd",
        "data-mcp-args",
        "data-mcp-timeout",
        "data-mcp-allow",
        "data-mcp-deny",
      ];
      for (const attr of dataAttrs) {
        if (active.hasAttribute(attr)) {
          selector = `[${attr}="${CSS.escape(active.getAttribute(attr))}"]`;
          break;
        }
      }
    }
    if (!selector) {
      return null;
    }
    let selStart = null;
    let selEnd = null;
    try {
      if (typeof active.selectionStart === "number") {
        selStart = active.selectionStart;
        selEnd = active.selectionEnd;
      }
    } catch {
      // Input types such as `number` do not support selectionStart in Chromium
    }
    return { selector, selStart, selEnd };
  }

  /**
   * Restore focus and cursor selection inside `#form-panel-container` after re-render.
   *
   * @summary Re-focuses the matching form input without scrolling the viewport.
   * @param {HTMLElement} container - Left-pane form container element.
   * @param {Object|null} snapshot - Snapshot returned by `captureFormFocus`.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function restoreFormFocus(container, snapshot) {
    if (!snapshot || !snapshot.selector) {
      return;
    }
    const nextEl = container.querySelector(snapshot.selector);
    if (!nextEl || nextEl.disabled) {
      return;
    }
    nextEl.focus({ preventScroll: true });
    if (snapshot.selStart !== null && snapshot.selEnd !== null) {
      try {
        nextEl.setSelectionRange(snapshot.selStart, snapshot.selEnd);
      } catch {
        // Ignore input types that disallow programmatic selection ranges
      }
    }
  }

  /**
   * Render the Permission Rule Chip Builder (`allow` / `ask` / `deny`) HTML
   * with a 1-click segmented bucket switcher, dedicated rule composer box,
   * and attached searchable rule list panel.
   *
   * @summary Shared component used by CLI `settings.json` and Desktop `config.json`.
   * @param {string} targetScope - Either `"cli"` or `"desktop"`.
   * @param {Object} permsObj - Object containing `allow`, `ask`, and `deny` arrays.
   * @returns {string} HTML string for the permission rule manager.
   * @throws {never} Never throws.
   */
  function buildPermissionsWidgetHtml(targetScope, permsObj) {
    const bucket = AppStore.activePermBucket || "allow";
    const bucketMetaMap = {
      allow: { title: "Allow Grants", short: "Allow" },
      ask: { title: "Ask / Review", short: "Ask" },
      deny: { title: "Deny / Block", short: "Deny" },
    };
    const bucketMeta = bucketMetaMap[bucket] || bucketMetaMap.allow;
    const allRules = Array.isArray(permsObj[bucket]) ? permsObj[bucket] : [];
    const rawQuery = String(AppStore.permFilterQuery ?? "").trim();
    const q = rawQuery.toLowerCase();
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

    const emptyRulesHtml = q
      ? `<div class="text-body-secondary small p-2 d-flex align-items-center flex-wrap gap-2">
           <span>No ${escapeHtml(bucketMeta.short.toLowerCase())} rules match "<strong>${escapeHtml(rawQuery)}</strong>".</span>
           <button type="button" class="btn btn-sm btn-link p-0 text-decoration-none" id="btn-empty-clear-perm-search">Clear search</button>
         </div>`
      : `<div class="text-body-secondary small p-2">No ${escapeHtml(bucketMeta.short.toLowerCase())} rules configured yet. Add one above.</div>`;

    const chipsHtml = filtered.length
      ? filtered
          .map(
            (item) => `
          <span class="rule-chip">
            <span>${escapeHtml(item.r)}</span>
            <button type="button" class="rule-chip-remove" data-remove-rule-idx="${item.idx}" aria-label="Remove rule" title="Remove rule">&times;</button>
          </span>`
          )
          .join("")
      : emptyRulesHtml;

    const listCountText = q
      ? `Showing ${filtered.length} of ${allRules.length}`
      : `${allRules.length} ${allRules.length === 1 ? "rule" : "rules"}`;

    const u = escapeHtml(String(AppStore.state.dev_user ?? "").trim() || UNSET_USER_TOKEN);
    const allowCount = (permsObj.allow || []).length;
    const askCount = (permsObj.ask || []).length;
    const denyCount = (permsObj.deny || []).length;

    return `
      <div class="section-block" data-perm-scope="${escapeHtml(targetScope)}">
        <div class="d-flex justify-content-between align-items-center mb-1">
          <div class="section-heading mb-0">Permission Grants (Allow / Ask / Deny)</div>
          <span class="badge studio-badge-neutral" style="font-size:0.69rem;">Precedence: Deny &gt; Ask &gt; Allow</span>
        </div>
        <div class="section-desc">Switch permission buckets below, compose new grant rules, or search configured rules in place.</div>
        ${linkedNotice}

        <!-- 1. Segmented Bucket Switcher -->
        <div class="perm-bucket-tabs" role="tablist" aria-label="Permission Grant Buckets">
          <button type="button" role="tab" aria-selected="${bucket === "allow"}" class="perm-bucket-tab ${bucket === "allow" ? "active" : ""}" data-bucket-tab="allow">
            <span>Allow Grants</span>
            <span class="perm-bucket-count">${allowCount}</span>
          </button>
          <button type="button" role="tab" aria-selected="${bucket === "ask"}" class="perm-bucket-tab ${bucket === "ask" ? "active" : ""}" data-bucket-tab="ask">
            <span>Ask / Review</span>
            <span class="perm-bucket-count">${askCount}</span>
          </button>
          <button type="button" role="tab" aria-selected="${bucket === "deny"}" class="perm-bucket-tab ${bucket === "deny" ? "active" : ""}" data-bucket-tab="deny">
            <span>Deny / Block</span>
            <span class="perm-bucket-count">${denyCount}</span>
          </button>
        </div>
        <select id="select-perm-bucket" class="d-none" aria-hidden="true" tabindex="-1">
          <option value="allow" ${bucket === "allow" ? "selected" : ""}>Allow Grants (${allowCount})</option>
          <option value="ask" ${bucket === "ask" ? "selected" : ""}>Ask / Review Grants (${askCount})</option>
          <option value="deny" ${bucket === "deny" ? "selected" : ""}>Deny / Block Grants (${denyCount})</option>
        </select>

        <!-- 2. Dedicated New-Rule Composer Box -->
        <div class="studio-composer-box">
          <div class="studio-composer-header">
            <span class="studio-composer-title">+ Add New ${escapeHtml(bucketMeta.short)} Rule</span>
            <span class="studio-composer-hint">Pick a syntax preset or type directly, then press Enter</span>
          </div>
          <div class="row g-2">
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="select-rule-template">Quick Syntax Preset (Optional)</label>
              </div>
              <select id="select-rule-template" class="form-select form-select-sm">
                <option value="">Choose syntax preset...</option>
                <option value="command(git status)">command(...) — Literal Command</option>
                <option value="command(regex:^git\\s+(status|diff)$)">command(regex:...) — Regex Pattern</option>
                <option value="read_file(/home/${u}/workspace)">read_file(/path) — Read Path</option>
                <option value="write_file(/home/${u}/workspace)">write_file(/path) — Write Path</option>
                <option value="read_url(docs.cloud.google.com)">read_url(domain) — URL Domain</option>
                <option value="mcp(catalog/*)">mcp(server/tool) — Lazy MCP Tool</option>
              </select>
            </div>
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="input-new-perm-rule">Rule Expression to Add</label>
              </div>
              <div class="input-group input-group-sm">
                <input type="text" id="input-new-perm-rule" class="form-control mono-input" placeholder="e.g. command(git status)">
                <button type="button" id="btn-add-perm-rule" class="btn btn-primary fw-semibold px-2">+ Add Rule</button>
              </div>
            </div>
          </div>
        </div>

        <!-- 3. Configured Rules List Panel with Attached Search Bar -->
        <div class="studio-list-panel">
          <div class="studio-list-toolbar">
            <div class="studio-list-title">
              <span>Configured ${escapeHtml(bucketMeta.title)}</span>
              <span class="badge studio-badge-neutral">${escapeHtml(listCountText)}</span>
            </div>
            ${buildSearchBoxHtml("input-perm-search", "btn-clear-perm-search", AppStore.permFilterQuery, "Search configured rules...")}
          </div>
          <div class="rule-chip-list">${chipsHtml}</div>
        </div>
      </div>
    `;
  }

  /**
   * Wire event listeners for the segmented Permission Rule Chip Builder.
   *
   * @summary Handles 1-click bucket tabs, syntax preset insertion with argument
   *   highlighting, instant list search/clear, duplicate guard, and rule deletion.
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

    const switchBucket = (nextBucket) => {
      if (!nextBucket || !["allow", "ask", "deny"].includes(nextBucket)) {
        return;
      }
      AppStore.activePermBucket = nextBucket;
      renderActiveFormPanel(false);
    };

    container.querySelectorAll("[data-bucket-tab]").forEach((tabBtn) => {
      tabBtn.addEventListener("click", () => {
        switchBucket(tabBtn.dataset.bucketTab);
      });
    });

    container.querySelector("#select-perm-bucket")?.addEventListener("change", (e) => {
      switchBucket(e.target.value);
    });

    const searchInput = container.querySelector("#input-perm-search");
    if (searchInput) {
      searchInput.addEventListener("input", () => {
        AppStore.permFilterQuery = searchInput.value;
        renderActiveFormPanel(true);
      });
    }

    const clearPermSearch = () => {
      AppStore.permFilterQuery = "";
      renderActiveFormPanel(false);
      document.getElementById("input-perm-search")?.focus();
    };
    container.querySelector("#btn-clear-perm-search")?.addEventListener("click", clearPermSearch);
    container.querySelector("#btn-empty-clear-perm-search")?.addEventListener("click", clearPermSearch);

    container.querySelector("#btn-inline-unlink")?.addEventListener("click", () => {
      AppStore.state.sync_permissions = false;
      renderStep1Controls();
      renderActiveFormPanel(false);
      scheduleFormCompile(false);
    });

    const newRuleInput = container.querySelector("#input-new-perm-rule");
    const tplSelect = container.querySelector("#select-rule-template");
    if (tplSelect && newRuleInput) {
      tplSelect.addEventListener("change", () => {
        const chosen = tplSelect.value;
        if (chosen) {
          newRuleInput.value = chosen;
          tplSelect.selectedIndex = 0;
          refreshSingleSelectDisplay(tplSelect);
          newRuleInput.focus();
          // Select the inner argument inside parentheses so the admin can immediately overtype it
          const openParen = chosen.indexOf("(");
          const closeParen = chosen.lastIndexOf(")");
          if (openParen >= 0 && closeParen > openParen) {
            try {
              newRuleInput.setSelectionRange(openParen + 1, closeParen);
            } catch {
              // Ignore if selection range is unsupported
            }
          }
        }
      });
    }

    const addRule = () => {
      if (!newRuleInput) {
        return;
      }
      const val = newRuleInput.value.trim();
      if (!val) {
        newRuleInput.focus();
        return;
      }
      const perms = getTargetPerms();
      const arr = perms[AppStore.activePermBucket];
      if (arr.includes(val)) {
        showToast("Rule already exists in this permission bucket", "warning");
        newRuleInput.select();
        return;
      }
      arr.unshift(val);
      const activeQuery = AppStore.permFilterQuery.trim().toLowerCase();
      if (activeQuery && !val.toLowerCase().includes(activeQuery)) {
        AppStore.permFilterQuery = "";
        showToast("Added rule (cleared search filter so it is visible)", "info");
      }
      syncMirrorIfLinked();
      newRuleInput.value = "";
      renderActiveFormPanel(false);
      document.getElementById("input-new-perm-rule")?.focus();
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
        const arr = perms[AppStore.activePermBucket];
        if (!Array.isArray(arr) || !Number.isInteger(idx) || idx < 0 || idx >= arr.length) {
          return;
        }
        arr.splice(idx, 1);
        syncMirrorIfLinked();
        renderActiveFormPanel(false);
        scheduleFormCompile(false);
      });
    });
  }

  /**
   * Render Step 3B: Focused visual form controls for `AppStore.selectedFileId`.
   *
   * @summary Renders ONLY the active file's form fields directly below the
   *   File Reference Card on the Left Panel while optionally preserving focus.
   * @param {boolean} [preserveFocus=false] - Whether to preserve active input focus & cursor.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function renderActiveFormPanel(preserveFocus = false) {
    AppStore.deferredFormRender = false;
    const container = document.getElementById("form-panel-container");
    if (!container) {
      return;
    }
    const fid = AppStore.selectedFileId;
    const meta = CATALOG_BY_ID[fid];
    if (!fid || !meta) {
      container.innerHTML = "";
      return;
    }

    const focusSnap = preserveFocus ? captureFormFocus(container) : null;
    const s = AppStore.state;
    const secretType = AppStore.showSecrets ? "text" : "password";
    const eyeCaption = AppStore.showSecrets ? "Hide" : "Show";
    let html = "";

    const uState = getWorkstationUserState();
    if (meta.requires_user && (uState.isMissing || uState.isInvalid)) {
      const reasonText = uState.isInvalid
        ? uState.errorMessage
        : `<code>${escapeHtml(meta.filename)}</code> deploys inside a developer home directory (<code>~/.gemini/...</code> / <code>~/.jetbrains/...</code>) and requires a valid Workstation Username before export.`;
      html += `
        <div id="form-missing-user-banner" class="alert alert-danger d-flex align-items-center justify-content-between gap-2 py-2 px-3 mb-2" style="font-size: 0.76rem;">
          <div>
            <strong>Workstation Username Required:</strong> ${reasonText}
          </div>
          <button type="button" id="btn-focus-dev-user" class="btn btn-sm btn-danger text-nowrap py-1 px-2" style="font-size: 0.72rem;">
            Set Username
          </button>
        </div>
      `;
    }

    if (fid === "admin_settings") {
      const gw = s.gateway;
      const customHeaders = gw.customHeaders || [];
      const headerColHead = customHeaders.length
        ? `<div class="row g-2 align-items-center studio-col-header">
             <div class="col-6">Header Name (Key)</div>
             <div class="col">Header Value</div>
             <div class="col-auto" style="width: 30px;"></div>
           </div>`
        : "";
      const headersRows = customHeaders
        .map(
          (h, idx) => `
          <div class="row g-2 align-items-center mb-1">
            <div class="col-6">
              <input type="text" class="form-control form-control-sm mono-input" data-gw-hdr-key="${idx}" value="${escapeHtml(h.key)}" placeholder="X-Cost-Center">
            </div>
            <div class="col">
              <input type="text" class="form-control form-control-sm mono-input" data-gw-hdr-val="${idx}" value="${escapeHtml(h.value)}" placeholder="CC-9941-SEC">
            </div>
            <div class="col-auto">
              <button type="button" class="btn btn-sm btn-outline-danger btn-row-delete" data-gw-hdr-del="${idx}" aria-label="Remove header" title="Remove header">&times;</button>
            </div>
          </div>`
        )
        .join("");

      const catalogModels = gw.models || [];
      const modelColHead = catalogModels.length
        ? `<div class="row g-2 align-items-center studio-col-header">
             <div class="col-6">Model ID (models.list)</div>
             <div class="col">Display Name (Optional)</div>
             <div class="col-auto" style="width: 30px;"></div>
           </div>`
        : "";
      const modelRows = catalogModels
        .map(
          (m, idx) => `
          <div class="row g-2 align-items-center mb-1">
            <div class="col-6">
              <input type="text" class="form-control form-control-sm mono-input" data-gw-mdl-id="${idx}" value="${escapeHtml(m.modelId)}" placeholder="gemini-3.8-flash">
            </div>
            <div class="col">
              <input type="text" class="form-control form-control-sm" data-gw-mdl-name="${idx}" value="${escapeHtml(m.displayName || "")}" placeholder="Display Name (optional)">
            </div>
            <div class="col-auto">
              <button type="button" class="btn btn-sm btn-outline-danger btn-row-delete" data-gw-mdl-del="${idx}" aria-label="Remove model" title="Remove model">&times;</button>
            </div>
          </div>`
        )
        .join("");

      const wireOptions = renderSelectOptions(
        [
          { value: "genai", label: "genai (Default / ACP)" },
          { value: "openai", label: "openai (/v1/chat/completions)" },
        ],
        gw.wireProtocol
      );

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
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="gw-url">Gateway HTTPS Endpoint URL</label>
              </div>
              <input id="gw-url" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(gw.url)}" placeholder="https://gateway.corp.example.com">
            </div>
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="gw-wire">Wire Protocol</label>
              </div>
              <select id="gw-wire" class="form-select form-select-sm">${wireOptions}</select>
            </div>
          </div>

          <div class="row g-2">
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="gw-apikey">Gateway Bearer API Key</label>
                <div class="form-check mb-0 d-flex align-items-center gap-1" style="min-height: 0;">
                  <input class="form-check-input mt-0" type="checkbox" id="gw-omit-key" ${gw.omitApiKeyInMdm ? "checked" : ""}>
                  <label class="form-check-label text-nowrap" style="font-size:0.7rem;" for="gw-omit-key">Omit (Tier-2 Env)</label>
                </div>
              </div>
              <div class="input-group input-group-sm">
                <input id="gw-apikey" type="${secretType}" class="form-control mono-input" value="${escapeHtml(gw.apiKey)}" ${gw.omitApiKeyInMdm ? "disabled" : ""} placeholder="REPLACE_WITH_GATEWAY_API_KEY">
                <button type="button" class="btn btn-outline-secondary btn-toggle-secret">${eyeCaption}</button>
              </div>
            </div>
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="gw-cacert">Top-Level CA Bundle Path (POSIX)</label>
              </div>
              <input id="gw-cacert" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(gw.caCertPath)}" placeholder="/etc/ssl/certs/ca-certificates.crt">
            </div>
          </div>
        </div>

        <div class="section-block">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <div>
              <div class="d-flex align-items-center gap-2">
                <span class="section-heading mb-0">FinOps &amp; Attribution Headers</span>
                <span class="badge studio-badge-neutral">${customHeaders.length}</span>
              </div>
              <div class="section-desc mb-0">Pinned in Tier-1 MDM so developers cannot spoof chargeback headers.</div>
            </div>
            <button type="button" id="btn-add-gw-header" class="btn btn-sm btn-outline-primary py-0 px-2" style="font-size:0.75rem;">+ Add Header</button>
          </div>
          ${headerColHead}
          ${headersRows || '<div class="text-body-secondary small">No custom headers configured. Click "+ Add Header" above.</div>'}
          <div id="gw-hdr-key-feedback" class="text-danger small mt-1 d-none"></div>
        </div>

        <div class="section-block">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <div>
              <div class="d-flex align-items-center gap-2">
                <span class="section-heading mb-0">Approved Model Catalog</span>
                <span class="badge studio-badge-neutral">${catalogModels.length}</span>
              </div>
              <div class="section-desc mb-0">Top-level GA <code>models.defaultModelId</code> and <code>models.list</code>.</div>
            </div>
            <button type="button" id="btn-add-gw-model" class="btn btn-sm btn-outline-primary py-0 px-2" style="font-size:0.75rem;">+ Add Model</button>
          </div>
          <div class="row g-2 mb-2">
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="gw-default-model">Default Model ID (models.defaultModelId)</label>
              </div>
              <input id="gw-default-model" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(gw.defaultModelId)}">
            </div>
          </div>
          ${modelColHead}
          ${modelRows || '<div class="text-body-secondary small">No models listed in catalog. Click "+ Add Model" above.</div>'}
          <div id="gw-mdl-id-feedback" class="text-danger small mt-1 d-none"></div>
        </div>
      `;
    } else if (fid === "gateway_env") {
      const ge = s.gateway_env;
      const envWireOptions = renderSelectOptions(
        [
          { value: "genai", label: "genai" },
          { value: "openai", label: "openai" },
        ],
        ge.wireProtocol
      );
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
            <div class="studio-field-label-row">
              <label class="form-label-sm" for="env-url">AGY_LLM_GATEWAY_URL</label>
            </div>
            <input id="env-url" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(ge.url)}">
          </div>
          <div class="row g-2 mb-2">
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="env-apikey">AGY_LLM_GATEWAY_API_KEY</label>
              </div>
              <div class="input-group input-group-sm">
                <input id="env-apikey" type="${secretType}" class="form-control mono-input" value="${escapeHtml(ge.apiKey)}">
                <button type="button" class="btn btn-outline-secondary btn-toggle-secret">${eyeCaption}</button>
              </div>
            </div>
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="env-wire">AGY_LLM_GATEWAY_WIRE_PROTOCOL</label>
              </div>
              <select id="env-wire" class="form-select form-select-sm">${envWireOptions}</select>
            </div>
          </div>
          <div class="mb-2">
            <div class="studio-field-label-row">
              <label class="form-label-sm" for="env-cacert">AGY_LLM_GATEWAY_CA_CERT</label>
            </div>
            <input id="env-cacert" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(ge.caCert)}">
          </div>
          <div class="mb-2">
            <div class="studio-field-label-row">
              <label class="form-label-sm" for="env-headers">AGY_LLM_GATEWAY_HEADERS (Comma-separated Key: Value pairs)</label>
            </div>
            <input id="env-headers" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(ge.headers)}">
          </div>
          <div>
            <div class="studio-field-label-row">
              <label class="form-label-sm" for="env-models">AGY_LLM_GATEWAY_MODELS (Comma-separated model IDs)</label>
            </div>
            <input id="env-models" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(ge.models)}">
          </div>
        </div>
      `;
    } else if (fid === "cli_settings") {
      const c = s.cli;
      const showHistoryInput = Boolean(c.includeOptionalUiKeys || c.historySize !== 50);
      const agentModeOpts = renderSelectOptions(
        [
          { value: "plan", label: "plan (Recommended)" },
          { value: "accept-edits", label: "accept-edits" },
          { value: "auto", label: "auto" },
          { value: "", label: '"" (Client Default)' },
        ],
        c.agentMode
      );
      const toolPermOpts = renderSelectOptions(
        [
          { value: "proceed-in-sandbox", label: "proceed-in-sandbox" },
          { value: "request-review", label: "request-review" },
          { value: "strict", label: "strict (Zero Auto-Run)" },
          { value: "always-proceed", label: "always-proceed" },
        ],
        c.toolPermission
      );
      const artifactOpts = renderSelectOptions(
        [
          { value: "asks-for-review", label: "asks-for-review" },
          { value: "agent-decides", label: "agent-decides" },
          { value: "always-proceed", label: "always-proceed" },
        ],
        c.artifactReviewPolicy
      );

      html += `
        <div class="section-block">
          <div class="section-heading">CLI &amp; VS Code Execution Sandbox</div>
          <div class="section-desc">Enforced by <code>agy</code> CLI, VS Code, and Visual Studio extensions.</div>
          <div class="row g-2 mb-1">
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="cli-agent-mode">Agent Mode (<code>agentMode</code>)</label>
              </div>
              <select id="cli-agent-mode" class="form-select form-select-sm">${agentModeOpts}</select>
            </div>
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="cli-tool-perm">Tool Permission (<code>toolPermission</code>)</label>
              </div>
              <select id="cli-tool-perm" class="form-select form-select-sm">${toolPermOpts}</select>
            </div>
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="cli-artifact-review">Artifact Review (<code>artifactReviewPolicy</code>)</label>
              </div>
              <select id="cli-artifact-review" class="form-select form-select-sm">${artifactOpts}</select>
            </div>
            <div class="col-sm-6 ${showHistoryInput ? "" : "d-none"}" id="cli-optional-row">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="cli-history-size">History Size (<code>historySize</code>, 0 = Ephemeral)</label>
              </div>
              <input id="cli-history-size" type="number" min="0" max="500" class="form-control form-control-sm" value="${escapeHtml(c.historySize)}">
            </div>
          </div>

          <div class="studio-toggle-strip">
            <div class="form-check form-switch mb-0">
              <input class="form-check-input" type="checkbox" id="cli-enable-sandbox" ${c.enableTerminalSandbox ? "checked" : ""}>
              <label class="form-check-label small" for="cli-enable-sandbox">Terminal Sandbox (<code>enableTerminalSandbox</code>)</label>
            </div>
            <div class="form-check form-switch mb-0">
              <input class="form-check-input" type="checkbox" id="cli-non-ws" ${c.allowNonWorkspaceAccess ? "checked" : ""}>
              <label class="form-check-label small" for="cli-non-ws">Outside-Workspace Files (<code>allowNonWorkspaceAccess</code>)</label>
            </div>
            <div class="form-check form-switch mb-0">
              <input class="form-check-input" type="checkbox" id="cli-opt-ui" ${c.includeOptionalUiKeys ? "checked" : ""}>
              <label class="form-check-label small" for="cli-opt-ui">Configure <code>historySize</code> &amp; UI Toggles</label>
            </div>
          </div>

          <div class="studio-toggle-strip ${c.includeOptionalUiKeys ? "" : "d-none"}">
            <div class="form-check form-switch mb-0">
              <input class="form-check-input" type="checkbox" id="cli-ui-notif" ${c.notifications ? "checked" : ""}>
              <label class="form-check-label small" for="cli-ui-notif">Notifications (<code>notifications</code>)</label>
            </div>
            <div class="form-check form-switch mb-0">
              <input class="form-check-input" type="checkbox" id="cli-ui-survey" ${c.showFeedbackSurvey ? "checked" : ""}>
              <label class="form-check-label small" for="cli-ui-survey">Feedback Survey (<code>showFeedbackSurvey</code>)</label>
            </div>
            <div class="form-check form-switch mb-0">
              <input class="form-check-input" type="checkbox" id="cli-ui-tips" ${c.showTips ? "checked" : ""}>
              <label class="form-check-label small" for="cli-ui-tips">Startup Tips (<code>showTips</code>)</label>
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
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="cli-sbp-addr">Proxy Address</label>
              </div>
              <input id="cli-sbp-addr" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(c.sandboxProxyAddress)}" placeholder="http://proxy.corp.example.com:3128">
            </div>
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="cli-sbp-cert">Single-Cert Root CA PEM</label>
              </div>
              <input id="cli-sbp-cert" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(c.sandboxProxyCertFile)}" placeholder="/etc/antigravity/certs/corp-root-ca.pem">
            </div>
          </div>
        </div>

        ${buildPermissionsWidgetHtml("cli", c.permissions)}
      `;
    } else if (fid === "desktop_config") {
      const d = s.desktop;
      const activePerms = s.sync_permissions ? s.cli.permissions : d.permissions;
      const autoExecOpts = renderSelectOptions(
        [
          { value: "CASCADE_COMMANDS_AUTO_EXECUTION_PROCEED_IN_SANDBOX", label: "PROCEED_IN_SANDBOX" },
          { value: "CASCADE_COMMANDS_AUTO_EXECUTION_DISABLED", label: "DISABLED (Require Review)" },
          { value: "CASCADE_COMMANDS_AUTO_EXECUTION_EAGER", label: "EAGER" },
        ],
        d.autoExecutionPolicy
      );
      const deskArtOpts = renderSelectOptions(
        [
          { value: "ARTIFACT_REVIEW_MODE_ALWAYS", label: "ALWAYS" },
          { value: "ARTIFACT_REVIEW_MODE_TURBO", label: "TURBO" },
        ],
        d.artifactReviewMode
      );
      const browserJsOpts = renderSelectOptions(
        [
          { value: "BROWSER_JS_EXECUTION_POLICY_DISABLED", label: "DISABLED (Hardened)" },
          { value: "BROWSER_JS_EXECUTION_POLICY_REQUEST_REVIEW", label: "REQUEST_REVIEW" },
          { value: "BROWSER_JS_EXECUTION_POLICY_TURBO", label: "TURBO" },
        ],
        d.browserJsExecutionPolicy
      );
      const nonWsOpts = renderSelectOptions(
        [
          { value: "", label: "(Omit — Client Default)" },
          { value: "NON_WORKSPACE_FILE_ACCESS_POLICY_DISABLED", label: "DISABLED (Workspace Only)" },
          { value: "NON_WORKSPACE_FILE_ACCESS_POLICY_ENABLED", label: "ENABLED" },
        ],
        d.nonWorkspaceFileAccessPolicy || ""
      );
      const internetOpts = renderSelectOptions(
        [
          { value: "", label: "(Omit — Client Default)" },
          { value: "INTERNET_ACCESS_POLICY_DISABLED", label: "DISABLED (Air-Gapped)" },
          { value: "INTERNET_ACCESS_POLICY_ALLOWLIST", label: "ALLOWLIST" },
          { value: "INTERNET_ACCESS_POLICY_ENABLED", label: "ENABLED" },
        ],
        d.internetAccessPolicy || ""
      );

      html += `
        <div class="section-block">
          <div class="section-heading">Desktop App &amp; Self-Hosted Web Hub (userSettings)</div>
          <div class="section-desc">Enforced by Antigravity Desktop App (2.15.0+) and <code>agy --hub</code> (:4400).</div>
          <div class="row g-2 mb-2">
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="desk-auto-exec">Auto-Execution (<code>autoExecutionPolicy</code>)</label>
              </div>
              <select id="desk-auto-exec" class="form-select form-select-sm">${autoExecOpts}</select>
            </div>
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="desk-artifact">Artifact Review (<code>artifactReviewMode</code>)</label>
              </div>
              <select id="desk-artifact" class="form-select form-select-sm">${deskArtOpts}</select>
            </div>
          </div>

          <div class="row g-2 mb-2">
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="desk-browser-js">Browser JS Policy (<code>browserJsExecutionPolicy</code>)</label>
              </div>
              <select id="desk-browser-js" class="form-select form-select-sm">${browserJsOpts}</select>
            </div>
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="desk-nonws-policy">Outside-Workspace Files (<code>nonWorkspaceFileAccessPolicy</code>)</label>
              </div>
              <select id="desk-nonws-policy" class="form-select form-select-sm">${nonWsOpts}</select>
            </div>
          </div>

          <div class="row g-2">
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="desk-internet-policy">Internet Access Policy (<code>internetAccessPolicy</code>)</label>
              </div>
              <select id="desk-internet-policy" class="form-select form-select-sm">${internetOpts}</select>
            </div>
          </div>

          <div class="studio-toggle-strip">
            <div class="form-check form-switch mb-0">
              <input class="form-check-input" type="checkbox" id="desk-sandbox" ${d.enableTerminalSandbox ? "checked" : ""}>
              <label class="form-check-label small" for="desk-sandbox">Terminal Sandbox (<code>enableTerminalSandbox</code>)</label>
            </div>
            <div class="form-check form-switch mb-0">
              <input class="form-check-input" type="checkbox" id="desk-net" ${d.sandboxAllowNetwork ? "checked" : ""}>
              <label class="form-check-label small" for="desk-net">Sandbox Network Access (<code>sandboxAllowNetwork</code>)</label>
            </div>
          </div>
        </div>

        ${buildPermissionsWidgetHtml("desktop", activePerms)}
      `;
    } else if (fid === "browser_allowlist") {
      const domains = s.browser_domains || [];
      const rawDomQuery = String(AppStore.domainFilterQuery ?? "").trim();
      const domQ = rawDomQuery.toLowerCase();
      const filteredDomains = domQ
        ? domains.map((dom, idx) => ({ dom, idx })).filter((item) => item.dom.toLowerCase().includes(domQ))
        : domains.map((dom, idx) => ({ dom, idx }));

      const emptyDomHtml = domQ
        ? `<div class="text-body-secondary small p-2 d-flex align-items-center flex-wrap gap-2">
             <span>No hostnames match "<strong>${escapeHtml(rawDomQuery)}</strong>".</span>
             <button type="button" class="btn btn-sm btn-link p-0 text-decoration-none" id="btn-empty-clear-domain-search">Clear search</button>
           </div>`
        : '<div class="text-body-secondary small p-2">No hostnames configured yet. Add a trusted hostname above.</div>';

      const chips = filteredDomains.length
        ? filteredDomains
            .map(
              (item) => `
              <span class="rule-chip">
                <span>${escapeHtml(item.dom)}</span>
                <button type="button" class="rule-chip-remove" data-del-domain="${item.idx}" aria-label="Remove domain" title="Remove domain">&times;</button>
              </span>`
            )
            .join("")
        : emptyDomHtml;

      const domCountText = domQ
        ? `Showing ${filteredDomains.length} of ${domains.length}`
        : `${domains.length} ${domains.length === 1 ? "hostname" : "hostnames"}`;

      html += `
        <div class="section-block">
          <div class="section-heading">Trusted Browser Subagent Hostnames</div>
          <div class="section-desc">Enter bare hostnames (no <code>https://</code> scheme or path). Lock the file using the commands above so developers cannot click "Always allow".</div>

          <div class="studio-composer-box">
            <div class="studio-composer-header">
              <span class="studio-composer-title">+ Add Trusted Hostname</span>
              <span class="studio-composer-hint">Bare domain or wildcard (e.g. *.corp.example.com)</span>
            </div>
            <div class="input-group input-group-sm">
              <input id="input-new-domain" type="text" class="form-control mono-input" placeholder="docs.internal.example.com">
              <button id="btn-add-domain" type="button" class="btn btn-primary fw-semibold px-2">+ Add Hostname</button>
            </div>
          </div>

          <div class="studio-list-panel">
            <div class="studio-list-toolbar">
              <div class="studio-list-title">
                <span>Configured Hostnames</span>
                <span class="badge studio-badge-neutral">${escapeHtml(domCountText)}</span>
              </div>
              ${buildSearchBoxHtml("input-domain-search", "btn-clear-domain-search", AppStore.domainFilterQuery, "Search hostnames...")}
            </div>
            <div class="rule-chip-list">${chips}</div>
          </div>
        </div>
      `;
    } else if (fid === "mcp_config") {
      const allServers = s.mcp_servers || [];
      const expandedSet = getMcpExpandedSet(allServers.length);
      const rawMcpQuery = String(AppStore.mcpFilterQuery ?? "").trim();
      const mcpQ = rawMcpQuery.toLowerCase();
      const indexedServers = allServers.map((srv, idx) => ({ srv, idx }));
      const filteredServers = mcpQ
        ? indexedServers.filter(({ srv }) => {
            const hay = `${srv.name || ""} ${srv.transport || ""} ${srv.serverUrl || ""} ${srv.command || ""} ${(srv.enabledTools || []).join(" ")} ${(srv.disabledTools || []).join(" ")}`.toLowerCase();
            return hay.includes(mcpQ);
          })
        : indexedServers;

      const mcpCountText = mcpQ
        ? `Showing ${filteredServers.length} of ${allServers.length}`
        : `${allServers.length}`;

      const visibleExpandedCount = filteredServers.filter(({ idx }) => expandedSet.has(idx)).length;
      const allVisibleExpanded =
        filteredServers.length > 0 && visibleExpandedCount === filteredServers.length;
      const allVisibleCollapsed = filteredServers.length === 0 || visibleExpandedCount === 0;

      const showMcpSearch = allServers.length > 1 || Boolean(mcpQ);
      const showMcpToolbar = allServers.length > 0 || Boolean(mcpQ);
      const mcpToolbarHtml = showMcpToolbar
        ? `<div class="mcp-toolbar-row">
             <div class="mcp-bulk-actions">
               ${
                 filteredServers.length > 0
                   ? `<button type="button" id="btn-mcp-expand-all" class="mcp-bulk-btn" ${allVisibleExpanded ? "disabled" : ""}>&#9662; Expand All</button>
                      <button type="button" id="btn-mcp-collapse-all" class="mcp-bulk-btn" ${allVisibleCollapsed ? "disabled" : ""}>&#9656; Collapse All</button>`
                   : ""
               }
             </div>
             ${showMcpSearch ? buildSearchBoxHtml("input-mcp-search", "btn-clear-mcp-search", AppStore.mcpFilterQuery, "Search MCP servers...") : ""}
           </div>`
        : "";

      const serversHtml = filteredServers.length
        ? filteredServers
            .map(({ srv, idx }) => {
              const isExpanded = expandedSet.has(idx);
              const endpointSummary = formatMcpEndpointSummary(srv);
              const toolBadge = formatMcpToolsBadge(srv);
              return `
              <div class="mcp-server-card ${isExpanded ? "is-expanded" : ""}" data-mcp-card="${idx}">
                <div class="mcp-card-header">
                  <button type="button" class="mcp-card-toggle" data-mcp-toggle="${idx}" aria-expanded="${isExpanded ? "true" : "false"}" title="${isExpanded ? "Collapse server configuration" : "Expand server configuration"}">
                    <svg class="mcp-card-chevron" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                      <polyline points="6 3.5 10.5 8 6 12.5"></polyline>
                    </svg>
                    <span class="mcp-card-title" data-mcp-hdr-name="${idx}">${escapeHtml(String(srv.name || "").trim() || "(unnamed)")}</span>
                    <span class="badge ${srv.transport === "http" ? "studio-badge-primary" : "studio-badge-neutral"} mcp-transport-pill">${srv.transport === "http" ? "Remote HTTP" : "Local stdio"}</span>
                    <span class="mcp-card-summary" data-mcp-hdr-summary="${idx}">${escapeHtml(endpointSummary)}</span>
                    <span class="mcp-card-tools-pill ${toolBadge.tone ? `tone-${toolBadge.tone}` : "d-none"}" data-mcp-hdr-tools="${idx}">${escapeHtml(toolBadge.text)}</span>
                  </button>
                  <div class="mcp-card-actions">
                    <div class="form-check form-switch mb-0 d-flex align-items-center gap-1">
                      <input class="form-check-input mt-0" type="checkbox" id="mcp-en-${idx}" data-mcp-enabled="${idx}" ${!srv.disabled ? "checked" : ""}>
                      <label class="form-check-label mcp-enable-label ${!srv.disabled ? "is-enabled" : ""}" for="mcp-en-${idx}">${!srv.disabled ? "Enabled" : "Disabled"}</label>
                    </div>
                    <button type="button" class="btn btn-sm btn-outline-danger btn-row-delete" data-mcp-del="${idx}" aria-label="Remove MCP server" title="Remove MCP server">&times;</button>
                  </div>
                </div>

                <div class="mcp-card-body ${isExpanded ? "" : "d-none"}" data-mcp-body="${idx}">
                  <div class="row g-2 mb-2">
                    <div class="col-sm-6">
                      <div class="studio-field-label-row"><label class="form-label-sm">Server Key (<code>mcpServers.&lt;name&gt;</code>)</label></div>
                      <input type="text" class="form-control form-control-sm mono-input fw-semibold" data-mcp-name="${idx}" value="${escapeHtml(srv.name)}" placeholder="server_name">
                    </div>
                    <div class="col-sm-6">
                      <div class="studio-field-label-row"><label class="form-label-sm">Transport Protocol</label></div>
                      <select class="form-select form-select-sm" data-mcp-transport="${idx}">
                        <option value="stdio" ${srv.transport === "stdio" ? "selected" : ""}>Local stdio</option>
                        <option value="http" ${srv.transport === "http" ? "selected" : ""}>Remote HTTP</option>
                      </select>
                    </div>
                  </div>

                  ${
                    srv.transport === "http"
                      ? `<div class="mb-2">
                           <div class="studio-field-label-row"><label class="form-label-sm">Remote Endpoint URL (<code>serverUrl</code>)</label></div>
                           <input type="text" class="form-control form-control-sm mono-input" data-mcp-url="${idx}" value="${escapeHtml(srv.serverUrl)}" placeholder="https://mcp.internal.example.com/mcp/">
                         </div>`
                      : `<div class="row g-2 mb-2">
                           <div class="col-sm-6">
                             <div class="studio-field-label-row"><label class="form-label-sm">Executable (<code>command</code>)</label></div>
                             <input type="text" class="form-control form-control-sm mono-input" data-mcp-cmd="${idx}" value="${escapeHtml(srv.command)}" placeholder="/usr/local/bin/mcp_server">
                           </div>
                           <div class="col-sm-6">
                             <div class="studio-field-label-row"><label class="form-label-sm">Arguments (<code>args</code>, comma-sep)</label></div>
                             <input type="text" class="form-control form-control-sm mono-input" data-mcp-args="${idx}" value="${escapeHtml((srv.args || []).join(", "))}">
                           </div>
                         </div>`
                  }

                  <div class="row g-2">
                    <div class="col-sm-4">
                      <div class="studio-field-label-row"><label class="form-label-sm">Timeout (s)</label></div>
                      <input type="number" min="1" max="3600" class="form-control form-control-sm mono-input" data-mcp-timeout="${idx}" value="${escapeHtml(srv.timeoutSeconds ?? "")}" placeholder="Omit">
                    </div>
                    <div class="col-sm-4">
                      <div class="studio-field-label-row"><label class="form-label-sm">Allowed Tools (<code>enabledTools</code>)</label></div>
                      <input type="text" class="form-control form-control-sm mono-input" data-mcp-allow="${idx}" value="${escapeHtml((srv.enabledTools || []).join(", "))}">
                    </div>
                    <div class="col-sm-4">
                      <div class="studio-field-label-row"><label class="form-label-sm">Blocked Tools (<code>disabledTools</code>)</label></div>
                      <input type="text" class="form-control form-control-sm mono-input" data-mcp-deny="${idx}" value="${escapeHtml((srv.disabledTools || []).join(", "))}">
                    </div>
                  </div>
                </div>
              </div>`;
            })
            .join("")
        : mcpQ
          ? `<div class="text-body-secondary small p-2 d-flex align-items-center flex-wrap gap-2">
               <span>No MCP servers match "<strong>${escapeHtml(rawMcpQuery)}</strong>".</span>
               <button type="button" class="btn btn-sm btn-link p-0 text-decoration-none" id="btn-empty-clear-mcp-search">Clear search</button>
             </div>`
          : '<div class="text-body-secondary small">No MCP servers configured. Click "+ Add Server" above.</div>';

      html += `
        <div class="section-block">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <div>
              <div class="d-flex align-items-center gap-2">
                <span class="section-heading mb-0">MCP Server Definitions</span>
                <span class="badge studio-badge-neutral">${escapeHtml(mcpCountText)}</span>
              </div>
              <div class="section-desc mb-0">Keep lazy loading (default) so <code>permissions.deny</code> <code>mcp(...)</code> rules apply inside <code>call_mcp_tool</code>.</div>
            </div>
            <button type="button" id="btn-add-mcp" class="btn btn-sm btn-primary fw-semibold py-1 px-2" style="font-size:0.75rem;">+ Add Server</button>
          </div>
          ${mcpToolbarHtml}
          ${serversHtml}
          <div id="mcp-name-feedback" class="text-danger small mt-1 d-none"></div>
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
            <div class="col-sm-4">
              <div class="studio-field-label-row"><label class="form-label-sm" for="hook-pre-matcher">Tool Regex Matcher</label></div>
              <input id="hook-pre-matcher" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(h.preMatcher)}">
            </div>
            <div class="col-sm-6">
              <div class="studio-field-label-row"><label class="form-label-sm" for="hook-pre-cmd">Guard Command</label></div>
              <input id="hook-pre-cmd" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(h.preCommand)}">
            </div>
            <div class="col-sm-2">
              <div class="studio-field-label-row"><label class="form-label-sm" for="hook-pre-timeout">Timeout (s)</label></div>
              <input id="hook-pre-timeout" type="number" min="1" max="300" class="form-control form-control-sm mono-input" value="${escapeHtml(h.preTimeout ?? 10)}">
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
            <div class="col-sm-4">
              <div class="studio-field-label-row"><label class="form-label-sm" for="hook-post-matcher">Tool Regex Matcher</label></div>
              <input id="hook-post-matcher" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(h.postMatcher)}">
            </div>
            <div class="col-sm-6">
              <div class="studio-field-label-row"><label class="form-label-sm" for="hook-post-cmd">Audit Command</label></div>
              <input id="hook-post-cmd" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(h.postCommand)}">
            </div>
            <div class="col-sm-2">
              <div class="studio-field-label-row"><label class="form-label-sm" for="hook-post-timeout">Timeout (s)</label></div>
              <input id="hook-post-timeout" type="number" min="1" max="300" class="form-control form-control-sm mono-input" value="${escapeHtml(h.postTimeout ?? 10)}">
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
            <div class="studio-field-label-row"><label class="form-label-sm" for="hook-banner-txt">Compliance Banner Text</label></div>
            <input id="hook-banner-txt" type="text" class="form-control form-control-sm" value="${escapeHtml(h.sessionBannerText)}">
          </div>
        </div>
      `;
    } else if (fid === "guard_sh" || fid === "guard_ps1") {
      const isPs = fid === "guard_ps1";
      const scriptText = String(s.scripts?.[fid] || "");
      const lineCount = scriptText ? scriptText.split("\n").length : 0;
      const ruleMatches = scriptText.match(/RULE-[A-Z0-9-]+/g) || [];
      const uniqueRules = Array.from(new Set(ruleMatches));

      html += `
        <div class="section-block">
          <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-1">
            <div class="section-heading mb-0">${isPs ? "Windows PowerShell" : "Linux / macOS POSIX Bash"} Deterministic Guard</div>
            <span class="badge studio-badge-neutral mono-input" style="font-size: 0.71rem;">${lineCount} lines · ${uniqueRules.length} policy rule(s)</span>
          </div>
          <div class="section-desc">
            Edit the full guard script directly in the live code editor on the right. Changes round-trip into your single-file download and MDM <code>.zip</code> bundle.
          </div>
          <ul class="small text-body-secondary mb-2 ps-3">
            <li><strong>Exit Code 0</strong>: Permits compliant tool call and records JSONL SIEM event.</li>
            <li><strong>Exit Code 2</strong>: Hard-blocks violating tool call and surfaces stderr policy reason to the agent.</li>
            <li><strong>Active Rule IDs</strong>: <code>${escapeHtml(uniqueRules.join(", ") || "Custom script")}</code></li>
          </ul>
          <button type="button" id="btn-reset-guard-script" class="btn btn-sm btn-outline-secondary">Reset Script to Canonical Default</button>
        </div>
      `;
    } else if (fid === "acp_json") {
      const acp = s.acp;
      const gw = s.gateway;
      const acpWireOpts = renderSelectOptions(
        [
          { value: "genai", label: "genai (Required by ACP 1.3.0+)" },
          { value: "openai", label: "openai (Unsupported by ACP)" },
        ],
        gw.wireProtocol
      );
      html += `
        <div class="section-block">
          <div class="section-heading">JetBrains IDEs &amp; Zed Editor Server Definition (acp.json)</div>
          <div class="section-desc">
            Configures <code>agent_servers.Antigravity</code> executable, CLI arguments, and inherited Gateway environment variables.
          </div>
          <div class="row g-2 mb-2">
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="acp-cmd">Antigravity CLI Executable Path</label>
              </div>
              <input id="acp-cmd" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(acp.command)}">
            </div>
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="acp-args">CLI Arguments (comma-sep)</label>
              </div>
              <input id="acp-args" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml((acp.args || ["acp"]).join(", "))}">
            </div>
          </div>
          <div class="row g-2">
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="acp-gw-url">AGY_LLM_GATEWAY_URL (Synced with Group 01)</label>
              </div>
              <input id="acp-gw-url" type="text" class="form-control form-control-sm mono-input" value="${escapeHtml(gw.url)}">
            </div>
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="acp-gw-wire">AGY_LLM_GATEWAY_WIRE_PROTOCOL</label>
              </div>
              <select id="acp-gw-wire" class="form-select form-select-sm">${acpWireOpts}</select>
            </div>
          </div>
        </div>
      `;
    } else if (fid === "acp_auth") {
      const acp = s.acp;
      const authTypeOpts = renderSelectOptions(
        [{ value: "gateway", label: "gateway (Required for Enterprise Gateway)" }],
        acp.authType || "gateway"
      );
      html += `
        <div class="section-block">
          <div class="section-heading">ACP Gateway Auth Selector (~/.gemini/antigravity-acp/settings.json)</div>
          <div class="section-desc">
            Instructs the JetBrains &amp; Zed ACP server (<code>1.3.0+</code>) to authenticate via Enterprise Gateway mode instead of interactive OAuth.
          </div>
          <div class="row g-2">
            <div class="col-sm-6">
              <div class="studio-field-label-row">
                <label class="form-label-sm" for="acp-auth-type">ACP Auth Type (auth.type)</label>
              </div>
              <select id="acp-auth-type" class="form-select form-select-sm">${authTypeOpts}</select>
            </div>
          </div>
        </div>
      `;
    }

    container.innerHTML = html;
    bindActiveFormEvents(container, fid);
    syncStudioSingleSelects(container);
    if (focusSnap) {
      restoreFormFocus(container, focusSnap);
    }
  }

  /**
   * Attach input/change listeners to the currently rendered left-pane form.
   *
   * @summary Resolves `AppStore.state` dynamically inside every event callback so
   *   background `/api/compile` responses that replace `AppStore.state` (`skipForm: true`)
   *   never leave `[x]` delete, `+ Add`, or input handlers bound to a detached state object.
   * @param {HTMLElement} container - Left-pane form container.
   * @param {string} fid - Active `file_id`.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function bindActiveFormEvents(container, fid) {
    // Always resolve the live state object at event time rather than caching across async compiles
    const getState = () => AppStore.state;

    container.querySelector("#btn-focus-dev-user")?.addEventListener("click", () => {
      const userEl = document.getElementById("input-dev-user");
      if (userEl) {
        userEl.scrollIntoView({ behavior: "smooth", block: "center" });
        userEl.focus();
      }
    });

    container.querySelectorAll(".btn-toggle-secret").forEach((btn) => {
      btn.addEventListener("click", () => {
        AppStore.showSecrets = !AppStore.showSecrets;
        renderActiveFormPanel(false);
      });
    });

    if (fid === "admin_settings") {
      const getGw = () => getState().gateway;

      container.querySelector("#gw-enabled")?.addEventListener("change", (e) => {
        getGw().enabled = e.target.checked;
        scheduleFormCompile(false);
      });
      container.querySelector("#gw-url")?.addEventListener("input", (e) => {
        getGw().url = e.target.value;
        getState().gateway_env.url = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#gw-wire")?.addEventListener("change", (e) => {
        getGw().wireProtocol = e.target.value;
        getState().gateway_env.wireProtocol = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#gw-omit-key")?.addEventListener("change", (e) => {
        getGw().omitApiKeyInMdm = e.target.checked;
        renderActiveFormPanel(false);
        scheduleFormCompile(false);
      });
      container.querySelector("#gw-apikey")?.addEventListener("input", (e) => {
        getGw().apiKey = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#gw-cacert")?.addEventListener("input", (e) => {
        getGw().caCertPath = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#gw-default-model")?.addEventListener("input", (e) => {
        getGw().defaultModelId = e.target.value;
        scheduleFormCompile(false);
      });

      const updateHeaderKeyFeedback = () =>
        refreshUniqueKeyFeedback(
          container,
          "[data-gw-hdr-key]",
          "gw-hdr-key-feedback",
          "gateway.customHeaders",
          true
        );
      const updateModelIdFeedback = () =>
        refreshUniqueKeyFeedback(
          container,
          "[data-gw-mdl-id]",
          "gw-mdl-id-feedback",
          "models.list[].modelId",
          false
        );

      updateHeaderKeyFeedback();
      updateModelIdFeedback();

      container.querySelector("#btn-add-gw-header")?.addEventListener("click", () => {
        const headers = getGw().customHeaders;
        const uniqueKey = nextUniqueIdentifier(
          headers.map((h) => h.key),
          "X-Enterprise-Team",
          "X-Custom-Header-"
        );
        const hdrSuffix = uniqueKey.match(/(\d+)$/);
        const defaultVal =
          uniqueKey === "X-Enterprise-Team"
            ? "Platform"
            : `Value-${hdrSuffix ? hdrSuffix[1] : "1"}`;
        headers.push({ key: uniqueKey, value: defaultVal });
        renderActiveFormPanel(false);
        scheduleFormCompile(false);
      });
      container.querySelectorAll("[data-gw-hdr-key]").forEach((inp) => {
        inp.addEventListener("input", () => {
          const idx = Number(inp.dataset.gwHdrKey);
          const headers = getGw().customHeaders;
          if (Array.isArray(headers) && Number.isInteger(idx) && idx >= 0 && idx < headers.length) {
            headers[idx].key = inp.value;
            updateHeaderKeyFeedback();
            scheduleFormCompile(false);
          }
        });
      });
      container.querySelectorAll("[data-gw-hdr-val]").forEach((inp) => {
        inp.addEventListener("input", () => {
          const idx = Number(inp.dataset.gwHdrVal);
          const headers = getGw().customHeaders;
          if (Array.isArray(headers) && Number.isInteger(idx) && idx >= 0 && idx < headers.length) {
            headers[idx].value = inp.value;
            scheduleFormCompile(false);
          }
        });
      });
      container.querySelectorAll("[data-gw-hdr-del]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const idx = Number(btn.dataset.gwHdrDel);
          const headers = getGw().customHeaders;
          if (!Array.isArray(headers) || !Number.isInteger(idx) || idx < 0 || idx >= headers.length) {
            return;
          }
          headers.splice(idx, 1);
          renderActiveFormPanel(false);
          scheduleFormCompile(false);
        });
      });

      container.querySelector("#btn-add-gw-model")?.addEventListener("click", () => {
        const models = getGw().models;
        const uniqueModelId = nextUniqueIdentifier(
          models.map((m) => m.modelId),
          "gemini-3.8-flash",
          "gemini-custom-model-"
        );
        const suffixMatch = uniqueModelId.match(/(\d+)$/);
        const displayName =
          uniqueModelId === "gemini-3.8-flash"
            ? "Gemini 3.8 Flash"
            : `Custom Enterprise Model ${suffixMatch ? suffixMatch[1] : ""}`.trim();
        models.push({ modelId: uniqueModelId, displayName });
        renderActiveFormPanel(false);
        scheduleFormCompile(false);
      });
      container.querySelectorAll("[data-gw-mdl-id]").forEach((inp) => {
        inp.addEventListener("input", () => {
          const idx = Number(inp.dataset.gwMdlId);
          const models = getGw().models;
          if (Array.isArray(models) && Number.isInteger(idx) && idx >= 0 && idx < models.length) {
            models[idx].modelId = inp.value;
            updateModelIdFeedback();
            scheduleFormCompile(false);
          }
        });
      });
      container.querySelectorAll("[data-gw-mdl-name]").forEach((inp) => {
        inp.addEventListener("input", () => {
          const idx = Number(inp.dataset.gwMdlName);
          const models = getGw().models;
          if (Array.isArray(models) && Number.isInteger(idx) && idx >= 0 && idx < models.length) {
            models[idx].displayName = inp.value;
            scheduleFormCompile(false);
          }
        });
      });
      container.querySelectorAll("[data-gw-mdl-del]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const idx = Number(btn.dataset.gwMdlDel);
          const models = getGw().models;
          if (!Array.isArray(models) || !Number.isInteger(idx) || idx < 0 || idx >= models.length) {
            return;
          }
          models.splice(idx, 1);
          renderActiveFormPanel(false);
          scheduleFormCompile(false);
        });
      });
    } else if (fid === "gateway_env") {
      const getGe = () => getState().gateway_env;

      container.querySelector("#env-export-prefix")?.addEventListener("change", (e) => {
        getGe().exportPrefix = e.target.checked;
        scheduleFormCompile(false);
      });
      container.querySelector("#env-url")?.addEventListener("input", (e) => {
        getGe().url = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#env-apikey")?.addEventListener("input", (e) => {
        getGe().apiKey = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#env-wire")?.addEventListener("change", (e) => {
        getGe().wireProtocol = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#env-cacert")?.addEventListener("input", (e) => {
        getGe().caCert = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#env-headers")?.addEventListener("input", (e) => {
        getGe().headers = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#env-models")?.addEventListener("input", (e) => {
        getGe().models = e.target.value;
        scheduleFormCompile(false);
      });
    } else if (fid === "cli_settings") {
      const getCli = () => getState().cli;

      container.querySelector("#cli-agent-mode")?.addEventListener("change", (e) => {
        getCli().agentMode = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#cli-tool-perm")?.addEventListener("change", (e) => {
        getCli().toolPermission = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#cli-artifact-review")?.addEventListener("change", (e) => {
        getCli().artifactReviewPolicy = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#cli-enable-sandbox")?.addEventListener("change", (e) => {
        getCli().enableTerminalSandbox = e.target.checked;
        scheduleFormCompile(false);
      });
      container.querySelector("#cli-non-ws")?.addEventListener("change", (e) => {
        getCli().allowNonWorkspaceAccess = e.target.checked;
        scheduleFormCompile(false);
      });
      container.querySelector("#cli-opt-ui")?.addEventListener("change", (e) => {
        const c = getCli();
        c.includeOptionalUiKeys = e.target.checked;
        if (!c.includeOptionalUiKeys && c.historySize === 50) {
          c.notifications = false;
          c.showFeedbackSurvey = false;
          c.showTips = false;
        }
        renderActiveFormPanel(false);
        scheduleFormCompile(false);
      });
      container.querySelector("#cli-history-size")?.addEventListener("input", (e) => {
        getCli().historySize = e.target.value === "" ? 50 : Number(e.target.value);
        scheduleFormCompile(false);
      });
      container.querySelector("#cli-ui-notif")?.addEventListener("change", (e) => {
        getCli().notifications = e.target.checked;
        scheduleFormCompile(false);
      });
      container.querySelector("#cli-ui-survey")?.addEventListener("change", (e) => {
        getCli().showFeedbackSurvey = e.target.checked;
        scheduleFormCompile(false);
      });
      container.querySelector("#cli-ui-tips")?.addEventListener("change", (e) => {
        getCli().showTips = e.target.checked;
        scheduleFormCompile(false);
      });
      container.querySelector("#cli-sbp-enabled")?.addEventListener("change", (e) => {
        const c = getCli();
        c.sandboxProxyEnabled = e.target.checked;
        if (c.sandboxProxyEnabled && !c.sandboxProxyAddress) {
          c.sandboxProxyAddress = "http://proxy.internal.example.com:3128";
          c.sandboxProxyCertFile = "/etc/antigravity/certs/corp-root-ca.pem";
        }
        if (!c.sandboxProxyEnabled) {
          c.sandboxProxyAddress = "";
          c.sandboxProxyCertFile = "";
        }
        renderActiveFormPanel(false);
        scheduleFormCompile(false);
      });
      container.querySelector("#cli-sbp-addr")?.addEventListener("input", (e) => {
        getCli().sandboxProxyAddress = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#cli-sbp-cert")?.addEventListener("input", (e) => {
        getCli().sandboxProxyCertFile = e.target.value;
        scheduleFormCompile(false);
      });
      bindPermissionsWidgetEvents(container, "cli");
    } else if (fid === "desktop_config") {
      const getDesk = () => getState().desktop;

      container.querySelector("#desk-auto-exec")?.addEventListener("change", (e) => {
        getDesk().autoExecutionPolicy = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#desk-artifact")?.addEventListener("change", (e) => {
        getDesk().artifactReviewMode = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#desk-browser-js")?.addEventListener("change", (e) => {
        getDesk().browserJsExecutionPolicy = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#desk-sandbox")?.addEventListener("change", (e) => {
        getDesk().enableTerminalSandbox = e.target.checked;
        scheduleFormCompile(false);
      });
      container.querySelector("#desk-net")?.addEventListener("change", (e) => {
        getDesk().sandboxAllowNetwork = e.target.checked;
        scheduleFormCompile(false);
      });
      container.querySelector("#desk-nonws-policy")?.addEventListener("change", (e) => {
        getDesk().nonWorkspaceFileAccessPolicy = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#desk-internet-policy")?.addEventListener("change", (e) => {
        getDesk().internetAccessPolicy = e.target.value;
        scheduleFormCompile(false);
      });
      bindPermissionsWidgetEvents(container, "desktop");
    } else if (fid === "browser_allowlist") {
      const domSearchInput = container.querySelector("#input-domain-search");
      if (domSearchInput) {
        domSearchInput.addEventListener("input", () => {
          AppStore.domainFilterQuery = domSearchInput.value;
          renderActiveFormPanel(true);
        });
      }
      const clearDomainSearch = () => {
        AppStore.domainFilterQuery = "";
        renderActiveFormPanel(false);
        document.getElementById("input-domain-search")?.focus();
      };
      container.querySelector("#btn-clear-domain-search")?.addEventListener("click", clearDomainSearch);
      container.querySelector("#btn-empty-clear-domain-search")?.addEventListener("click", clearDomainSearch);

      const addDom = () => {
        const inp = container.querySelector("#input-new-domain");
        const val = (inp?.value || "").trim();
        if (!val) {
          inp?.focus();
          return;
        }
        const domains = getState().browser_domains;
        if (domains.includes(val)) {
          showToast("Hostname is already in the allowlist", "warning");
          inp?.select();
          return;
        }
        domains.push(val);
        const activeQuery = AppStore.domainFilterQuery.trim().toLowerCase();
        if (activeQuery && !val.toLowerCase().includes(activeQuery)) {
          AppStore.domainFilterQuery = "";
          showToast("Added hostname (cleared search filter so it is visible)", "info");
        }
        inp.value = "";
        renderActiveFormPanel(false);
        document.getElementById("input-new-domain")?.focus();
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
          const idx = Number(btn.dataset.delDomain);
          const domains = getState().browser_domains;
          if (!Array.isArray(domains) || !Number.isInteger(idx) || idx < 0 || idx >= domains.length) {
            return;
          }
          domains.splice(idx, 1);
          renderActiveFormPanel(false);
          scheduleFormCompile(false);
        });
      });
    } else if (fid === "mcp_config") {
      const mcpSearchInput = container.querySelector("#input-mcp-search");
      if (mcpSearchInput) {
        mcpSearchInput.addEventListener("input", () => {
          AppStore.mcpFilterQuery = mcpSearchInput.value;
          renderActiveFormPanel(true);
        });
      }
      const clearMcpSearch = () => {
        AppStore.mcpFilterQuery = "";
        renderActiveFormPanel(false);
        document.getElementById("input-mcp-search")?.focus();
      };
      container.querySelector("#btn-clear-mcp-search")?.addEventListener("click", clearMcpSearch);
      container.querySelector("#btn-empty-clear-mcp-search")?.addEventListener("click", clearMcpSearch);

      const syncBulkExpandButtons = () => {
        const cardEls = Array.from(container.querySelectorAll(".mcp-server-card[data-mcp-card]"));
        const expSet = getMcpExpandedSet((getState().mcp_servers || []).length);
        const visibleOpen = cardEls.filter((el) => expSet.has(Number(el.dataset.mcpCard))).length;
        const expandAllBtn = container.querySelector("#btn-mcp-expand-all");
        const collapseAllBtn = container.querySelector("#btn-mcp-collapse-all");
        if (expandAllBtn) {
          expandAllBtn.disabled = cardEls.length === 0 || visibleOpen === cardEls.length;
        }
        if (collapseAllBtn) {
          collapseAllBtn.disabled = cardEls.length === 0 || visibleOpen === 0;
        }
      };

      container.querySelectorAll("[data-mcp-toggle]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const idx = Number(btn.dataset.mcpToggle);
          const servers = getState().mcp_servers || [];
          const expSet = getMcpExpandedSet(servers.length);
          const nextOpen = !expSet.has(idx);
          if (nextOpen) {
            expSet.add(idx);
          } else {
            expSet.delete(idx);
          }
          const cardEl = container.querySelector(`[data-mcp-card="${idx}"]`);
          const bodyEl = container.querySelector(`[data-mcp-body="${idx}"]`);
          cardEl?.classList.toggle("is-expanded", nextOpen);
          bodyEl?.classList.toggle("d-none", !nextOpen);
          btn.setAttribute("aria-expanded", nextOpen ? "true" : "false");
          btn.title = nextOpen ? "Collapse server configuration" : "Expand server configuration";
          syncBulkExpandButtons();
        });
      });

      container.querySelector("#btn-mcp-expand-all")?.addEventListener("click", () => {
        const servers = getState().mcp_servers || [];
        const expSet = getMcpExpandedSet(servers.length);
        container.querySelectorAll(".mcp-server-card[data-mcp-card]").forEach((cardEl) => {
          const idx = Number(cardEl.dataset.mcpCard);
          expSet.add(idx);
          cardEl.classList.add("is-expanded");
          container.querySelector(`[data-mcp-body="${idx}"]`)?.classList.remove("d-none");
          const tBtn = container.querySelector(`[data-mcp-toggle="${idx}"]`);
          if (tBtn) {
            tBtn.setAttribute("aria-expanded", "true");
            tBtn.title = "Collapse server configuration";
          }
        });
        syncBulkExpandButtons();
      });

      container.querySelector("#btn-mcp-collapse-all")?.addEventListener("click", () => {
        const servers = getState().mcp_servers || [];
        const expSet = getMcpExpandedSet(servers.length);
        container.querySelectorAll(".mcp-server-card[data-mcp-card]").forEach((cardEl) => {
          const idx = Number(cardEl.dataset.mcpCard);
          expSet.delete(idx);
          cardEl.classList.remove("is-expanded");
          container.querySelector(`[data-mcp-body="${idx}"]`)?.classList.add("d-none");
          const tBtn = container.querySelector(`[data-mcp-toggle="${idx}"]`);
          if (tBtn) {
            tBtn.setAttribute("aria-expanded", "false");
            tBtn.title = "Expand server configuration";
          }
        });
        syncBulkExpandButtons();
      });

      const updateMcpNameFeedback = () =>
        refreshUniqueKeyFeedback(
          container,
          "[data-mcp-name]",
          "mcp-name-feedback",
          "mcpServers",
          false
        );
      updateMcpNameFeedback();

      container.querySelector("#btn-add-mcp")?.addEventListener("click", () => {
        const servers = getState().mcp_servers;
        const expSet = getMcpExpandedSet(servers.length);
        const uniqueServerName = nextUniqueIdentifier(
          servers.map((srv) => srv.name),
          "",
          "corp_server_"
        );
        servers.push({
          name: uniqueServerName,
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
        const newIdx = servers.length - 1;
        expSet.add(newIdx);
        if (AppStore.mcpFilterQuery.trim()) {
          AppStore.mcpFilterQuery = "";
        }
        renderActiveFormPanel(false);
        const nameInp = container.querySelector(`[data-mcp-name="${newIdx}"]`);
        if (nameInp) {
          nameInp.scrollIntoView({ behavior: "smooth", block: "nearest" });
          nameInp.focus();
          nameInp.select();
        }
        scheduleFormCompile(false);
      });
      container.querySelectorAll("[data-mcp-name]").forEach((inp) => {
        inp.addEventListener("input", () => {
          const idx = Number(inp.dataset.mcpName);
          const servers = getState().mcp_servers;
          if (Array.isArray(servers) && Number.isInteger(idx) && idx >= 0 && idx < servers.length) {
            servers[idx].name = inp.value;
            syncMcpCardHeaderDom(container, idx, servers[idx]);
            updateMcpNameFeedback();
            scheduleFormCompile(false);
          }
        });
      });
      container.querySelectorAll("[data-mcp-transport]").forEach((sel) => {
        sel.addEventListener("change", () => {
          const idx = Number(sel.dataset.mcpTransport);
          const servers = getState().mcp_servers;
          if (Array.isArray(servers) && Number.isInteger(idx) && idx >= 0 && idx < servers.length) {
            servers[idx].transport = sel.value;
            getMcpExpandedSet(servers.length).add(idx);
            renderActiveFormPanel(false);
            scheduleFormCompile(false);
          }
        });
      });
      container.querySelectorAll("[data-mcp-enabled]").forEach((chk) => {
        chk.addEventListener("change", () => {
          const idx = Number(chk.dataset.mcpEnabled);
          const servers = getState().mcp_servers;
          if (Array.isArray(servers) && Number.isInteger(idx) && idx >= 0 && idx < servers.length) {
            servers[idx].disabled = !chk.checked;
            renderActiveFormPanel(false);
            scheduleFormCompile(false);
          }
        });
      });
      container.querySelectorAll("[data-mcp-del]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const idx = Number(btn.dataset.mcpDel);
          const servers = getState().mcp_servers;
          if (!Array.isArray(servers) || !Number.isInteger(idx) || idx < 0 || idx >= servers.length) {
            return;
          }
          if (AppStore.mcpExpandedIndices instanceof Set) {
            const shifted = new Set();
            AppStore.mcpExpandedIndices.forEach((openIdx) => {
              if (openIdx < idx) {
                shifted.add(openIdx);
              } else if (openIdx > idx) {
                shifted.add(openIdx - 1);
              }
            });
            AppStore.mcpExpandedIndices = shifted;
          }
          servers.splice(idx, 1);
          renderActiveFormPanel(false);
          scheduleFormCompile(false);
        });
      });
      container.querySelectorAll("[data-mcp-url]").forEach((inp) => {
        inp.addEventListener("input", () => {
          const idx = Number(inp.dataset.mcpUrl);
          const servers = getState().mcp_servers;
          if (Array.isArray(servers) && Number.isInteger(idx) && idx >= 0 && idx < servers.length) {
            servers[idx].serverUrl = inp.value;
            syncMcpCardHeaderDom(container, idx, servers[idx]);
            scheduleFormCompile(false);
          }
        });
      });
      container.querySelectorAll("[data-mcp-cmd]").forEach((inp) => {
        inp.addEventListener("input", () => {
          const idx = Number(inp.dataset.mcpCmd);
          const servers = getState().mcp_servers;
          if (Array.isArray(servers) && Number.isInteger(idx) && idx >= 0 && idx < servers.length) {
            servers[idx].command = inp.value;
            syncMcpCardHeaderDom(container, idx, servers[idx]);
            scheduleFormCompile(false);
          }
        });
      });
      container.querySelectorAll("[data-mcp-args]").forEach((inp) => {
        inp.addEventListener("input", () => {
          const idx = Number(inp.dataset.mcpArgs);
          const servers = getState().mcp_servers;
          if (Array.isArray(servers) && Number.isInteger(idx) && idx >= 0 && idx < servers.length) {
            servers[idx].args = inp.value
              .split(",")
              .map((x) => x.trim())
              .filter(Boolean);
            syncMcpCardHeaderDom(container, idx, servers[idx]);
            scheduleFormCompile(false);
          }
        });
      });
      container.querySelectorAll("[data-mcp-timeout]").forEach((inp) => {
        inp.addEventListener("input", () => {
          const idx = Number(inp.dataset.mcpTimeout);
          const servers = getState().mcp_servers;
          if (Array.isArray(servers) && Number.isInteger(idx) && idx >= 0 && idx < servers.length) {
            const rawVal = inp.value.trim();
            servers[idx].timeoutSeconds = rawVal === "" ? null : Number(rawVal);
            scheduleFormCompile(false);
          }
        });
      });
      container.querySelectorAll("[data-mcp-allow]").forEach((inp) => {
        inp.addEventListener("input", () => {
          const idx = Number(inp.dataset.mcpAllow);
          const servers = getState().mcp_servers;
          if (Array.isArray(servers) && Number.isInteger(idx) && idx >= 0 && idx < servers.length) {
            servers[idx].enabledTools = inp.value
              .split(",")
              .map((x) => x.trim())
              .filter(Boolean);
            syncMcpCardHeaderDom(container, idx, servers[idx]);
            scheduleFormCompile(false);
          }
        });
      });
      container.querySelectorAll("[data-mcp-deny]").forEach((inp) => {
        inp.addEventListener("input", () => {
          const idx = Number(inp.dataset.mcpDeny);
          const servers = getState().mcp_servers;
          if (Array.isArray(servers) && Number.isInteger(idx) && idx >= 0 && idx < servers.length) {
            servers[idx].disabledTools = inp.value
              .split(",")
              .map((x) => x.trim())
              .filter(Boolean);
            syncMcpCardHeaderDom(container, idx, servers[idx]);
            scheduleFormCompile(false);
          }
        });
      });
    } else if (fid === "hooks_config") {
      const getHooks = () => getState().hooks;

      container.querySelector("#hook-pre-en")?.addEventListener("change", (e) => {
        getHooks().enablePreToolUse = e.target.checked;
        renderActiveFormPanel(false);
        scheduleFormCompile(false);
      });
      container.querySelector("#hook-pre-matcher")?.addEventListener("input", (e) => {
        getHooks().preMatcher = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#hook-pre-cmd")?.addEventListener("input", (e) => {
        getHooks().preCommand = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#hook-pre-timeout")?.addEventListener("input", (e) => {
        getHooks().preTimeout = Number(e.target.value || 10);
        scheduleFormCompile(false);
      });
      container.querySelector("#hook-post-en")?.addEventListener("change", (e) => {
        getHooks().enablePostToolUse = e.target.checked;
        renderActiveFormPanel(false);
        scheduleFormCompile(false);
      });
      container.querySelector("#hook-post-matcher")?.addEventListener("input", (e) => {
        getHooks().postMatcher = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#hook-post-cmd")?.addEventListener("input", (e) => {
        getHooks().postCommand = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#hook-post-timeout")?.addEventListener("input", (e) => {
        getHooks().postTimeout = Number(e.target.value || 10);
        scheduleFormCompile(false);
      });
      container.querySelector("#hook-banner-en")?.addEventListener("change", (e) => {
        getHooks().enableSessionStartBanner = e.target.checked;
        renderActiveFormPanel(false);
        scheduleFormCompile(false);
      });
      container.querySelector("#hook-banner-txt")?.addEventListener("input", (e) => {
        getHooks().sessionBannerText = e.target.value;
        scheduleFormCompile(false);
      });
    } else if (fid === "guard_sh" || fid === "guard_ps1") {
      container.querySelector("#btn-reset-guard-script")?.addEventListener("click", async () => {
        try {
          await flushPendingSync();
          const fresh = await postJson("/api/preset", {
            preset_id: "balanced",
            dev_user: getState().dev_user,
          });
          getState().scripts[fid] = fresh.state.scripts[fid];
          renderActiveFormPanel(false);
          scheduleFormCompile(false);
          showToast("Guard script restored to canonical default", "success");
        } catch (err) {
          showToast(err.message, "danger");
        }
      });
    } else if (fid === "acp_json") {
      container.querySelector("#acp-cmd")?.addEventListener("input", (e) => {
        getState().acp.command = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#acp-args")?.addEventListener("input", (e) => {
        const parsedArgs = e.target.value
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean);
        getState().acp.args = parsedArgs.length ? parsedArgs : ["acp"];
        scheduleFormCompile(false);
      });
      container.querySelector("#acp-gw-url")?.addEventListener("input", (e) => {
        getState().gateway.url = e.target.value;
        getState().gateway_env.url = e.target.value;
        scheduleFormCompile(false);
      });
      container.querySelector("#acp-gw-wire")?.addEventListener("change", (e) => {
        getState().gateway.wireProtocol = e.target.value;
        getState().gateway_env.wireProtocol = e.target.value;
        scheduleFormCompile(false);
      });
    } else if (fid === "acp_auth") {
      container.querySelector("#acp-auth-type")?.addEventListener("change", (e) => {
        getState().acp.authType = e.target.value;
        scheduleFormCompile(false);
      });
    }
  }

  /**
   * Switch the active editor and form pane to a specific policy file ID.
   *
   * @summary Used by clickable `.studio-jump-pill` badges inside the Validation Drawer
   *   so admins can jump straight to any file reporting an error or warning.
   * @param {string} targetFid - Target `file_id` from `CATALOG_BY_ID`.
   * @returns {Promise<void>} Resolves once pending sync is flushed and panels update.
   * @throws {never} Never throws.
   */
  async function jumpToPolicyFile(targetFid) {
    if (!targetFid || !CATALOG_BY_ID[targetFid] || !AppStore.activeFileIds.includes(targetFid)) {
      return;
    }
    await flushPendingSync();
    AppStore.selectedFileId = targetFid;
    const activeSelect = document.getElementById("active-file-selector");
    if (activeSelect) {
      activeSelect.value = targetFid;
      syncStudioSingleSelects(activeSelect);
    }
    renderFileReferenceCard(true);
    renderActiveFormPanel(false);
    renderEditorPane();
    renderValidationDrawer();
  }

  /**
   * Update ONLY the right-pane header without resetting cursor focus in `#code-editor`.
   *
   * @summary Updates active filename, per-file status pill (`#active-file-status-pill`),
   *   bundle validation badge (`#global-validation-badge`), and Auto-Fix All button.
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

    const activePill = document.getElementById("active-file-status-pill");
    const badge = document.getElementById("global-validation-badge");
    const fixAllBtn = document.getElementById("btn-fix-all");
    const v = AppStore.validation;
    const multiFileBundle = (AppStore.activeFileIds || []).length > 1;

    if (activePill) {
      if (multiFileBundle && fid && v) {
        const fileIssues = (v.issues_by_file && v.issues_by_file[fid]) || [];
        const fErr = fileIssues.filter((i) => i.severity === "ERROR").length;
        const fWarn = fileIssues.filter((i) => i.severity === "WARN").length;
        if (fErr > 0) {
          activePill.className = "badge rounded-pill status-badge-error px-2 py-1";
          activePill.textContent = `This File: ${fErr} Error(s)`;
        } else if (fWarn > 0) {
          activePill.className = "badge rounded-pill status-badge-warn px-2 py-1";
          activePill.textContent = `This File: ${fWarn} Warn`;
        } else {
          activePill.className = "badge rounded-pill status-badge-pass px-2 py-1";
          activePill.textContent = "This File: PASS";
        }
      } else {
        activePill.className = "badge rounded-pill px-2 py-1 d-none";
      }
    }

    if (badge && v) {
      const prefix = multiFileBundle ? "Bundle · " : "";
      if (v.error_count > 0) {
        badge.className = "badge rounded-pill status-badge-error px-2 py-1";
        badge.textContent = `${prefix}ERROR · ${v.error_count} Error(s), ${v.warn_count} Warn`;
      } else if (v.warn_count > 0) {
        badge.className = "badge rounded-pill status-badge-warn px-2 py-1";
        badge.textContent = `${prefix}WARN · ${v.warn_count} Warning(s)`;
      } else {
        badge.className = "badge rounded-pill status-badge-pass px-2 py-1";
        badge.textContent = `${prefix}PASS · Valid`;
      }
    }
    if (fixAllBtn && v) {
      fixAllBtn.classList.toggle("d-none", !(v.fixable_count > 0));
      fixAllBtn.textContent = `Auto-Fix All (${v.fixable_count})`;
    }
    refreshSyncPillForSelectedFile();
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
      if (editor.value !== content) {
        editor.value = content;
      }
      updateEditorGutter(content);
    }
  }

  /**
   * Render the Right-Pane Real-Time Validation Drawer.
   *
   * @summary Displays PASS status, cross-file bundle issue jump pills when the
   *   active file passes while sibling files have findings, or actionable
   *   per-issue `Auto-Fix` buttons.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function renderValidationDrawer() {
    const countEl = document.getElementById("drawer-issue-count");
    const drawer = document.getElementById("drawer-content");
    if (!drawer) {
      return;
    }

    const scopeSelect = document.getElementById("select-validation-scope");
    const showAll = scopeSelect?.value === "all";
    const v = AppStore.validation || { issues_by_file: {}, all_issues: [] };
    const scopedIssues = showAll
      ? v.all_issues || []
      : (v.issues_by_file && v.issues_by_file[AppStore.selectedFileId]) || [];

    if (countEl) {
      countEl.textContent = String(
        scopedIssues.filter((i) => i.severity !== "INFO").length
      );
    }

    const bindJumpAndShowAllHandlers = () => {
      drawer.querySelectorAll("[data-jump-fid]").forEach((pillBtn) => {
        pillBtn.addEventListener("click", () => {
          jumpToPolicyFile(pillBtn.dataset.jumpFid);
        });
      });
      drawer.querySelector("#btn-drawer-show-all")?.addEventListener("click", () => {
        if (scopeSelect) {
          scopeSelect.value = "all";
          syncStudioSingleSelects(scopeSelect);
          renderValidationDrawer();
        }
      });
    };

    if (!scopedIssues.length) {
      const otherActionable = !showAll
        ? (v.all_issues || []).filter(
            (i) =>
              i.file_id !== AppStore.selectedFileId &&
              (i.severity === "ERROR" || i.severity === "WARN")
          )
        : [];

      let crossFileBannerHtml = "";
      if (otherActionable.length > 0) {
        const byFid = {};
        otherActionable.forEach((iss) => {
          byFid[iss.file_id] = (byFid[iss.file_id] || 0) + 1;
        });
        const jumpPillsHtml = Object.keys(byFid)
          .map((fidKey) => {
            const fn = CATALOG_BY_ID[fidKey]?.filename || fidKey;
            return `<button type="button" class="studio-jump-pill" data-jump-fid="${escapeHtml(fidKey)}" title="Switch to ${escapeHtml(fn)}">${escapeHtml(fn)} (${byFid[fidKey]})</button>`;
          })
          .join(" ");

        crossFileBannerHtml = `
          <div class="mt-2 p-2 rounded studio-subcard d-flex flex-wrap align-items-center justify-content-between gap-2" style="font-size: 0.75rem;">
            <div class="d-flex flex-wrap align-items-center gap-1">
              <span class="text-body-secondary">Other selected bundle files have <strong>${otherActionable.length}</strong> finding(s):</span>
              ${jumpPillsHtml}
            </div>
            <button type="button" id="btn-drawer-show-all" class="btn btn-sm btn-outline-primary py-0 px-2" style="font-size: 0.72rem;">Show All Selected Files</button>
          </div>`;
      }

      const activeFn = CATALOG_BY_ID[AppStore.selectedFileId]?.filename || "Active file";
      const passSubject = showAll ? "All selected files" : escapeHtml(activeFn);
      drawer.innerHTML = `
        <div class="d-flex align-items-center gap-2 p-2 rounded status-badge-pass">
          <strong>PASS (${passSubject}):</strong>
          <span>Zero schema, UTF-8 BOM, sandbox mount, or cross-OS runtime issues detected.</span>
        </div>
        ${crossFileBannerHtml}`;
      bindJumpAndShowAllHandlers();
      return;
    }

    drawer.innerHTML = scopedIssues
      .map((issue) => {
        const fMeta = CATALOG_BY_ID[issue.file_id];
        const fileTag =
          showAll && fMeta
            ? `<button type="button" class="studio-jump-pill me-1" data-jump-fid="${escapeHtml(issue.file_id)}" title="Switch editor to ${escapeHtml(fMeta.filename)}">${escapeHtml(fMeta.filename)}</button>`
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
              <div class="fw-semibold d-flex flex-wrap align-items-center gap-1" style="font-size:0.8rem;">
                <span class="badge ${issue.severity === "ERROR" ? "text-bg-danger" : issue.severity === "WARN" ? "text-bg-warning" : "text-bg-info"} me-1">${escapeHtml(issue.severity)}</span>
                ${fileTag}<span>${escapeHtml(issue.title)}${lineTag}</span>
              </div>
              <div class="text-body-secondary mt-1" style="font-size:0.76rem;">${escapeHtml(issue.message)}</div>
            </div>
            ${fixBtn}
          </div>`;
      })
      .join("");

    bindJumpAndShowAllHandlers();

    drawer.querySelectorAll("[data-autofix-code]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const targetFid = btn.dataset.autofixFid;
        const code = btn.dataset.autofixCode;
        try {
          await flushPendingSync();
          AppStore.activeAbortController?.abort();
          AppStore.syncSeq += 1;
          const res = await postJson("/api/autofix", {
            file_id: targetFid,
            issue_code: code,
            content: AppStore.files[targetFid] || "",
            state: AppStore.state,
          });
          delete AppStore.unparsedCodeFiles[targetFid];
          AppStore.selectedFileId = targetFid;
          applyServerPayload(res);
          refreshSyncPillForSelectedFile();
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
   * Update `AppStore.state.dev_user` and rewrite workspace user home paths in permissions.
   *
   * @summary Preserves empty username state when `#input-dev-user` is cleared
   *   (using `UNSET_USER_TOKEN` inside permission path templates so mandatory
   *   validation flags user-scoped files) and rewrites `/home/<prev>/` and
   *   `/Users/<prev>/` cleanly whenever a valid username is entered or changed.
   * @param {string} rawValue - Raw string value from `#input-dev-user`.
   * @param {boolean} isBlur - True when triggered on input blur.
   * @returns {void} Returns nothing.
   * @throws {never} Never throws.
   */
  function applyWorkstationUserChange(rawValue, isBlur) {
    const nextUser = String(rawValue ?? "").trim();
    const prevUser = String(AppStore.lastDevUser ?? "").trim();
    const currentUser = String(AppStore.state.dev_user ?? "").trim();

    if (nextUser === currentUser) {
      if (isBlur) {
        const userEl = document.getElementById("input-dev-user");
        if (userEl && userEl.value !== nextUser) {
          userEl.value = nextUser;
        }
      }
      renderWorkstationUserStatus();
      return;
    }

    const isNextSyntacticallyValid =
      !nextUser || validateWorkstationUsernameClient(nextUser) === null;

    if (isNextSyntacticallyValid) {
      const oldToken = prevUser || UNSET_USER_TOKEN;
      const nextToken = nextUser || UNSET_USER_TOKEN;
      if (oldToken !== nextToken) {
        const swapUserPaths = (arr) =>
          (arr || []).map((r) =>
            String(r)
              .replace(`/home/${oldToken}/`, `/home/${nextToken}/`)
              .replace(`/Users/${oldToken}/`, `/Users/${nextToken}/`)
              .replace(`/home/${UNSET_USER_TOKEN}/`, `/home/${nextToken}/`)
              .replace(`/Users/${UNSET_USER_TOKEN}/`, `/Users/${nextToken}/`)
          );
        ["allow", "ask", "deny"].forEach((b) => {
          AppStore.state.cli.permissions[b] = swapUserPaths(AppStore.state.cli.permissions[b]);
          AppStore.state.desktop.permissions[b] = swapUserPaths(AppStore.state.desktop.permissions[b]);
        });
      }
      AppStore.lastDevUser = nextUser;
    }

    AppStore.state.dev_user = nextUser;
    if (isBlur) {
      const userEl = document.getElementById("input-dev-user");
      if (userEl && userEl.value !== nextUser) {
        userEl.value = nextUser;
      }
    }
    renderWorkstationUserStatus();
    scheduleFormCompile(true, { keepCurrentUnparsed: true });
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

    // Upgrade all static/modal <select class="form-select"> elements to custom Studio dropdowns
    syncStudioSingleSelects(document);

    // Guard #form-panel-container against mid-click DOM replacement between mousedown and mouseup
    const formPanelEl = document.getElementById("form-panel-container");
    const markFormPointerDown = () => {
      AppStore.isPointerDownInForm = true;
    };
    const releaseFormPointerLatch = () => {
      if (!AppStore.isPointerDownInForm && !AppStore.deferredFormRender) {
        return;
      }
      AppStore.isPointerDownInForm = false;
      if (AppStore.deferredFormRender) {
        // Queue after mouseup + click complete in the current event turn
        setTimeout(() => {
          if (AppStore.deferredFormRender && !AppStore.isPointerDownInForm) {
            renderActiveFormPanel(true);
          }
        }, 0);
      }
    };
    formPanelEl?.addEventListener("pointerdown", markFormPointerDown);
    formPanelEl?.addEventListener("mousedown", markFormPointerDown);
    window.addEventListener("pointerup", releaseFormPointerLatch, true);
    window.addEventListener("pointercancel", releaseFormPointerLatch, true);
    window.addEventListener("mouseup", releaseFormPointerLatch, true);

    // Sync fixed-strategy Popper multi-select & single-select dropdown widths & viewport height
    document.querySelectorAll(".studio-multiselect-btn").forEach((btn) => {
      btn.parentElement?.addEventListener("show.bs.dropdown", () => {
        syncDropdownMenuGeometry(btn);
      });
      btn.parentElement?.addEventListener("shown.bs.dropdown", () => {
        syncDropdownMenuGeometry(btn);
      });
    });

    const syncOpenDropdowns = () => {
      document
        .querySelectorAll(
          ".studio-multiselect-btn[aria-expanded='true'], .studio-singleselect-btn[aria-expanded='true']"
        )
        .forEach((btn) => {
          syncDropdownMenuGeometry(btn);
        });
    };

    window.addEventListener("resize", syncOpenDropdowns);
    document
      .querySelector(".left-scroll-area")
      ?.addEventListener("scroll", syncOpenDropdowns, { passive: true });

    // Reset Scope button
    document.getElementById("btn-reset-scope")?.addEventListener("click", () => {
      clearTimeout(AppStore.codeSyncTimer);
      clearTimeout(AppStore.formSyncTimer);
      AppStore.codeSyncTimer = null;
      AppStore.formSyncTimer = null;
      AppStore.pendingCodeSync = null;
      AppStore.pendingFormSync = null;
      AppStore.activeAbortController?.abort();
      AppStore.syncSeq += 1;
      AppStore.unparsedCodeFiles = {};
      AppStore.fileDetailsExpanded = false;
      AppStore.fileLockExpanded = false;
      AppStore.permFilterQuery = "";
      AppStore.domainFilterQuery = "";
      AppStore.mcpFilterQuery = "";
      AppStore.mcpExpandedIndices = null;
      AppStore.state.os_list = [];
      AppStore.state.surfaces = [];
      AppStore.state.selected_file_ids = [];
      AppStore.availableFileIds = [];
      AppStore.activeFileIds = [];
      AppStore.selectedFileId = "";
      renderAllPanels();
      showToast("Reset OS, Surface, and File scope", "info");
    });

    // Step 1: Target OS Multi-Select Checkboxes & Select All / Clear
    const updateOsFromDom = async () => {
      const checked = [];
      document.querySelectorAll("[data-os-value]").forEach((chk) => {
        if (chk.checked) {
          checked.push(chk.dataset.osValue);
        }
      });
      await flushPendingSync();
      AppStore.state.os_list = checked;
      renderStep1Controls();
      scheduleFormCompile(true, { keepCurrentUnparsed: true });
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
    const updateSurfacesFromDom = async () => {
      const checked = [];
      document.querySelectorAll("[data-surface-value]").forEach((chk) => {
        if (chk.checked) {
          checked.push(chk.dataset.surfaceValue);
        }
      });
      await flushPendingSync();
      AppStore.state.surfaces = checked;
      renderStep1Controls();
      scheduleFormCompile(true, { keepCurrentUnparsed: true });
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
    const devUserInput = document.getElementById("input-dev-user");
    devUserInput?.addEventListener("input", (e) => {
      applyWorkstationUserChange(e.target.value, false);
    });
    devUserInput?.addEventListener("blur", (e) => {
      applyWorkstationUserChange(e.target.value, true);
    });

    document.getElementById("select-perm-sync")?.addEventListener("change", async (e) => {
      const nextLinked = e.target.value === "linked";
      await flushPendingSync();
      AppStore.state.sync_permissions = nextLinked;
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
      const presetText = e.target.selectedOptions[0]?.text || presetId;
      try {
        clearTimeout(AppStore.codeSyncTimer);
        clearTimeout(AppStore.formSyncTimer);
        AppStore.codeSyncTimer = null;
        AppStore.formSyncTimer = null;
        AppStore.pendingCodeSync = null;
        AppStore.pendingFormSync = null;
        AppStore.activeAbortController?.abort();
        AppStore.syncSeq += 1;

        const res = await postJson("/api/preset", {
          preset_id: presetId,
          dev_user: AppStore.state.dev_user,
          preserve_scope: true,
          os_list: AppStore.state.os_list,
          surfaces: AppStore.state.surfaces,
          selected_file_ids: AppStore.state.selected_file_ids,
        });
        applyServerPayload(res, { resetUnparsed: true });
        refreshSyncPillForSelectedFile();
        showToast(`Loaded policy preset: ${presetText}`, "primary");
      } catch (err) {
        showToast(err.message, "danger");
      }
    });

    // Step 2: Target Config Files Select All / Clear
    document.getElementById("btn-files-select-all")?.addEventListener("click", async () => {
      await flushPendingSync();
      AppStore.state.selected_file_ids = [...AppStore.availableFileIds];
      if (!AppStore.selectedFileId && AppStore.availableFileIds.length > 0) {
        AppStore.selectedFileId = AppStore.availableFileIds[0];
      }
      scheduleFormCompile(true, { keepCurrentUnparsed: true });
    });
    document.getElementById("btn-files-clear")?.addEventListener("click", async () => {
      await flushPendingSync();
      AppStore.unparsedCodeFiles = {};
      AppStore.state.selected_file_ids = [];
      AppStore.selectedFileId = "";
      scheduleFormCompile(true);
    });

    // Step 2: Currently Editing File single-select dropdown
    document.getElementById("active-file-selector")?.addEventListener("change", async (e) => {
      const nextFileId = e.target.value;
      await flushPendingSync();
      AppStore.selectedFileId = nextFileId;
      renderFileReferenceCard(true);
      renderActiveFormPanel(false);
      renderEditorPane();
      renderValidationDrawer();
    });

    // Step 3A: Collapsible File Details & Manual Permissions / Lock CLI
    document.getElementById("btn-toggle-file-details")?.addEventListener("click", () => {
      AppStore.fileDetailsExpanded = !AppStore.fileDetailsExpanded;
      renderFileReferenceCard(AppStore.activeFileIds.length > 0);
    });

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
        await flushPendingSync();
        AppStore.activeAbortController?.abort();
        AppStore.syncSeq += 1;
        const res = await postJson("/api/autofix", {
          file_id: "ALL_FILES",
          issue_code: "ALL",
          files: AppStore.files,
          state: AppStore.state,
        });
        applyServerPayload(res, { resetUnparsed: true });
        refreshSyncPillForSelectedFile();
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
        const editedFileId = AppStore.selectedFileId;
        if (!editedFileId) {
          return;
        }
        const raw = editor.value;
        AppStore.files[editedFileId] = raw;
        updateEditorGutter(raw);
        scheduleCodeSync(editedFileId, raw);
      });

      editor.addEventListener("blur", () => {
        if (AppStore.pendingCodeSync) {
          flushPendingSync();
        }
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
          delete AppStore.unparsedCodeFiles[fid];
          AppStore.files[fid] = pretty;
          renderEditorPane();
          scheduleCodeSync(fid, pretty);
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
      await flushPendingSync();
      const fid = AppStore.selectedFileId;
      const meta = CATALOG_BY_ID[fid];
      if (!meta) {
        return;
      }
      const devUser = String(AppStore.state.dev_user ?? "").trim();
      if (meta.requires_user) {
        const userErr = validateWorkstationUsernameClient(devUser);
        if (userErr) {
          renderWorkstationUserStatus();
          const userEl = document.getElementById("input-dev-user");
          userEl?.scrollIntoView({ behavior: "smooth", block: "center" });
          userEl?.focus();
          showToast(
            `Workstation Username is required before exporting '${meta.filename}'.`,
            "danger"
          );
          return;
        }
      }
      try {
        const resp = await fetch("/api/download-file", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            file_id: fid,
            content: AppStore.files[fid] || "",
            dev_user: devUser,
          }),
        });
        if (!resp.ok) {
          let errMsg = "Failed to download file";
          try {
            const errJson = await resp.json();
            if (errJson && errJson.error) {
              errMsg = errJson.error;
            }
          } catch (_ignore) {
            // Keep default fallback message when body is non-JSON
          }
          throw new Error(errMsg);
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
      await flushPendingSync();
      if (!AppStore.activeFileIds.length) {
        return;
      }
      const uState = getWorkstationUserState();
      if (uState.isBlocking) {
        renderWorkstationUserStatus();
        const userEl = document.getElementById("input-dev-user");
        userEl?.scrollIntoView({ behavior: "smooth", block: "center" });
        userEl?.focus();
        showToast(uState.errorMessage || "Enter a valid Workstation Username before exporting.", "danger");
        return;
      }
      try {
        const resp = await fetch("/api/download-zip", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ state: AppStore.state }),
        });
        if (!resp.ok) {
          let errMsg = "Failed to build MDM ZIP bundle";
          try {
            const errJson = await resp.json();
            if (errJson && errJson.error) {
              errMsg = errJson.error;
            }
          } catch (_ignore) {
            // Keep default fallback message when body is non-JSON
          }
          throw new Error(errMsg);
        }
        const blob = await resp.blob();
        triggerBrowserDownload(blob, "antigravity-mdm-policy-bundle.zip");
        showToast("Downloaded antigravity-mdm-policy-bundle.zip", "success");
      } catch (err) {
        showToast(err.message, "danger");
      }
    });

    // Validation Drawer Scope Dropdown & Right-Pane Header Status Pills
    document.getElementById("select-validation-scope")?.addEventListener("change", () => {
      renderValidationDrawer();
    });

    const toggleBundleValidationScope = () => {
      const scopeSel = document.getElementById("select-validation-scope");
      if (!scopeSel) {
        return;
      }
      scopeSel.value = scopeSel.value === "all" ? "active" : "all";
      syncStudioSingleSelects(scopeSel);
      renderValidationDrawer();
    };

    const globalValBadge = document.getElementById("global-validation-badge");
    globalValBadge?.addEventListener("click", toggleBundleValidationScope);
    globalValBadge?.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        toggleBundleValidationScope();
      }
    });

    document.getElementById("active-file-status-pill")?.addEventListener("click", () => {
      const scopeSel = document.getElementById("select-validation-scope");
      if (scopeSel) {
        scopeSel.value = "active";
        syncStudioSingleSelects(scopeSel);
        renderValidationDrawer();
      }
    });

    // Top-Bar Reference Guide Modal Section, OS & Quick Search Controls
    document.getElementById("select-ref-section")?.addEventListener("change", (e) => {
      AppStore.refModalSection = e.target.value;
      renderReferenceGuideModal();
    });

    document.getElementById("select-ref-cli-os")?.addEventListener("change", (e) => {
      AppStore.refModalCliOs = e.target.value;
      renderReferenceGuideModal();
    });

    document.getElementById("input-ref-search")?.addEventListener("input", (e) => {
      AppStore.refFilterQuery = e.target.value;
      renderReferenceGuideModal();
    });

    document.getElementById("btn-clear-ref-search")?.addEventListener("click", () => {
      AppStore.refFilterQuery = "";
      renderReferenceGuideModal();
      document.getElementById("input-ref-search")?.focus();
    });

    document.getElementById("referenceGuideModal")?.addEventListener("show.bs.modal", () => {
      if (AppStore.state.os_list.length === 1) {
        AppStore.refModalCliOs = AppStore.state.os_list[0];
        const osSel = document.getElementById("select-ref-cli-os");
        if (osSel) {
          osSel.value = AppStore.refModalCliOs;
          syncStudioSingleSelects(osSel);
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
      await flushPendingSync();
      AppStore.activeAbortController?.abort();
      AppStore.syncSeq += 1;
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
        applyServerPayload(data, { resetUnparsed: true });
        refreshSyncPillForSelectedFile();
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
        await flushPendingSync();
        AppStore.activeAbortController?.abort();
        AppStore.syncSeq += 1;
        const res = await postJson("/api/import", {
          file_id: explicitType,
          raw_text: rawText,
          state: AppStore.state,
        });
        const importedId = res.imported_files?.[0]?.detected_file_id;
        if (importedId && CATALOG_BY_ID[importedId]) {
          AppStore.selectedFileId = importedId;
        }
        applyServerPayload(res, { resetUnparsed: true });
        refreshSyncPillForSelectedFile();
        closeImportModal();
        showToast(`Imported into ${CATALOG_BY_ID[AppStore.selectedFileId].filename}`, "success");
      } catch (err) {
        showToast(err.message, "danger");
      }
    });

    // Import Modal: Load Sibling Repository Baseline
    document.getElementById("btn-import-repo-baseline")?.addEventListener("click", async () => {
      try {
        await flushPendingSync();
        AppStore.activeAbortController?.abort();
        AppStore.syncSeq += 1;
        const res = await postJson("/api/import", {
          load_repo_baseline: true,
          state: AppStore.state,
        });
        applyServerPayload(res, { autoSelectFiles: true, resetUnparsed: true });
        refreshSyncPillForSelectedFile();
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
