/*
 * ==============================================================================
 * FILE HEADER: Go Antigravity Enterprise Gateway — Core Reverse Proxy Server
 * ==============================================================================
 * Author: Pradeep Singh
 * License: Apache-2.0
 *
 * Purpose:
 *   Production-grade HTTP reverse proxy server (Go 1.24 + golang.org/x/oauth2)
 *   that authenticates and routes Google Antigravity client traffic (Desktop App,
 *   `agy` CLI, VS Code / Visual Studio, and JetBrains / Zed ACP) to the Gemini
 *   Enterprise Agent Platform (`aiplatform.googleapis.com`, Vertex AI).
 *
 * Architecture / Context:
 *   Organized into 7 explicit code blocks mirroring the Python implementation:
 *     - BLOCK 1: Standardized Gateway Variables & Unified Env/Settings Loader.
 *     - BLOCK 2: Operational Constants & Server State Struct (`GatewayServer`).
 *     - BLOCK 3: Server Initializer & GCP IAM ADC Token Source (`NewGatewayServer`).
 *     - BLOCK 4: Health Check & Telemetry Short-Circuit Handlers (`/healthz`, `/v1beta:*`, `/v1internal:*`).
 *     - BLOCK 5: Standardized Google RPC Error & Conversational Policy Block Formatters.
 *     - BLOCK 6: Core 9-Stage Reverse Proxy Pipeline (`handleProxy`) with SSE Zero-Buffer Flush.
 *     - BLOCK 7: HTTP Server Lifecycle & Graceful Shutdown Entrypoint (`main`).
 *
 * Dependencies / Side Effects:
 *   - Auto-loads `.env` / `../.env` and `settings.env` / `../settings.env` (without
 *     overriding OS environment variables).
 *   - Requires Google Application Default Credentials (ADC) with `roles/aiplatform.user`
 *     (plus `roles/modelarmor.user` and `roles/dlp.user` when Model Armor is enabled).
 * ==============================================================================
 */
package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/subtle"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"

	"golang.org/x/oauth2"
	"golang.org/x/oauth2/google"
)

// ==============================================================================
// BLOCK 1: GATEWAY SERVER VARIABLES & UNIFIED SETTINGS LOADER
// ==============================================================================
// Precedence order resolved by getEnv (highest to lowest):
//   1. OS environment variables (Cloud Run / GKE / exported shell vars)
//   2. Local `.env` or `../.env` (secret overrides such as GATEWAY_API_KEY)
//   3. Unified `settings.env` or `../settings.env` (shared default values)
//   4. Fallback string defined below
var (
	// [REQUIRED] Default GCP Project ID with aiplatform.googleapis.com enabled
	PROJECT_ID = getEnv("PROJECT_ID", "REPLACE_WITH_PROJECT_ID")

	// [REQUIRED] Secret bearer token(s) required in "Authorization: Bearer <GATEWAY_API_KEY>"
	// Supports a single token or comma-separated tokens for zero-downtime rotation / per-team keys.
	GATEWAY_API_KEY = getEnv("GATEWAY_API_KEY", "REPLACE_WITH_GATEWAY_API_KEY")

	// [OPTIONAL] Default Gemini Enterprise Agent Platform region
	REGION = getEnv("REGION", "europe-west1")

	// [OPTIONAL] TCP port the gateway HTTP server listens on
	PORT = getEnv("PORT", "8080")

	// [OPTIONAL] Structured JSON log verbosity ("INFO" or "DEBUG")
	LOG_LEVEL = getEnv("LOG_LEVEL", "INFO")

	// [OPTIONAL] Emit structured client telemetry payloads (/v1internal:*, /v1beta:*) to stdout for SIEM/BigQuery sinks
	LOG_TELEMETRY_PAYLOADS = getEnv("LOG_TELEMETRY_PAYLOADS", "false")

	// [OPTIONAL] Skip GCP ADC token initialization ("true" ONLY for offline local tests)
	SKIP_ADC_INIT = getEnv("SKIP_ADC_INIT", "false")
)

var loadEnvOnce sync.Once

