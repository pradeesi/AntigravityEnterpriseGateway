# ==============================================================================
# FILE HEADER: Automated Verification Suite — Antigravity Admin Policy Studio
# ==============================================================================
# Purpose:
#   End-to-end pytest verification covering Flask REST routes, all 11 starter
#   presets/recipes, sibling `agy-config/configs/` baseline import, two-way
#   Form <-> Code round-trip custom-key preservation, linked/unlinked cross-
#   surface permission sync, BOM-free single/ZIP exports, and every cross-OS
#   validator & 1-click Auto-Fix rule.
#
# Architecture / Context:
#   Exercises `app.create_app()` via Flask's in-process test client with zero
#   external network dependencies.
#
# Dependencies / Side Effects:
#   Requires `pytest` and the sibling modules in `agy-policy-studio/`.
# ==============================================================================

from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import zipfile

import pytest

STUDIO_ROOT = Path(__file__).resolve().parent.parent
if str(STUDIO_ROOT) not in sys.path:
    sys.path.insert(0, str(STUDIO_ROOT))

from app import create_app
from studio_engine import PRESET_METADATA


@pytest.fixture()
def client():
    """Create a configured Flask test client for stateless API verification.

    Summary:
        Instantiates `create_app()` in testing mode.
    Parameters:
        None.
    Return Value:
        FlaskClient: In-memory WSGI test client.
    Exceptions/Errors:
        None.
    """
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def test_index_and_health_endpoints(client) -> None:
    """Verify UI HTML rendering, Light theme default, security headers & `/health`.

    Summary:
        Checks `GET /health` and `GET /` for status 200, single `<h1>`, default
        `data-bs-theme="light"`, and `X-Content-Type-Options: nosniff`.
    Parameters:
        client (FlaskClient): Active Flask test client.
    Return Value:
        None.
    Exceptions/Errors:
        AssertionError: If HTML or health contract fails.
    """
    h_resp = client.get("/health")
    assert h_resp.status_code == 200
    assert h_resp.get_json()["status"] == "ok"

    ui_resp = client.get("/")
    assert ui_resp.status_code == 200
    html = ui_resp.get_data(as_text=True)
    assert 'data-bs-theme="light"' in html
    assert html.count("<h1") == 1
    assert "Antigravity Admin Policy Studio" in html
    assert ui_resp.headers.get("X-Content-Type-Options") == "nosniff"


def test_all_presets_and_recipes_compile_cleanly(client) -> None:
    """Verify all 4 core presets and 7 enterprise recipes compile with zero errors.

    Summary:
        Iterates over `PRESET_METADATA`, calls `POST /api/preset`, and asserts
        `error_count == 0` and `warn_count == 0` on every template.
    Parameters:
        client (FlaskClient): Active Flask test client.
    Return Value:
        None.
    Exceptions/Errors:
        AssertionError: If any preset/recipe produces validation errors/warnings.
    """
    meta_resp = client.get("/api/presets")
    assert meta_resp.status_code == 200
    assert len(meta_resp.get_json()["presets"]) == len(PRESET_METADATA)

    for preset in PRESET_METADATA:
        resp = client.post("/api/preset", json={"preset_id": preset["id"], "dev_user": "agydev"})
        assert resp.status_code == 200, f"Preset {preset['id']} HTTP failure"
        payload = resp.get_json()
        val = payload["validation"]
        assert val["error_count"] == 0, f"Preset {preset['id']} had errors: {val['all_issues']}"
        assert val["warn_count"] == 0, f"Preset {preset['id']} had warnings: {val['all_issues']}"


def test_two_way_sync_preserves_custom_keys_and_permission_link(client) -> None:
    """Verify two-way Code <-> Form sync preserves custom JSON keys & sync toggle.

    Summary:
        Injects custom corporate metadata into `admin_settings.json` via
        `/api/sync-code`, recompiles via `/api/compile`, and verifies both custom
        key survival and linked vs. separate CLI/Desktop permission behavior.
    Parameters:
        client (FlaskClient): Active Flask test client.
    Return Value:
        None.
    Exceptions/Errors:
        AssertionError: If custom keys are dropped or permission sync fails.
    """
    init_resp = client.post("/api/preset", json={"preset_id": "balanced", "dev_user": "alice"})
    data = init_resp.get_json()
    state = data["state"]

    adm_obj = json.loads(data["files"]["admin_settings"])
    adm_obj["xEnterpriseChangeTicket"] = "CHG-40291"
    adm_obj["gateway"]["xCustomGatewayTag"] = "emea-finops"

    sync_resp = client.post(
        "/api/sync-code",
        json={
            "file_id": "admin_settings",
            "content": json.dumps(adm_obj, indent=2),
            "state": state,
        },
    )
    assert sync_resp.status_code == 200
    synced = sync_resp.get_json()

    # Modify a structured form field and recompile; custom keys must remain intact!
    synced["state"]["gateway"]["defaultModelId"] = "gemini-3.1-pro-preview"
    recomp = client.post("/api/compile", json={"state": synced["state"]}).get_json()
    re_adm = json.loads(recomp["files"]["admin_settings"])
    assert re_adm["xEnterpriseChangeTicket"] == "CHG-40291"
    assert re_adm["gateway"]["xCustomGatewayTag"] == "emea-finops"
    assert re_adm["models"]["defaultModelId"] == "gemini-3.1-pro-preview"

    # Linked permissions: adding a rule in CLI settings.json mirrors to Desktop config.json
    cli_obj = json.loads(recomp["files"]["cli_settings"])
    cli_obj["permissions"]["deny"].append("mcp(rogue_server/*)")
    linked_res = client.post(
        "/api/sync-code",
        json={
            "file_id": "cli_settings",
            "content": json.dumps(cli_obj, indent=2),
            "state": recomp["state"],
        },
    ).get_json()
    desk_obj = json.loads(linked_res["files"]["desktop_config"])
    assert "mcp(rogue_server/*)" in desk_obj["userSettings"]["globalPermissionGrants"]["deny"]

    # Unlinked permissions: CLI and Desktop diverge cleanly when sync_permissions is False
    unlinked_state = linked_res["state"]
    unlinked_state["sync_permissions"] = False
    unlinked_state["desktop"]["permissions"]["deny"] = ["command(rm)"]
    unlinked_res = client.post("/api/compile", json={"state": unlinked_state}).get_json()
    assert "mcp(rogue_server/*)" in json.loads(unlinked_res["files"]["cli_settings"])["permissions"]["deny"]
    assert "mcp(rogue_server/*)" not in json.loads(unlinked_res["files"]["desktop_config"])["userSettings"]["globalPermissionGrants"]["deny"]


