/*
 * ==============================================================================
 * FILE HEADER: Go Antigravity Enterprise Gateway — Model Armor & Dynamic Router
 * ==============================================================================
 * Author: Pradeep Singh
 * License: Apache-2.0
 *
 * Purpose:
 *   Implements Google Cloud Model Armor prompt/response screening, Cloud SDP
 *   in-place PII redaction, multi-turn blocked-history scrubbing, Gemini 4
 *   thinking-level normalization, and dynamic multi-project/multi-region routing.
 *
 * Architecture / Context:
 *   Organized into 7 explicit code blocks invoked by `GatewayServer.handleProxy`
 *   in `main.go` before forwarding requests to `aiplatform.googleapis.com`:
 *     - BLOCK 1: Standardized Model Armor & Dynamic Routing Variables.
 *     - BLOCK 2: Routing & Model Armor Data Structures (`RouterAndArmorConfig`, `RouteTarget`).
 *     - BLOCK 3: Configuration Parsers (`LoadRouterAndArmorConfig`, `parseKeyValueEnv`, `parseCSVEnv`).
 *     - BLOCK 4: Dynamic Route Resolution Engine (`ResolveRouteTarget`, `BuildRoutedVertexURL`).
 *     - BLOCK 5: Google Cloud Model Armor Enforcement Engine (`InjectNativeModelArmorConfig`,
 *                `SanitizePromptInline`, `ReplaceLastUserPromptText`).
 *     - BLOCK 6: Multi-Turn History Scrubbing & Conversational Policy Block Helpers.
 *     - BLOCK 7: Gemini 4+ Thinking-Level Normalization Engine (`NormalizeThinkingConfigForModel`).
 *
 * Dependencies / Side Effects:
 *   - Reads configuration via `getEnv` (from `main.go`) across OS env, `.env`, and `settings.env`.
 *   - In `inline` mode, sends HTTPS POST requests to
 *     `https://modelarmor.<REGION>.rep.googleapis.com/v1/...:sanitizeUserPrompt`.
 * ==============================================================================
 */
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
)

// ==============================================================================
// BLOCK 1: MODEL ARMOR & DYNAMIC ROUTING VARIABLES
// ==============================================================================
var (
	// [OPTIONAL] Master toggle from unified settings.env ("true" or "false")
	ENABLE_MODEL_ARMOR = getEnv("ENABLE_MODEL_ARMOR", "true")

	// [OPTIONAL] Google Cloud Model Armor template ID (e.g., "agy-enterprise-armor")
	MODEL_ARMOR_TEMPLATE_ID = getEnv("MODEL_ARMOR_TEMPLATE_ID", "")

	// [OPTIONAL] Enforcement mode: "inline", "native", or "disabled"
	MODEL_ARMOR_MODE = getEnv("MODEL_ARMOR_MODE", "inline")

	// [OPTIONAL] Block requests if inline Model Armor API is unreachable ("true" or "false")
	MODEL_ARMOR_FAIL_CLOSED = getEnv("MODEL_ARMOR_FAIL_CLOSED", "true")

	// [OPTIONAL] Comma-separated X-Cost-Center=PROJECT_ID routing map
	COST_CENTER_PROJECT_MAP = getEnv("COST_CENTER_PROJECT_MAP", "")

	// [OPTIONAL] Comma-separated MODEL_ID=REGION routing map
	MODEL_REGION_MAP = getEnv("MODEL_REGION_MAP", "")

	// [OPTIONAL] Comma-separated fallback regions retried on HTTP 429 or 503
	FAILOVER_REGIONS = getEnv("FAILOVER_REGIONS", "")

	// [OPTIONAL] Flash model substituted if an unpatched client emits MODEL_PLACEHOLDER_M50
	DEFAULT_FLASH_FALLBACK_MODEL = getEnv("DEFAULT_FLASH_FALLBACK_MODEL", "gemini-3.8-flash")

	// [OPTIONAL] Custom OpenAI-compatible upstream base URL for /v1/chat/completions (blank uses Vertex AI OpenAI endpoint)
	OPENAI_UPSTREAM_BASE_URL = getEnv("OPENAI_UPSTREAM_BASE_URL", "")
)

// ==============================================================================
// BLOCK 2: ROUTING & MODEL ARMOR DATA STRUCTURES
// ==============================================================================

/*
 * Summary: Holds startup-parsed routing maps and Model Armor settings.
 * Parameters:
 *   - Populated once at startup via LoadRouterAndArmorConfig.
 * Return Value:
 *   - RouterAndArmorConfig struct value.
 * Exceptions/Errors:
 *   - None.
 */
type RouterAndArmorConfig struct {
	DefaultProject            string
	DefaultRegion             string
	FailoverRegions           []string
	CostCenterProjects        map[string]string
	ModelRegions              map[string]string
	ModelArmorTemplateID      string
	ModelArmorMode            string
	ModelArmorFailClosed      bool
	DefaultFlashFallbackModel string
	OpenAIUpstreamBaseURL     string
}

