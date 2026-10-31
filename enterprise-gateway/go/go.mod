// ==============================================================================
// FILE HEADER: Go Module Definition — Antigravity Enterprise Gateway
// ==============================================================================
// Purpose:
//   Defines the Go 1.24 module and Google OAuth2 / ADC dependencies.
// Architecture / Context:
//   Consumed by `go build` locally and in `go/Dockerfile` during Cloud Run builds.
// Dependencies / Side Effects:
//   Locks `golang.org/x/oauth2` v0.28.0 for thread-safe IAM token caching.
// ==============================================================================
module antigravity-gateway

go 1.24

require golang.org/x/oauth2 v0.28.0

require (
	cloud.google.com/go/compute/metadata v0.6.0 // indirect
	golang.org/x/sys v0.28.0 // indirect
)