def test_validator_and_autofix_all_edge_cases(client) -> None:
    """Verify detection and deterministic 1-click Auto-Fix across all 9 categories.

    Summary:
        Tests UTF-8 BOM, malformed JSON line/col, Preview v2.0 drift, ACP openai
        mismatch, `unsandboxed(*)` deny, `exebox` glob/rel/Windows/root mounts,
        Windows PowerShell `RequiresExactMatch`, multi-CA `sandboxProxy`, MCP
        `eager: true`, `.toolCall.toolName` + `sed_file`, and plaintext secrets.
    Parameters:
        client (FlaskClient): Active Flask test client.
    Return Value:
        None.
    Exceptions/Errors:
        AssertionError: If any validation code or Auto-Fix remediation fails.
    """
    base_state = client.post("/api/preset", json={"preset_id": "balanced", "dev_user": "alice"}).get_json()["state"]

    # 1. Malformed JSON reports exact line & column
    bad_json_res = client.post(
        "/api/validate",
        json={"file_id": "admin_settings", "content": "{\n  \"gateway\": {\n    \"enabled\": true,\n  }\n}"},
    ).get_json()
    assert bad_json_res["error_count"] == 1
    assert bad_json_res["issues"][0]["code"] == "ERR_JSON_SYNTAX"
    assert bad_json_res["issues"][0]["line"] in (3, 4)

    # 2. UTF-8 BOM + Preview v2.0 drift + ACP openai + live secret in admin_settings.json
    preview_bom_bytes = b"\xef\xbb\xbf" + json.dumps(
        {
            "auth": {"suppressInteractiveLogin": True},
            "gateway": {
                "enabled": True,
                "url": "http://gateway.corp.example.com",
                "apiKey": "sk-live-real-secret-token-123456",
                "wireProtocol": "openai",
                "caCertPath": "/etc/ssl/certs/ca-certificates.crt",
                "models": {"filter": ["gemini-3.8-flash", "gemini-3.1-pro-preview"]},
            },
        }
    ).encode("utf-8")

    imp_resp = client.post(
        "/api/import",
        data={
            "state": json.dumps(base_state),
            "files": (io.BytesIO(preview_bom_bytes), "admin_settings.json"),
        },
        content_type="multipart/form-data",
    )
    assert imp_resp.status_code == 200
    imp_data = imp_resp.get_json()
    codes = {i["code"] for i in imp_data["validation"]["issues_by_file"]["admin_settings"]}
    assert {
        "ERR_UTF8_BOM",
        "ERR_PREVIEW_NESTED_CACERT",
        "ERR_PREVIEW_NESTED_MODELS",
        "WARN_PREVIEW_SUPPRESS_LOGIN",
        "ERR_ACP_OPENAI_UNSUPPORTED",
        "WARN_INSECURE_HTTP_GATEWAY",
        "WARN_PLAINTEXT_SECRET",
    }.issubset(codes)

    fixed_adm = client.post(
        "/api/autofix",
        json={
            "file_id": "admin_settings",
            "issue_code": "ALL",
            "content": imp_data["files"]["admin_settings"],
            "state": imp_data["state"],
        },
    ).get_json()
    assert fixed_adm["validation"]["issues_by_file"]["admin_settings"] == []

    # 3. CLI settings: unsandboxed(*), exebox globs/rel/C:\, write_file(/usr), multi-CA sandboxProxy, PowerShell regex
    broken_cli = json.dumps(
        {
            "agentMode": "plan",
            "toolPermission": "proceed-in-sandbox",
            "enableTerminalSandbox": True,
            "allowNonWorkspaceAccess": False,
            "sandboxProxy": {
                "http": {
                    "address": "http://proxy.corp.example.com:3128",
                    "certFile": "/etc/ssl/certs/ca-certificates.crt",
                }
            },
            "permissions": {
                "allow": [
                    "command(cargo test)",
                    "read_file(./relative_dir)",
                    "mcp(catalog/ping_catalog)",
                ],
                "ask": [],
                "deny": [
                    "unsandboxed(*)",
                    "read_file(/home/alice/*.pem)",
                    "read_file(C:\\Windows\\System32\\config\\SAM)",
                    "write_file(/usr)",
                    r"command(regex:^curl\s+-d)",
                ],
            },
        }
    )
    val_cli = client.post(
        "/api/validate",
        json={
            "file_id": "cli_settings",
            "content": broken_cli,
            "os_list": ["linux", "macos", "windows"],
            "surfaces": ["cli"],
            "dev_user": "alice",
        },
    ).get_json()
    cli_codes = {i["code"] for i in val_cli["issues"]}
    assert {
        "ERR_DENY_UNSANDBOXED_WILDCARD",
        "ERR_EXEBOX_GLOB_PATH",
        "ERR_EXEBOX_RELATIVE_PATH",
        "ERR_EXEBOX_WINDOWS_DRIVE_PATH",
        "ERR_EXEBOX_ROOT_SYSTEM_DIR",
        "ERR_SANDBOX_PROXY_MULTI_CERT_BUNDLE",
        "WARN_MISSING_GEMINI_READ_FOR_MCP",
        "WARN_WIN_POWERSHELL_EXACT_MATCH",
        "WARN_SINGLE_TOKEN_REGEX_DENY",
    }.issubset(cli_codes)

    fixed_cli = client.post(
        "/api/autofix",
        json={
            "file_id": "cli_settings",
            "issue_code": "ALL",
            "content": broken_cli,
            "state": base_state,
        },
    ).get_json()
    assert fixed_cli["validation"]["issues_by_file"]["cli_settings"] == []

    # 4. MCP eager:true & enabled example.com + Hooks .toolCall.toolName & missing sed_file
    broken_mcp = json.dumps(
        {
            "mcpServers": {
                "demo": {
                    "serverUrl": "https://mcp.example.com/sse",
                    "disabled": False,
                    "tools": {"ping": {"eager": True}},
                }
            }
        }
    )
    fixed_mcp = client.post(
        "/api/autofix",
        json={"file_id": "mcp_config", "issue_code": "ALL", "content": broken_mcp, "state": base_state},
    ).get_json()
    assert fixed_mcp["validation"]["issues_by_file"]["mcp_config"] == []

    broken_hooks = json.dumps(
        {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "^(write_file|edit_file)$",
                        "hooks": [
                            {
                                "type": "command",
                                "command": 'powershell.exe -File "C:\\ProgramData\\Antigravity\\bin\\agy_security_guard.ps1" .toolCall.toolName',
                            }
                        ],
                    }
                ]
            }
        }
    )
    fixed_hooks = client.post(
        "/api/autofix",
        json={"file_id": "hooks_config", "issue_code": "ALL", "content": broken_hooks, "state": base_state},
    ).get_json()
    assert fixed_hooks["validation"]["issues_by_file"]["hooks_config"] == []
    repaired_hook_str = fixed_hooks["files"]["hooks_config"]
    assert "sed_file" in repaired_hook_str
    assert ".toolCall.name" in repaired_hook_str