/*
 * Summary: Holds per-request resolved GCP project, region, PT flag, thinking level, OpenAI state, and Armor template paths.
 * Parameters:
 *   - Computed per HTTP request by ResolveRouteTarget.
 * Return Value:
 *   - RouteTarget struct value.
 * Exceptions/Errors:
 *   - None.
 */
type RouteTarget struct {
	ProjectID             string
	Region                string
	FailoverRegions       []string
	ModelAction           string
	DedicatedPT           bool
	ThinkingLevel         string
	PromptTemplateName    string
	RespTemplateName      string
	IsOpenAIChat          bool
	OpenAIModelID         string
	OpenAIUpstreamBaseURL string
	M50FallbackApplied    bool
}

var thinkingSuffixMap = []struct {
	suffix string
	level  string
}{
	{"-high", "HIGH"},
	{"-medium", "MEDIUM"},
	{"-low", "LOW"},
	{"-minimal", "MINIMAL"},
}

// ==============================================================================
// BLOCK 3: CONFIGURATION PARSERS (Startup Initialization)
// ==============================================================================

/*
 * Summary: Initializes RouterAndArmorConfig from Block 1 variables.
 * Parameters:
 *   - defaultProject (string): Default GCP Project ID from main.go.
 *   - defaultRegion (string): Default GCP Region from main.go.
 * Return Value:
 *   - RouterAndArmorConfig: Parsed routing and security policy configuration.
 * Exceptions/Errors:
 *   - None.
 */
func LoadRouterAndArmorConfig(defaultProject, defaultRegion string) RouterAndArmorConfig {
	mode := strings.ToLower(strings.TrimSpace(MODEL_ARMOR_MODE))
	if mode == "" {
		mode = "inline"
	}
	if strings.EqualFold(strings.TrimSpace(ENABLE_MODEL_ARMOR), "false") {
		mode = "disabled"
	}
	failClosed := !strings.EqualFold(strings.TrimSpace(MODEL_ARMOR_FAIL_CLOSED), "false")
	flashFallback := strings.TrimSpace(DEFAULT_FLASH_FALLBACK_MODEL)
	if flashFallback == "" {
		flashFallback = "gemini-3.8-flash"
	}

	return RouterAndArmorConfig{
		DefaultProject:            defaultProject,
		DefaultRegion:             defaultRegion,
		FailoverRegions:           parseCSVEnv(FAILOVER_REGIONS),
		CostCenterProjects:        parseKeyValueEnv(COST_CENTER_PROJECT_MAP),
		ModelRegions:              parseKeyValueEnv(MODEL_REGION_MAP),
		ModelArmorTemplateID:      strings.TrimSpace(MODEL_ARMOR_TEMPLATE_ID),
		ModelArmorMode:            mode,
		ModelArmorFailClosed:      failClosed,
		DefaultFlashFallbackModel: flashFallback,
		OpenAIUpstreamBaseURL:     strings.TrimSpace(OPENAI_UPSTREAM_BASE_URL),
	}
}

/*
 * Summary: Parses a comma-separated "Key1=Val1,Key2=Val2" string into a map.
 * Parameters:
 *   - raw (string): Comma-separated key=value pairs.
 * Return Value:
 *   - map[string]string: Map of non-empty trimmed keys and values.
 * Exceptions/Errors:
 *   - Malformed entries without "=" are ignored safely.
 */
func parseKeyValueEnv(raw string) map[string]string {
	result := make(map[string]string)
	for _, pair := range strings.Split(raw, ",") {
		if kv := strings.SplitN(strings.TrimSpace(pair), "=", 2); len(kv) == 2 {
			k := strings.TrimSpace(kv[0])
			v := strings.TrimSpace(kv[1])
			if k != "" && v != "" {
				result[k] = v
			}
		}
	}
	return result
}

/*
 * Summary: Parses a comma-separated list of strings into a slice of trimmed non-empty strings.
 * Parameters:
 *   - raw (string): Comma-separated string list (e.g., "europe-west4,europe-west3").
 * Return Value:
 *   - []string: Slice of non-empty trimmed items.
 * Exceptions/Errors:
 *   - Returns nil/empty slice when input is blank.
 */
func parseCSVEnv(raw string) []string {
	var out []string
	for _, item := range strings.Split(raw, ",") {
		if trimmed := strings.TrimSpace(item); trimmed != "" {
			out = append(out, trimmed)
		}
	}
	return out
}

// ==============================================================================
// BLOCK 4: DYNAMIC ROUTE RESOLUTION ENGINE
// ==============================================================================

/*
 * Summary: Resolves target GCP project, region, PT flag, thinking level, OpenAI state, and Model Armor template per request.
 * Parameters:
 *   - r (*http.Request): Incoming Antigravity HTTP request.
 *   - body ([]byte): Raw JSON request body (inspected for `model` on `/v1/chat/completions`).
 *   - cfg (RouterAndArmorConfig): Parsed routing and Model Armor configuration.
 * Return Value:
 *   - RouteTarget: Resolved routing target metadata.
 * Exceptions/Errors:
 *   - None.
 */
