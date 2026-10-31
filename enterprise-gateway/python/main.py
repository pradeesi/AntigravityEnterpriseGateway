# ==============================================================================
# FILE HEADER: Python Antigravity Enterprise Gateway — Core Reverse Proxy Server
# ==============================================================================
# Author: Pradeep Singh
# License: Apache-2.0
#
# Purpose:
#   Production-grade asynchronous HTTP reverse proxy server (FastAPI + httpx +
#   google-auth) that authenticates and routes Google Antigravity client traffic
#   (Desktop App, `agy` CLI, VS Code / Visual Studio, and JetBrains / Zed ACP)
#   to the Gemini Enterprise Agent Platform (`aiplatform.googleapis.com`).
#
# Architecture / Context:
#   Organized into 7 explicit code blocks mirroring `go/main.go`:
#     - BLOCK 1: Standardized Gateway Variables (auto-loaded from `.env` / `settings.env`).
#     - BLOCK 2: Operational Constants & Structured JSON Logging Setup (`INFO` / `DEBUG`).
#     - BLOCK 3: GCP IAM Token Manager (`GCPTokenManager`) — thread-safe ADC caching.
#     - BLOCK 4: Application Lifespan & Connection Pool Initialization (`lifespan`).
#     - BLOCK 5: Health Check & Google RPC Error / Conversational Policy Block Formatters.
#     - BLOCK 6: Core 9-Stage Reverse Proxy Pipeline (`handle_proxy`) with SSE Zero-Buffer Flush.
#     - BLOCK 7: Uvicorn Server Entrypoint (`timeout_keep_alive=3600`).
#
# Dependencies / Side Effects:
#   - Auto-loads `.env` / `../.env` and `settings.env` / `../settings.env`.
#   - Requires Google Application Default Credentials (ADC) with `roles/aiplatform.user`
#     (plus `roles/modelarmor.user` and `roles/dlp.user` when Model Armor is enabled).
# ==============================================================================

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import sys
import threading
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Optional

import google.auth
import google.auth.transport.requests
import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from routing_and_armor import (
    RouterAndArmorConfig,
    build_routed_vertex_url,
    format_policy_block_message,
    get_env,
    inject_native_model_armor_config,
    load_router_and_armor_config,
    normalize_openai_chat_payload,
    normalize_thinking_config_for_model,
    replace_last_user_prompt_text,
    resolve_route_target,
    sanitize_prompt_inline,
    scrub_blocked_history_turns,
)

# ==============================================================================
# BLOCK 1: GATEWAY SERVER VARIABLES (Loaded from .env / settings.env / OS Env)
# ==============================================================================
# [REQUIRED] Default GCP Project ID where `aiplatform.googleapis.com` is enabled
PROJECT_ID: str = get_env("PROJECT_ID", "REPLACE_WITH_PROJECT_ID")

# [REQUIRED] Shared secret bearer token(s) sent in `Authorization: Bearer <GATEWAY_API_KEY>`
# Supports a single token or comma-separated tokens for zero-downtime rotation / per-team keys.
GATEWAY_API_KEY: str = get_env("GATEWAY_API_KEY", "REPLACE_WITH_GATEWAY_API_KEY")

# [OPTIONAL] Default Gemini Enterprise Agent Platform region
REGION: str = get_env("REGION", "europe-west1")

# [OPTIONAL] TCP port on which the FastAPI / Uvicorn HTTP server listens
PORT: int = int(get_env("PORT", "8080"))

# [OPTIONAL] Structured JSON log verbosity ("INFO" or "DEBUG")
LOG_LEVEL: str = get_env("LOG_LEVEL", "INFO")

# [OPTIONAL] Emit structured client telemetry payloads (/v1internal:*, /v1beta:*) to stdout for SIEM/BigQuery sinks
LOG_TELEMETRY_PAYLOADS: str = get_env("LOG_TELEMETRY_PAYLOADS", "false")

# [OPTIONAL] Skip GCP ADC token initialization ("true" ONLY for offline local tests)
SKIP_ADC_INIT: str = get_env("SKIP_ADC_INIT", "false")