def test_bom_free_downloads_and_mdm_zip_roundtrip(client) -> None:
    """Verify BOM-free single-file downloads and full MDM `.zip` bundle round-trip.

    Summary:
        Downloads individual POSIX (`.json`) and Windows (`.ps1`) files plus the
        full OS-structured `.zip` archive, checks zero BOM bytes across every
        entry, and re-imports the `.zip` archive with zero validation errors.
    Parameters:
        client (FlaskClient): Active Flask test client.
    Return Value:
        None.
    Exceptions/Errors:
        AssertionError: If BOM bytes appear or ZIP round-trip fails.
    """
    init = client.post("/api/preset", json={"preset_id": "repo_baseline", "dev_user": "corpdev"}).get_json()

    # Single JSON file download strips accidental BOM and uses LF
    dl_json = client.post(
        "/api/download-file",
        json={"file_id": "admin_settings", "content": "\ufeff" + init["files"]["admin_settings"]},
    )
    assert dl_json.status_code == 200
    raw_adm_bytes = dl_json.get_data()
    assert not raw_adm_bytes.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in raw_adm_bytes

    # Single PowerShell script download uses CRLF and zero BOM
    dl_ps1 = client.post(
        "/api/download-file",
        json={"file_id": "guard_ps1", "content": "\ufeff" + init["files"]["guard_ps1"]},
    )
    assert dl_ps1.status_code == 200
    raw_ps1_bytes = dl_ps1.get_data()
    assert not raw_ps1_bytes.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in raw_ps1_bytes

    # Full MDM ZIP download
    zip_resp = client.post("/api/download-zip", json={"state": init["state"]})
    assert zip_resp.status_code == 200
    zip_bytes = zip_resp.get_data()

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        names = set(zf.namelist())
        assert "linux/etc/antigravity/admin_settings.json" in names
        assert "macos/Library/Application Support/Antigravity/admin_settings.json" in names
        assert "windows/ProgramData/Antigravity/admin_settings.json" in names
        assert "windows/ProgramData/Antigravity/bin/agy_security_guard.ps1" in names
        assert "scripts/lock_linux.sh" in names
        assert "scripts/lock_macos.sh" in names
        assert "scripts/lock_windows.ps1" in names
        assert "README_DEPLOYMENT.md" in names
        for name in names:
            assert not zf.read(name).startswith(b"\xef\xbb\xbf"), f"BOM found in {name}"
        # Multi-OS Windows admin_settings.json automatically omits POSIX /etc/ssl caCertPath
        win_adm = json.loads(zf.read("windows/ProgramData/Antigravity/admin_settings.json").decode("utf-8"))
        assert "caCertPath" not in win_adm

    # Round-trip re-import of the generated MDM ZIP archive
    reimp = client.post(
        "/api/import",
        data={
            "state": json.dumps(init["state"]),
            "files": (io.BytesIO(zip_bytes), "antigravity-mdm-policy-bundle.zip"),
        },
        content_type="multipart/form-data",
    )
    assert reimp.status_code == 200
    reimp_json = reimp.get_json()
    assert reimp_json["validation"]["error_count"] == 0
    assert reimp_json["validation"]["warn_count"] == 0


def test_progressive_dropdown_ui_and_per_file_lock_cli_and_selective_zip(client) -> None:
    """Verify progressive multi-select UI, per-file lock CLI, and selective ZIP export.

    Summary:
        1. Asserts `GET /` renders Bootstrap multi-select dropdowns (`dropdownOsBtn`,
           `dropdownSurfaceBtn`, `dropdownFilesBtn`), places `#preset-selector` inside
           `#step2-policy-files-card`, renders `#step3-file-ref-card` with Purpose,
           Surfaces, Target Paths, Docs link, and `#pre-file-lock-cmd`, and contains
           zero overflowing `.file-tab-strip` or `.studio-scopebar` pill rows.
        2. Verifies progressive Step 1 empty scope (`os_list=[]`, `surfaces=[]`)
           returns `available_file_ids == []` and `active_file_ids == []`.
        3. Verifies subset `selected_file_ids` populates `per_file_cli` (`MarshalSparse`
           pre-init + `chattr +i` on Linux; BOM-free `UTF8Encoding($false)` + `attrib +R`
           + `icacls` on Windows) and packages ONLY the checked files into the MDM `.zip`.
        4. Verifies `POST /api/preset` `preserve_scope=True` preserves user-chosen
           OS/Surface scope on general presets while recipe presets set tailored scope.
    Parameters:
        client (FlaskClient): Active Flask test client.
    Return Value:
        None.
    Exceptions/Errors:
        AssertionError: If progressive UI DOM, per-file CLI, or selective ZIP fails.
    """
    ui_html = client.get("/").get_data(as_text=True)
    assert 'id="dropdownOsBtn"' in ui_html
    assert 'id="dropdownSurfaceBtn"' in ui_html
    assert 'id="step2-policy-files-card"' in ui_html
    assert 'id="dropdownFilesBtn"' in ui_html
    assert 'id="active-file-selector"' in ui_html
    assert 'id="step3-file-ref-card"' in ui_html
    assert 'id="section-box-file-details" class="collapsible-section-box mb-2"' in ui_html
    assert 'id="btn-toggle-file-details"' in ui_html
    assert 'id="file-details-body" class="collapsible-section-body d-none"' in ui_html
    assert 'id="section-box-file-lock" class="collapsible-section-box"' in ui_html
    assert 'id="file-lock-cli-body" class="collapsible-section-body d-none"' in ui_html
    assert 'id="pre-file-lock-cmd"' in ui_html
    assert 'id="right-empty-state"' in ui_html
    assert "file-tab-strip" not in ui_html
    assert "studio-scopebar" not in ui_html
    assert ui_html.count('data-bs-popper-config=\'{"strategy":"fixed"}\'') == 3

    # Confirm #preset-selector sits inside #step2-policy-files-card on the left panel
    step2_idx = ui_html.index('id="step2-policy-files-card"')
    preset_idx = ui_html.index('id="preset-selector"')
    step3_idx = ui_html.index('id="step3-file-ref-card"')
    assert step2_idx < preset_idx < step3_idx

    # Step 1 empty progressive state returns zero available/active files
    empty_comp = client.post(
        "/api/compile",
        json={"state": {"os_list": [], "surfaces": [], "selected_file_ids": [], "dev_user": "alice"}},
    ).get_json()
    assert empty_comp["available_file_ids"] == []
    assert empty_comp["active_file_ids"] == []

    # Subset file selection generates exact per-file lock CLI and selective MDM ZIP
    scoped_state = client.post("/api/preset", json={"preset_id": "balanced", "dev_user": "alice"}).get_json()["state"]
    scoped_state["os_list"] = ["linux", "windows"]
    scoped_state["surfaces"] = ["cli"]
    scoped_state["selected_file_ids"] = ["admin_settings", "cli_settings"]

    scoped_comp = client.post("/api/compile", json={"state": scoped_state}).get_json()
    assert scoped_comp["active_file_ids"] == ["admin_settings", "cli_settings"]
    assert "mcp_config" in scoped_comp["available_file_ids"]

    presets_meta = client.get("/api/presets").get_json()
    cli_ref = next(item for item in presets_meta["catalog"] if item["id"] == "cli_settings")
    assert cli_ref["doc_url"].startswith("https://")
    assert cli_ref["surface_details"]
    assert cli_ref["permissions_summary"]

    linux_lock = scoped_comp["per_file_cli"]["cli_settings"]["linux"]["lock"]
    assert "agy --version" in linux_lock
    assert 'chattr +i "/home/alice/.gemini/antigravity-cli/settings.json"' in linux_lock
    assert "chattr -i" in scoped_comp["per_file_cli"]["cli_settings"]["linux"]["unlock"]

    win_lock = scoped_comp["per_file_cli"]["cli_settings"]["windows"]["lock"]
    assert "UTF8Encoding($false)" in win_lock
    assert "attrib.exe +R" in win_lock
    assert "icacls.exe" in win_lock

    sel_zip_resp = client.post("/api/download-zip", json={"state": scoped_comp["state"]})
    assert sel_zip_resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(sel_zip_resp.get_data()), "r") as zf:
        sel_names = set(zf.namelist())
        assert "linux/etc/antigravity/admin_settings.json" in sel_names
        assert "linux/home/alice/.gemini/antigravity-cli/settings.json" in sel_names
        assert "windows/ProgramData/Antigravity/admin_settings.json" in sel_names
        assert "windows/Users/alice/.gemini/antigravity-cli/settings.json" in sel_names
        assert "scripts/lock_linux.sh" in sel_names
        assert "scripts/lock_windows.ps1" in sel_names
        assert "scripts/lock_macos.sh" not in sel_names
        # Unselected files must NOT be packaged into the selective ZIP
        assert not any("mcp_config.json" in n for n in sel_names)
        assert not any("hooks.json" in n for n in sel_names)

    # preserve_scope=True keeps user OS/Surfaces on general presets, while OS recipes tailor scope
    preserved = client.post(
        "/api/preset",
        json={
            "preset_id": "hardened",
            "dev_user": "alice",
            "preserve_scope": True,
            "os_list": ["macos"],
            "surfaces": ["desktop"],
            "selected_file_ids": ["admin_settings", "desktop_config"],
        },
    ).get_json()
    assert preserved["state"]["os_list"] == ["macos"]
    assert preserved["state"]["surfaces"] == ["desktop"]
    assert preserved["active_file_ids"] == ["admin_settings", "desktop_config"]

    win_recipe = client.post(
        "/api/preset",
        json={
            "preset_id": "recipe_windows_enterprise",
            "dev_user": "alice",
            "preserve_scope": True,
            "os_list": ["macos"],
            "surfaces": ["desktop"],
        },
    ).get_json()
    assert win_recipe["state"]["os_list"] == ["windows"]