/*
 * Summary: Loads `.env` and `settings.env` once, then resolves a configuration variable.
 * Parameters:
 *   - key (string): Standardized environment variable name.
 *   - fallback (string): In-code default value used when env/settings files omit the key.
 * Return Value:
 *   - string: Resolved configuration value with leading/trailing whitespace trimmed.
 * Exceptions/Errors:
 *   - None; falls back safely if configuration files do not exist.
 */
func getEnv(key, fallback string) string {
	loadEnvOnce.Do(func() {
		// Load higher-priority `.env` files first so `settings.env` only fills unset keys.
		for _, candidate := range []string{".env", "../.env", "settings.env", "../settings.env"} {
			loadDotEnvFile(candidate)
		}
	})

	if val := strings.TrimSpace(os.Getenv(key)); val != "" {
		// Prefer an explicit admin edit in fallback over an unedited REPLACE_WITH_* placeholder.
		if strings.HasPrefix(val, "REPLACE_WITH_") && fallback != "" && !strings.HasPrefix(fallback, "REPLACE_WITH_") {
			return strings.TrimSpace(fallback)
		}
		return val
	}
	return strings.TrimSpace(fallback)
}

/*
 * Summary: Parses a key=value environment file and populates unset OS environment variables.
 * Parameters:
 *   - filePath (string): Relative or absolute path to `.env` or `settings.env`.
 * Return Value:
 *   - None (mutates process environment for unset keys with non-empty values).
 * Exceptions/Errors:
 *   - Silently returns if `filePath` is absent or unreadable.
 */
func loadDotEnvFile(filePath string) {
	file, err := os.Open(filePath)
	if err != nil {
		return
	}
	defer func() {
		_ = file.Close()
	}()

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		line = strings.TrimPrefix(line, "export ")
		kv := strings.SplitN(line, "=", 2)
		if len(kv) != 2 {
			continue
		}
		k := strings.TrimSpace(kv[0])
		v := strings.Trim(strings.TrimSpace(kv[1]), `"'`)
		// Skip empty values in settings.env so lower-priority files or fallbacks are not shadowed by "".
		if k != "" && v != "" && strings.TrimSpace(os.Getenv(k)) == "" {
			_ = os.Setenv(k, v)
		}
	}
}

// ==============================================================================
// BLOCK 2: OPERATIONAL CONSTANTS & SERVER STATE STRUCT
// ==============================================================================
const (
	// cloudPlatformScope is the downscoped OAuth2 scope for Vertex AI and Model Armor APIs.
	cloudPlatformScope = "https://www.googleapis.com/auth/cloud-platform"

	// streamBufferBytes sets a 4 KiB read buffer so SSE chunks flush without proxy buffering.
	streamBufferBytes = 4096
)

/*
 * Summary: Encapsulates runtime configuration, cached GCP IAM token source, and shared HTTP client.
 * Parameters:
 *   - Struct fields initialized via NewGatewayServer.
 * Return Value:
 *   - GatewayServer struct instance.
 * Exceptions/Errors:
 *   - None.
 */
type GatewayServer struct {
	projectID     string
	region        string
	gatewayAPIKey string
	routingCfg    RouterAndArmorConfig
	tokenSource   oauth2.TokenSource
	httpClient    *http.Client
	logger        *slog.Logger
}

// ==============================================================================
// BLOCK 3: SERVER INITIALIZER & GCP IAM ADC TOKEN SOURCE
// ==============================================================================

/*
 * Summary: Validates required configuration, initializes cached Google ADC credentials, and builds GatewayServer.
 * Parameters:
 *   - ctx (context.Context): Startup context used for Google credential discovery.
 *   - logger (*slog.Logger): Structured JSON logger writing to stdout.
 * Return Value:
 *   - (*GatewayServer, error): Ready-to-serve GatewayServer pointer, or error on invalid config/ADC failure.
 * Exceptions/Errors:
 *   - Returns an error if PROJECT_ID or GATEWAY_API_KEY is missing/placeholder or if ADC discovery fails.
 */