# ==============================================================================
# BLOCK 2: OPERATIONAL CONSTANTS & STRUCTURED JSON LOGGING SETUP
# ==============================================================================
CLOUD_PLATFORM_SCOPE: str = "https://www.googleapis.com/auth/cloud-platform"
STREAM_BUFFER_BYTES: int = 4096  # 4 KiB unbuffered SSE chunk size


def configure_logger(level_str: str) -> logging.Logger:
    """Configure a structured JSON logger writing to stdout for Cloud Logging / GKE ingestion.

    Summary:
        Initializes a non-propagating stdout logger formatted as raw JSON lines.

    Parameters:
        level_str (str): Log verbosity level ('INFO' or 'DEBUG').

    Returns:
        logging.Logger: Configured logger instance.

    Raises:
        None.
    """
    logger_instance = logging.getLogger("antigravity_gateway")
    logger_instance.setLevel(
        logging.DEBUG if level_str.upper() == "DEBUG" else logging.INFO
    )
    if not logger_instance.handlers:
        handler = logging.StreamHandler(sys.stdout)
        # Emit raw message string because each log call serializes a JSON object.
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger_instance.addHandler(handler)
    logger_instance.propagate = False
    return logger_instance


logger = configure_logger(LOG_LEVEL)


# ==============================================================================
# BLOCK 3: GCP IAM TOKEN MANAGER (Application Default Credentials Caching)
# ==============================================================================
class GCPTokenManager:
    """Thread-safe Google Application Default Credentials (ADC) OAuth2 token cache.

    Summary:
        Mints and caches short-lived GCP IAM access tokens and refreshes them off
        the async event loop so concurrent SSE streams never stall or stampede IAM.

    Parameters:
        skip_adc_init (bool): When True, bypasses ADC discovery and returns a mock token.

    Returns:
        GCPTokenManager instance.

    Raises:
        google.auth.exceptions.DefaultCredentialsError: When ADC credentials are unavailable.
    """

    def __init__(self, skip_adc_init: bool = False) -> None:
        """Initialize the GCPTokenManager with Application Default Credentials.

        Parameters:
            skip_adc_init (bool): Whether to skip real GCP ADC initialization for offline tests.

        Returns:
            None.

        Raises:
            google.auth.exceptions.DefaultCredentialsError: If GCP credentials cannot be discovered.
        """
        self.skip_adc_init = skip_adc_init
        self._lock = threading.Lock()
        self._credentials = None
        self._auth_request = google.auth.transport.requests.Request()

        if self.skip_adc_init:
            logger.warning(
                json.dumps(
                    {
                        "level": "WARN",
                        "msg": "SKIP_ADC_INIT=true set; using mock token source for local contract testing",
                    }
                )
            )
        else:
            creds, _ = google.auth.default(scopes=[CLOUD_PLATFORM_SCOPE])
            self._credentials = creds

    def _get_token_sync(self) -> str:
        """Synchronously retrieve or refresh the cached GCP IAM OAuth2 access token.

        Parameters:
            None.

        Returns:
            str: Valid Google Cloud IAM access token.

        Raises:
            google.auth.exceptions.RefreshError: If IAM token refresh fails.
        """
        if self.skip_adc_init:
            return "mock-gcp-iam-token"

        # Serialize token refresh across worker threads to prevent duplicate refresh storms.
        with self._lock:
            if (
                not self._credentials.valid
                or self._credentials.expired
                or not self._credentials.token
            ):
                self._credentials.refresh(self._auth_request)
            return str(self._credentials.token)

    async def get_access_token(self) -> str:
        """Asynchronously retrieve a valid GCP IAM OAuth2 access token without blocking Uvicorn.

        Parameters:
            None.

        Returns:
            str: Valid Google Cloud IAM access token.

        Raises:
            google.auth.exceptions.RefreshError: If IAM token refresh fails.
        """
        return await asyncio.to_thread(self._get_token_sync)


# ==============================================================================
# BLOCK 4: APPLICATION LIFESPAN & CONNECTION POOL INITIALIZATION
# ==============================================================================
class GatewayState:
    """Container for shared runtime dependencies across the FastAPI lifecycle.

    Summary:
        Holds singleton references to GCPTokenManager, pooled httpx.AsyncClient,
        and parsed RouterAndArmorConfig.
    """

    token_manager: Optional[GCPTokenManager] = None
    http_client: Optional[httpx.AsyncClient] = None
    routing_cfg: Optional[RouterAndArmorConfig] = None