func ResolveRouteTarget(r *http.Request, body []byte, cfg RouterAndArmorConfig) RouteTarget {
	target := RouteTarget{
		ProjectID:       cfg.DefaultProject,
		Region:          cfg.DefaultRegion,
		FailoverRegions: cfg.FailoverRegions,
	}

	// Step 1: Cost-Center Chargeback Routing via X-Cost-Center header.
	if cc := strings.TrimSpace(r.Header.Get("X-Cost-Center")); cc != "" {
		if mappedProject, ok := cfg.CostCenterProjects[cc]; ok && mappedProject != "" {
			target.ProjectID = mappedProject
		}
	}

	// Step 2: Detect GenAI URL path vs. OpenAI Chat Completions wire protocol (/v1/chat/completions).
	path := r.URL.Path
	modelID := ""
	actionSuffix := ""

	if strings.HasSuffix(strings.TrimRight(path, "/"), "/chat/completions") {
		target.IsOpenAIChat = true
		target.OpenAIUpstreamBaseURL = cfg.OpenAIUpstreamBaseURL
		if len(body) > 0 {
			var openAIPayload struct {
				Model string `json:"model"`
			}
			if err := json.Unmarshal(body, &openAIPayload); err == nil {
				rawModel := strings.TrimSpace(openAIPayload.Model)
				modelID = strings.TrimPrefix(rawModel, "google/")
			}
		}
	} else if strings.HasPrefix(path, "/v1beta/models/") {
		target.ModelAction = strings.TrimPrefix(path, "/v1beta/models/")
		parts := strings.SplitN(target.ModelAction, ":", 2)
		modelID = parts[0]
		if len(parts) > 1 {
			actionSuffix = ":" + parts[1]
		}
	} else if idx := strings.Index(path, "/publishers/google/models/"); idx != -1 {
		target.ModelAction = path[idx+len("/publishers/google/models/"):]
		parts := strings.SplitN(target.ModelAction, ":", 2)
		modelID = parts[0]
		if len(parts) > 1 {
			actionSuffix = ":" + parts[1]
		}
	}

	// Step 2b: Guard against unmapped MODEL_PLACEHOLDER_M50 / MODEL_PLACEHOLDER_* enums
	// emitted during background titling/checkpointing when a client omits a Flash model.
	upperModel := strings.ToUpper(modelID)
	if upperModel == "MODEL_PLACEHOLDER_M50" || strings.HasPrefix(upperModel, "MODEL_PLACEHOLDER_") {
		modelID = cfg.DefaultFlashFallbackModel
		target.M50FallbackApplied = true
	}

	// Step 3a: Provisioned Throughput ("-pt") suffix detection.
	if strings.HasSuffix(modelID, "-pt") {
		target.DedicatedPT = true
		modelID = strings.TrimSuffix(modelID, "-pt")
	}

	// Step 3b: Thinking-level suffix alias detection (e.g., "gemini-4-argon-high").
	lowerModelID := strings.ToLower(modelID)
	for _, entry := range thinkingSuffixMap {
		if strings.HasSuffix(lowerModelID, entry.suffix) {
			target.ThinkingLevel = entry.level
			modelID = modelID[:len(modelID)-len(entry.suffix)]
			break
		}
	}

	// Support "-pt" appearing before the thinking suffix (e.g., "gemini-4-argon-pt-high").
	if strings.HasSuffix(modelID, "-pt") {
		target.DedicatedPT = true
		modelID = strings.TrimSuffix(modelID, "-pt")
	}

	if target.IsOpenAIChat {
		target.OpenAIModelID = modelID
	} else if target.ModelAction != "" {
		target.ModelAction = modelID + actionSuffix
	}

	// Step 4: Model-specific regional placement; Gemini 4 and 3.x models default to "global" PayGo endpoint.
	if mappedRegion, ok := cfg.ModelRegions[modelID]; ok && mappedRegion != "" {
		target.Region = mappedRegion
	} else if strings.HasPrefix(modelID, "gemini-4-") || strings.HasPrefix(modelID, "gemini-3.") {
		target.Region = "global"
	}

	// Step 5: Construct regional Model Armor template resource name (Model Armor is regional, never "global").
	if cfg.ModelArmorTemplateID != "" && cfg.ModelArmorMode != "disabled" {
		armorRegion := target.Region
		if armorRegion == "global" {
			armorRegion = cfg.DefaultRegion
			if armorRegion == "" || armorRegion == "global" {
				armorRegion = "europe-west1"
			}
		}
		templateName := fmt.Sprintf(
			"projects/%s/locations/%s/templates/%s",
			target.ProjectID, armorRegion, cfg.ModelArmorTemplateID,
		)
		target.PromptTemplateName = templateName
		target.RespTemplateName = templateName
	}

	return target
}