func NewGatewayServer(ctx context.Context, logger *slog.Logger) (*GatewayServer, error) {
	if PROJECT_ID == "" || PROJECT_ID == "REPLACE_WITH_PROJECT_ID" {
		return nil, fmt.Errorf("PROJECT_ID is required: set it in settings.env, .env, or environment variables")
	}
	if GATEWAY_API_KEY == "" || GATEWAY_API_KEY == "REPLACE_WITH_GATEWAY_API_KEY" {
		return nil, fmt.Errorf("GATEWAY_API_KEY is required: set it in .env or mount via Secret Manager")
	}

	var reusableTokenSource oauth2.TokenSource
	if strings.EqualFold(SKIP_ADC_INIT, "true") {
		logger.Warn("SKIP_ADC_INIT=true set; using mock token source for local contract testing")
		reusableTokenSource = oauth2.StaticTokenSource(&oauth2.Token{AccessToken: "mock-gcp-iam-token"})
	} else {
		ts, err := google.DefaultTokenSource(ctx, cloudPlatformScope)
		if err != nil {
			return nil, fmt.Errorf("failed to initialize Google DefaultTokenSource: %w", err)
		}
		reusableTokenSource = oauth2.ReuseTokenSource(nil, ts)
	}

	return &GatewayServer{
		projectID:     PROJECT_ID,
		region:        REGION,
		gatewayAPIKey: GATEWAY_API_KEY,
		routingCfg:    LoadRouterAndArmorConfig(PROJECT_ID, REGION),
		tokenSource:   reusableTokenSource,
		httpClient: &http.Client{
			// 60-minute timeout prevents premature disconnects on long-running agentic streams.
			Timeout: 60 * time.Minute,
		},
		logger: logger,
	}, nil
}

// ==============================================================================
// BLOCK 4: HEALTH CHECK & TELEMETRY SHORT-CIRCUIT HANDLERS
// ==============================================================================

/*
 * Summary: Responds to internal container liveness/readiness probes on GET /healthz.
 * Parameters:
 *   - w (http.ResponseWriter): Outgoing HTTP response writer.
 *   - r (*http.Request): Incoming health check HTTP request.
 * Return Value:
 *   - Writes HTTP 200 OK with plain-text body "OK".
 * Exceptions/Errors:
 *   - None.
 */
func (s *GatewayServer) handleHealthz(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte("OK"))
}

/*
 * Summary: Acknowledges Antigravity client telemetry endpoints (/v1beta:* and /v1internal:*) with 200 OK and optional SIEM logging.
 * Parameters:
 *   - w (http.ResponseWriter): Outgoing HTTP response writer.
 *   - r (*http.Request): Incoming telemetry RPC HTTP request.
 * Return Value:
 *   - Writes HTTP 200 OK with empty JSON object "{}" so clients do not retry non-Vertex telemetry paths.
 * Exceptions/Errors:
 *   - None.
 */
func (s *GatewayServer) handleTelemetry(w http.ResponseWriter, r *http.Request) {
	if strings.EqualFold(strings.TrimSpace(LOG_TELEMETRY_PAYLOADS), "true") {
		rawBytes, _ := io.ReadAll(r.Body)
		var parsedPayload any
		if len(rawBytes) > 0 {
			if err := json.Unmarshal(rawBytes, &parsedPayload); err != nil {
				parsedPayload = string(rawBytes)
			}
		}
		rpcMethod := r.URL.Path
		if idx := strings.Index(rpcMethod, ":"); idx != -1 {
			rpcMethod = rpcMethod[idx+1:]
		}
		s.logger.Info("Captured Antigravity client telemetry event",
			slog.String("event_type", "antigravity_client_telemetry"),
			slog.String("rpc_method", rpcMethod),
			slog.String("path", r.URL.Path),
			slog.String("user_agent", r.Header.Get("User-Agent")),
			slog.String("cost_center", r.Header.Get("X-Cost-Center")),
			slog.String("corporate_bu", r.Header.Get("X-Corporate-BU")),
			slog.Any("telemetry_payload", parsedPayload),
		)
	} else {
		s.logger.Debug("Acknowledging client telemetry call",
			slog.String("path", r.URL.Path),
			slog.String("user_agent", r.Header.Get("User-Agent")),
			slog.String("cost_center", r.Header.Get("X-Cost-Center")),
		)
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte("{}"))
}