def test_requirements_and_file_reference_guide_modal(client) -> None:
    """Verify Top-Bar Requirements & File Guide Modal DOM, Reference Matrix, and 11-File CLI.

    Summary:
        1. Asserts `GET /` renders `#btn-open-reference` in `.studio-topbar` and
           `#referenceGuideModal` containing `#select-ref-section`,
           `#select-ref-cli-os`, `#tbody-ref-os`, `#tbody-ref-versions`, and
           `#tbody-ref-files`.
        2. Asserts `GET /api/presets` returns `"reference"` with 3 OS minimum
           requirement entries (`Windows`, `macOS`, `Linux`) and 6 Antigravity
           surface minimum version entries (`1.2.15`, `2.15.0`, `1.3.0`, etc.),
           and verifies all 11 `catalog` entries include `mandatory_status`,
           `mandatory_variant`, `mandatory_note`, and `doc_url`.
        3. Asserts `POST /api/compile` populates `all_files_cli` for all 11 files
           across `linux`, `macos`, and `windows` even when Step 1 scope is empty
           (`os_list=[]`, `surfaces=[]`), substituting `dev_user` cleanly.
    Parameters:
        client (FlaskClient): Active Flask test client.
    Return Value:
        None.
    Exceptions/Errors:
        AssertionError: If modal markup, reference metadata, or 11-file CLI fails.
    """
    ui_html = client.get("/").get_data(as_text=True)
    assert 'id="btn-open-reference"' in ui_html
    assert "Requirements &amp; File Guide" in ui_html
    assert 'id="referenceGuideModal"' in ui_html
    assert 'id="select-ref-section"' in ui_html
    assert 'id="select-ref-cli-os"' in ui_html
    assert 'id="tbody-ref-os"' in ui_html
    assert 'id="tbody-ref-versions"' in ui_html
    assert 'id="tbody-ref-files"' in ui_html

    presets_json = client.get("/api/presets").get_json()
    assert "reference" in presets_json
    ref = presets_json["reference"]
    assert len(ref["os_requirements"]) == 3
    os_names = {row["os"] for row in ref["os_requirements"]}
    assert os_names == {"Windows", "macOS", "Linux"}

    assert len(ref["version_requirements"]) == 6
    ver_blob = json.dumps(ref["version_requirements"])
    assert "1.2.15" in ver_blob
    assert "2.15.0" in ver_blob
    assert "1.3.0" in ver_blob

    catalog = presets_json["catalog"]
    assert len(catalog) == 11
    for item in catalog:
        assert item.get("mandatory_status"), f"Missing mandatory_status on {item['id']}"
        assert item.get("mandatory_variant"), f"Missing mandatory_variant on {item['id']}"
        assert item.get("mandatory_note"), f"Missing mandatory_note on {item['id']}"
        assert item.get("doc_url", "").startswith("https://"), f"Missing doc_url on {item['id']}"

    comp = client.post(
        "/api/compile",
        json={"state": {"os_list": [], "surfaces": [], "selected_file_ids": [], "dev_user": "corpadmin"}},
    ).get_json()
    assert "all_files_cli" in comp
    assert len(comp["all_files_cli"]) == 11
    assert "corpadmin" in comp["all_files_cli"]["cli_settings"]["linux"]["lock"]
    assert "corpadmin" in comp["all_files_cli"]["cli_settings"]["macos"]["lock"]
    assert "corpadmin" in comp["all_files_cli"]["cli_settings"]["windows"]["lock"]
    assert "icacls.exe" in comp["all_files_cli"]["admin_settings"]["windows"]["lock"]
    assert "chflags schg" in comp["all_files_cli"]["admin_settings"]["macos"]["lock"]
    assert "chattr +i" in comp["all_files_cli"]["admin_settings"]["linux"]["lock"]


