#!/usr/bin/env python3
"""
==============================================================================
FILE HEADER: capture_gateway_request.py — Record what a surface sends to the gateway
==============================================================================
Purpose:
    Starts a local mock Enterprise Gateway, points the machine-wide
    admin_settings.json at it for one CLI print-mode run, and saves every
    request body the client sends. Used to explain gateway-side behavior such
    as Model Armor screening the full turn text when the <USER_REQUEST>
    wrapper is missing or differs between operating systems / surfaces.

Architecture / Context:
    Standalone diagnostic in the verification harness (not part of the matrix).
    The mock answers generateContent / streamGenerateContent with a fixed
    "DONE" model turn and acknowledges telemetry (`POST /v1beta:*`) with `{}`,
    as the public gateway docs require of a real gateway.

Dependencies / Side Effects:
    Python 3.10+ standard library and the harness package (agyv). Must run as
    root (Linux) or an administrator (Windows): it temporarily replaces the MDM
    admin_settings.json and restores the original copy when it finishes, even
    on errors. Writes captured bodies to --out (default <WORK_ROOT>/captures).
    Never use it on a machine where other Antigravity sessions are running.
==============================================================================
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agyv.env import ADMIN_SETTINGS, IS_WINDOWS, TEST_USER, WORK_ROOT  # noqa: E402
from agyv.surfaces.cli import AGY_BIN, as_user, user_env  # noqa: E402

LOG = logging.getLogger("agyv.capture")

# A dummy credential for the mock only; the real gateway key is never used here.
MOCK_API_KEY = "capture-mock-key"
SSE_REPLY = {"candidates": [{"content": {"role": "model", "parts": [{"text": "DONE"}]},
                             "finishReason": "STOP", "index": 0}],
             "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2}}


class _CaptureHandler(BaseHTTPRequestHandler):
    """HTTP handler that stores each request and returns a minimal valid reply."""

    out_dir: Path = Path(".")
    counter = 0
    lock = threading.Lock()

    def log_message(self, fmt: str, *args) -> None:  # noqa: D401 — silence default stderr logging
        """Route http.server logging through the module logger at DEBUG level."""
        LOG.debug("mock: " + fmt, *args)

    def _save(self, body: bytes) -> None:
        """Persist one request (path, selected headers, body) as JSON.

        Parameters:
            body (bytes): Raw request body.
        Return Value:
            None.
        Exceptions/Errors:
            OSError: If the capture file can't be written.
        """
        with self.lock:
            type(self).counter += 1
            index = type(self).counter
        try:
            parsed = json.loads(body.decode("utf-8")) if body else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = body.decode("utf-8", "replace")
        record = {"index": index, "method": self.command, "path": self.path,
                  "user_agent": self.headers.get("User-Agent", ""),
                  "x_goog_api_client": self.headers.get("X-Goog-Api-Client", ""),
                  "body": parsed}
        (self.out_dir / f"request_{index:03d}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")

    def do_GET(self) -> None:  # noqa: N802 — http.server naming
        """Answer GETs (health/model probes) with an empty JSON object."""
        self._save(b"")
        self._reply_json({})

    def do_POST(self) -> None:  # noqa: N802 — http.server naming
        """Store the body; reply with SSE / JSON for model calls, `{}` for telemetry."""
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length > 0 else b""
        self._save(body)
        if ":streamGenerateContent" in self.path:
            payload = f"data: {json.dumps(SSE_REPLY)}\r\n\r\n".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        elif ":generateContent" in self.path:
            self._reply_json(SSE_REPLY)
        else:
            self._reply_json({})

    def _reply_json(self, obj: dict) -> None:
        """Send `obj` as a 200 JSON response."""
        payload = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _mock_admin_settings(port: int) -> str:
    """Build a gateway-mode admin_settings.json that targets the local mock.

    Parameters:
        port (int): Mock listening port.
    Return Value:
        str: JSON document.
    Exceptions/Errors:
        None.
    """
    return json.dumps({"gateway": {"enabled": True, "url": f"http://127.0.0.1:{port}",
                                   "apiKey": MOCK_API_KEY, "wireProtocol": "genai"},
                       "models": {"defaultModelId": "gemini-3.8-flash",
                                  "list": [{"modelId": "gemini-3.8-flash"}]}}, indent=2)


def capture(prompt: str, port: int, out_dir: Path, timeout_s: int) -> int:
    """Run one CLI print-mode prompt against the mock and save every request.

    Parameters:
        prompt (str): Prompt to send (exactly as a matrix probe would).
        port (int): Local port for the mock (1024-65535).
        out_dir (Path): Folder for request_NNN.json files and the CLI output.
        timeout_s (int): CLI timeout in seconds.
    Return Value:
        int: Number of requests captured.
    Exceptions/Errors:
        ValueError: Invalid port or empty prompt.
        OSError: admin_settings.json can't be backed up or restored.
    """
    if not prompt.strip():
        raise ValueError("prompt must not be empty")
    if not 1024 <= port <= 65535:
        raise ValueError("port must be between 1024 and 65535")
    out_dir.mkdir(parents=True, exist_ok=True)
    _CaptureHandler.out_dir = out_dir
    server = ThreadingHTTPServer(("127.0.0.1", port), _CaptureHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    backup = ADMIN_SETTINGS.with_name(ADMIN_SETTINGS.name + ".capture-backup")
    had_original = ADMIN_SETTINGS.exists()
    if had_original:
        shutil.copy2(ADMIN_SETTINGS, backup)
    home = Path(tempfile.mkdtemp(prefix="agyv-capture-", dir=str(WORK_ROOT) if WORK_ROOT.exists() else None))
    try:
        ADMIN_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        ADMIN_SETTINGS.write_text(_mock_admin_settings(port), encoding="utf-8")
        workspace = home / "ws"
        workspace.mkdir(parents=True)
        if not IS_WINDOWS:
            shutil.chown(home, user=TEST_USER, group=TEST_USER)
            shutil.chown(workspace, user=TEST_USER, group=TEST_USER)
        env = user_env(home)
        cmd = as_user([AGY_BIN, "-p", prompt, "--output-format", "stream-json"], env)
        LOG.info("running the CLI against the mock on port %d", port)
        proc = subprocess.run(cmd, cwd=workspace, env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout_s, check=False)
        (out_dir / "cli_stdout.jsonl").write_text(proc.stdout, encoding="utf-8")
        (out_dir / "cli_stderr.txt").write_text(proc.stderr, encoding="utf-8")
        time.sleep(1)  # let late telemetry posts land before shutdown
    finally:
        # Restore the real MDM file first: a failed restore would leave clients on the mock.
        if had_original:
            shutil.copy2(backup, ADMIN_SETTINGS)
            backup.unlink(missing_ok=True)
        else:
            ADMIN_SETTINGS.unlink(missing_ok=True)
        server.shutdown()
        shutil.rmtree(home, ignore_errors=True)
    return _CaptureHandler.counter


def main(argv: list[str]) -> int:
    """CLI entry point.

    Parameters:
        argv (list[str]): Command-line arguments (without the program name).
    Return Value:
        int: 0 when at least one request was captured, 1 otherwise.
    Exceptions/Errors:
        None (errors are logged).
    """
    parser = argparse.ArgumentParser(description=__doc__.split("Purpose:")[0])
    parser.add_argument("--prompt", required=True, help="prompt to send")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--out", type=Path, default=WORK_ROOT / "captures" / time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        count = capture(args.prompt, args.port, args.out, args.timeout)
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        LOG.error("capture failed: %s", exc)
        return 1
    LOG.info("captured %d request(s) in %s", count, args.out)
    return 0 if count else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
