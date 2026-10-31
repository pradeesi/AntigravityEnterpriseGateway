# ==============================================================================
# FILE HEADER: Python Container Build Definition — Antigravity Enterprise Gateway
# ==============================================================================
# Author: Pradeep Singh
# License: Apache-2.0
#
# Purpose:
#   Packages the FastAPI + httpx + google-auth reverse proxy into a hardened,
#   non-root `python:3.12-slim` container image.
#
# Architecture / Context:
#   Used by `./install.sh --runtime=python` (Cloud Run `--source=./python`) or
#   standalone `docker build` for GKE / on-prem deployments.
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
# BLOCK 2: Hardened Non-Root Python 3.12 Runtime Image
# ------------------------------------------------------------------------------
FROM python:3.12-slim

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

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PROJECT_ID="${PROJECT_ID}" \
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

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -r gateway && useradd -r -g gateway gateway

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py routing_and_armor.py ./
RUN chown -R gateway:gateway /app

USER gateway
EXPOSE 8080

CMD ["python", "main.py"]