// ==============================================================================
// BLOCK 5: GOOGLE RPC ERROR & CONVERSATIONAL POLICY BLOCK FORMATTERS
// ==============================================================================

/*
 * Summary: Maps an HTTP status code and reason code to a canonical Google RPC status and service domain.
 * Parameters:
 *   - statusCode (int): HTTP status code (e.g., 400, 401, 429, 502).
 *   - reason (string): Machine-readable error reason identifier.
 * Return Value:
 *   - (string, string): Tuple of (canonicalRPCStatus, serviceDomain).
 * Exceptions/Errors:
 *   - Defaults unknown status codes to ("INTERNAL", domain).
 */
func httpStatusToCanonicalRPCStatus(statusCode int, reason string) (string, string) {
	domain := "antigravity-enterprise-gateway"
	if strings.HasPrefix(reason, "MODEL_ARMOR_") {
		domain = "modelarmor.googleapis.com"
	} else if strings.HasPrefix(reason, "UPSTREAM_VERTEX_") || strings.HasPrefix(reason, "GCP_IAM_") {
		domain = "aiplatform.googleapis.com"
	}

	switch statusCode {
	case http.StatusBadRequest:
		return "INVALID_ARGUMENT", domain
	case http.StatusUnauthorized:
		return "UNAUTHENTICATED", domain
	case http.StatusForbidden:
		return "PERMISSION_DENIED", domain
	case http.StatusNotFound:
		return "NOT_FOUND", domain
	case http.StatusTooManyRequests:
		return "RESOURCE_EXHAUSTED", domain
	case http.StatusBadGateway, http.StatusServiceUnavailable, http.StatusGatewayTimeout:
		return "UNAVAILABLE", domain
	default:
		return "INTERNAL", domain
	}
}

/*
 * Summary: Writes a structured Google RPC JSON error payload with remediation hints.
 * Parameters:
 *   - w (http.ResponseWriter): Outgoing HTTP response writer.
 *   - statusCode (int): HTTP status code to return.
 *   - reason (string): Machine-readable error code (e.g., "INVALID_GATEWAY_API_KEY").
 *   - message (string): Human-readable description of the failure.
 *   - troubleshootingHint (string): Actionable remediation advice for admins/developers.
 * Return Value:
 *   - Writes JSON error response to `w`.
 * Exceptions/Errors:
 *   - None.
 */
func writeJSONError(w http.ResponseWriter, statusCode int, reason, message, troubleshootingHint string) {
	rpcStatus, domain := httpStatusToCanonicalRPCStatus(statusCode, reason)
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(statusCode)
	payload, _ := json.Marshal(map[string]any{
		"error": map[string]any{
			"code":    statusCode,
			"message": message,
			"status":  rpcStatus,
			"details": []map[string]any{
				{
					"@type":  "type.googleapis.com/google.rpc.ErrorInfo",
					"reason": reason,
					"domain": domain,
					"metadata": map[string]string{
						"troubleshootingHint": troubleshootingHint,
						"uiMessage":           "true",
					},
				},
			},
		},
	})
	_, _ = w.Write(payload)
}

/*
 * Summary: Emits a conversational HTTP 200 policy-block response matching the client's wire protocol.
 * Parameters:
 *   - w (http.ResponseWriter): Outgoing HTTP response writer.
 *   - r (*http.Request): Incoming client HTTP request.
 *   - body ([]byte): Raw incoming JSON request payload.
 *   - reason (string): Human-readable Model Armor security filter trigger description.
 * Return Value:
 *   - Writes an SSE or JSON response with X-Model-Armor-Blocked headers (or HTTP 400 if X-Armor-Block-Status: 400).
 * Exceptions/Errors:
 *   - None.
 */