state = GatewayState()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Validate startup configuration, initialize ADC and HTTP pool, and close cleanly on shutdown.

    Summary:
        Fails fast if PROJECT_ID or GATEWAY_API_KEY are unconfigured, creates a
        3600s-timeout httpx.AsyncClient pool, and drains connections on SIGTERM.

    Parameters:
        app (FastAPI): FastAPI application instance.

    Returns:
        AsyncIterator[None]: Async context manager lifecycle yield.

    Raises:
        SystemExit: Exits with status 1 if required configuration or ADC initialization fails.
    """
    if not PROJECT_ID or PROJECT_ID == "REPLACE_WITH_PROJECT_ID":
        logger.error(
            json.dumps(
                {
                    "level": "ERROR",
                    "msg": "PROJECT_ID is required: set it in settings.env, .env, or environment variables",
                }
            )
        )
        sys.exit(1)

    if not GATEWAY_API_KEY or GATEWAY_API_KEY == "REPLACE_WITH_GATEWAY_API_KEY":
        logger.error(
            json.dumps(
                {
                    "level": "ERROR",
                    "msg": "GATEWAY_API_KEY is required: set it in .env or mount via Secret Manager",
                }
            )
        )
        sys.exit(1)

    skip_adc = SKIP_ADC_INIT.strip().lower() == "true"
    try:
        state.token_manager = GCPTokenManager(skip_adc_init=skip_adc)
    except Exception as exc:
        logger.error(
            json.dumps(
                {
                    "level": "ERROR",
                    "msg": "Failed to initialize Google Application Default Credentials",
                    "error": str(exc),
                }
            )
        )
        sys.exit(1)

    state.routing_cfg = load_router_and_armor_config(PROJECT_ID, REGION)
    state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=30.0, read=3600.0, write=3600.0, pool=30.0),
        follow_redirects=False,
    )

    logger.info(
        json.dumps(
            {
                "level": "INFO",
                "msg": "Antigravity Enterprise Gateway (Python) started",
                "port": PORT,
                "project_id": PROJECT_ID,
                "region": REGION,
                "model_armor_mode": state.routing_cfg.model_armor_mode,
                "model_armor_template": state.routing_cfg.model_armor_template_id,
            }
        )
    )
    yield

    if state.http_client:
        await state.http_client.aclose()
    logger.info(
        json.dumps(
            {
                "level": "INFO",
                "msg": "Shutting down Antigravity Enterprise Gateway gracefully...",
            }
        )
    )


# Disable auto-generated OpenAPI endpoints so all paths route cleanly through handle_proxy.
app = FastAPI(
    title="Antigravity Enterprise Gateway",
    description="Enterprise reverse proxy routing Google Antigravity clients to Gemini Enterprise Agent Platform.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


# ==============================================================================
# BLOCK 5: HEALTH CHECK & GOOGLE RPC ERROR / CONVERSATIONAL BLOCK FORMATTERS
# ==============================================================================
@app.get("/healthz")
async def handle_healthz() -> PlainTextResponse:
    """Respond to internal container liveness and readiness probes on GET /healthz.

    Summary:
        Returns plain-text 200 OK for GKE readiness/liveness and local Docker probes.

    Parameters:
        None.

    Returns:
        PlainTextResponse: HTTP 200 OK with body 'OK'.

    Raises:
        None.
    """
    return PlainTextResponse(content="OK", status_code=200)


def http_status_to_canonical_rpc_status(
    status_code: int, reason: str
) -> tuple[str, str]:
    """Map an HTTP status code and reason identifier to Google RPC status and service domain.

    Parameters:
        status_code (int): HTTP status code.
        reason (str): Machine-readable error reason identifier.

    Returns:
        tuple[str, str]: (canonical_rpc_status, error_domain).

    Raises:
        None.
    """
    domain = "antigravity-enterprise-gateway"
    if reason.startswith("MODEL_ARMOR_"):
        domain = "modelarmor.googleapis.com"
    elif reason.startswith("UPSTREAM_VERTEX_") or reason.startswith("GCP_IAM_"):
        domain = "aiplatform.googleapis.com"

    status_map = {
        400: "INVALID_ARGUMENT",
        401: "UNAUTHENTICATED",
        403: "PERMISSION_DENIED",
        404: "NOT_FOUND",
        429: "RESOURCE_EXHAUSTED",
        502: "UNAVAILABLE",
        503: "UNAVAILABLE",
        504: "UNAVAILABLE",
    }
    return status_map.get(status_code, "INTERNAL"), domain


def build_json_error_response(
    status_code: int,
    reason: str,
    message: str,
    troubleshooting_hint: str,
    headers: Optional[Dict[str, str]] = None,
) -> JSONResponse:
    """Build a standardized Google RPC JSON error response with troubleshooting hints.

    Parameters:
        status_code (int): HTTP status code to emit.
        reason (str): Machine-readable error reason identifier.
        message (str): Human-readable explanation of what failed.
        troubleshooting_hint (str): Actionable remediation guidance for admins/developers.
        headers (Optional[Dict[str, str]]): Optional extra HTTP response headers.

    Returns:
        JSONResponse: Structured Google RPC JSON error payload.

    Raises:
        None.
    """
    rpc_status, domain = http_status_to_canonical_rpc_status(status_code, reason)
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            "error": {
                "code": status_code,
                "message": message,
                "status": rpc_status,
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": reason,
                        "domain": domain,
                        "metadata": {
                            "troubleshootingHint": troubleshooting_hint,
                            "uiMessage": "true",
                        },
                    }
                ],
            }
        },
    )


def build_policy_block_http_response(request: Request, body: bytes, reason: str):
    """Build a conversational HTTP 200 policy-block response matching the client's wire protocol.

    Summary:
        Returns a valid SSE or JSON assistant turn (`finishReason: "STOP"`) so Antigravity
        renders the security policy notice in chat instead of displaying an error banner.

    Parameters:
        request (Request): Incoming FastAPI HTTP request.
        body (bytes): Raw JSON request body.
        reason (str): Human-readable Model Armor filter block reason.

    Returns:
        StreamingResponse | JSONResponse: Wire-protocol-compatible block notice (or HTTP 400 if requested).

    Raises:
        None.
    """
    headers = {
        "X-Model-Armor-Blocked": "true",
        "X-Model-Armor-Reason": reason,
    }

    if request.headers.get("x-armor-block-status", "").strip() == "400":
        return build_json_error_response(
            status_code=400,
            reason="MODEL_ARMOR_BLOCKED",
            message=reason,
            troubleshooting_hint="Modify the prompt to comply with your organization's acceptable use policy, or review the Google Cloud Model Armor template configuration.",
            headers=headers,
        )

    raw_body_str = body.decode("utf-8", errors="ignore")
    if (
        "<USER_REQUEST>" not in raw_body_str
        and "title" in raw_body_str.lower()
        and len(raw_body_str) < 4000
    ):
        message_text = "Blocked by Organization Security Policy"
    else:
        message_text = format_policy_block_message(reason)

    path = request.url.path
    query = request.url.query.lower()
    is_sse = "alt=sse" in query or ":streamgeneratecontent" in path.lower()

    # OpenAI Wire Protocol (/v1/chat/completions)
    if path.rstrip("/").endswith("/chat/completions"):
        if is_sse or '"stream":true' in raw_body_str.replace(" ", "").lower():
            chunk_payload = {
                "id": "chatcmpl-armor-blocked",
                "object": "chat.completion.chunk",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": message_text},
                        "finish_reason": "stop",
                    }
                ],
            }
            sse_bytes = (
                f"data: {json.dumps(chunk_payload)}\n\ndata: [DONE]\n\n".encode("utf-8")
            )
            return StreamingResponse(
                iter([sse_bytes]),
                status_code=200,
                headers=headers,
                media_type="text/event-stream",
            )
        return JSONResponse(
            status_code=200,
            headers=headers,
            content={
                "id": "chatcmpl-armor-blocked",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": message_text},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    # Default GenAI / Vertex AI Wire Protocol (:streamGenerateContent / :generateContent)
    genai_payload = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [{"text": message_text}],
                },
                "finishReason": "STOP",
                "index": 0,
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 0,
            "candidatesTokenCount": 0,
            "totalTokenCount": 0,
        },
    }

    if is_sse:
        sse_event = f"data: {json.dumps(genai_payload)}\n\n".encode("utf-8")
        return StreamingResponse(
            iter([sse_event]),
            status_code=200,
            headers=headers,
            media_type="text/event-stream",
        )

    return JSONResponse(
        status_code=200,
        headers=headers,
        content=genai_payload,
    )


# ==============================================================================
# BLOCK 6: CORE 9-STAGE REVERSE PROXY PIPELINE
# ==============================================================================
def verify_gateway_api_key(auth_header: str, configured_keys: str) -> bool:
    """Validate incoming Authorization Bearer token in constant time across one or more keys.

    Summary:
        Compares `auth_header` against every comma-separated key in `configured_keys`
        using `hmac.compare_digest` without early termination to prevent timing leaks
        while enabling zero-downtime key rotation or per-team API keys.

    Parameters:
        auth_header (str): Incoming HTTP `Authorization` header value.
        configured_keys (str): Single key or comma-separated list of valid Gateway API keys.

    Returns:
        bool: True if `auth_header` matches at least one configured `Bearer <key>` token.

    Raises:
        None.
    """
    candidates = [k.strip() for k in configured_keys.split(",") if k.strip()]
    if not candidates or not auth_header:
        return False

    auth_bytes = auth_header.encode("utf-8")
    matched = False
    for key in candidates:
        expected_bytes = f"Bearer {key}".encode("utf-8")
        if hmac.compare_digest(auth_bytes, expected_bytes):
            matched = True
    return matched


@app.api_route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
)
async def handle_proxy(request: Request, full_path: str):
    """Authenticate Antigravity requests, enforce Model Armor, route dynamically, and stream SSE.

    Parameters:
        request (Request): Incoming FastAPI HTTP request.
        full_path (str): Wildcard URL path captured by FastAPI.

    Returns:
        JSONResponse | StreamingResponse: Telemetry/error payload or unbuffered SSE stream.

    Raises:
        None (all upstream/IAM errors are caught and returned as Google RPC JSON responses).
    """
    path = request.url.path

    # STAGE 6.1: Constant-Time Ingress Bearer Token Authentication (prevents byte-timing attacks).
    auth_header = request.headers.get("authorization", "")
    if not verify_gateway_api_key(auth_header, GATEWAY_API_KEY):
        logger.warning(
            json.dumps(
                {
                    "level": "WARN",
                    "msg": "Unauthorized request rejected",
                    "method": request.method,
                    "path": path,
                    "remote_addr": request.client.host if request.client else "",
                }
            )
        )
        return build_json_error_response(
            status_code=401,
            reason="INVALID_GATEWAY_API_KEY",
            message="Unauthorized: invalid or missing Gateway API key in Authorization header.",
            troubleshooting_hint="Verify that 'gateway.apiKey' in admin_settings.json (or AGY_LLM_GATEWAY_API_KEY) matches the GATEWAY_API_KEY secret configured on the Enterprise Gateway.",
        )

    # STAGE 6.2: Background Telemetry & Metrics Endpoint Short-Circuiting (/v1beta:* and /v1internal:*).
    if path.startswith("/v1internal:") or path.startswith("/v1beta:"):
        if LOG_TELEMETRY_PAYLOADS.strip().lower() == "true":
            telemetry_raw = await request.body()
            parsed_telemetry = None
            if telemetry_raw:
                try:
                    parsed_telemetry = json.loads(telemetry_raw)
                except Exception:
                    parsed_telemetry = telemetry_raw.decode("utf-8", errors="replace")
            rpc_method = path.split(":", 1)[1] if ":" in path else path
            logger.info(
                json.dumps(
                    {
                        "level": "INFO",
                        "event_type": "antigravity_client_telemetry",
                        "msg": "Captured Antigravity client telemetry event",
                        "rpc_method": rpc_method,
                        "path": path,
                        "user_agent": request.headers.get("user-agent", ""),
                        "cost_center": request.headers.get("x-cost-center", ""),
                        "corporate_bu": request.headers.get("x-corporate-bu", ""),
                        "telemetry_payload": parsed_telemetry,
                    }
                )
            )
        else:
            logger.debug(
                json.dumps(
                    {
                        "level": "DEBUG",
                        "msg": "Acknowledging client telemetry call",
                        "path": path,
                        "user_agent": request.headers.get("user-agent", ""),
                        "cost_center": request.headers.get("x-cost-center", ""),
                    }
                )
            )
        return JSONResponse(status_code=200, content={})

    # STAGE 6.3: Read Request Body Once (supports Model Armor inspection and failover replay).
    body = await request.body()

    assert state.routing_cfg is not None
    assert state.token_manager is not None
    assert state.http_client is not None

    # STAGE 6.4: Dynamic Endpoint Route Resolution.
    route_target = resolve_route_target(
        path=path,
        headers=dict(request.headers),
        cfg=state.routing_cfg,
        body=body,
    )
    if route_target.m50_fallback_applied:
        logger.warning(
            json.dumps(
                {
                    "level": "WARN",
                    "msg": "Rewrote unmapped MODEL_PLACEHOLDER_M50 request to configured Flash fallback model; include a Flash model (e.g., gemini-3.8-flash) in models.list / AGY_LLM_GATEWAY_MODELS",
                    "fallback_model": state.routing_cfg.default_flash_fallback_model,
                    "client_path": path,
                }
            )
        )

    # STAGE 6.5: Downscoped GCP IAM Access Token Minting via Cached ADC.
    try:
        access_token = await state.token_manager.get_access_token()
    except Exception as exc:
        logger.error(
            json.dumps(
                {
                    "level": "ERROR",
                    "msg": "Failed to obtain GCP IAM access token",
                    "error": str(exc),
                }
            )
        )
        return build_json_error_response(
            status_code=500,
            reason="GCP_IAM_TOKEN_EXCHANGE_FAILED",
            message="Internal Server Error: failed to obtain GCP IAM access token for Gemini Enterprise Agent Platform.",
            troubleshooting_hint="Verify that the Gateway's attached GCP Service Account has active Application Default Credentials (ADC) and is granted 'roles/aiplatform.user' on the target project.",
        )

    # STAGE 6.6: Multi-Turn History Scrubbing, Thinking / OpenAI Normalization & Model Armor Enforcement.
    body = scrub_blocked_history_turns(body)
    body = normalize_thinking_config_for_model(body, route_target)
    body = normalize_openai_chat_payload(body, route_target)

    if (
        state.routing_cfg.model_armor_mode == "inline"
        and route_target.prompt_template_name
    ):
        blocked, reason, sanitized_text, armor_err = await sanitize_prompt_inline(
            client=state.http_client,
            body=body,
            target=route_target,
            access_token=access_token,
            logger=logger,
        )
        if armor_err is not None:
            logger.error(
                json.dumps(
                    {
                        "level": "ERROR",
                        "msg": "Model Armor inline pre-flight check failed",
                        "error": str(armor_err),
                    }
                )
            )
            if state.routing_cfg.model_armor_fail_closed:
                return build_json_error_response(
                    status_code=502,
                    reason="MODEL_ARMOR_UNAVAILABLE",
                    message=f"Bad Gateway: Google Cloud Model Armor security service is unreachable or returned an error ({armor_err}) while fail-closed policy is active.",
                    troubleshooting_hint="Verify that 'modelarmor.googleapis.com' is enabled, the template ID in MODEL_ARMOR_TEMPLATE_ID exists in the target region, and the Gateway Service Account has 'roles/modelarmor.user' and 'roles/dlp.user'.",
                )
        elif blocked:
            logger.warning(
                json.dumps(
                    {
                        "level": "WARN",
                        "msg": "Request blocked by Model Armor policy",
                        "template": route_target.prompt_template_name,
                        "reason": reason,
                    }
                )
            )
            return build_policy_block_http_response(request, body, reason)
        elif sanitized_text:
            body = replace_last_user_prompt_text(body, sanitized_text)
    elif (
        state.routing_cfg.model_armor_mode == "native"
        and route_target.prompt_template_name
    ):
        body = inject_native_model_armor_config(body, route_target)

    # STAGE 6.7: Construct Upstream Headers & Preserve Gemini Enterprise PAYG Attribution.
    out_headers: Dict[str, str] = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    user_agent = request.headers.get("user-agent", "")
    if user_agent:
        out_headers["User-Agent"] = user_agent

    for k, v in request.headers.items():
        if k.lower().startswith("x-"):
            out_headers[k] = v

    if (
        route_target.project_id != PROJECT_ID
        and "x-goog-user-project" not in {k.lower() for k in out_headers}
    ):
        out_headers["X-Goog-User-Project"] = route_target.project_id

    if route_target.dedicated_pt:
        out_headers["X-Vertex-AI-LLM-Request-Type"] = "dedicated"

    # STAGE 6.8: Upstream Vertex AI Dispatch with Automatic Multi-Region 429/503 Failover.
    candidate_regions = [route_target.region] + route_target.failover_regions
    upstream_resp: Optional[httpx.Response] = None
    raw_query = request.url.query

    for idx, active_region in enumerate(candidate_regions):
        active_target_url = build_routed_vertex_url(
            target=route_target,
            active_region=active_region,
            orig_path=path,
            raw_query=raw_query,
        )
        req = state.http_client.build_request(
            method=request.method,
            url=active_target_url,
            headers=out_headers,
            content=body,
        )
        try:
            upstream_resp = await state.http_client.send(req, stream=True)
        except Exception as exc:
            logger.error(
                json.dumps(
                    {
                        "level": "ERROR",
                        "msg": "Downstream Vertex AI request failed",
                        "region": active_region,
                        "url": active_target_url,
                        "error": str(exc),
                    }
                )
            )
            if idx < len(candidate_regions) - 1:
                continue
            return build_json_error_response(
                status_code=502,
                reason="UPSTREAM_VERTEX_AI_UNREACHABLE",
                message=f"Bad Gateway: failed to reach Gemini Enterprise Agent Platform backend at {active_target_url} ({exc}).",
                troubleshooting_hint="Verify outbound network connectivity from the Gateway to '*.aiplatform.googleapis.com', check VPC Service Controls / firewall rules, and confirm REGION is valid.",
            )

        if (
            upstream_resp.status_code in (429, 503)
            and idx < len(candidate_regions) - 1
        ):
            await upstream_resp.aclose()
            logger.warning(
                json.dumps(
                    {
                        "level": "WARN",
                        "msg": "Region returned capacity error; failing over to next region",
                        "failed_region": active_region,
                        "status_code": upstream_resp.status_code,
                        "next_region": candidate_regions[idx + 1],
                    }
                )
            )
            continue
        break

    assert upstream_resp is not None

    logger.info(
        json.dumps(
            {
                "level": "INFO",
                "msg": "Proxying inference request",
                "method": request.method,
                "client_path": path,
                "target_project": route_target.project_id,
                "target_region": route_target.region,
                "upstream_status": upstream_resp.status_code,
                "user_agent": user_agent,
                "cost_center": request.headers.get("x-cost-center", ""),
            }
        )
    )

    # STAGE 6.9: Strip Hop-by-Hop Framing Headers & Flush SSE Stream Chunks Immediately.
    excluded_resp_headers = {
        "content-encoding",
        "content-length",
        "transfer-encoding",
        "connection",
    }
    response_headers = {
        k: v
        for k, v in upstream_resp.headers.items()
        if k.lower() not in excluded_resp_headers
    }

    async def stream_upstream_chunks() -> AsyncIterator[bytes]:
        """Yield decoded 4 KiB byte chunks immediately with zero buffering and close upstream stream on exit."""
        try:
            async for chunk in upstream_resp.aiter_bytes(chunk_size=STREAM_BUFFER_BYTES):
                if chunk:
                    yield chunk
        except Exception as exc:
            logger.debug(
                json.dumps(
                    {
                        "level": "DEBUG",
                        "msg": "Client disconnected during stream write",
                        "error": str(exc),
                    }
                )
            )
        finally:
            await upstream_resp.aclose()

    return StreamingResponse(
        stream_upstream_chunks(),
        status_code=upstream_resp.status_code,
        headers=response_headers,
        media_type=upstream_resp.headers.get("content-type"),
    )


# ==============================================================================
# BLOCK 7: UVICORN SERVER ENTRYPOINT (60-Minute Keep-Alive for Agentic Streams)
# ==============================================================================
if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        timeout_keep_alive=3600,
        log_level=LOG_LEVEL.lower(),
    )
