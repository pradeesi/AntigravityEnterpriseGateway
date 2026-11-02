# ==============================================================================
# FILE HEADER: Python Antigravity Enterprise Gateway — Model Armor & Dynamic Router
# ==============================================================================
# Author: Pradeep Singh
# License: Apache-2.0
#
# Purpose:
#   Implements Google Cloud Model Armor prompt/response screening, Cloud SDP
#   in-place PII redaction, multi-turn blocked-history scrubbing, Gemini 4
#   thinking-level normalization, and dynamic multi-project/multi-region routing.
#
# Architecture / Context:
#   Organized into 7 explicit code blocks mirroring `go/routing_and_armor.go`:
#     - BLOCK 1: Unified Environment & Settings Loader (`_load_env_files`, `get_env`).
#     - BLOCK 2: Standardized Model Armor & Dynamic Routing Variables.
#     - BLOCK 3: Routing & Model Armor Data Structures (`RouterAndArmorConfig`, `RouteTarget`).
#     - BLOCK 4: Configuration Parsers (`parse_key_value_env`, `parse_csv_env`, `load_router_and_armor_config`).
#     - BLOCK 5: Dynamic Route Resolution Engine (`resolve_route_target`, `build_routed_vertex_url`).
#     - BLOCK 6: Google Cloud Model Armor Enforcement Engine (`inject_native_model_armor_config`,
#                `sanitize_prompt_inline`, `replace_last_user_prompt_text`, `scrub_blocked_history_turns`,
#                `format_policy_block_message`).
#     - BLOCK 7: Gemini 4+ Thinking-Level Normalization Engine (`normalize_thinking_config_for_model`).
#
# Dependencies / Side Effects:
#   - Auto-loads `.env` / `../.env` and `settings.env` / `../settings.env`.
#   - In `inline` mode, makes outbound HTTPS POST calls to
#     `https://modelarmor.<REGION>.rep.googleapis.com/v1/...:sanitizeUserPrompt`.
# ==============================================================================

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from dotenv import dotenv_values


