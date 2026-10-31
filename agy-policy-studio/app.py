# ==============================================================================
# FILE HEADER: Stateless Flask Web Server — Antigravity Admin Policy Studio
# ==============================================================================
# Purpose:
#   Exposes the responsive Bootstrap 5.3 Policy Studio UI and stateless REST API
#   for authoring, importing, validating, auto-remediating, and exporting all 8
#   canonical Antigravity enterprise configuration groups across Linux, macOS,
#   and Windows.
#
# Architecture / Context:
#   Entry point for local (`./run.sh`), Gunicorn (`Dockerfile`), Google Cloud
#   Run, and GKE deployments. Delegates validation/auto-fix logic to
#   `validator_engine.py` and state compilation/ZIP bundling to
#   `studio_engine.py`. Maintains 100% stateless operation with zero disk writes
#   and zero credential logging.
#
# Dependencies / Side Effects:
#   Reads optional runtime configuration from environment variables (`PORT`,
#   `FLASK_HOST`, `FLASK_DEBUG`, `LOG_LEVEL`, `MAX_UPLOAD_MB`,
#   `DEFAULT_DEV_USER`, `REPO_BASELINE_DIR`) via `python-dotenv`.
# ==============================================================================

from __future__ import annotations

import io
import json
import logging
import os
from typing import Any

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge

from studio_engine import (
    ALL_OS,
    ALL_SURFACES,
    FILE_CATALOG,
    FILE_CATALOG_BY_ID,
    PRESET_METADATA,
    REFERENCE_GUIDE,
    build_default_state,
    build_mdm_zip_bundle,
    compile_studio_state,
    import_archive_or_files,
    load_preset_state,
    parse_file_into_state,
)
from validator_engine import apply_autofix, detect_file_type, validate_bundle, validate_single_file

load_dotenv(override=False)

LOG_LEVEL_NAME = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL_NAME, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("agy_policy_studio")


def _parse_positive_int(raw_val: str | None, default: int, minimum: int = 1, maximum: int = 64) -> int:
    """Validate and clamp an integer environment variable safely.

    Summary:
        Parses integer configuration bounds defensively without raising uncaught
        `ValueError` exceptions on malformed environment strings.
    Parameters:
        raw_val (str | None): Raw environment variable string.
        default (int): Fallback value if missing or invalid.
        minimum (int): Lower clamp bound.
        maximum (int): Upper clamp bound.
    Return Value:
        int: Validated integer within `[minimum, maximum]`.
    Exceptions/Errors:
        None.
    """
    if not raw_val:
        return default
    try:
        parsed = int(raw_val.strip())
        return max(minimum, min(maximum, parsed))
    except ValueError:
        logger.warning("Invalid integer config '%s'; falling back to %d", raw_val, default)
        return default