/*
 * Summary: Builds the fully qualified regional or global Vertex AI (or custom OpenAI) HTTPS backend URL.
 * Parameters:
 *   - target (RouteTarget): Resolved target project, OpenAI flag, and model action.
 *   - activeRegion (string): Region for the current attempt (primary or failover).
 *   - origPath (string): Original request path for pass-through routes.
 *   - rawQuery (string): Raw URL query parameters (e.g., "alt=sse").
 * Return Value:
 *   - string: Complete upstream HTTPS URL.
 * Exceptions/Errors:
 *   - None.
 */
func BuildRoutedVertexURL(target RouteTarget, activeRegion, origPath, rawQuery string) string {
	if target.IsOpenAIChat && target.OpenAIUpstreamBaseURL != "" {
		base := strings.TrimRight(target.OpenAIUpstreamBaseURL, "/")
		var targetURL string
		switch {
		case strings.HasSuffix(base, "/chat/completions"):
			targetURL = base
		case strings.HasSuffix(base, "/v1"):
			targetURL = base + "/chat/completions"
		default:
			targetURL = base + "/v1/chat/completions"
		}
		if rawQuery != "" {
			targetURL += "?" + rawQuery
		}
		return targetURL
	}

	var targetPath string
	if target.IsOpenAIChat {
		targetPath = fmt.Sprintf(
			"/v1beta1/projects/%s/locations/%s/endpoints/openapi/chat/completions",
			target.ProjectID, activeRegion,
		)
	} else if target.ModelAction != "" {
		targetPath = fmt.Sprintf(
			"/v1beta1/projects/%s/locations/%s/publishers/google/models/%s",
			target.ProjectID, activeRegion, target.ModelAction,
		)
	} else {
		targetPath = origPath
	}

	host := fmt.Sprintf("%s-aiplatform.googleapis.com", activeRegion)
	if activeRegion == "global" {
		host = "aiplatform.googleapis.com"
	}

	targetURL := fmt.Sprintf("https://%s%s", host, targetPath)
	if rawQuery != "" {
		targetURL += "?" + rawQuery
	}
	return targetURL
}

// ==============================================================================
// BLOCK 5: GOOGLE CLOUD MODEL ARMOR ENFORCEMENT ENGINE
// ==============================================================================

/*
 * Summary: Injects native `modelArmorConfig` into a Vertex AI generateContent payload if absent.
 * Parameters:
 *   - body ([]byte): Raw JSON request body.
 *   - target (RouteTarget): Resolved target containing prompt and response template paths.
 * Return Value:
 *   - []byte: Updated JSON request body (or original bytes if OpenAI mode or non-JSON).
 * Exceptions/Errors:
 *   - Falls back safely to original `body` on JSON parse errors.
 */
func InjectNativeModelArmorConfig(body []byte, target RouteTarget) []byte {
	if target.IsOpenAIChat || target.PromptTemplateName == "" || len(body) == 0 {
		return body
	}
	var payload map[string]any
	if err := json.Unmarshal(body, &payload); err != nil {
		return body
	}
	if _, exists := payload["modelArmorConfig"]; !exists {
		payload["modelArmorConfig"] = map[string]any{
			"promptTemplateName":   target.PromptTemplateName,
			"responseTemplateName": target.RespTemplateName,
		}
		if updated, err := json.Marshal(payload); err == nil {
			return updated
		}
	}
	return body
}

/*
 * Summary: Extracts the raw text of the final message turn from either GenAI `contents[]` or OpenAI `messages[]`.
 * Parameters:
 *   - body ([]byte): Raw JSON request body.
 * Return Value:
 *   - string: Extracted final turn text, or empty string if absent.
 * Exceptions/Errors:
 *   - Returns empty string safely on malformed JSON.
 */
/*
 * Summary: Strips internal Antigravity `<SYSTEM_MESSAGE>` and `<SYSTEM_REMINDER>` blocks before Model Armor scanning.
 * Parameters:
 *   - text (string): Raw turn text extracted from GenAI `contents`.
 * Return Value:
 *   - string: Cleaned user text with IDE harness system wrappers removed.
 * Exceptions/Errors:
 *   - None.
 */
func stripIdeHarnessTags(text string) string {
	for _, tag := range []string{"SYSTEM_MESSAGE", "SYSTEM_REMINDER"} {
		openTag := "<" + tag + ">"
		closeTag := "</" + tag + ">"
		for {
			start := strings.Index(text, openTag)
			if start == -1 {
				break
			}
			end := strings.Index(text[start:], closeTag)
			if end == -1 {
				break
			}
			text = text[:start] + text[start+end+len(closeTag):]
		}
	}
	return strings.TrimSpace(text)
}

