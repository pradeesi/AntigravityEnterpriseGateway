# Google Cloud Model Armor & Cloud SDP (DLP) Module

This module provisions, verifies, and tears down **Layer 1** of the Antigravity Enterprise Gateway security posture: regional **Google Cloud Sensitive Data Protection (SDP / DLP)** Inspect & De-identify templates linked to a **Google Cloud Model Armor** template.

When you run [`../install.sh`](../install.sh) or [`../uninstall.sh`](../uninstall.sh) from the parent directory with `ENABLE_MODEL_ARMOR="true"` in [`../settings.env`](../settings.env), those scripts automatically invoke [`model_armor_manager.sh`](./model_armor_manager.sh). You can also run `model_armor_manager.sh` standalone at any time.

---

## Directory Layout

```text
model-armor-sdp/
├── README.md                          # Module documentation & threat coverage matrix
├── model_armor_manager.sh             # Block-structured CLI (`provision`, `verify`, `deprovision`)
└── templates/
    ├── sdp_inspect_template.json      # 25 built-in PCI/Credential/PII InfoTypes + 14 CUSTOM_SEC_* regexes
    ├── sdp_deidentify_template.json   # Replaces matched spans with [INFOTYPE] tags
    └── model_armor_filters.json       # RAI filter thresholds (DANGEROUS: MEDIUM_AND_ABOVE, etc.)
```

---

## Security Coverage Matrix

| Filter / Detector Category | Template Source | Runtime Gateway Action (`inline` Mode) |
| :--- | :--- | :--- |
| **Prompt Injection & Jailbreak** (`piAndJailbreakFilterSettings`) | Model Armor ML Classifier (`HIGH` confidence — tuned for AI coding IDEs) | Conversational HTTP 200 Security Block |
| **Malicious URIs** (`maliciousUriFilterSettings`) | Model Armor URI Classifier | Conversational HTTP 200 Security Block |
| **Responsible AI** (`DANGEROUS`, `HATE_SPEECH`, `HARASSMENT`, `SEXUALLY_EXPLICIT`) | `templates/model_armor_filters.json` | Conversational HTTP 200 Security Block |
| **14 Custom Cyber-Security & Data Governance Domains (`CUSTOM_SEC_*`)**:<br>1. `CUSTOM_SEC_NETWORK_RECON_AND_SCANNING`<br>2. `CUSTOM_SEC_VULNERABILITY_PENTEST_AND_EXPLOIT`<br>3. `CUSTOM_SEC_PRIVILEGE_ESCALATION_AND_AUTH_BYPASS`<br>4. `CUSTOM_SEC_DOS_DDOS_AND_TRAFFIC_FLOOD`<br>5. `CUSTOM_SEC_DEFENSE_EVASION_AND_MALWARE`<br>6. `CUSTOM_SEC_RANSOMWARE_WIPER_AND_DATA_SABOTAGE`<br>7. `CUSTOM_SEC_PHISHING_SPOOFING_AND_EXFILTRATION`<br>8. `CUSTOM_SEC_WEBSITE_CLONING_AND_SCRAPING`<br>9. `CUSTOM_SEC_EMAIL_AND_IDENTITY_IMPERSONATION`<br>10. `CUSTOM_SEC_CLEARTEXT_EXPOSURE_AND_DLP_BYPASS`<br>11. `CUSTOM_SEC_SENSITIVE_DATA_AND_SECRET_FILE_READ`<br>12. `CUSTOM_SEC_PERSONAL_FILE_DISCOVERY_AND_SCAN`<br>13. `CUSTOM_SEC_UNAUTHORIZED_FILE_ENCRYPTION`<br>14. `CUSTOM_SEC_UNAUTHORIZED_FILE_DELETION` | `templates/sdp_inspect_template.json` | Conversational HTTP 200 Security Block (`[CUSTOM_*]` / `CUSTOM_*` InfoType detection) + Multi-Turn History Scrubbing |
| **25 Built-In PCI, Financial, Credential & PII InfoTypes** (`CREDIT_CARD_NUMBER`, `IBAN_CODE`, `AWS_CREDENTIALS`, `GCP_API_KEY`, `JSON_WEB_TOKEN`, `PASSWORD`, `SSL_CERTIFICATE`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `PASSPORT`, etc.) | `templates/sdp_inspect_template.json` + `sdp_deidentify_template.json` | In-place redaction (`[CREDIT_CARD_NUMBER]`, `[PASSWORD]`, etc.) before forwarding to Vertex AI |

---

## Standalone Usage

```bash
# 1. Interactive provisioning (lists accessible GCP projects and runs 9 live verification tests)
./model_armor_manager.sh provision

# 2. Non-interactive provisioning for a specific project/region
./model_armor_manager.sh provision --project=YOUR_PROJECT_ID --region=europe-west1

# 3. Run the 9 live :sanitizeUserPrompt verification tests standalone
./model_armor_manager.sh verify --project=YOUR_PROJECT_ID --region=europe-west1

# 4. Dependency-ordered teardown (Model Armor -> SDP De-identify -> SDP Inspect)
./model_armor_manager.sh deprovision --project=YOUR_PROJECT_ID --region=europe-west1 --yes
```