func writePolicyBlockResponse(w http.ResponseWriter, r *http.Request, body []byte, reason string) {
	w.Header().Set("X-Model-Armor-Blocked", "true")
	w.Header().Set("X-Model-Armor-Reason", reason)

	// Allow automated test suites to opt into hard HTTP 400 responses via header.
	if strings.TrimSpace(r.Header.Get("X-Armor-Block-Status")) == "400" {
		writeJSONError(
			w,
			http.StatusBadRequest,
			"MODEL_ARMOR_BLOCKED",
			reason,
			"Modify the prompt to comply with your organization's acceptable use policy, or review the Google Cloud Model Armor template configuration.",
		)
		return
	}

	rawBodyStr := string(body)
	var messageText string
	// Keep sidebar conversation title concise if the blocked request was a background title-generation call.
	if !strings.Contains(rawBodyStr, "<USER_REQUEST>") &&
		strings.Contains(strings.ToLower(rawBodyStr), "title") &&
		len(rawBodyStr) < 4000 {
		messageText = "Blocked by Organization Security Policy"
	} else {
		messageText = FormatPolicyBlockMessage(reason)
	}

	path := r.URL.Path
	query := strings.ToLower(r.URL.RawQuery)
	isSSE := strings.Contains(query, "alt=sse") || strings.Contains(strings.ToLower(path), ":streamgeneratecontent")

	// OpenAI Wire Protocol (/v1/chat/completions)
	if strings.HasSuffix(strings.TrimRight(path, "/"), "/chat/completions") {
		compactBody := strings.ToLower(strings.ReplaceAll(rawBodyStr, " ", ""))
		if isSSE || strings.Contains(compactBody, `"stream":true`) {
			chunkPayload, _ := json.Marshal(map[string]any{
				"id":     "chatcmpl-armor-blocked",
				"object": "chat.completion.chunk",
				"choices": []map[string]any{
					{
						"index": 0,
						"delta": map[string]any{
							"role":    "assistant",
							"content": messageText,
						},
						"finish_reason": "stop",
					},
				},
			})
			w.Header().Set("Content-Type", "text/event-stream")
			w.WriteHeader(http.StatusOK)
			_, _ = fmt.Fprintf(w, "data: %s\n\ndata: [DONE]\n\n", string(chunkPayload))
			if flusher, ok := w.(http.Flusher); ok {
				flusher.Flush()
			}
			return
		}

		openAIPayload, _ := json.Marshal(map[string]any{
			"id":     "chatcmpl-armor-blocked",
			"object": "chat.completion",
			"choices": []map[string]any{
				{
					"index": 0,
					"message": map[string]any{
						"role":    "assistant",
						"content": messageText,
					},
					"finish_reason": "stop",
				},
			},
		})
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(openAIPayload)
		return
	}

	// Default GenAI / Vertex AI Wire Protocol (:streamGenerateContent / :generateContent)
	genAIPayload, _ := json.Marshal(map[string]any{
		"candidates": []map[string]any{
			{
				"content": map[string]any{
					"role": "model",
					"parts": []map[string]any{
						{"text": messageText},
					},
				},
				"finishReason": "STOP",
				"index":        0,
			},
		},
		"usageMetadata": map[string]any{
			"promptTokenCount":     0,
			"candidatesTokenCount": 0,
			"totalTokenCount":      0,
		},
	})

	if isSSE {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		_, _ = fmt.Fprintf(w, "data: %s\n\n", string(genAIPayload))
		if flusher, ok := w.(http.Flusher); ok {
			flusher.Flush()
		}
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(genAIPayload)
}

// ==============================================================================
// BLOCK 6: CORE 9-STAGE REVERSE PROXY PIPELINE
// ==============================================================================

/*
 * Summary: Validates the incoming Authorization Bearer token in constant time across one or more configured keys.
 * Parameters:
 *   - authHeader (string): Incoming HTTP Authorization header value.
 *   - configuredKeys (string): Single key or comma-separated list of valid Gateway API keys.
 * Return Value:
 *   - bool: True if authHeader matches at least one configured `Bearer <key>` token.
 * Exceptions/Errors:
 *   - None.
 */
func verifyGatewayAPIKey(authHeader, configuredKeys string) bool {
	if authHeader == "" || configuredKeys == "" {
		return false
	}
	authBytes := []byte(authHeader)
	matched := 0
	hasCandidate := false
	for _, rawKey := range strings.Split(configuredKeys, ",") {
		key := strings.TrimSpace(rawKey)
		if key == "" {
			continue
		}
		hasCandidate = true
		expected := []byte("Bearer " + key)
		matched |= subtle.ConstantTimeCompare(authBytes, expected)
	}
	return hasCandidate && matched == 1
}

/*
 * Summary: Authenticates Antigravity requests, enforces Model Armor, routes dynamically, and streams SSE.
 * Parameters:
 *   - w (http.ResponseWriter): Outgoing HTTP response writer (implements http.Flusher for SSE).
 *   - r (*http.Request): Incoming Antigravity client HTTP request.
 * Return Value:
 *   - Streams upstream Vertex AI response or writes structured error/telemetry response.
 * Exceptions/Errors:
 *   - Emits HTTP 400, 401, 500, or 502 Google RPC JSON errors on validation or upstream failures.
 */
func (s *GatewayServer) handleProxy(w http.ResponseWriter, r *http.Request) {
	// STAGE 6.1: Constant-Time Ingress Bearer Key Authentication (prevents byte-timing side channels).
	authHeader := r.Header.Get("Authorization")
	if !verifyGatewayAPIKey(authHeader, s.gatewayAPIKey) {
		s.logger.Warn("Unauthorized request rejected",
			slog.String("method", r.Method),
			slog.String("path", r.URL.Path),
			slog.String("remote_addr", r.RemoteAddr),
		)
		writeJSONError(
			w,
			http.StatusUnauthorized,
			"INVALID_GATEWAY_API_KEY",
			"Unauthorized: invalid or missing Gateway API key in Authorization header.",
			"Verify that 'gateway.apiKey' in admin_settings.json (or AGY_LLM_GATEWAY_API_KEY) matches the GATEWAY_API_KEY secret configured on the Enterprise Gateway.",
		)
		return
	}

	// STAGE 6.2: Short-Circuit Background Client Telemetry Endpoints (/v1beta:* and /v1internal:*).
	if strings.HasPrefix(r.URL.Path, "/v1internal:") || strings.HasPrefix(r.URL.Path, "/v1beta:") {
		s.handleTelemetry(w, r)
		return
	}

	// STAGE 6.3: Read Request Body Once (allows Model Armor inspection and multi-region failover replay).
	body, err := io.ReadAll(r.Body)
	if err != nil {
		s.logger.Error("Failed to read request body", slog.String("error", err.Error()))
		writeJSONError(
			w,
			http.StatusBadRequest,
			"INVALID_REQUEST_BODY",
			"Bad Request: failed to read incoming HTTP request body.",
			"Verify that the client connection was not interrupted while sending the request payload.",
		)
		return
	}

	// STAGE 6.4: Resolve Dynamic Endpoint Route (Cost-Center project, region, PT flag, thinking level, OpenAI, Armor template).
	routeTarget := ResolveRouteTarget(r, body, s.routingCfg)
	if routeTarget.M50FallbackApplied {
		s.logger.Warn("Rewrote unmapped MODEL_PLACEHOLDER_M50 request to configured Flash fallback model; include a Flash model (e.g., gemini-3.8-flash) in models.list / AGY_LLM_GATEWAY_MODELS",
			slog.String("fallback_model", s.routingCfg.DefaultFlashFallbackModel),
			slog.String("client_path", r.URL.Path),
		)
	}

	// STAGE 6.5: Mint Downscoped GCP IAM Access Token via Cached ADC TokenSource.
	token, err := s.tokenSource.Token()
	if err != nil {
		s.logger.Error("Failed to obtain GCP IAM access token", slog.String("error", err.Error()))
		writeJSONError(
			w,
			http.StatusInternalServerError,
			"GCP_IAM_TOKEN_EXCHANGE_FAILED",
			"Internal Server Error: failed to obtain GCP IAM access token for Gemini Enterprise Agent Platform.",
			"Verify that the Gateway's attached GCP Service Account has active Application Default Credentials (ADC) and is granted 'roles/aiplatform.user' on the target project.",
		)
		return
	}

	// STAGE 6.6: Scrub Previously Blocked Turns, Normalize Gemini 4 Thinking / OpenAI Config, and Enforce Model Armor.
	body = ScrubBlockedHistoryTurns(body)
	body = NormalizeThinkingConfigForModel(body, routeTarget)
	body = NormalizeOpenAIChatPayload(body, routeTarget)

	if s.routingCfg.ModelArmorMode == "inline" && routeTarget.PromptTemplateName != "" {
		blocked, reason, sanitizedText, armorErr := SanitizePromptInline(r.Context(), s.httpClient, body, routeTarget, token.AccessToken, s.logger)
		if armorErr != nil {
			s.logger.Error("Model Armor inline pre-flight check failed", slog.String("error", armorErr.Error()))
			if s.routingCfg.ModelArmorFailClosed {
				writeJSONError(
					w,
					http.StatusBadGateway,
					"MODEL_ARMOR_UNAVAILABLE",
					fmt.Sprintf("Bad Gateway: Google Cloud Model Armor security service is unreachable or returned an error (%v) while fail-closed policy is active.", armorErr),
					"Verify that 'modelarmor.googleapis.com' is enabled, the template ID in MODEL_ARMOR_TEMPLATE_ID exists in the target region, and the Gateway Service Account has 'roles/modelarmor.user' and 'roles/dlp.user'.",
				)
				return
			}
		} else if blocked {
			s.logger.Warn("Request blocked by Model Armor policy",
				slog.String("template", routeTarget.PromptTemplateName),
				slog.String("reason", reason),
			)
			writePolicyBlockResponse(w, r, body, reason)
			return
		} else if sanitizedText != "" {
			body = ReplaceLastUserPromptText(body, sanitizedText)
		}
	} else if s.routingCfg.ModelArmorMode == "native" && routeTarget.PromptTemplateName != "" {
		body = InjectNativeModelArmorConfig(body, routeTarget)
	}

	// STAGE 6.7 & 6.8: Construct Attribution Headers & Dispatch Upstream with Multi-Region 429/503 Failover.
	candidateRegions := append([]string{routeTarget.Region}, routeTarget.FailoverRegions...)
	var resp *http.Response
	var activeTargetURL string

	for idx, activeRegion := range candidateRegions {
		activeTargetURL = BuildRoutedVertexURL(routeTarget, activeRegion, r.URL.Path, r.URL.RawQuery)
		outReq, reqErr := http.NewRequestWithContext(r.Context(), r.Method, activeTargetURL, bytes.NewReader(body))
		if reqErr != nil {
			s.logger.Error("Failed to construct downstream request", slog.String("error", reqErr.Error()))
			writeJSONError(
				w,
				http.StatusInternalServerError,
				"DOWNSTREAM_REQUEST_BUILD_FAILED",
				fmt.Sprintf("Internal Server Error: failed to construct downstream Vertex AI request (%v).", reqErr),
				"Verify that PROJECT_ID, REGION, and the incoming request URL path are valid.",
			)
			return
		}

		outReq.Header.Set("Authorization", "Bearer "+token.AccessToken)
		outReq.Header.Set("Content-Type", "application/json")

		// Forward User-Agent unchanged so PAYG usage attributes to the organization's Gemini Enterprise contract.
		if ua := r.Header.Get("User-Agent"); ua != "" {
			outReq.Header.Set("User-Agent", ua)
		}

		// Propagate X-Goog-Api-Client and custom enterprise attribution headers (X-Cost-Center, X-Corporate-BU).
		for k, v := range r.Header {
			if strings.HasPrefix(strings.ToLower(k), "x-") {
				for _, val := range v {
					outReq.Header.Add(k, val)
				}
			}
		}

		if routeTarget.ProjectID != s.projectID && outReq.Header.Get("X-Goog-User-Project") == "" {
			outReq.Header.Set("X-Goog-User-Project", routeTarget.ProjectID)
		}

		if routeTarget.DedicatedPT {
			outReq.Header.Set("X-Vertex-AI-LLM-Request-Type", "dedicated")
		}

		resp, err = s.httpClient.Do(outReq)
		if err != nil {
			s.logger.Error("Downstream Vertex AI request failed",
				slog.String("region", activeRegion),
				slog.String("url", activeTargetURL),
				slog.String("error", err.Error()),
			)
			if idx < len(candidateRegions)-1 {
				continue
			}
			writeJSONError(
				w,
				http.StatusBadGateway,
				"UPSTREAM_VERTEX_AI_UNREACHABLE",
				fmt.Sprintf("Bad Gateway: failed to reach Gemini Enterprise Agent Platform backend at %s (%v).", activeTargetURL, err),
				"Verify outbound network connectivity from the Gateway to '*.aiplatform.googleapis.com', check VPC Service Controls / firewall rules, and confirm REGION is valid.",
			)
			return
		}

		// Fail over to secondary regions if primary region returns capacity errors before streaming begins.
		if (resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode == http.StatusServiceUnavailable) && idx < len(candidateRegions)-1 {
			_ = resp.Body.Close()
			s.logger.Warn("Region returned capacity error; failing over to next region",
				slog.String("failed_region", activeRegion),
				slog.Int("status_code", resp.StatusCode),
				slog.String("next_region", candidateRegions[idx+1]),
			)
			continue
		}
		break
	}

	defer func() {
		_ = resp.Body.Close()
	}()

	s.logger.Info("Proxying inference request",
		slog.String("method", r.Method),
		slog.String("client_path", r.URL.Path),
		slog.String("target_project", routeTarget.ProjectID),
		slog.String("target_region", routeTarget.Region),
		slog.Int("upstream_status", resp.StatusCode),
		slog.String("user_agent", r.Header.Get("User-Agent")),
		slog.String("cost_center", r.Header.Get("X-Cost-Center")),
	)

	// STAGE 6.9: Copy Upstream Headers & Stream SSE Chunks with Zero Buffering.
	for k, v := range resp.Header {
		for _, val := range v {
			w.Header().Add(k, val)
		}
	}
	w.WriteHeader(resp.StatusCode)

	flusher, isFlusher := w.(http.Flusher)
	buf := make([]byte, streamBufferBytes)
	for {
		n, readErr := resp.Body.Read(buf)
		if n > 0 {
			if _, writeErr := w.Write(buf[:n]); writeErr != nil {
				s.logger.Debug("Client disconnected during stream write", slog.String("error", writeErr.Error()))
				break
			}
			if isFlusher {
				flusher.Flush()
			}
		}
		if readErr != nil {
			break
		}
	}
}

// ==============================================================================
// BLOCK 7: HTTP SERVER LIFECYCLE & GRACEFUL SHUTDOWN ENTRYPOINT
// ==============================================================================

/*
 * Summary: Configures JSON logging, initializes GatewayServer, binds routes, and handles graceful shutdown.
 * Parameters:
 *   - None (reads configuration via Block 1 variables).
 * Return Value:
 *   - None (exits 0 on clean SIGINT/SIGTERM shutdown, 1 on startup/bind error).
 * Exceptions/Errors:
 *   - Calls os.Exit(1) if Gateway initialization or TCP listener binding fails.
 */
func main() {
	logLevel := slog.LevelInfo
	if strings.EqualFold(LOG_LEVEL, "DEBUG") {
		logLevel = slog.LevelDebug
	}
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: logLevel}))
	slog.SetDefault(logger)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	gateway, err := NewGatewayServer(ctx, logger)
	if err != nil {
		logger.Error("Gateway initialization failed", slog.String("error", err.Error()))
		os.Exit(1)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", gateway.handleHealthz)
	mux.HandleFunc("/", gateway.handleProxy)

	server := &http.Server{
		Addr:         ":" + PORT,
		Handler:      mux,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 60 * time.Minute,
		IdleTimeout:  120 * time.Second,
	}

	go func() {
		logger.Info("Antigravity Enterprise Gateway (Go) started",
			slog.String("port", PORT),
			slog.String("project_id", gateway.projectID),
			slog.String("region", gateway.region),
			slog.String("model_armor_mode", gateway.routingCfg.ModelArmorMode),
			slog.String("model_armor_template", gateway.routingCfg.ModelArmorTemplateID),
		)
		if serveErr := server.ListenAndServe(); serveErr != nil && serveErr != http.ErrServerClosed {
			logger.Error("HTTP server failed", slog.String("error", serveErr.Error()))
			os.Exit(1)
		}
	}()

	<-ctx.Done()
	logger.Info("Shutting down Antigravity Enterprise Gateway gracefully...")
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	_ = server.Shutdown(shutdownCtx)
}
