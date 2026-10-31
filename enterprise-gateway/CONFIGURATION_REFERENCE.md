# Unified Configuration Reference — Antigravity Enterprise Gateway

This document describes every configuration setting in [`settings.env`](./settings.env), secret override in [`.env.example`](./.env.example), and client-side MDM setting in [`admin_settings.json`](./admin_settings.json).

---

## 1. Configuration Precedence Model (Server & Installer)

All scripts (`install.sh`, `uninstall.sh`, `model-armor-sdp/model_armor_manager.sh`) and both Gateway runtimes (`python/` and `go/`) resolve configuration using the exact same priority order (highest to lowest):

1. **CLI Flags / OS Environment Variables** (e.g., `./install.sh --runtime=go --region=europe-west4`, Cloud Run `--set-env-vars`, or GKE `ConfigMap`/`Secret`)
2. **Local `.env` File** (git-ignored; used for local secret overrides such as `GATEWAY_API_KEY`)
3. **Unified `settings.env` File** (tracked in version control; provides default values for every setting and can be edited in-file or overridden interactively during `./install.sh`)
4. **In-Code Fallback Constants** (`BLOCK 1` of `main.py` / `main.go` and `routing_and_armor.py` / `routing_and_armor.go`)

---

## 2. Unified `settings.env` & `.env` Variables