def test_airgapped_local_assets_and_csp(client) -> None:
    """Verify Policy Studio has zero external CDN dependencies and serves all assets locally.

    Summary:
        Confirms `GET /` emits a strict self-only `Content-Security-Policy`,
        contains zero external `<link>` or `<script src="http...">` CDN/font
        references, serves Bootstrap 5.3.3 CSS/JS and WOFF2 fonts locally with
        HTTP 200, and bundles an offline Python wheelhouse in `vendor/wheels/`.
    Parameters:
        client: Flask test client fixture.
    Return Value:
        None.
    Exceptions/Errors:
        AssertionError: Raised if any asset relies on public internet access.
    """
    import re

    resp = client.get("/")
    assert resp.status_code == 200
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "font-src 'self'" in csp

    html = resp.get_data(as_text=True)
    assert "cdn.jsdelivr.net" not in html
    assert "fonts.googleapis.com" not in html
    assert "fonts.gstatic.com" not in html
    assert not re.search(r'<(?:link|script)\b[^>]*(?:href|src)=["\']https?://', html, flags=re.IGNORECASE)

    # Verify all static stylesheets and JS bundles load locally
    for asset_path in (
        "/static/css/fonts.css",
        "/static/css/studio.css",
        "/static/vendor/bootstrap/bootstrap.min.css",
        "/static/vendor/bootstrap/bootstrap.bundle.min.js",
        "/static/js/studio.js",
    ):
        asset_resp = client.get(asset_path)
        assert asset_resp.status_code == 200, f"Missing local static asset {asset_path}"
        assert len(asset_resp.data) > 500, f"Unexpectedly small static asset {asset_path}"

    # Verify every local @font-face WOFF2 file referenced in fonts.css exists and loads
    fonts_css = client.get("/static/css/fonts.css").get_data(as_text=True)
    assert "https://" not in fonts_css and "http://" not in fonts_css
    woff_urls = re.findall(r"url\(([^)]+\.woff2)\)", fonts_css)
    assert len(woff_urls) >= 2
    for rel_woff in woff_urls:
        clean_rel = rel_woff.strip("'\"")
        # Resolve `../vendor/fonts/...` relative to `/static/css/`
        norm_url = "/static/" + clean_rel.removeprefix("../")
        woff_resp = client.get(norm_url)
        assert woff_resp.status_code == 200, f"Missing local font file {norm_url}"
        assert len(woff_resp.data) > 5000, f"Corrupt or empty WOFF2 font {norm_url}"

    # Verify offline Python wheelhouse exists with core packages
    studio_root = Path(__file__).resolve().parent.parent
    wheels_dir = studio_root / "vendor" / "wheels"
    assert wheels_dir.is_dir(), "Offline Python wheelhouse directory vendor/wheels/ is missing"
    wheel_names = " ".join(p.name.lower() for p in wheels_dir.iterdir())
    for required_pkg in ("flask-", "werkzeug-", "gunicorn-", "python_dotenv-", "pytest-", "markupsafe-"):
        assert required_pkg in wheel_names, f"Missing {required_pkg} in offline vendor/wheels/"