# ==============================================================================
# BLOCK 1: UNIFIED ENVIRONMENT & SETTINGS FILE LOADER
# ==============================================================================
def _load_env_files() -> None:
    """Load `.env` and `settings.env` files in strict priority order without shadowing with blank values.

    Summary:
        Populates unset OS environment variables from `.env`, `../.env`,
        `settings.env`, and `../settings.env` (highest to lowest priority).

    Parameters:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    module_dir = Path(__file__).resolve().parent
    candidates = [
        Path(".env"),
        Path("../.env"),
        module_dir / ".env",
        module_dir.parent / ".env",
        Path("settings.env"),
        Path("../settings.env"),
        module_dir / "settings.env",
        module_dir.parent / "settings.env",
    ]
    seen_paths = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen_paths or not resolved.is_file():
            continue
        seen_paths.add(resolved)
        for key, val in dotenv_values(resolved).items():
            if not key or val is None:
                continue
            cleaned_val = val.strip()
            # Ignore empty strings in settings.env so lower-priority files or fallbacks still work.
            if cleaned_val and not os.environ.get(key, "").strip():
                os.environ[key] = cleaned_val


_load_env_files()


def get_env(key: str, fallback: str = "") -> str:
    """Retrieve a standardized configuration variable or fall back to the in-code default.

    Parameters:
        key (str): Standardized environment variable name.
        fallback (str): Default value used when env/settings files omit the key.

    Returns:
        str: Resolved configuration value with surrounding whitespace stripped.

    Raises:
        None.
    """
    val = os.getenv(key, "").strip()
    if val:
        if (
            val.startswith("REPLACE_WITH_")
            and fallback
            and not fallback.startswith("REPLACE_WITH_")
        ):
            return fallback.strip()
        return val
    return fallback.strip()


# ==============================================================================
# BLOCK 2: MODEL ARMOR & DYNAMIC ROUTING VARIABLES
# ==============================================================================
ENABLE_MODEL_ARMOR: str = get_env("ENABLE_MODEL_ARMOR", "true")
MODEL_ARMOR_TEMPLATE_ID: str = get_env("MODEL_ARMOR_TEMPLATE_ID", "")
MODEL_ARMOR_MODE: str = get_env("MODEL_ARMOR_MODE", "inline")
MODEL_ARMOR_FAIL_CLOSED: str = get_env("MODEL_ARMOR_FAIL_CLOSED", "true")
COST_CENTER_PROJECT_MAP: str = get_env("COST_CENTER_PROJECT_MAP", "")
MODEL_REGION_MAP: str = get_env("MODEL_REGION_MAP", "")
FAILOVER_REGIONS: str = get_env("FAILOVER_REGIONS", "")
DEFAULT_FLASH_FALLBACK_MODEL: str = get_env(
    "DEFAULT_FLASH_FALLBACK_MODEL", "gemini-3.8-flash"
)
OPENAI_UPSTREAM_BASE_URL: str = get_env("OPENAI_UPSTREAM_BASE_URL", "")


# ==============================================================================
# BLOCK 3: ROUTING & MODEL ARMOR DATA STRUCTURES
# ==============================================================================
@dataclass
class RouterAndArmorConfig:
    """Holds startup-parsed routing maps and Model Armor settings.

    Attributes:
        default_project (str): Default GCP project ID from main.py.
        default_region (str): Default GCP region from main.py.
        failover_regions (List[str]): Ordered list of secondary regions for 429/503 failover.
        cost_center_projects (Dict[str, str]): Map of X-Cost-Center header values to GCP project IDs.
        model_regions (Dict[str, str]): Map of Gemini model IDs to target GCP regions.
        model_armor_template_id (str): Google Cloud Model Armor template ID.
        model_armor_mode (str): Enforcement mode ('inline', 'native', or 'disabled').
        model_armor_fail_closed (bool): Whether to reject requests if inline Model Armor is unreachable.
        default_flash_fallback_model (str): Flash model substituted for unmapped MODEL_PLACEHOLDER_M50 enums.
        openai_upstream_base_url (str): Optional custom upstream base URL for `/v1/chat/completions`.
    """

    default_project: str
    default_region: str
    failover_regions: List[str] = field(default_factory=list)
    cost_center_projects: Dict[str, str] = field(default_factory=dict)
    model_regions: Dict[str, str] = field(default_factory=dict)
    model_armor_template_id: str = ""
    model_armor_mode: str = "inline"
    model_armor_fail_closed: bool = True
    default_flash_fallback_model: str = "gemini-3.8-flash"
    openai_upstream_base_url: str = ""


@dataclass
class RouteTarget:
    """Holds per-request resolved project, region, PT flag, thinking level, OpenAI state, and Model Armor templates.

    Attributes:
        project_id (str): Resolved target GCP project ID.
        region (str): Resolved primary GCP region (or 'global').
        failover_regions (List[str]): Secondary regions retried on HTTP 429/503.
        model_action (str): Extracted '<model_id>:<action>' segment with suffixes stripped.
        dedicated_pt (bool): True if the requested model had a '-pt' Provisioned Throughput suffix.
        thinking_level (str): Explicit thinking level ('LOW', 'MEDIUM', 'HIGH', 'MINIMAL') if requested.
        prompt_template_name (str): Full Model Armor template resource name for user prompts.
        resp_template_name (str): Full Model Armor template resource name for model responses.
        is_openai_chat (bool): True when the request targets OpenAI wire protocol (`/v1/chat/completions`).
        openai_model_id (str): Clean resolved model ID for OpenAI Chat Completions payloads.
        openai_upstream_base_url (str): Custom OpenAI upstream base URL if configured; empty uses Vertex AI OpenAI endpoint.
        m50_fallback_applied (bool): True when an unmapped `MODEL_PLACEHOLDER_*` enum was rewritten to Flash.
    """

    project_id: str
    region: str
    failover_regions: List[str] = field(default_factory=list)
    model_action: str = ""
    dedicated_pt: bool = False
    thinking_level: str = ""
    prompt_template_name: str = ""
    resp_template_name: str = ""
    is_openai_chat: bool = False
    openai_model_id: str = ""
    openai_upstream_base_url: str = ""
    m50_fallback_applied: bool = False


# ==============================================================================
# BLOCK 4: CONFIGURATION PARSERS (Startup Initialization)
# ==============================================================================
def parse_key_value_env(raw: str) -> Dict[str, str]:
    """Parse a comma-separated 'Key1=Val1,Key2=Val2' string into a dictionary.

    Parameters:
        raw (str): Comma-separated key=value pairs.

    Returns:
        Dict[str, str]: Dictionary of non-empty trimmed keys and values.

    Raises:
        None.
    """
    result: Dict[str, str] = {}
    for pair in raw.split(","):
        pair_clean = pair.strip()
        if "=" in pair_clean:
            k, v = pair_clean.split("=", 1)
            k_clean, v_clean = k.strip(), v.strip()
            if k_clean and v_clean:
                result[k_clean] = v_clean
    return result


def parse_csv_env(raw: str) -> List[str]:
    """Parse a comma-separated list of strings into a list of non-empty trimmed items.

    Parameters:
        raw (str): Comma-separated string values.

    Returns:
        List[str]: List of non-empty trimmed strings.

    Raises:
        None.
    """
    return [item.strip() for item in raw.split(",") if item.strip()]


def load_router_and_armor_config(
    default_project: str, default_region: str
) -> RouterAndArmorConfig:
    """Initialize RouterAndArmorConfig from Block 2 variables.

    Parameters:
        default_project (str): Default GCP project ID from main.py.
        default_region (str): Default GCP region from main.py.

    Returns:
        RouterAndArmorConfig: Initialized routing and Model Armor configuration.

    Raises:
        None.
    """
    mode = MODEL_ARMOR_MODE.strip().lower() or "inline"
    if ENABLE_MODEL_ARMOR.strip().lower() == "false":
        mode = "disabled"
    fail_closed = MODEL_ARMOR_FAIL_CLOSED.strip().lower() != "false"
    flash_fallback = DEFAULT_FLASH_FALLBACK_MODEL.strip() or "gemini-3.8-flash"

    return RouterAndArmorConfig(
        default_project=default_project,
        default_region=default_region,
        failover_regions=parse_csv_env(FAILOVER_REGIONS),
        cost_center_projects=parse_key_value_env(COST_CENTER_PROJECT_MAP),
        model_regions=parse_key_value_env(MODEL_REGION_MAP),
        model_armor_template_id=MODEL_ARMOR_TEMPLATE_ID.strip(),
        model_armor_mode=mode,
        model_armor_fail_closed=fail_closed,
        default_flash_fallback_model=flash_fallback,
        openai_upstream_base_url=OPENAI_UPSTREAM_BASE_URL.strip(),
    )


# ==============================================================================
# BLOCK 5: DYNAMIC ROUTE RESOLUTION ENGINE
# ==============================================================================
THINKING_SUFFIX_MAP: Dict[str, str] = {
    "-high": "HIGH",
    "-medium": "MEDIUM",
    "-low": "LOW",
    "-minimal": "MINIMAL",
}


def resolve_route_target(
    path: str,
    headers: Dict[str, str],
    cfg: RouterAndArmorConfig,
    body: bytes = b"",
) -> RouteTarget:
    """Dynamically resolve target GCP project, region, PT flag, thinking level, OpenAI target, and Model Armor templates.

    Parameters:
        path (str): Incoming request URL path.
        headers (Dict[str, str]): Incoming HTTP headers.
        cfg (RouterAndArmorConfig): Parsed routing and Model Armor configuration.
        body (bytes): Optional raw JSON request body (inspected for `model` on `/v1/chat/completions`).

    Returns:
        RouteTarget: Resolved routing target parameters for the current request.

    Raises:
        None.
    """
    target = RouteTarget(
        project_id=cfg.default_project,
        region=cfg.default_region,
        failover_regions=list(cfg.failover_regions),
    )

    # Step 1: Cost-Center Chargeback Routing via X-Cost-Center header.
    cost_center = (
        headers.get("x-cost-center", "") or headers.get("X-Cost-Center", "")
    ).strip()
    if cost_center and cost_center in cfg.cost_center_projects:
        target.project_id = cfg.cost_center_projects[cost_center]

    # Step 2: Detect GenAI URL path vs. OpenAI Chat Completions wire protocol (`/v1/chat/completions`).
    model_id = ""
    action_suffix = ""
    if path.rstrip("/").endswith("/chat/completions"):
        target.is_openai_chat = True
        target.openai_upstream_base_url = cfg.openai_upstream_base_url
        if body:
            try:
                payload = json.loads(body)
                if isinstance(payload, dict) and isinstance(payload.get("model"), str):
                    raw_openai_model = payload["model"].strip()
                    if raw_openai_model.startswith("google/"):
                        model_id = raw_openai_model[len("google/") :]
                    else:
                        model_id = raw_openai_model
            except Exception:
                model_id = ""
    elif path.startswith("/v1beta/models/"):
        target.model_action = path[len("/v1beta/models/") :]
        parts = target.model_action.split(":", 1)
        model_id = parts[0]
        action_suffix = f":{parts[1]}" if len(parts) > 1 else ""
    elif "/publishers/google/models/" in path:
        idx = path.index("/publishers/google/models/")
        target.model_action = path[idx + len("/publishers/google/models/") :]
        parts = target.model_action.split(":", 1)
        model_id = parts[0]
        action_suffix = f":{parts[1]}" if len(parts) > 1 else ""

    # Step 2b: Guard against unmapped `MODEL_PLACEHOLDER_M50` / `MODEL_PLACEHOLDER_*` enums
    # emitted during background titling/checkpointing when a client omits a Flash model.
    if model_id.upper() == "MODEL_PLACEHOLDER_M50" or model_id.upper().startswith(
        "MODEL_PLACEHOLDER_"
    ):
        model_id = cfg.default_flash_fallback_model
        target.m50_fallback_applied = True

    # Step 3a: Provisioned Throughput ('-pt') suffix handling.
    if model_id.endswith("-pt"):
        target.dedicated_pt = True
        model_id = model_id[:-3]

    # Step 3b: Thinking-level suffix alias handling (e.g., 'gemini-4-argon-high').
    lower_model_id = model_id.lower()
    for suffix, level_val in THINKING_SUFFIX_MAP.items():
        if lower_model_id.endswith(suffix):
            target.thinking_level = level_val
            model_id = model_id[: -len(suffix)]
            break

    if model_id.endswith("-pt"):
        target.dedicated_pt = True
        model_id = model_id[:-3]

    if target.is_openai_chat:
        target.openai_model_id = model_id
    elif target.model_action:
        target.model_action = f"{model_id}{action_suffix}"

    # Step 4: Model-specific regional placement; Gemini 4 and 3.x default to 'global' PayGo endpoint.
    if model_id and model_id in cfg.model_regions:
        target.region = cfg.model_regions[model_id]
    elif model_id.startswith(("gemini-4-", "gemini-3.")):
        target.region = "global"

    # Step 5: Build regional Model Armor template resource name.
    if cfg.model_armor_template_id and cfg.model_armor_mode != "disabled":
        armor_region = target.region
        if armor_region == "global":
            armor_region = (
                cfg.default_region
                if cfg.default_region and cfg.default_region != "global"
                else "europe-west1"
            )
        template_name = (
            f"projects/{target.project_id}/locations/{armor_region}"
            f"/templates/{cfg.model_armor_template_id}"
        )
        target.prompt_template_name = template_name
        target.resp_template_name = template_name

    return target


def build_routed_vertex_url(
    target: RouteTarget, active_region: str, orig_path: str, raw_query: str
) -> str:
    """Construct the target regional or global Gemini Enterprise Agent Platform (or custom OpenAI) URL.

    Parameters:
        target (RouteTarget): Resolved project, OpenAI flag, and model action metadata.
        active_region (str): Active region for the current attempt (primary or failover).
        orig_path (str): Original request URL path for pass-through endpoints.
        raw_query (str): Raw URL query string (e.g., 'alt=sse').

    Returns:
        str: Fully qualified HTTPS backend URL.

    Raises:
        None.
    """
    if target.is_openai_chat:
        if target.openai_upstream_base_url:
            base = target.openai_upstream_base_url.rstrip("/")
            if base.endswith("/chat/completions"):
                url = base
            elif base.endswith("/v1"):
                url = f"{base}/chat/completions"
            else:
                url = f"{base}/v1/chat/completions"
            if raw_query:
                url = f"{url}?{raw_query}"
            return url

        target_path = (
            f"/v1beta1/projects/{target.project_id}/locations/{active_region}"
            "/endpoints/openapi/chat/completions"
        )
    elif target.model_action:
        target_path = (
            f"/v1beta1/projects/{target.project_id}/locations/{active_region}"
            f"/publishers/google/models/{target.model_action}"
        )
    else:
        target_path = orig_path

    host = (
        "aiplatform.googleapis.com"
        if active_region == "global"
        else f"{active_region}-aiplatform.googleapis.com"
    )
    url = f"https://{host}{target_path}"
    if raw_query:
        url = f"{url}?{raw_query}"
    return url


# ==============================================================================
# BLOCK 6: GOOGLE CLOUD MODEL ARMOR ENFORCEMENT ENGINE
# ==============================================================================
def inject_native_model_armor_config(body: bytes, target: RouteTarget) -> bytes:
    """Inject native `modelArmorConfig` into a generateContent JSON payload if absent.

    Parameters:
        body (bytes): Raw JSON request body.
        target (RouteTarget): Resolved target containing prompt and response template names.

    Returns:
        bytes: Updated JSON request body (or original bytes if OpenAI mode or parsing fails).

    Raises:
        None.
    """
    if target.is_openai_chat or not target.prompt_template_name or not body:
        return body
    try:
        payload: Dict[str, Any] = json.loads(body)
        if isinstance(payload, dict) and "modelArmorConfig" not in payload:
            payload["modelArmorConfig"] = {
                "promptTemplateName": target.prompt_template_name,
                "responseTemplateName": target.resp_template_name,
            }
            return json.dumps(payload).encode("utf-8")
    except Exception:
        return body
    return body


def _strip_ide_harness_tags(text: str) -> str:
    """Remove internal Antigravity `<SYSTEM_MESSAGE>` and `<SYSTEM_REMINDER>` blocks before scanning."""
    for tag in ("SYSTEM_MESSAGE", "SYSTEM_REMINDER"):
        open_tag = f"<{tag}>"
        close_tag = f"</{tag}>"
        while True:
            start = text.find(open_tag)
            if start == -1:
                break
            end = text.find(close_tag, start)
            if end == -1:
                break
            text = text[:start] + text[end + len(close_tag) :]
    return text.strip()


def _extract_last_turn_text(payload: Dict[str, Any]) -> str:
    """Extract raw human user text from either GenAI `contents[]` or OpenAI `messages[]`.

    Parameters:
        payload (Dict[str, Any]): Parsed request JSON payload.

    Returns:
        str: Concatenated text of the final user turn, or empty string on automated tool-return turns.

    Raises:
        None.
    """
    contents = payload.get("contents")
    if isinstance(contents, list) and contents:
        last_content = contents[-1]
        if isinstance(last_content, dict):
            parts = last_content.get("parts", [])
            has_func_resp = False
            extracted_chunks: List[str] = []
            for p in parts:
                if not isinstance(p, dict):
                    continue
                if p.get("functionResponse"):
                    has_func_resp = True
                    continue
                if p.get("text"):
                    extracted_chunks.append(str(p["text"]))
            combined = "\n".join(extracted_chunks)
            if has_func_resp and "<USER_REQUEST>" not in combined:
                return ""
            return _strip_ide_harness_tags(combined)

    messages = payload.get("messages")
    if isinstance(messages, list) and messages:
        last_msg = messages[-1]
        if isinstance(last_msg, dict):
            content_val = last_msg.get("content")
            if isinstance(content_val, str):
                return content_val.strip()
            if isinstance(content_val, list):
                chunks: List[str] = []
                for item in content_val:
                    if isinstance(item, dict) and item.get("text"):
                        chunks.append(str(item["text"]))
                return "\n".join(chunks).strip()

    return ""


async def sanitize_prompt_inline(
    client: httpx.AsyncClient,
    body: bytes,
    target: RouteTarget,
    access_token: str,
    logger: logging.Logger,
) -> Tuple[bool, str, Optional[str], Optional[Exception]]:
    """Call Google Cloud Model Armor `:sanitizeUserPrompt` inline before invoking Vertex AI.

    Parameters:
        client (httpx.AsyncClient): Shared async HTTP client.
        body (bytes): Raw generateContent or OpenAI chat.completions JSON request payload.
        target (RouteTarget): Resolved route target containing PromptTemplateName.
        access_token (str): Downscoped GCP IAM OAuth2 Bearer token.
        logger (logging.Logger): Structured semantic logger.

    Returns:
        Tuple[bool, str, Optional[str], Optional[Exception]]:
            (blocked, block_reason, sanitized_replacement_text, error).

    Raises:
        None (network/HTTP exceptions are captured and returned as the 4th tuple item).
    """
    if not target.prompt_template_name or not body:
        return False, "", None, None

    try:
        payload = json.loads(body)
        if not isinstance(payload, dict):
            return False, "", None, None

        raw_turn_text = _extract_last_turn_text(payload)
        if not raw_turn_text:
            return False, "", None, None

        # Isolate inner <USER_REQUEST> text so benign IDE XML metadata does not dilute ML classifiers.
        if "<USER_REQUEST>" in raw_turn_text and "</USER_REQUEST>" in raw_turn_text:
            start_idx = raw_turn_text.index("<USER_REQUEST>") + len("<USER_REQUEST>")
            end_idx = raw_turn_text.index("</USER_REQUEST>", start_idx)
            prompt_text = raw_turn_text[start_idx:end_idx].strip()
        else:
            prompt_text = raw_turn_text

        if not prompt_text:
            return False, "", None, None
    except Exception:
        return False, "", None, None

    template_parts = target.prompt_template_name.split("/")
    armor_region = template_parts[3] if len(template_parts) >= 4 else "europe-west1"
    armor_url = (
        f"https://modelarmor.{armor_region}.rep.googleapis.com/v1/"
        f"{target.prompt_template_name}:sanitizeUserPrompt"
    )

    try:
        resp = await client.post(
            armor_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"userPromptData": {"text": prompt_text}},
            timeout=15.0,
        )
        if resp.status_code != 200:
            logger.warning(
                json.dumps(
                    {
                        "level": "WARN",
                        "msg": "Model Armor API returned non-200 status",
                        "status_code": resp.status_code,
                        "response": resp.text,
                    }
                )
            )
            return (
                False,
                "",
                None,
                RuntimeError(f"Model Armor API returned status {resp.status_code}"),
            )

        armor_resp = resp.json()
        sanitization = armor_resp.get("sanitizationResult", {})
        filter_results = sanitization.get("filterResults", {})

        # Pass 1 (Order-Independent Hard Blocks): Evaluate RAI, CSAM, Prompt Injection/Jailbreak,
        # Malicious URI, and Custom Security `[CUSTOM_*]` SDP rules across ALL filterResults entries
        # before considering PII redaction so map key ordering can never bypass a hard block.
        sdp_redacted_candidate: str = ""
        for _, fr in filter_results.items():
            if not isinstance(fr, dict):
                continue
            for hard_block_key in (
                "csamFilterFilterResult",
                "raiFilterResult",
                "piAndJailbreakFilterResult",
                "maliciousUriFilterResult",
            ):
                sub_res = fr.get(hard_block_key, {})
                if (
                    isinstance(sub_res, dict)
                    and sub_res.get("matchState") == "MATCH_FOUND"
                ):
                    return (
                        True,
                        f"Blocked by Google Cloud Model Armor security filter ({hard_block_key}).",
                        None,
                        None,
                    )

            sdp_res = fr.get("sdpFilterResult", {})
            if isinstance(sdp_res, dict):
                deid_res = sdp_res.get("deidentifyResult", {})
                if not isinstance(deid_res, dict):
                    deid_res = {}
                redacted = deid_res.get("data", {}).get("text", "")
                info_types = deid_res.get("infoTypes", [])
                has_custom_infotype = isinstance(info_types, list) and any(
                    str(it).startswith("CUSTOM_") for it in info_types
                )
                if "[CUSTOM_" in redacted or has_custom_infotype:
                    return (
                        True,
                        "Blocked by Google Cloud Model Armor custom enterprise security rule (prohibited offensive/evasion activity detected).",
                        None,
                        None,
                    )
                if redacted and redacted != prompt_text:
                    sdp_redacted_candidate = redacted

        # Pass 2 (Cloud SDP PII/Credential Redaction): Safe to forward redacted text only when zero hard blocks matched.
        if sdp_redacted_candidate:
            logger.info(
                json.dumps(
                    {
                        "msg": "Redacted sensitive prompt data via Cloud SDP",
                        "template": target.prompt_template_name,
                    }
                )
            )
            if raw_turn_text != prompt_text:
                sdp_redacted_candidate = raw_turn_text.replace(
                    prompt_text, sdp_redacted_candidate, 1
                )
            return False, "", sdp_redacted_candidate, None

        if sanitization.get("filterMatchState") == "MATCH_FOUND":
            return (
                True,
                "Blocked by Google Cloud Model Armor policy (Prompt Injection, Jailbreak, PII/PCI/Credentials, or Malicious URI detected).",
                None,
                None,
            )
    except Exception as exc:
        return False, "", None, exc

    return False, "", None, None


def replace_last_user_prompt_text(body: bytes, redacted_text: str) -> bytes:
    """Replace the text of the final user turn in GenAI `contents` or OpenAI `messages` with SDP-redacted text.

    Parameters:
        body (bytes): Original JSON request body.
        redacted_text (str): Redacted prompt text from Model Armor SDP filter.

    Returns:
        bytes: Updated JSON request body with sensitive PII/PCI/credentials masked.

    Raises:
        None.
    """
    try:
        payload = json.loads(body)
        contents = payload.get("contents")
        if isinstance(contents, list) and contents and isinstance(contents[-1], dict):
            contents[-1]["parts"] = [{"text": redacted_text}]
            return json.dumps(payload).encode("utf-8")

        messages = payload.get("messages")
        if isinstance(messages, list) and messages and isinstance(messages[-1], dict):
            messages[-1]["content"] = redacted_text
            return json.dumps(payload).encode("utf-8")
    except Exception:
        return body
    return body


POLICY_BLOCK_MARKER = "Prompt Blocked by Organization Security Policy"


def scrub_blocked_history_turns(body: bytes) -> bytes:
    """Scrub previously blocked historical user turns across GenAI `contents` or OpenAI `messages`.

    Parameters:
        body (bytes): Raw generateContent or chat.completions JSON request payload.

    Returns:
        bytes: Updated JSON request body with previously blocked historical user turns scrubbed.

    Raises:
        None.
    """
    if not body:
        return body
    try:
        payload = json.loads(body)
        modified = False

        contents = payload.get("contents")
        if isinstance(contents, list) and len(contents) >= 2:
            for idx in range(len(contents) - 1):
                curr_turn = contents[idx]
                next_turn = contents[idx + 1]
                if not isinstance(curr_turn, dict) or not isinstance(next_turn, dict):
                    continue
                if curr_turn.get("role") == "user" and next_turn.get("role") == "model":
                    model_parts = next_turn.get("parts", [])
                    model_text = " ".join(
                        str(p.get("text", ""))
                        for p in model_parts
                        if isinstance(p, dict)
                    )
                    if POLICY_BLOCK_MARKER in model_text:
                        curr_turn["parts"] = [
                            {
                                "text": "[Previous user prompt was blocked and removed by organization security policy.]"
                            }
                        ]
                        modified = True

        messages = payload.get("messages")
        if isinstance(messages, list) and len(messages) >= 2:
            for idx in range(len(messages) - 1):
                curr_msg = messages[idx]
                next_msg = messages[idx + 1]
                if not isinstance(curr_msg, dict) or not isinstance(next_msg, dict):
                    continue
                if (
                    curr_msg.get("role") == "user"
                    and next_msg.get("role") == "assistant"
                    and POLICY_BLOCK_MARKER in str(next_msg.get("content", ""))
                ):
                    curr_msg["content"] = (
                        "[Previous user prompt was blocked and removed by organization security policy.]"
                    )
                    modified = True

        if modified:
            return json.dumps(payload).encode("utf-8")
    except Exception:
        return body
    return body


def format_policy_block_message(reason: str) -> str:
    """Format a user-friendly conversational response explaining that security policy blocked the prompt.

    Parameters:
        reason (str): Specific Model Armor filter or rule reason string.

    Returns:
        str: Markdown-formatted policy block response rendered directly in the Antigravity chat UI.

    Raises:
        None.
    """
    return (
        f"🛡️ **{POLICY_BLOCK_MARKER}**\n\n"
        "Your organization's AI security gateway (**Google Cloud Model Armor**) prevented this prompt from being processed.\n\n"
        f"- **Security Filter Details:** {reason}\n\n"
        "Please modify your request to comply with your organization's acceptable use policies, "
        "or contact your IT/Security administrator if you need this access to continue."
    )


# ==============================================================================
# BLOCK 7: GEMINI 4+ THINKING-LEVEL NORMALIZATION ENGINE
# ==============================================================================
def normalize_thinking_config_for_model(body: bytes, target: RouteTarget) -> bytes:
    """Normalize generationConfig.thinkingConfig for Gemini 4+ models or explicit thinking-level suffixes.

    Parameters:
        body (bytes): Raw generateContent JSON request payload.
        target (RouteTarget): Resolved route target containing model_action and thinking_level.

    Returns:
        bytes: Updated JSON request body preventing HTTP 400 INVALID_ARGUMENT on `gemini-4-argon`.

    Raises:
        None.
    """
    if not body or not target.model_action:
        return body

    model_id = target.model_action.split(":", 1)[0].lower()
    is_gemini_4 = model_id.startswith("gemini-4")
    explicit_level = target.thinking_level.strip().upper()

    if not is_gemini_4 and not explicit_level:
        return body

    try:
        payload = json.loads(body)
        if not isinstance(payload, dict):
            return body

        if (
            explicit_level
            and "generationConfig" not in payload
            and "generation_config" not in payload
        ):
            payload["generationConfig"] = {
                "thinkingConfig": {
                    "includeThoughts": True,
                    "thinkingLevel": "LOW"
                    if (is_gemini_4 and explicit_level == "MINIMAL")
                    else explicit_level,
                }
            }
            return json.dumps(payload).encode("utf-8")

        modified = False
        for gen_key in ("generationConfig", "generation_config"):
            gen_cfg = payload.get(gen_key)
            if not isinstance(gen_cfg, dict):
                continue

            if (
                explicit_level
                and "thinkingConfig" not in gen_cfg
                and "thinking_config" not in gen_cfg
            ):
                think_key_name = (
                    "thinking_config"
                    if gen_key == "generation_config"
                    else "thinkingConfig"
                )
                level_key_name = (
                    "thinking_level"
                    if gen_key == "generation_config"
                    else "thinkingLevel"
                )
                inc_key_name = (
                    "include_thoughts"
                    if gen_key == "generation_config"
                    else "includeThoughts"
                )
                gen_cfg[think_key_name] = {
                    inc_key_name: True,
                    level_key_name: "LOW"
                    if (is_gemini_4 and explicit_level == "MINIMAL")
                    else explicit_level,
                }
                modified = True
                continue

            for think_key in ("thinkingConfig", "thinking_config"):
                think_cfg = gen_cfg.get(think_key)
                if not isinstance(think_cfg, dict):
                    continue

                budget_val = None
                for b_key in ("thinkingBudget", "thinking_budget"):
                    if b_key in think_cfg:
                        budget_val = think_cfg.pop(b_key)
                        modified = True

                level_field = (
                    "thinking_level"
                    if think_key == "thinking_config"
                    else "thinkingLevel"
                )
                existing_level_key = (
                    "thinking_level"
                    if "thinking_level" in think_cfg
                    else "thinkingLevel"
                )
                existing_level = str(think_cfg.get(existing_level_key, "")).upper()

                if explicit_level:
                    final_level = (
                        "LOW"
                        if (
                            is_gemini_4
                            and explicit_level
                            in ("MINIMAL", "THINKING_LEVEL_MINIMAL")
                        )
                        else explicit_level
                    )
                    think_cfg[level_field] = final_level
                    modified = True
                elif budget_val is not None and not existing_level:
                    try:
                        b_num = int(budget_val)
                    except (ValueError, TypeError):
                        b_num = -1

                    if b_num < 0 or b_num > 4096:
                        mapped_level = "HIGH"
                    elif b_num <= 1024:
                        mapped_level = "LOW"
                    else:
                        mapped_level = "MEDIUM"

                    think_cfg[level_field] = mapped_level
                    modified = True
                elif is_gemini_4 and existing_level in (
                    "MINIMAL",
                    "THINKING_LEVEL_MINIMAL",
                ):
                    think_cfg[existing_level_key] = "LOW"
                    modified = True

        if modified:
            return json.dumps(payload).encode("utf-8")
    except Exception:
        return body
    return body


def normalize_openai_chat_payload(body: bytes, target: RouteTarget) -> bytes:
    """Normalize OpenAI `/v1/chat/completions` payloads for Vertex AI OpenAI or custom upstreams.

    Summary:
        Rewrites `model` to include the `google/` publisher prefix required by Vertex AI's
        OpenAI-compatible endpoint (`/endpoints/openapi/chat/completions`), substitutes clean
        model IDs after `-pt` / thinking-suffix / `MODEL_PLACEHOLDER_M50` resolution, and maps
        explicit thinking suffixes to `reasoning_effort` when absent.

    Parameters:
        body (bytes): Raw `/v1/chat/completions` JSON request payload.
        target (RouteTarget): Resolved route target containing OpenAI metadata and thinking level.

    Returns:
        bytes: Normalized JSON request body, or original `body` on non-OpenAI/invalid JSON.

    Raises:
        None.
    """
    if not body or not target.is_openai_chat:
        return body

    try:
        payload = json.loads(body)
        if not isinstance(payload, dict):
            return body

        modified = False
        if target.openai_model_id:
            if target.openai_upstream_base_url:
                desired_model = target.openai_model_id
            elif "/" in target.openai_model_id:
                desired_model = target.openai_model_id
            else:
                desired_model = f"google/{target.openai_model_id}"

            if payload.get("model") != desired_model:
                payload["model"] = desired_model
                modified = True

        explicit_level = target.thinking_level.strip().upper()
        if explicit_level and "reasoning_effort" not in payload:
            effort_map = {
                "MINIMAL": "low",
                "LOW": "low",
                "MEDIUM": "medium",
                "HIGH": "high",
            }
            if explicit_level in effort_map:
                payload["reasoning_effort"] = effort_map[explicit_level]
                modified = True

        if modified:
            return json.dumps(payload).encode("utf-8")
    except Exception:
        return body
    return body