| Block | Key | Type | Default (`settings.env`) | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **Block 1: Core & Runtime** | `PROJECT_ID` | `string` | `""` *(interactive selector)* | Target GCP Project ID with `aiplatform.googleapis.com` enabled. Leave blank to pick interactively from `gcloud projects list`. |
| **Block 1: Core & Runtime** | `GATEWAY_RUNTIME` | `string` | `"python"` | Selects which Gateway implementation `./install.sh` deploys to Cloud Run (`python` or `go`). |
| **Block 1: Core & Runtime** | `REGION` | `string` | `"europe-west1"` | Default Cloud Run deployment region and regional Model Armor / Cloud SDP location. |
| **Block 1: Core & Runtime** | `PORT` | `integer` | `"8080"` | TCP listener port inside the container or local host. |
| **Block 1: Core & Runtime** | `LOG_LEVEL` | `string` | `"INFO"` | Structured JSON stdout logging level (`INFO` or `DEBUG`). |
| **Block 1: Core & Runtime** | `LOG_TELEMETRY_PAYLOADS` | `boolean` | `"false"` | When `"true"`, parses and logs full JSON payloads sent to `/v1internal:*` and `/v1beta:*` (`event_type: "antigravity_client_telemetry"`) to stdout for SIEM / BigQuery / Splunk log sinks before returning `200 OK` (`{}`). |
| **Block 1: Core & Runtime** | `SKIP_ADC_INIT` | `boolean` | `"false"` | Set to `"true"` **only** for offline local contract testing without GCP credentials. |
| **Secret (`.env` / GSM)** | `GATEWAY_API_KEY` | `string` | Auto-generated in Secret Manager | Shared bearer token(s) sent by Antigravity clients in `Authorization: Bearer <GATEWAY_API_KEY>`. Supports a single key or comma-separated keys (`key1,key2`) for zero-downtime key rotation or per-team tokens, validated in constant time (`hmac.compare_digest` / `subtle.ConstantTimeCompare`). |
| **Block 2: Cloud Run** | `SERVICE_NAME` | `string` | `"antigravity-gateway"` | Cloud Run service name. |
| **Block 2: Cloud Run** | `SA_NAME` | `string` | `"agy-gateway-sa"` | GCP Service Account short name (`<SA_NAME>@<PROJECT_ID>.iam.gserviceaccount.com`). |
| **Block 2: Cloud Run** | `SECRET_NAME` | `string` | `"agy-gateway-api-key"` | Google Secret Manager secret storing `GATEWAY_API_KEY`. |
| **Block 2: Cloud Run** | `CLOUD_RUN_INGRESS` | `string` | `"all"` | Cloud Run network ingress perimeter (`"all"`, `"internal"`, or `"internal-and-cloud-load-balancing"`). Combine `"internal"` with `--no-invoker-iam-check` for private VPC-only access without breaking `Authorization: Bearer <GATEWAY_API_KEY>`. |
| **Block 2: Cloud Run** | `CLOUD_RUN_CPU` | `string` | `"1"` | vCPU allocation per Cloud Run container instance. |
| **Block 2: Cloud Run** | `CLOUD_RUN_MEMORY` | `string` | `"512Mi"` | Memory limit per Cloud Run container instance. |
| **Block 2: Cloud Run** | `CLOUD_RUN_MIN_INSTANCES` | `integer` | `"1"` | Warm minimum instances to eliminate cold-start latency on interactive coding prompts. |
| **Block 2: Cloud Run** | `CLOUD_RUN_MAX_INSTANCES` | `integer` | `"10"` | Maximum autoscaling instances. |
| **Block 2: Cloud Run** | `CLOUD_RUN_TIMEOUT` | `integer` | `"3600"` | Request timeout in seconds (`3600` = 60 minutes) required for long-running unbuffered SSE streams. |
| **Block 3: Model Armor & SDP** | `ENABLE_MODEL_ARMOR` | `boolean` | `"true"` | Master toggle to provision and enforce Google Cloud Model Armor + Cloud SDP templates. |
| **Block 3: Model Armor & SDP** | `MODEL_ARMOR_MODE` | `string` | `"inline"` | `"inline"` (pre-flight `:sanitizeUserPrompt` with conversational HTTP 200 blocks & PII redaction across both GenAI `contents[]` and OpenAI `messages[]`), `"native"` (injects `modelArmorConfig` into Vertex AI GenAI payload), or `"disabled"`. |
| **Block 3: Model Armor & SDP** | `MODEL_ARMOR_FAIL_CLOSED` | `boolean` | `"true"` | Rejects requests with HTTP `502` if the Model Armor API is unreachable in `"inline"` mode. |
| **Block 3: Model Armor & SDP** | `SDP_INSPECT_TEMPLATE_ID` | `string` | `"agy-pci-creds-pii-inspect"` | Regional Cloud SDP Inspect template ID (`model-armor-sdp/templates/sdp_inspect_template.json`). |
| **Block 3: Model Armor & SDP** | `SDP_DEID_TEMPLATE_ID` | `string` | `"agy-pci-creds-pii-deid"` | Regional Cloud SDP De-identify template ID (`model-armor-sdp/templates/sdp_deidentify_template.json`). |
| **Block 3: Model Armor & SDP** | `MODEL_ARMOR_TEMPLATE_ID` | `string` | `"agy-enterprise-armor"` | Regional Google Cloud Model Armor template ID. |
| **Block 3: Model Armor & SDP** | `RUN_VERIFICATION_TESTS` | `boolean` | `"true"` | Executes the 5 live `:sanitizeUserPrompt` assertions during installation. |
| **Block 4: Dynamic Routing** | `COST_CENTER_PROJECT_MAP` | `string` | `""` | Comma-separated `X-Cost-Center=PROJECT_ID` map for per-BU billing/quota isolation (injects `X-Goog-User-Project`). |
| **Block 4: Dynamic Routing** | `MODEL_REGION_MAP` | `string` | `""` | Comma-separated `MODEL_ID=REGION` override map (`gemini-4-*` and `gemini-3.*` default to `global`). |
| **Block 4: Dynamic Routing** | `FAILOVER_REGIONS` | `string` | `""` | Comma-separated secondary regions retried automatically when primary region returns HTTP `429` or `503`. |
| **Block 4: Dynamic Routing** | `DEFAULT_FLASH_FALLBACK_MODEL` | `string` | `"gemini-3.8-flash"` | Flash model automatically substituted if an unpatched client omits a Flash tier and emits `MODEL_PLACEHOLDER_M50` / `MODEL_PLACEHOLDER_*`. |
| **Block 4: Dynamic Routing** | `OPENAI_UPSTREAM_BASE_URL` | `string` | `""` *(Vertex OpenAI)* | Optional custom OpenAI-compatible upstream base URL for `POST /v1/chat/completions` (e.g., LiteLLM / Portkey). When blank, routes to Vertex AI's OpenAI Chat Completions endpoint (`/v1beta1/projects/{PROJECT}/locations/{REGION}/endpoints/openapi/chat/completions`) with `"model": "google/{MODEL_ID}"`. |
| **Block 5: Uninstall** | `DELETE_CLOUD_RUN_SERVICE` | `boolean` | `"true"` | Whether `./uninstall.sh` removes the Cloud Run service by default. |
| **Block 5: Uninstall** | `DELETE_MODEL_ARMOR_SDP` | `boolean` | `"true"` | Whether `./uninstall.sh` removes the Model Armor & SDP templates by default. |
| **Block 5: Uninstall** | `DELETE_SECRET` | `boolean` | `"false"` | Whether `./uninstall.sh` deletes the Secret Manager key (`--delete-secret` overrides to `true`). |
| **Block 5: Uninstall** | `DELETE_SERVICE_ACCOUNT` | `boolean` | `"false"` | Whether `./uninstall.sh` deletes the Service Account (`--delete-sa` overrides to `true`). |

---

## 3. Antigravity Client 3-Tier Configuration Precedence (`MDM > Env Vars > User Settings`)