def test_symmetric_two_way_sync_all_eleven_files_and_deletions(client) -> None:
    """Verify lossless symmetric Form <-> Code round-trips and deletions across all 11 files.

    Summary:
        Exercises `POST /api/sync-code` followed by `POST /api/compile` across all
        11 canonical files, explicitly testing key/item deletions, nested custom
        JSON keys, apostrophes in SessionStart banners, custom `.env` lines, and
        ACP Gateway environment propagation.
    Parameters:
        client: Flask test client fixture.
    Return Value:
        None.
    Exceptions/Errors:
        AssertionError: Raised if any edit reverts or fails to round-trip cleanly.
    """
    init = client.post("/api/preset", json={"preset_id": "balanced", "dev_user": "alice"}).get_json()
    state = init["state"]

    # 1. admin_settings: delete customHeaders & models.list, clear defaultModelId, add nested custom key
    admin_raw = json.dumps(
        {
            "caCertPath": "/etc/antigravity/custom-ca.pem",
            "gateway": {
                "enabled": True,
                "url": "https://gw-sync.corp.example.com",
                "wireProtocol": "openai",
                "customEnterpriseFlag": True,
            },
            "models": {"defaultModelId": "", "list": []},
        },
        indent=2,
    )
    r1 = client.post("/api/sync-code", json={"file_id": "admin_settings", "content": admin_raw, "state": state}).get_json()
    assert r1["code_synced"] is True
    state = r1["state"]
    assert state["gateway"]["omitApiKeyInMdm"] is True
    assert state["gateway"]["customHeaders"] == []
    assert state["gateway"]["models"] == []
    assert state["gateway"]["defaultModelId"] == ""
    assert state["gateway_env"]["url"] == "https://gw-sync.corp.example.com"
    assert state["gateway_env"]["wireProtocol"] == "openai"

    recompiled_admin = json.loads(
        client.post("/api/compile", json={"state": state}).get_json()["files"]["admin_settings"]
    )
    assert "customHeaders" not in recompiled_admin["gateway"]
    assert recompiled_admin["gateway"]["customEnterpriseFlag"] is True
    assert recompiled_admin["models"] == {"defaultModelId": "", "list": []}

    # 2. gateway_env: remove CA_CERT & HEADERS, toggle off `export `, preserve custom extra env line
    env_raw = (
        'AGY_LLM_GATEWAY_URL="https://env-gw.corp.example.com"\n'
        'AGY_LLM_GATEWAY_API_KEY="sk-test-placeholder"\n'
        'AGY_LLM_GATEWAY_WIRE_PROTOCOL="genai"\n'
        "# AGY_LLM_GATEWAY_CA_CERT=/commented/out.pem\n"
        'CUSTOM_CORP_REGION="europe-west1"\n'
    )
    r2 = client.post("/api/sync-code", json={"file_id": "gateway_env", "content": env_raw, "state": state}).get_json()
    assert r2["code_synced"] is True
    state = r2["state"]
    assert state["gateway_env"]["exportPrefix"] is False
    assert state["gateway_env"]["caCert"] == ""
    assert state["gateway_env"]["headers"] == ""
    assert state["gateway_env"]["models"] == ""
    recompiled_env = client.post("/api/compile", json={"state": state}).get_json()["files"]["gateway_env"]
    assert "AGY_LLM_GATEWAY_CA_CERT=" not in recompiled_env
    assert 'CUSTOM_CORP_REGION="europe-west1"' in recompiled_env

    # 3. cli_settings: set historySize + UI suppression, then delete them and verify they stay deleted
    cli_with_ui = json.loads(r2["files"]["cli_settings"])
    cli_with_ui["historySize"] = 0
    cli_with_ui["notifications"] = False
    cli_with_ui["showFeedbackSurvey"] = False
    cli_with_ui["showTips"] = True
    cli_with_ui["sandboxProxy"] = {
        "http": {
            "address": "http://proxy.corp.example.com:3128",
            "certFile": "/etc/antigravity/certs/root.pem",
            "noProxy": "localhost,127.0.0.1",
        }
    }
    r3a = client.post(
        "/api/sync-code",
        json={"file_id": "cli_settings", "content": json.dumps(cli_with_ui), "state": state},
    ).get_json()
    assert r3a["code_synced"] is True
    state = r3a["state"]
    assert state["cli"]["includeOptionalUiKeys"] is True
    assert state["cli"]["historySize"] == 0
    assert state["cli"]["showTips"] is True

    del cli_with_ui["historySize"]
    del cli_with_ui["notifications"]
    del cli_with_ui["showFeedbackSurvey"]
    del cli_with_ui["showTips"]
    r3b = client.post(
        "/api/sync-code",
        json={"file_id": "cli_settings", "content": json.dumps(cli_with_ui), "state": state},
    ).get_json()
    state = r3b["state"]
    assert state["cli"]["includeOptionalUiKeys"] is False
    assert state["cli"]["historySize"] == 50
    recompiled_cli = json.loads(client.post("/api/compile", json={"state": state}).get_json()["files"]["cli_settings"])
    assert "historySize" not in recompiled_cli
    assert "notifications" not in recompiled_cli
    assert recompiled_cli["sandboxProxy"]["http"]["noProxy"] == "localhost,127.0.0.1"

    # 4. desktop_config: add nonWorkspaceFileAccessPolicy & internetAccessPolicy, then delete them
    desk_doc = json.loads(r3b["files"]["desktop_config"])
    desk_doc["userSettings"]["nonWorkspaceFileAccessPolicy"] = "NON_WORKSPACE_FILE_ACCESS_POLICY_DISABLED"
    desk_doc["userSettings"]["internetAccessPolicy"] = "INTERNET_ACCESS_POLICY_DISABLED"
    desk_doc["userSettings"]["customDesktopFlag"] = "enabled"
    r4a = client.post(
        "/api/sync-code",
        json={"file_id": "desktop_config", "content": json.dumps(desk_doc), "state": state},
    ).get_json()
    state = r4a["state"]
    assert state["desktop"]["nonWorkspaceFileAccessPolicy"] == "NON_WORKSPACE_FILE_ACCESS_POLICY_DISABLED"
    assert state["desktop"]["internetAccessPolicy"] == "INTERNET_ACCESS_POLICY_DISABLED"

    del desk_doc["userSettings"]["nonWorkspaceFileAccessPolicy"]
    del desk_doc["userSettings"]["internetAccessPolicy"]
    r4b = client.post(
        "/api/sync-code",
        json={"file_id": "desktop_config", "content": json.dumps(desk_doc), "state": state},
    ).get_json()
    state = r4b["state"]
    assert state["desktop"]["nonWorkspaceFileAccessPolicy"] == ""
    assert state["desktop"]["internetAccessPolicy"] == ""
    recompiled_desk = json.loads(
        client.post("/api/compile", json={"state": state}).get_json()["files"]["desktop_config"]
    )
    assert "nonWorkspaceFileAccessPolicy" not in recompiled_desk["userSettings"]
    assert recompiled_desk["userSettings"]["customDesktopFlag"] == "enabled"

    # 5. browser_allowlist: edit domain list including comments
    r5 = client.post(
        "/api/sync-code",
        json={
            "file_id": "browser_allowlist",
            "content": "# Header\nportal.internal.example.com\ngit.internal.example.com\n",
            "state": state,
        },
    ).get_json()
    assert r5["code_synced"] is True
    state = r5["state"]
    assert state["browser_domains"] == ["portal.internal.example.com", "git.internal.example.com"]

    # 6. mcp_config: omit timeoutSeconds and preserve custom per-server headers
    mcp_doc = {
        "mcpServers": {
            "corp_api": {
                "serverUrl": "https://mcp.corp.example.com/sse",
                "disabled": True,
                "enabledTools": ["get_status"],
                "disabledTools": ["drop_db"],
                "headers": {"X-MCP-Tenant": "secops"},
            }
        }
    }
    r6 = client.post(
        "/api/sync-code",
        json={"file_id": "mcp_config", "content": json.dumps(mcp_doc), "state": state},
    ).get_json()
    assert r6["code_synced"] is True
    state = r6["state"]
    assert state["mcp_servers"][0]["timeoutSeconds"] is None
    recompiled_mcp = json.loads(client.post("/api/compile", json={"state": state}).get_json()["files"]["mcp_config"])
    assert "timeoutSeconds" not in recompiled_mcp["mcpServers"]["corp_api"]
    assert recompiled_mcp["mcpServers"]["corp_api"]["headers"] == {"X-MCP-Tenant": "secops"}

    # 7. hooks_config: round-trip SessionStart banner containing apostrophes + custom Stop hook
    state["hooks"]["enableSessionStartBanner"] = True
    state["hooks"]["sessionBannerText"] = "Admin's strict policy: do not exfiltrate secrets."
    compiled_hooks = client.post("/api/compile", json={"state": state}).get_json()["files"]["hooks_config"]
    hooks_obj = json.loads(compiled_hooks)
    hooks_obj["hooks"]["Stop"] = [{"matcher": ".*", "hooks": [{"type": "command", "command": "/bin/true"}]}]
    r7 = client.post(
        "/api/sync-code",
        json={"file_id": "hooks_config", "content": json.dumps(hooks_obj), "state": state},
    ).get_json()
    assert r7["code_synced"] is True
    state = r7["state"]
    assert state["hooks"]["sessionBannerText"] == "Admin's strict policy: do not exfiltrate secrets."
    recompiled_hooks = json.loads(
        client.post("/api/compile", json={"state": state}).get_json()["files"]["hooks_config"]
    )
    assert "Stop" in recompiled_hooks["hooks"]

    # 8 & 9. guard_sh and guard_ps1 script round-trips
    for script_fid, marker in (("guard_sh", "# CUSTOM_BASH_MARKER"), ("guard_ps1", "# CUSTOM_PS1_MARKER")):
        custom_script = state["scripts"][script_fid] + f"\n{marker}\n"
        rs = client.post(
            "/api/sync-code",
            json={"file_id": script_fid, "content": custom_script, "state": state},
        ).get_json()
        assert rs["code_synced"] is True
        state = rs["state"]
        assert marker in client.post("/api/compile", json={"state": state}).get_json()["files"][script_fid]

    # 10 & 11. acp_json (all 6 env vars + extraEnv) and acp_auth
    acp_doc = {
        "agent_servers": {
            "Antigravity": {
                "command": "/opt/antigravity/bin/agy",
                "args": ["acp", "--verbose"],
                "env": {
                    "AGY_LLM_GATEWAY_URL": "https://acp-gw.corp.example.com",
                    "AGY_LLM_GATEWAY_API_KEY": "REPLACE_ACP_KEY",
                    "AGY_LLM_GATEWAY_WIRE_PROTOCOL": "genai",
                    "AGY_LLM_GATEWAY_CA_CERT": "/etc/ssl/corp.pem",
                    "AGY_LLM_GATEWAY_HEADERS": "X-Team: IDE,X-Env: Prod",
                    "AGY_LLM_GATEWAY_MODELS": "gemini-3.8-flash,gemini-3.1-pro-preview",
                    "ACP_CUSTOM_TRACE": "1",
                },
            }
        }
    }
    r10 = client.post(
        "/api/sync-code",
        json={"file_id": "acp_json", "content": json.dumps(acp_doc), "state": state},
    ).get_json()
    assert r10["code_synced"] is True
    state = r10["state"]
    assert state["acp"]["command"] == "/opt/antigravity/bin/agy"
    assert state["acp"]["args"] == ["acp", "--verbose"]
    assert state["gateway"]["url"] == "https://acp-gw.corp.example.com"
    recompiled_acp = json.loads(client.post("/api/compile", json={"state": state}).get_json()["files"]["acp_json"])
    assert recompiled_acp["agent_servers"]["Antigravity"]["env"]["ACP_CUSTOM_TRACE"] == "1"
    assert recompiled_acp["agent_servers"]["Antigravity"]["env"]["AGY_LLM_GATEWAY_HEADERS"] == "X-Team: IDE,X-Env: Prod"

    r11 = client.post(
        "/api/sync-code",
        json={"file_id": "acp_auth", "content": json.dumps({"auth": {"type": "oauth"}}), "state": state},
    ).get_json()
    assert r11["code_synced"] is True
    assert r11["state"]["acp"]["authType"] == "oauth"
    assert any(i["code"] == "ERR_ACP_AUTH_TYPE" for i in r11["validation"]["issues_by_file"]["acp_auth"])


