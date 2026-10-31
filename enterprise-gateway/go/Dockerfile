# ==============================================================================
# FILE HEADER: Go Container Build Definition — Antigravity Enterprise Gateway
# ==============================================================================
# Author: Pradeep Singh
# License: Apache-2.0
#
# Purpose:
#   Multi-stage Dockerfile compiling a static Go 1.24 Linux binary and packaging
#   it into a hardened, non-root Alpine 3.21 runtime image.
#
# Architecture / Context:
#   Used by `./install.sh --runtime=go` (Cloud Run `--source=./go`) or standalone
#   `docker build` for GKE / on-prem deployments.
#
# Dependencies / Side Effects:
#   Exposes TCP port 8080; runtime configuration is injected via Cloud Run / GKE
#   environment variables and Secret Manager (`GATEWAY_API_KEY`).
# ==============================================================================

# ------------------------------------------------------------------------------
# BLOCK 1: Build-Time Default Arguments
# ------------------------------------------------------------------------------
ARG PROJECT_ID="REPLACE_WITH_PROJECT_ID"
ARG REGION="europe-west1"
ARG PORT="8080"
ARG LOG_LEVEL="INFO"
ARG ENABLE_MODEL_ARMOR="true"
ARG MODEL_ARMOR_TEMPLATE_ID="agy-enterprise-armor"
ARG MODEL_ARMOR_MODE="inline"
ARG MODEL_ARMOR_FAIL_CLOSED="true"
ARG COST_CENTER_PROJECT_MAP=""
ARG MODEL_REGION_MAP=""
ARG FAILOVER_REGIONS=""

# ------------------------------------------------------------------------------
# BLOCK 2: Stage 1 — Static Go 1.24 Binary Compilation
# ------------------------------------------------------------------------------
FROM golang:1.24-alpine AS builder
WORKDIR /app

COPY go.mod go.sum* ./
RUN go mod download

COPY *.go ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o gateway .

# ------------------------------------------------------------------------------
# BLOCK 3: Stage 2 — Minimal Non-Root Alpine 3.21 Runtime Image
# ------------------------------------------------------------------------------
FROM alpine:3.21

ARG PROJECT_ID
ARG REGION
ARG PORT
ARG LOG_LEVEL
ARG ENABLE_MODEL_ARMOR
ARG MODEL_ARMOR_TEMPLATE_ID
ARG MODEL_ARMOR_MODE
ARG MODEL_ARMOR_FAIL_CLOSED
ARG COST_CENTER_PROJECT_MAP
ARG MODEL_REGION_MAP
ARG FAILOVER_REGIONS

ENV PROJECT_ID="${PROJECT_ID}" \
    REGION="${REGION}" \
    PORT="${PORT}" \
    LOG_LEVEL="${LOG_LEVEL}" \
    ENABLE_MODEL_ARMOR="${ENABLE_MODEL_ARMOR}" \
    MODEL_ARMOR_TEMPLATE_ID="${MODEL_ARMOR_TEMPLATE_ID}" \
    MODEL_ARMOR_MODE="${MODEL_ARMOR_MODE}" \
    MODEL_ARMOR_FAIL_CLOSED="${MODEL_ARMOR_FAIL_CLOSED}" \
    COST_CENTER_PROJECT_MAP="${COST_CENTER_PROJECT_MAP}" \
    MODEL_REGION_MAP="${MODEL_REGION_MAP}" \
    FAILOVER_REGIONS="${FAILOVER_REGIONS}"

RUN apk --no-cache add ca-certificates tzdata && \
    addgroup -S gateway && adduser -S -G gateway gateway

WORKDIR /app
COPY --from=builder /app/gateway /app/gateway
USER gateway

EXPOSE 8080
ENTRYPOINT ["/app/gateway"]