func extractLastTurnText(body []byte) string {
	var payload map[string]any
	if err := json.Unmarshal(body, &payload); err != nil {
		return ""
	}

	if contents, ok := payload["contents"].([]any); ok && len(contents) > 0 {
		if lastContent, ok := contents[len(contents)-1].(map[string]any); ok {
			parts, _ := lastContent["parts"].([]any)
			hasFuncResp := false
			var builder strings.Builder
			for _, p := range parts {
				pMap, ok := p.(map[string]any)
				if !ok {
					continue
				}
				if _, ok := pMap["functionResponse"].(map[string]any); ok {
					hasFuncResp = true
					continue
				}
				if t, ok := pMap["text"].(string); ok && t != "" {
					builder.WriteString(t)
					builder.WriteString("\n")
				}
			}
			combined := builder.String()
			// Skip automated tool-execution return turns that contain no new human <USER_REQUEST>.
			if hasFuncResp && !strings.Contains(combined, "<USER_REQUEST>") {
				return ""
			}
			return stripIdeHarnessTags(combined)
		}
	}

	if messages, ok := payload["messages"].([]any); ok && len(messages) > 0 {
		if lastMsg, ok := messages[len(messages)-1].(map[string]any); ok {
			switch contentVal := lastMsg["content"].(type) {
			case string:
				return strings.TrimSpace(contentVal)
			case []any:
				var builder strings.Builder
				for _, item := range contentVal {
					if itemMap, ok := item.(map[string]any); ok {
						if t, ok := itemMap["text"].(string); ok && t != "" {
							builder.WriteString(t)
							builder.WriteString("\n")
						}
					}
				}
				return strings.TrimSpace(builder.String())
			}
		}
	}

	return ""
}

/*
 * Summary: Calls Model Armor `:sanitizeUserPrompt` inline before forwarding the request to Vertex AI.
 * Parameters:
 *   - ctx (context.Context): Request context.
 *   - client (*http.Client): Shared HTTP client.
 *   - body ([]byte): Raw generateContent or OpenAI chat.completions JSON request payload.
 *   - target (RouteTarget): Resolved route target containing PromptTemplateName.
 *   - accessToken (string): GCP IAM OAuth2 Bearer access token.
 *   - logger (*slog.Logger): Structured JSON logger.
 * Return Value:
 *   - (bool, string, string, error): Tuple of (blocked, blockReason, sanitizedReplacementText, error).
 * Exceptions/Errors:
 *   - Returns non-nil error if the Model Armor REST call fails or returns non-200 status.
 */