def test_sync_code_reports_false_on_malformed_json_and_recovers(client) -> None:
    """Verify `/api/sync-code` flags malformed JSON via `code_synced: False` without corrupting state.

    Summary:
        Ensures mid-keystroke JSON syntax errors return `code_synced: False` plus
        `ERR_JSON_SYNTAX` while preserving structured state, and immediately return
        `code_synced: True` once valid JSON syntax is restored, alongside cache-busting
        `?v=` asset URLs and clean `204`/`404` HTTP responses.
    Parameters:
        client: Flask test client fixture.
    Return Value:
        None.
    Exceptions/Errors:
        AssertionError: Raised if malformed JSON claims `code_synced: True` or 404 returns 500.
    """
    init = client.post("/api/preset", json={"preset_id": "balanced"}).get_json()
    state = init["state"]

    bad_resp = client.post(
        "/api/sync-code",
        json={"file_id": "cli_settings", "content": '{"agentMode": "strict",}', "state": state},
    )
    assert bad_resp.status_code == 200
    bad_data = bad_resp.get_json()
    assert bad_data["code_synced"] is False
    assert bad_data["state"]["cli"]["agentMode"] == "plan"
    assert any(i["code"] == "ERR_JSON_SYNTAX" for i in bad_data["validation"]["issues_by_file"]["cli_settings"])

    good_resp = client.post(
        "/api/sync-code",
        json={"file_id": "cli_settings", "content": '{"agentMode": "accept-edits"}', "state": bad_data["state"]},
    )
    good_data = good_resp.get_json()
    assert good_data["code_synced"] is True
    assert good_data["state"]["cli"]["agentMode"] == "accept-edits"

    # Verify cache-busting asset query string, Cache-Control header, favicon 204, and real 404
    index_resp = client.get("/")
    index_html = index_resp.get_data(as_text=True)
    assert "studio.js?v=" in index_html
    assert "studio.css?v=" in index_html
    assert "no-cache" in index_resp.headers.get("Cache-Control", "")
    assert client.get("/favicon.ico").status_code == 204
    assert client.get("/non-existent-endpoint").status_code == 404


def test_single_click_delete_handlers_avoid_stale_state_closures(client) -> None:
    """Verify `studio.js` and `studio.css` keep single-click `[x]` deletion race-free.

    Summary:
        Ensures `bindActiveFormEvents` resolves `AppStore.state` dynamically via
        `getState()` rather than caching a detached `const s = AppStore.state`
        closure across `/api/compile` round-trips, guards `#form-panel-container`
        with `isPointerDownInForm` / `deferredFormRender`, and serves `.btn-row-delete`
        hit-target styling.
    Parameters:
        client: Flask test client fixture.
    Return Value:
        None.
    Exceptions/Errors:
        AssertionError: If stale closure patterns reappear or `.btn-row-delete` is missing.
    """
    js_src = client.get("/static/js/studio.js").get_data(as_text=True)
    css_src = client.get("/static/css/studio.css").get_data(as_text=True)

    bind_idx = js_src.index("function bindActiveFormEvents(")
    bind_end = js_src.index("function renderEditorHeaderOnly(", bind_idx)
    bind_body = js_src[bind_idx:bind_end]

    assert "const getState = () => AppStore.state;" in bind_body
    assert "const s = AppStore.state;" not in bind_body
    assert "isPointerDownInForm" in js_src
    assert "deferredFormRender" in js_src
    assert "nextUniqueIdentifier(" in bind_body
    assert "refreshUniqueKeyFeedback(" in bind_body
    assert "btn-row-delete" in js_src
    assert ".btn-row-delete" in css_src


