#!/usr/bin/env python3
"""
==============================================================================
FILE HEADER: env.py — Platform paths and gateway settings for the harness
==============================================================================
Purpose:
    Resolves the per-OS locations the Antigravity clients read (MDM
    admin_settings.json, per-user ~/.gemini files) and loads the Enterprise
    Gateway URL and API key that every test round points the clients at.

Architecture / Context:
    Imported by files.py, runner.py and the surface drivers of the
    agy-config/verification harness. Runs on the test VM (Linux or Windows),
    never on the operator workstation.

Dependencies / Side Effects:
    Python 3.10+ standard library. Reads the operator-provisioned secrets:
      Linux:   /etc/agy-verify/gateway.env + /etc/agy-verify/gateway_api_key
      Windows: C:\\ProgramData\\agy-verify\\secrets\\gateway.env + gateway_api_key
    Environment variables AGYV_GATEWAY_URL / AGYV_GATEWAY_API_KEY_FILE override them.
==============================================================================
"""

from __future__ import annotations

import logging
import os
import platform
from dataclasses import dataclass
from pathlib import Path

LOG = logging.getLogger("agyv.env")

IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    SECRETS_DIR = Path(r"C:\ProgramData\agy-verify\secrets")
    ADMIN_SETTINGS = Path(r"C:\ProgramData\Antigravity\admin_settings.json")
    WORK_ROOT = Path(r"C:\agyv")
else:
    SECRETS_DIR = Path("/etc/agy-verify")
    ADMIN_SETTINGS = Path("/etc/antigravity/admin_settings.json")
    WORK_ROOT = Path("/var/tmp/agyv")

# The non-root OS user that every Linux surface runs as (created by bootstrap).
TEST_USER = os.environ.get("AGYV_TEST_USER", "agyt")


@dataclass(frozen=True)
class GatewayConfig:
    """Enterprise Gateway connection details used to build admin_settings.json.

    Attributes:
        url (str): HTTPS base URL of the gateway.
        api_key (str): Gateway API key (never logged).
        models (tuple[str, ...]): Model IDs the test admin_settings.json allows.
        default_model (str): Default model ID.
    """

    url: str
    api_key: str
    models: tuple[str, ...] = ("gemini-3.8-flash", "gemini-3.7-flash")
    default_model: str = "gemini-3.8-flash"


def _read_env_file(path: Path) -> dict[str, str]:
    """Parse a KEY=VALUE env file, ignoring blanks and comments.

    Parameters:
        path (Path): File to parse.
    Return Value:
        dict[str, str]: Parsed values (empty if the file is missing).
    Exceptions/Errors:
        OSError: If the file exists but can't be read.
    """
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"')
    return values


def load_gateway() -> GatewayConfig:
    """Load the gateway URL and API key provisioned on the test VM.

    Return Value:
        GatewayConfig: Validated gateway settings.
    Exceptions/Errors:
        RuntimeError: If the URL isn't HTTPS or the key is missing/empty.
    """
    env_file = _read_env_file(SECRETS_DIR / "gateway.env")
    url = os.environ.get("AGYV_GATEWAY_URL") or env_file.get("GATEWAY_URL", "")
    key_file = Path(os.environ.get("AGYV_GATEWAY_API_KEY_FILE", SECRETS_DIR / "gateway_api_key"))
    if not url.startswith("https://"):
        raise RuntimeError(f"gateway URL must be https:// (got {url!r}); set GATEWAY_URL in {SECRETS_DIR}")
    if not key_file.exists():
        raise RuntimeError(f"gateway API key file not found: {key_file}")
    api_key = key_file.read_text(encoding="utf-8").strip()
    if not api_key:
        raise RuntimeError(f"gateway API key file is empty: {key_file}")
    return GatewayConfig(url=url.rstrip("/"), api_key=api_key)


def redact(text: str, gateway: GatewayConfig) -> str:
    """Remove the gateway API key (and URL host) from evidence text.

    Parameters:
        text (str): Text that may contain secrets.
        gateway (GatewayConfig): Values to scrub.
    Return Value:
        str: Text with the key replaced by <REDACTED_GATEWAY_KEY> and the URL by <GATEWAY_URL>.
    Exceptions/Errors:
        None.
    """
    return text.replace(gateway.api_key, "<REDACTED_GATEWAY_KEY>").replace(gateway.url, "<GATEWAY_URL>")