func SanitizePromptInline(
	ctx context.Context,
	client *http.Client,
	body []byte,
	target RouteTarget,
	accessToken string,
	logger *slog.Logger,
) (bool, string, string, error) {
	if target.PromptTemplateName == "" || len(body) == 0 {
		return false, "", "", nil
	}

	rawTurnText := extractLastTurnText(body)
	if rawTurnText == "" {
		return false, "", "", nil
	}

	// Isolate inner <USER_REQUEST> text so benign IDE XML metadata does not dilute Model Armor ML classifiers.
	promptText := rawTurnText
	if startIdx := strings.Index(rawTurnText, "<USER_REQUEST>"); startIdx != -1 {
		contentStart := startIdx + len("<USER_REQUEST>")
		if endOffset := strings.Index(rawTurnText[contentStart:], "</USER_REQUEST>"); endOffset != -1 {
			promptText = strings.TrimSpace(rawTurnText[contentStart : contentStart+endOffset])
		}
	}
	if promptText == "" {
		return false, "", "", nil
	}

	// Extract actual template region directly from projects/{P}/locations/{R}/templates/{T}.
	armorRegion := "europe-west1"
	if parts := strings.Split(target.PromptTemplateName, "/"); len(parts) >= 4 {
		armorRegion = parts[3]
	}
	armorURL := fmt.Sprintf(
		"https://modelarmor.%s.rep.googleapis.com/v1/%s:sanitizeUserPrompt",
		armorRegion, target.PromptTemplateName,
	)
	armorReqBody, _ := json.Marshal(map[string]any{
		"userPromptData": map[string]any{
			"text": promptText,
		},
	})

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, armorURL, bytes.NewReader(armorReqBody))
	if err != nil {
		return false, "", "", err
	}
	req.Header.Set("Authorization", "Bearer "+accessToken)
	req.Header.Set("Content-Type", "application/json")

	resp, err := client.Do(req)
	if err != nil {
		return false, "", "", err
	}
	defer func() {
		_ = resp.Body.Close()
	}()

	respBytes, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		logger.Warn("Model Armor API returned non-200 status",
			slog.Int("status_code", resp.StatusCode),
			slog.String("response", string(respBytes)),
		)
		return false, "", "", fmt.Errorf("Model Armor API returned status %d", resp.StatusCode)
	}

	var armorResp struct {
		SanitizationResult struct {
			FilterMatchState string `json:"filterMatchState"`
			FilterResults    map[string]struct {
				CsamFilterFilterResult struct {
					MatchState string `json:"matchState"`
				} `json:"csamFilterFilterResult"`
				RaiFilterResult struct {
					MatchState string `json:"matchState"`
				} `json:"raiFilterResult"`
				PiAndJailbreakFilterResult struct {
					MatchState string `json:"matchState"`
				} `json:"piAndJailbreakFilterResult"`
				MaliciousUriFilterResult struct {
					MatchState string `json:"matchState"`
				} `json:"maliciousUriFilterResult"`
				SdpFilterResult struct {
					DeidentifyResult struct {
						Data struct {
							Text string `json:"text"`
						} `json:"data"`
						InfoTypes []string `json:"infoTypes"`
					} `json:"deidentifyResult"`
				} `json:"sdpFilterResult"`
			} `json:"filterResults"`
		} `json:"sanitizationResult"`
	}

	if err := json.Unmarshal(respBytes, &armorResp); err == nil {
		// Pass 1 (Order-Independent Hard Blocks): Because Go map iteration order is randomized,
		// evaluate all hard-block filters across EVERY filterResults entry before allowing SDP redaction.
		sdpRedactedCandidate := ""
		for _, fr := range armorResp.SanitizationResult.FilterResults {
			if fr.CsamFilterFilterResult.MatchState == "MATCH_FOUND" ||
				fr.RaiFilterResult.MatchState == "MATCH_FOUND" ||
				fr.PiAndJailbreakFilterResult.MatchState == "MATCH_FOUND" ||
				fr.MaliciousUriFilterResult.MatchState == "MATCH_FOUND" {
				return true, "Blocked by Google Cloud Model Armor security filter (RAI, CSAM, Prompt Injection/Jailbreak, or Malicious URI).", "", nil
			}
			for _, it := range fr.SdpFilterResult.DeidentifyResult.InfoTypes {
				if strings.HasPrefix(it, "CUSTOM_") {
					return true, "Blocked by Google Cloud Model Armor custom enterprise security rule (prohibited offensive/evasion activity detected).", "", nil
				}
			}
			if redacted := fr.SdpFilterResult.DeidentifyResult.Data.Text; redacted != "" {
				if strings.Contains(redacted, "[CUSTOM_") {
					return true, "Blocked by Google Cloud Model Armor custom enterprise security rule (prohibited offensive/evasion activity detected).", "", nil
				}
				if redacted != promptText {
					sdpRedactedCandidate = redacted
				}
			}
		}

		// Pass 2 (Cloud SDP PII/Credential Redaction): Safe to forward redacted prompt only when zero hard blocks matched.
		if sdpRedactedCandidate != "" {
			logger.Info("Redacted sensitive prompt data via Cloud SDP",
				slog.String("template", target.PromptTemplateName),
			)
			if rawTurnText != promptText {
				sdpRedactedCandidate = strings.Replace(rawTurnText, promptText, sdpRedactedCandidate, 1)
			}
			return false, "", sdpRedactedCandidate, nil
		}

		if armorResp.SanitizationResult.FilterMatchState == "MATCH_FOUND" {
			return true, "Blocked by Google Cloud Model Armor policy (Prompt Injection, Jailbreak, PII/PCI/Credentials, or Malicious URI detected).", "", nil
		}
	}
	return false, "", "", nil
}

/*
 * Summary: Replaces the final user turn text in GenAI `contents` or OpenAI `messages` with SDP-redacted text.
 * Parameters:
 *   - body ([]byte): Original JSON request payload.
 *   - redactedText (string): Redacted prompt string returned by Cloud SDP via Model Armor.
 * Return Value:
 *   - []byte: Updated JSON request body with sensitive PII/PCI/credentials masked.
 * Exceptions/Errors:
 *   - Returns original `body` unchanged if JSON unmarshaling fails.
 */
func ReplaceLastUserPromptText(body []byte, redactedText string) []byte {
	var payload map[string]any
	if err := json.Unmarshal(body, &payload); err != nil {
		return body
	}
	if contents, ok := payload["contents"].([]any); ok && len(contents) > 0 {
		if lastItem, ok := contents[len(contents)-1].(map[string]any); ok {
			lastItem["parts"] = []map[string]any{
				{"text": redactedText},
			}
			if updated, err := json.Marshal(payload); err == nil {
				return updated
			}
		}
	}
	if messages, ok := payload["messages"].([]any); ok && len(messages) > 0 {
		if lastMsg, ok := messages[len(messages)-1].(map[string]any); ok {
			lastMsg["content"] = redactedText
			if updated, err := json.Marshal(payload); err == nil {
				return updated
			}
		}
	}
	return body
}

// ==============================================================================
// BLOCK 6: MULTI-TURN HISTORY SCRUBBING & CONVERSATIONAL BLOCK HELPERS
// ==============================================================================

// PolicyBlockMarker identifies conversational security-block turns in multi-turn chat histories.
const PolicyBlockMarker = "Prompt Blocked by Organization Security Policy"

/*
 * Summary: Scrubs previously blocked historical user turns across GenAI `contents` or OpenAI `messages`.
 * Parameters:
 *   - body ([]byte): Raw generateContent or chat.completions JSON request payload.
 * Return Value:
 *   - []byte: Sanitized JSON payload with blocked historical user turns replaced by a neutral placeholder.
 * Exceptions/Errors:
 *   - Returns original `body` unchanged if fewer than 2 turns exist or JSON parsing fails.
 */