Antigravity clients (`2.15.0+` Desktop App, `agy 1.2.15+` CLI, VS Code, and `1.3.0+` JetBrains/Zed ACP) merge Gateway settings field-by-field in three tiers:

1. **Tier 1 — MDM Managed File (`admin_settings.json`, Highest Precedence)**:
   - **Linux**: `/etc/antigravity/admin_settings.json`
   - **macOS**: `/Library/Application Support/Antigravity/admin_settings.json`
   - **Windows**: `%ProgramData%\Antigravity\admin_settings.json`
   - *Tip*: `./install.sh` automatically generates a git-ignored `admin_settings.local.json` (`chmod 600`) pre-populated with your live Cloud Run `url` and `apiKey`.
2. **Tier 2 — Environment Variables (`AGY_LLM_GATEWAY_*`)**:
   - `AGY_LLM_GATEWAY_URL`, `AGY_LLM_GATEWAY_API_KEY`, `AGY_LLM_GATEWAY_WIRE_PROTOCOL` (`genai` or `openai`), `AGY_LLM_GATEWAY_CA_CERT`, `AGY_LLM_GATEWAY_HEADERS`, `AGY_LLM_GATEWAY_MODELS`.
3. **Tier 3 — User Settings (`~/.antigravity/settings.json`, Lowest Precedence)**:
   - Uses the same JSON schema as `admin_settings.json` (not read by the ACP server; pin attribution headers in Tier 1 `admin_settings.json`).

---

## 4. Wire Protocols & Client Telemetry Schemas (`LOG_TELEMETRY_PAYLOADS`)

### A. Supported Inference Wire Protocols

| Wire Protocol | Client Request Path | Upstream Backend Target | Notes |
| :--- | :--- | :--- | :--- |
| **`genai` (Default, Recommended)** | `POST /v1beta/models/{MODEL_ID}:streamGenerateContent?alt=sse` *(or `:generateContent` / `/v1beta1/projects/...`)* | `https://{REGION}-aiplatform.googleapis.com/v1beta1/projects/{PROJECT_ID}/locations/{REGION}/publishers/google/models/{MODEL_ID}:{ACTION}` *(or `aiplatform.googleapis.com` when `REGION=global`)* | Preserves native Gemini thinking, grounding, and function-calling fidelity. Required for JetBrains & Zed ACP. |
| **`openai`** | `POST /v1/chat/completions` | Default: `https://{REGION}-aiplatform.googleapis.com/v1beta1/projects/{PROJECT_ID}/locations/{REGION}/endpoints/openapi/chat/completions` *(rewrites `"model"` to `"google/{MODEL_ID}"`)*; or `OPENAI_UPSTREAM_BASE_URL` if configured | Supported by Antigravity Desktop App, `agy` CLI, and VS Code when `gateway.wireProtocol: "openai"`. Screened inline by Model Armor (`messages[]`). |

### B. Client Telemetry Endpoints (`/v1beta:*` & `/v1internal:*`)

Antigravity clients emit background productivity and UI interaction telemetry to endpoints that do **not** exist on `aiplatform.googleapis.com`. Both Python and Go gateways intercept `/v1beta:*` and `/v1internal:*`, return `HTTP 200 OK` (`{}`), and — when `LOG_TELEMETRY_PAYLOADS="true"` — emit structured JSON events (`event_type: "antigravity_client_telemetry"`) to stdout so Cloud Logging sinks can export them to **BigQuery, Splunk, or Datadog**:

1. **`POST /v1beta:recordCodeAssistMetrics` & `POST /v1internal:recordCodeAssistMetrics`** *(Productivity, latency & acceptance metrics)*:
   ```json
   {
     "project": "projects/my-gcp-project",
     "requestId": "req-uuid-98765",
     "metadata": {
       "ideType": "ANTIGRAVITY",
       "ideVersion": "2.15.0",
       "pluginVersion": "2.15.0"
     },
     "metrics": [
       {
         "timestamp": "2026-10-30T14:22:10.123Z",
         "actionLatencyMs": 450,
         "charactersAccepted": 142,
         "linesGenerated": 8,
         "modelId": "gemini-3.8-flash",
         "featureType": "AGENT_STEP_EXECUTION"
       }
     ]
   }
   ```
2. **`POST /v1internal:registerInteraction` & `POST /v1internal:recordInteraction`** *(Developer feature engagement & NUX state)*:
   ```json
   {
     "interaction": 2,
     "featureName": "AGENT_DIFF_REVIEW",
     "timestamp": "2026-10-30T14:23:05.000Z",
     "clientMetadata": {
       "os": "darwin",
       "arch": "arm64"
     }
   }
   ```
   - `interaction` enum values: `0` (`NUX_INTERACTION_TYPE_UNSPECIFIED`), `1` (`DISMISSED`), `2` (`ACCEPTED`).