def test_empty_default_username_and_mandatory_user_file_enforcement(client) -> None:
    """Verify default workstation username is empty and mandatory only for user-scoped files.

    Summary:
        Validates that:
          1. Initial HTML (`#input-dev-user`) and bootstrap state start with `dev_user == ""`
             and zero hardcoded `"alice"` fallback.
          2. All 7 user-scoped files (`cli_settings`, `desktop_config`, `browser_allowlist`,
             `mcp_config`, `hooks_config`, `acp_json`, `acp_auth`) emit
             `ERR_MISSING_WORKSTATION_USER` and reject `/api/download-file` +
             `/api/download-zip` with HTTP 400 when `dev_user` is blank or invalid.
          3. System-wide files (`admin_settings`, `gateway_env`, `guard_sh`, `guard_ps1`)
             emit zero username errors and export cleanly (HTTP 200) when `dev_user` is blank.
          4. Supplying a valid `dev_user` rewrites `__DEV_USER__` tokens, clears validation
             errors, supports `ERR_UNREPLACED_USER_PLACEHOLDER` Auto-Fix, and enables exports.
    Parameters:
        client: Flask test client fixture.
    Return Value:
        None.
    Exceptions/Errors:
        AssertionError: If default username is non-empty or mandatory checks fail.
    """
    # 1. Verify initial HTML and bootstrap payload have empty dev_user
    html = client.get("/").get_data(as_text=True)
    assert 'id="input-dev-user"' in html
    assert 'value="alice"' not in html

    preset_res = client.post("/api/preset", json={"preset_id": "balanced"}).get_json()
    assert preset_res["state"]["dev_user"] == ""

    issues_by_file = preset_res["validation"]["issues_by_file"]
    user_scoped = {
        "cli_settings",
        "desktop_config",
        "browser_allowlist",
        "mcp_config",
        "hooks_config",
        "acp_json",
        "acp_auth",
    }
    system_wide = {"admin_settings", "gateway_env", "guard_sh", "guard_ps1"}

    for fid in user_scoped:
        codes = {i["code"] for i in issues_by_file[fid]}
        assert "ERR_MISSING_WORKSTATION_USER" in codes, f"Expected ERR_MISSING_WORKSTATION_USER on {fid}"

    for fid in system_wide:
        codes = {i["code"] for i in issues_by_file[fid]}
        assert "ERR_MISSING_WORKSTATION_USER" not in codes
        assert "ERR_INVALID_WORKSTATION_USER" not in codes

    # 2. System-wide files compile cleanly and download (HTTP 200) with empty dev_user
    sys_state = dict(preset_res["state"])
    sys_state["selected_file_ids"] = ["admin_settings", "gateway_env", "guard_sh", "guard_ps1"]
    sys_compiled = client.post("/api/compile", json={"state": sys_state}).get_json()
    assert sys_compiled["validation"]["error_count"] == 0

    dl_admin = client.post(
        "/api/download-file",
        json={"file_id": "admin_settings", "content": sys_compiled["files"]["admin_settings"], "dev_user": ""},
    )
    assert dl_admin.status_code == 200

    dl_sys_zip = client.post("/api/download-zip", json={"state": sys_state})
    assert dl_sys_zip.status_code == 200
    with zipfile.ZipFile(io.BytesIO(dl_sys_zip.data), mode="r") as zf:
        names = set(zf.namelist())
        assert "linux/etc/antigravity/admin_settings.json" in names
        assert "windows/ProgramData/Antigravity/admin_settings.json" in names
        readme_md = zf.read("README_DEPLOYMENT.md").decode("utf-8")
        assert "N/A (System-wide files only)" in readme_md
        win_lock = zf.read("scripts/lock_windows.ps1").decode("utf-8")
        assert "__DEV_USER__" not in win_lock

    # 3. User-scoped files block download (HTTP 400) when dev_user is missing or invalid
    dl_cli_missing = client.post(
        "/api/download-file",
        json={"file_id": "cli_settings", "content": preset_res["files"]["cli_settings"], "dev_user": ""},
    )
    assert dl_cli_missing.status_code == 400
    assert "Workstation Username is required" in dl_cli_missing.get_json()["error"]

    dl_zip_missing = client.post("/api/download-zip", json={"state": preset_res["state"]})
    assert dl_zip_missing.status_code == 400
    assert "Workstation Username is required" in dl_zip_missing.get_json()["error"]

    bad_user_state = dict(preset_res["state"])
    bad_user_state["dev_user"] = "bad user/slash"
    bad_compiled = client.post("/api/compile", json={"state": bad_user_state}).get_json()
    assert any(
        i["code"] == "ERR_INVALID_WORKSTATION_USER"
        for i in bad_compiled["validation"]["issues_by_file"]["cli_settings"]
    )
    assert client.post("/api/download-zip", json={"state": bad_user_state}).status_code == 400

    # 4. Supplying valid dev_user substitutes __DEV_USER__, clears errors, and allows export
    valid_state = dict(preset_res["state"])
    valid_state["dev_user"] = "jdoe"
    valid_compiled = client.post("/api/compile", json={"state": valid_state}).get_json()
    assert valid_compiled["validation"]["error_count"] == 0
    assert "/home/jdoe/workspace" in valid_compiled["files"]["cli_settings"]
    assert "__DEV_USER__" not in valid_compiled["files"]["cli_settings"]

    dl_cli_ok = client.post(
        "/api/download-file",
        json={"file_id": "cli_settings", "content": valid_compiled["files"]["cli_settings"], "dev_user": "jdoe"},
    )
    assert dl_cli_ok.status_code == 200

    dl_zip_ok = client.post("/api/download-zip", json={"state": valid_compiled["state"]})
    assert dl_zip_ok.status_code == 200
    with zipfile.ZipFile(io.BytesIO(dl_zip_ok.data), mode="r") as zf:
        assert "linux/home/jdoe/.gemini/antigravity-cli/settings.json" in zf.namelist()

    # 5. Unreplaced __DEV_USER__ in raw text triggers ERR_UNREPLACED_USER_PLACEHOLDER and Auto-Fixes
    stale_content = valid_compiled["files"]["cli_settings"].replace("/home/jdoe/", "/home/__DEV_USER__/")
    val_stale = client.post(
        "/api/validate",
        json={"file_id": "cli_settings", "content": stale_content, "dev_user": "jdoe"},
    ).get_json()
    assert any(i["code"] == "ERR_UNREPLACED_USER_PLACEHOLDER" for i in val_stale["issues"])

    fixed_stale = client.post(
        "/api/autofix",
        json={
            "file_id": "cli_settings",
            "issue_code": "ERR_UNREPLACED_USER_PLACEHOLDER",
            "content": stale_content,
            "state": valid_compiled["state"],
        },
    ).get_json()
    assert "__DEV_USER__" not in fixed_stale["files"]["cli_settings"]
    assert "/home/jdoe/" in fixed_stale["files"]["cli_settings"]


def test_symmetrical_dropdown_and_control_grid_alignment(client) -> None:
    """
    Verify Step 1, Step 2, and Step 3B form controls use symmetrical 2-column grids and unified CSS tokens.

    Summary:
        Prevents asymmetric `col-sm-5`/`col-sm-7` column splits, uneven label heights,
        and mismatched height/border/chevron rules between `.studio-multiselect-btn`,
        `.form-select`, and `.form-control`.
    Parameters:
        client: Pytest Flask test client fixture.
    Returns:
        None.
    Raises:
        AssertionError: If asymmetrical column classes or missing CSS design tokens are found.
    """
    html = client.get("/").get_data(as_text=True)
    assert "col-sm-5" not in html
    assert "col-sm-7" not in html
    assert html.count('class="studio-field-label-row"') >= 7

    css = client.get("/static/css/studio.css").get_data(as_text=True)
    assert "--studio-control-height: 34px;" in css
    assert "--studio-chevron-bg:" in css
    assert ".studio-field-label-row" in css

    js = client.get("/static/js/studio.js").get_data(as_text=True)
    assert "col-sm-5" not in js
    assert "col-sm-7" not in js
    assert "col-md-7" not in js
    assert "col-md-5" not in js