func ScrubBlockedHistoryTurns(body []byte) []byte {
	if len(body) == 0 {
		return body
	}
	var payload map[string]any
	if err := json.Unmarshal(body, &payload); err != nil {
		return body
	}

	modified := false
	if contents, ok := payload["contents"].([]any); ok && len(contents) >= 2 {
		for idx := 0; idx < len(contents)-1; idx++ {
			currTurn, ok1 := contents[idx].(map[string]any)
			nextTurn, ok2 := contents[idx+1].(map[string]any)
			if !ok1 || !ok2 {
				continue
			}
			currRole, _ := currTurn["role"].(string)
			nextRole, _ := nextTurn["role"].(string)
			if currRole == "user" && nextRole == "model" {
				parts, _ := nextTurn["parts"].([]any)
				var modelText strings.Builder
				for _, p := range parts {
					if pMap, ok := p.(map[string]any); ok {
						if t, ok := pMap["text"].(string); ok {
							modelText.WriteString(t)
							modelText.WriteString(" ")
						}
					}
				}
				if strings.Contains(modelText.String(), PolicyBlockMarker) {
					currTurn["parts"] = []map[string]any{
						{"text": "[Previous user prompt was blocked and removed by organization security policy.]"},
					}
					modified = true
				}
			}
		}
	}

	if messages, ok := payload["messages"].([]any); ok && len(messages) >= 2 {
		for idx := 0; idx < len(messages)-1; idx++ {
			currMsg, ok1 := messages[idx].(map[string]any)
			nextMsg, ok2 := messages[idx+1].(map[string]any)
			if !ok1 || !ok2 {
				continue
			}
			currRole, _ := currMsg["role"].(string)
			nextRole, _ := nextMsg["role"].(string)
			nextContent, _ := nextMsg["content"].(string)
			if currRole == "user" && nextRole == "assistant" && strings.Contains(nextContent, PolicyBlockMarker) {
				currMsg["content"] = "[Previous user prompt was blocked and removed by organization security policy.]"
				modified = true
			}
		}
	}

	if modified {
		if updated, err := json.Marshal(payload); err == nil {
			return updated
		}
	}
	return body
}

/*
 * Summary: Formats a Markdown conversational security policy block notice for the Antigravity chat UI.
 * Parameters:
 *   - reason (string): Specific Model Armor / Cloud SDP filter trigger reason.
 * Return Value:
 *   - string: User-friendly Markdown block message.
 * Exceptions/Errors:
 *   - None.
 */
func FormatPolicyBlockMessage(reason string) string {
	return fmt.Sprintf(
		"🛡️ **%s**\n\nYour organization's AI security gateway (**Google Cloud Model Armor**) prevented this prompt from being processed.\n\n- **Security Filter Details:** %s\n\nPlease modify your request to comply with your organization's acceptable use policies, or contact your IT/Security administrator if you need this access to continue.",
		PolicyBlockMarker,
		reason,
	)
}

// ==============================================================================
// BLOCK 7: GEMINI 4+ THINKING & OPENAI WIRE PROTOCOL NORMALIZATION ENGINE
// ==============================================================================

/*
 * Summary: Converts unsupported `thinkingBudget`/`MINIMAL` fields to `thinkingLevel` (`LOW`/`MEDIUM`/`HIGH`) for Gemini 4+.
 * Parameters:
 *   - body ([]byte): Raw generateContent JSON request payload.
 *   - target (RouteTarget): Resolved target containing ModelAction and ThinkingLevel.
 * Return Value:
 *   - []byte: Normalized JSON request body preventing HTTP 400 INVALID_ARGUMENT on `gemini-4-argon`.
 * Exceptions/Errors:
 *   - Returns original `body` unchanged for non-Gemini-4 models without suffix aliases or on parse errors.
 */