def create_app() -> Flask:
    """Construct and configure the stateless Flask application instance.

    Summary:
        Initializes Flask settings, upload size limits, security response
        headers, error handlers, and all UI/API routes.
    Parameters:
        None.
    Return Value:
        Flask: Configured WSGI Flask application ready for Gunicorn or dev run.
    Exceptions/Errors:
        None.
    """
    application = Flask(__name__)
    max_mb = _parse_positive_int(os.getenv("MAX_UPLOAD_MB"), default=16, minimum=1, maximum=64)
    application.config["MAX_CONTENT_LENGTH"] = max_mb * 1024 * 1024
    application.config["JSON_SORT_KEYS"] = False

    @application.after_request
    def _apply_security_headers(resp: Response) -> Response:
        """Attach defensive HTTP security and no-store cache headers.

        Summary:
            Prevents MIME sniffing, clickjacking, and disk caching of API
            responses that may carry administrator-entered policy data.
        Parameters:
            resp (Response): Outgoing Flask HTTP response.
        Return Value:
            Response: Mutated Flask HTTP response with security headers.
        Exceptions/Errors:
            None.
        """
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "SAMEORIGIN"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "font-src 'self' data:; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'self'"
        )
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store, max-age=0"
        return resp

    @application.errorhandler(RequestEntityTooLarge)
    def _handle_payload_too_large(_exc: RequestEntityTooLarge) -> tuple[Response, int]:
        """Return structured JSON error when an upload exceeds MAX_UPLOAD_MB.

        Summary:
            Converts Werkzeug `413` exceptions into clean JSON payloads.
        Parameters:
            _exc (RequestEntityTooLarge): Triggered Werkzeug size limit error.
        Return Value:
            tuple[Response, int]: JSON error object and HTTP 413 status.
        Exceptions/Errors:
            None.
        """
        logger.warning("Rejected oversized upload payload (> %d MiB)", max_mb)
        return jsonify({"error": f"Upload exceeds maximum allowed size ({max_mb} MiB)."}), 413

    @application.errorhandler(Exception)
    def _handle_unexpected_error(exc: Exception) -> tuple[Response, int]:
        """Handle unexpected server exceptions without leaking stack traces.

        Summary:
            Logs server errors structurally without exposing sensitive values to
            clients.
        Parameters:
            exc (Exception): Unhandled exception instance.
        Return Value:
            tuple[Response, int]: Generic JSON error payload and HTTP 500 status.
        Exceptions/Errors:
            None.
        """
        logger.error("Unhandled error on %s %s: %s", request.method, request.path, type(exc).__name__)
        return jsonify({"error": "Internal studio processing error."}), 500

    def _require_json_dict() -> dict[str, Any]:
        """Extract and validate a JSON object body from the active HTTP request.

        Summary:
            Ensures incoming `POST /api/*` requests provide a JSON dictionary.
        Parameters:
            None.
        Return Value:
            dict[str, Any]: Parsed request dictionary.
        Exceptions/Errors:
            ValueError: If request payload is missing or not a JSON object.
        """
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a valid JSON object.")
        return payload

    @application.get("/health")
    def health_check() -> tuple[Response, int]:
        """Return container liveness/readiness health status for Cloud Run & GKE.

        Summary:
            Lightweight `/health` probe avoiding `/*z` paths reserved by Google
            Front End (GFE) on Cloud Run.
        Parameters:
            None.
        Return Value:
            tuple[Response, int]: `{"status": "ok"}` with HTTP 200.
        Exceptions/Errors:
            None.
        """
        return jsonify({"status": "ok", "service": "antigravity-admin-policy-studio"}), 200

    @application.get("/")
    def index_view() -> str:
        """Render the single-page Split-Pane Antigravity Policy Studio UI.

        Summary:
            Seeds initial client bootstrap data (`FILE_CATALOG`, `PRESET_METADATA`,
            and the compiled `balanced` enterprise preset) directly into the
            template so first paint requires zero extra round-trips.
        Parameters:
            None.
        Return Value:
            str: Rendered HTML5 document.
        Exceptions/Errors:
            None.
        """
        default_user = os.getenv("DEFAULT_DEV_USER", "alice").strip() or "alice"
        initial_state = build_default_state(dev_user=default_user)
        bootstrap = {
            "catalog": FILE_CATALOG,
            "presets": PRESET_METADATA,
            "reference": REFERENCE_GUIDE,
            "initial": compile_studio_state(initial_state),
        }
        return render_template("index.html", bootstrap_json=json.dumps(bootstrap))

    @application.get("/api/presets")
    def list_presets() -> tuple[Response, int]:
        """Return available starter presets, recipes, and canonical file metadata.

        Summary:
            Allows API consumers and automated UI clients to inspect all presets
            and supported configuration groups.
        Parameters:
            None.
        Return Value:
            tuple[Response, int]: JSON metadata dictionary and HTTP 200.
        Exceptions/Errors:
            None.
        """
        return jsonify({"presets": PRESET_METADATA, "catalog": FILE_CATALOG, "reference": REFERENCE_GUIDE}), 200

    @application.post("/api/preset")
    def apply_preset_route() -> tuple[Response, int]:
        """Load a named starter preset or `ADMIN_POLICY_EXAMPLES.md` recipe.

        Summary:
            Initializes studio state from `preset_id`, preserves the caller's
            `dev_user` if supplied, and returns compiled files + validation.
        Parameters:
            None (reads JSON body `{"preset_id": str, "dev_user": str}`).
        Return Value:
            tuple[Response, int]: Compiled studio state payload and HTTP 200/400.
        Exceptions/Errors:
            Returns HTTP 400 on unknown `preset_id` or malformed request JSON.
        """
        try:
            body = _require_json_dict()
            preset_id = str(body.get("preset_id", "balanced")).strip()
            dev_user = str(body.get("dev_user", os.getenv("DEFAULT_DEV_USER", "alice"))).strip() or "alice"
            state = load_preset_state(preset_id=preset_id, dev_user=dev_user)
            scope_specific_recipes = {
                "recipe_bastion_strict",
                "recipe_windows_enterprise",
                "recipe_jetbrains_zed_acp",
            }
            if body.get("preserve_scope") is True and preset_id not in scope_specific_recipes:
                if isinstance(body.get("os_list"), list):
                    state["os_list"] = [o for o in body["os_list"] if o in ALL_OS]
                if isinstance(body.get("surfaces"), list):
                    state["surfaces"] = [s for s in body["surfaces"] if s in ALL_SURFACES]
                if "selected_file_ids" in body:
                    state["selected_file_ids"] = body.get("selected_file_ids")
            logger.info("Loaded preset '%s' for dev_user='%s'", preset_id, dev_user)
            return jsonify(compile_studio_state(state)), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @application.post("/api/compile")
    def compile_route() -> tuple[Response, int]:
        """Compile structured form controls into canonical files and validation.

        Summary:
            Forward half of Two-Way Form -> Code synchronization.
        Parameters:
            None (reads JSON body `{"state": dict}`).
        Return Value:
            tuple[Response, int]: Compiled files, validation report, and CLI locks.
        Exceptions/Errors:
            Returns HTTP 400 if `state` is missing or invalid.
        """
        try:
            body = _require_json_dict()
            state = body.get("state")
            if not isinstance(state, dict):
                return jsonify({"error": "Missing or invalid 'state' object."}), 400
            return jsonify(compile_studio_state(state)), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @application.post("/api/sync-code")
    def sync_code_route() -> tuple[Response, int]:
        """Synchronize raw right-pane code edits back into structured form state.

        Summary:
            Reverse half of Two-Way Code -> Form synchronization. Preserves
            exact edited text in `files[file_id]` (including mid-edit syntax
            errors so the validator highlights the exact line/col) while updating
            structured `state` and synchronized surfaces when valid.
        Parameters:
            None (reads JSON body `{"file_id": str, "content": str, "state": dict}`).
        Return Value:
            tuple[Response, int]: Updated state, active files, and live validation.
        Exceptions/Errors:
            Returns HTTP 400 on invalid `file_id` or malformed JSON body.
        """
        try:
            body = _require_json_dict()
            file_id = str(body.get("file_id", "")).strip()
            if file_id not in FILE_CATALOG_BY_ID:
                return jsonify({"error": f"Unknown file_id: {file_id}"}), 400
            raw_content = str(body.get("content", ""))
            current_state = body.get("state")
            if not isinstance(current_state, dict):
                current_state = build_default_state()

            has_bom = raw_content.startswith("\ufeff")
            updated_state = parse_file_into_state(file_id, raw_content, current_state)
            compiled = compile_studio_state(updated_state)
            compiled["files"][file_id] = raw_content
            compiled["validation"] = validate_bundle(
                files_map=compiled["files"],
                os_list=compiled["state"]["os_list"],
                surfaces=compiled["state"]["surfaces"],
                dev_user=compiled["state"]["dev_user"],
                bom_map={file_id: has_bom},
            )
            return jsonify(compiled), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @application.post("/api/validate")
    def validate_route() -> tuple[Response, int]:
        """Validate standalone raw text or a map of configuration files.

        Summary:
            Supports standalone validation in the Import/Validate modal as well
            as automated CI policy linting via `curl`.
        Parameters:
            None (reads JSON body with `content` + optional `file_id`/`filename`
            or `files` dictionary).
        Return Value:
            tuple[Response, int]: Validation summary and detected file slot.
        Exceptions/Errors:
            Returns HTTP 400 on malformed request payload.
        """
        try:
            body = _require_json_dict()
            os_list = [o for o in body.get("os_list", ALL_OS) if o in ALL_OS] or list(ALL_OS)
            surfaces = [s for s in body.get("surfaces", ALL_SURFACES) if s in ALL_SURFACES] or list(ALL_SURFACES)
            dev_user = str(body.get("dev_user", "alice")).strip() or "alice"

            if isinstance(body.get("files"), dict):
                files_in = {str(k): str(v) for k, v in body["files"].items() if k in FILE_CATALOG_BY_ID}
                report = validate_bundle(files_in, os_list, surfaces, dev_user=dev_user)
                return jsonify(report), 200

            content = str(body.get("content", ""))
            filename = str(body.get("filename", ""))
            file_id = str(body.get("file_id", "")).strip() or detect_file_type(filename, content)
            if file_id not in FILE_CATALOG_BY_ID:
                return jsonify({"error": f"Unknown file_id: {file_id}"}), 400

            issues = validate_single_file(
                file_id=file_id,
                content=content,
                os_list=os_list,
                surfaces=surfaces,
                dev_user=dev_user,
                has_bom=content.startswith("\ufeff"),
            )
            return jsonify(
                {
                    "detected_file_id": file_id,
                    "error_count": sum(1 for i in issues if i["severity"] == "ERROR"),
                    "warn_count": sum(1 for i in issues if i["severity"] == "WARN"),
                    "issues": issues,
                }
            ), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @application.post("/api/autofix")
    def autofix_route() -> tuple[Response, int]:
        """Apply one specific validation Auto-Fix or `'ALL'` fixes across files.

        Summary:
            Remediates the requested `issue_code` (or `"ALL"` across either one
            file or the entire bundle), syncs the repaired file back into
            structured `state`, and returns updated validation results.
        Parameters:
            None (reads JSON body `{"file_id": str, "issue_code": str, "content": str, "state": dict}`).
        Return Value:
            tuple[Response, int]: Repaired compiled studio payload and HTTP 200.
        Exceptions/Errors:
            Returns HTTP 400 on invalid parameters.
        """
        try:
            body = _require_json_dict()
            issue_code = str(body.get("issue_code", "ALL")).strip() or "ALL"
            state = body.get("state")
            if not isinstance(state, dict):
                state = build_default_state()

            os_list = [o for o in state.get("os_list", ALL_OS) if o in ALL_OS] or list(ALL_OS)
            surfaces = [s for s in state.get("surfaces", ALL_SURFACES) if s in ALL_SURFACES] or list(ALL_SURFACES)
            dev_user = str(state.get("dev_user", "alice")).strip() or "alice"

            target_fid = str(body.get("file_id", "")).strip()
            files_override = body.get("files") if isinstance(body.get("files"), dict) else {}

            if target_fid == "ALL_FILES":
                compiled_initial = compile_studio_state(state)
                working_files = dict(compiled_initial["files"])
                working_files.update({str(k): str(v) for k, v in files_override.items() if k in FILE_CATALOG_BY_ID})
                for fid, raw_txt in list(working_files.items()):
                    fixed_txt = apply_autofix(fid, raw_txt, "ALL", os_list, surfaces, dev_user=dev_user)
                    state = parse_file_into_state(fid, fixed_txt, state)
                logger.info("Applied Fix-All across active studio bundle")
                return jsonify(compile_studio_state(state)), 200

            if target_fid not in FILE_CATALOG_BY_ID:
                return jsonify({"error": f"Unknown file_id: {target_fid}"}), 400

            raw_content = str(body.get("content", ""))
            fixed_content = apply_autofix(
                file_id=target_fid,
                content=raw_content,
                issue_code=issue_code,
                os_list=os_list,
                surfaces=surfaces,
                dev_user=dev_user,
            )
            updated_state = parse_file_into_state(target_fid, fixed_content, state)
            compiled = compile_studio_state(updated_state)
            compiled["files"][target_fid] = fixed_content
            compiled["validation"] = validate_bundle(
                files_map=compiled["files"],
                os_list=compiled["state"]["os_list"],
                surfaces=compiled["state"]["surfaces"],
                dev_user=compiled["state"]["dev_user"],
            )
            logger.info("Applied autofix '%s' on file '%s'", issue_code, target_fid)
            return jsonify(compiled), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @application.post("/api/import")
    def import_route() -> tuple[Response, int]:
        """Import uploaded files, `.zip` bundles, pasted raw text, or repo baseline.

        Summary:
            Supports both `multipart/form-data` uploads (preserving raw byte BOM
            inspection) and `application/json` pasted text / baseline imports.
        Parameters:
            None (reads multipart `files` + `state` OR JSON body).
        Return Value:
            tuple[Response, int]: Updated studio state, files, imported metadata,
            and BOM-aware validation report.
        Exceptions/Errors:
            Returns HTTP 400 on empty uploads, invalid ZIPs, or bad JSON.
        """
        try:
            if request.content_type and "multipart/form-data" in request.content_type.lower():
                raw_state_str = request.form.get("state", "{}")
                try:
                    current_state = json.loads(raw_state_str) if raw_state_str else build_default_state()
                except json.JSONDecodeError:
                    current_state = build_default_state()
                if not isinstance(current_state, dict):
                    current_state = build_default_state()

                uploaded = request.files.getlist("files")
                items: list[tuple[str, bytes]] = []
                for storage in uploaded:
                    if storage and storage.filename:
                        items.append((storage.filename, storage.read()))
                if not items:
                    return jsonify({"error": "No files provided in multipart upload."}), 400

                result = import_archive_or_files(items, current_state)
                logger.info("Imported %d file entry(ies) via multipart upload", len(result.get("imported_files", [])))
                return jsonify(result), 200

            body = _require_json_dict()
            current_state = body.get("state")
            if not isinstance(current_state, dict):
                current_state = build_default_state()

            if body.get("load_repo_baseline") is True:
                dev_user = str(current_state.get("dev_user", "alice")).strip() or "alice"
                baseline_state = load_preset_state("repo_baseline", dev_user=dev_user)
                baseline_state["os_list"] = current_state.get("os_list") or list(ALL_OS)
                baseline_state["surfaces"] = current_state.get("surfaces") or list(ALL_SURFACES)
                baseline_state["selected_file_ids"] = None
                compiled = compile_studio_state(baseline_state)
                compiled["imported_files"] = [
                    {"source_name": "agy-config/configs/*", "detected_file_id": "repo_baseline", "had_utf8_bom": False}
                ]
                logger.info("Imported sibling repository baseline into studio")
                return jsonify(compiled), 200

            raw_text = str(body.get("raw_text", ""))
            if not raw_text.strip():
                return jsonify({"error": "Pasted configuration text cannot be empty."}), 400
            hint_name = str(body.get("filename", ""))
            explicit_fid = str(body.get("file_id", "")).strip()
            if explicit_fid and explicit_fid in FILE_CATALOG_BY_ID:
                fname = FILE_CATALOG_BY_ID[explicit_fid]["filename"]
            else:
                fname = hint_name or "pasted_config"

            result = import_archive_or_files([(fname, raw_text.encode("utf-8"))], current_state)
            return jsonify(result), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @application.post("/api/download-file")
    def download_single_file_route() -> Response | tuple[Response, int]:
        """Stream a single BOM-free UTF-8 configuration file attachment.

        Summary:
            Strips any accidental UTF-8 BOM bytes and normalizes line endings
            (`CRLF` for `.ps1`, `LF` for JSON/env/sh/txt) before streaming.
        Parameters:
            None (reads JSON body `{"file_id": str, "content": str}`).
        Return Value:
            Response | tuple[Response, int]: File download attachment or HTTP 400.
        Exceptions/Errors:
            Returns HTTP 400 on unknown `file_id`.
        """
        try:
            body = _require_json_dict()
            file_id = str(body.get("file_id", "")).strip()
            if file_id not in FILE_CATALOG_BY_ID:
                return jsonify({"error": f"Unknown file_id: {file_id}"}), 400

            meta = FILE_CATALOG_BY_ID[file_id]
            raw_content = str(body.get("content", "")).lstrip("\ufeff")
            lf_content = raw_content.replace("\r\n", "\n")
            final_text = lf_content.replace("\n", "\r\n") if file_id == "guard_ps1" else lf_content
            filename = meta["filename"]

            return Response(
                final_text.encode("utf-8"),
                mimetype="application/octet-stream",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    "X-Content-Type-Options": "nosniff",
                },
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @application.post("/api/download-zip")
    def download_zip_route() -> Response | tuple[Response, int]:
        """Generate and stream the OS-structured BOM-free MDM `.zip` bundle.

        Summary:
            Packages all active configuration files into `linux/`, `macos/`, and
            `windows/` directory trees along with `scripts/lock_*` scripts and
            `README_DEPLOYMENT.md`.
        Parameters:
            None (reads JSON body `{"state": dict}`).
        Return Value:
            Response | tuple[Response, int]: `application/zip` download response.
        Exceptions/Errors:
            Returns HTTP 400 if `state` is missing or invalid.
        """
        try:
            body = _require_json_dict()
            state = body.get("state")
            if not isinstance(state, dict):
                return jsonify({"error": "Missing or invalid 'state' object."}), 400

            zip_bytes = build_mdm_zip_bundle(state)
            logger.info(
                "Generated MDM ZIP bundle (%d bytes) for OS=%s surfaces=%s",
                len(zip_bytes),
                ",".join(state.get("os_list", [])),
                ",".join(state.get("surfaces", [])),
            )
            return send_file(
                io.BytesIO(zip_bytes),
                mimetype="application/zip",
                as_attachment=True,
                download_name="antigravity-mdm-policy-bundle.zip",
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    return application


app = create_app()

if __name__ == "__main__":
    bind_host = os.getenv("FLASK_HOST", "0.0.0.0")
    bind_port = _parse_positive_int(os.getenv("PORT"), default=8090, minimum=1, maximum=65535)
    debug_enabled = os.getenv("FLASK_DEBUG", "false").strip().lower() == "true"
    logger.info("Starting Antigravity Admin Policy Studio on http://%s:%d", bind_host, bind_port)
    app.run(host=bind_host, port=bind_port, debug=debug_enabled)
