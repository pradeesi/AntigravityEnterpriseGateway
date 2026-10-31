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
    base_state = client.post("/api/preset", json={"preset_id": "balanced"}).get_json()["state"]

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