func NormalizeThinkingConfigForModel(body []byte, target RouteTarget) []byte {
	if len(body) == 0 || target.ModelAction == "" {
		return body
	}
	modelID := strings.ToLower(strings.SplitN(target.ModelAction, ":", 2)[0])
	isGemini4 := strings.HasPrefix(modelID, "gemini-4")
	explicitLevel := strings.ToUpper(strings.TrimSpace(target.ThinkingLevel))

	if !isGemini4 && explicitLevel == "" {
		return body
	}

	var payload map[string]any
	if err := json.Unmarshal(body, &payload); err != nil {
		return body
	}

	if explicitLevel != "" {
		_, hasGen1 := payload["generationConfig"]
		_, hasGen2 := payload["generation_config"]
		if !hasGen1 && !hasGen2 {
			finalLevel := explicitLevel
			if isGemini4 && finalLevel == "MINIMAL" {
				finalLevel = "LOW"
			}
			payload["generationConfig"] = map[string]any{
				"thinkingConfig": map[string]any{
					"includeThoughts": true,
					"thinkingLevel":   finalLevel,
				},
			}
			if updated, err := json.Marshal(payload); err == nil {
				return updated
			}
			return body
		}
	}

	modified := false
	for _, genKey := range []string{"generationConfig", "generation_config"} {
		genCfg, ok := payload[genKey].(map[string]any)
		if !ok {
			continue
		}

		if explicitLevel != "" {
			_, hasThink1 := genCfg["thinkingConfig"]
			_, hasThink2 := genCfg["thinking_config"]
			if !hasThink1 && !hasThink2 {
				finalLevel := explicitLevel
				if isGemini4 && finalLevel == "MINIMAL" {
					finalLevel = "LOW"
				}
				thinkKey := "thinkingConfig"
				levelKey := "thinkingLevel"
				incKey := "includeThoughts"
				if genKey == "generation_config" {
					thinkKey = "thinking_config"
					levelKey = "thinking_level"
					incKey = "include_thoughts"
				}
				genCfg[thinkKey] = map[string]any{
					incKey:   true,
					levelKey: finalLevel,
				}
				modified = true
				continue
			}
		}

		for _, thinkKey := range []string{"thinkingConfig", "thinking_config"} {
			thinkCfg, ok := genCfg[thinkKey].(map[string]any)
			if !ok {
				continue
			}

			var budgetVal any
			hasBudget := false
			for _, bKey := range []string{"thinkingBudget", "thinking_budget"} {
				if val, exists := thinkCfg[bKey]; exists {
					budgetVal = val
					hasBudget = true
					delete(thinkCfg, bKey)
					modified = true
				}
			}

			levelField := "thinkingLevel"
			if thinkKey == "thinking_config" {
				levelField = "thinking_level"
			}
			existingLevelKey := "thinkingLevel"
			if _, exists := thinkCfg["thinking_level"]; exists {
				existingLevelKey = "thinking_level"
			}
			existingLevel, _ := thinkCfg[existingLevelKey].(string)
			existingLevelUpper := strings.ToUpper(existingLevel)

			if explicitLevel != "" {
				finalLevel := explicitLevel
				if isGemini4 && (finalLevel == "MINIMAL" || finalLevel == "THINKING_LEVEL_MINIMAL") {
					finalLevel = "LOW"
				}
				thinkCfg[levelField] = finalLevel
				modified = true
			} else if hasBudget && existingLevelUpper == "" {
				bNum := -1.0
				if fVal, ok := budgetVal.(float64); ok {
					bNum = fVal
				}
				mappedLevel := "HIGH"
				if bNum >= 0 && bNum <= 1024 {
					mappedLevel = "LOW"
				} else if bNum > 1024 && bNum <= 4096 {
					mappedLevel = "MEDIUM"
				}
				thinkCfg[levelField] = mappedLevel
				modified = true
			} else if isGemini4 && (existingLevelUpper == "MINIMAL" || existingLevelUpper == "THINKING_LEVEL_MINIMAL") {
				thinkCfg[existingLevelKey] = "LOW"
				modified = true
			}
		}
	}

	if modified {
		if updated, err := json.Marshal(payload); err == nil {
			return updated
		}
	}
	return body
}

/*
 * Summary: Normalizes OpenAI `/v1/chat/completions` payloads for Vertex AI OpenAI or custom upstreams.
 * Parameters:
 *   - body ([]byte): Raw `/v1/chat/completions` JSON request payload.
 *   - target (RouteTarget): Resolved route target containing OpenAI metadata and thinking level.
 * Return Value:
 *   - []byte: Normalized JSON request body with `google/` model prefix (for Vertex OpenAI) and `reasoning_effort`.
 * Exceptions/Errors:
 *   - Returns original `body` unchanged for non-OpenAI requests or on JSON parse errors.
 */
func NormalizeOpenAIChatPayload(body []byte, target RouteTarget) []byte {
	if len(body) == 0 || !target.IsOpenAIChat {
		return body
	}
	var payload map[string]any
	if err := json.Unmarshal(body, &payload); err != nil {
		return body
	}

	modified := false
	if target.OpenAIModelID != "" {
		desiredModel := target.OpenAIModelID
		if target.OpenAIUpstreamBaseURL == "" && !strings.Contains(target.OpenAIModelID, "/") {
			desiredModel = "google/" + target.OpenAIModelID
		}
		if curModel, _ := payload["model"].(string); curModel != desiredModel {
			payload["model"] = desiredModel
			modified = true
		}
	}

	explicitLevel := strings.ToUpper(strings.TrimSpace(target.ThinkingLevel))
	if explicitLevel != "" {
		if _, exists := payload["reasoning_effort"]; !exists {
			switch explicitLevel {
			case "MINIMAL", "LOW":
				payload["reasoning_effort"] = "low"
				modified = true
			case "MEDIUM":
				payload["reasoning_effort"] = "medium"
				modified = true
			case "HIGH":
				payload["reasoning_effort"] = "high"
				modified = true
			}
		}
	}

	if modified {
		if updated, err := json.Marshal(payload); err == nil {
			return updated
		}
	}
	return body
}
