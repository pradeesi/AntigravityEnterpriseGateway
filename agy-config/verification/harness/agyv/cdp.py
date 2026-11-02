#!/usr/bin/env python3
"""
==============================================================================
FILE HEADER: cdp.py — Minimal synchronous Chrome DevTools Protocol client
==============================================================================
Purpose:
    Small CDP helper used to drive the Electron/Chromium front ends of the
    Antigravity App, the `agy --hub` web UI (in Chrome), and the VS Code
    extension webview: list targets, evaluate JavaScript (including inside
    the extension's nested #active-frame iframe), type text, press keys,
    click, and capture screenshots.

Architecture / Context:
    Imported by surfaces/hub.py and tools/explore_ui.py. Uses the HTTP
    /json endpoint for target discovery and one WebSocket per target. Under
    Xvfb, X11 screen capture of Electron is black, so screenshots go through
    Page.captureScreenshot.

Dependencies / Side Effects:
    websocket-client (installed in /opt/agy-verify/venv); Python 3.10+.
    Opens local TCP connections to 127.0.0.1:<port> only.
==============================================================================
"""

from __future__ import annotations

import base64
import json
import logging
import time
import urllib.request
from typing import Any, Optional

import websocket  # websocket-client

LOG = logging.getLogger("agyv.cdp")

# Returns the document that holds the Antigravity UI: the nested #active-frame
# document inside a VS Code webview, or the page document elsewhere.
UI_DOC_JS = ("(() => { const af = document.getElementById('active-frame'); "
             "return (af && af.contentDocument) ? af.contentDocument : document; })()")


def list_targets(port: int) -> list[dict[str, Any]]:
    """Return CDP targets from http://127.0.0.1:<port>/json (empty list if unreachable).

    Parameters:
        port (int): Remote debugging port.
    Return Value:
        list[dict]: Target descriptors.
    Exceptions/Errors:
        None.
    """
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError):
        return []


def wait_for_targets(port: int, timeout_s: float = 90) -> list[dict[str, Any]]:
    """Poll until at least one page/webview target exists.

    Parameters:
        port (int): Remote debugging port.
        timeout_s (float): How long to wait.
    Return Value:
        list[dict]: Targets (possibly empty on timeout).
    Exceptions/Errors:
        None.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        targets = [t for t in list_targets(port) if t.get("webSocketDebuggerUrl")]
        if targets:
            return targets
        time.sleep(1)
    return []


class Session:
    """One CDP WebSocket session bound to a target.

    Attributes:
        target (dict): Target descriptor.
    """

    def __init__(self, target: dict[str, Any]) -> None:
        """Open a WebSocket session to the given CDP target.

        Parameters:
            target (dict[str, Any]): CDP target descriptor containing `webSocketDebuggerUrl`.
        Return Value:
            None.
        Exceptions/Errors:
            KeyError: Missing `webSocketDebuggerUrl`.
            OSError: WebSocket connection failure.
        """
        self.target = target
        self.ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=30,
                                              suppress_origin=True)
        self._id = 0

    def close(self) -> None:
        """Close the WebSocket."""
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001 — closing a dead socket is fine
            pass

    def call(self, method: str, params: Optional[dict] = None, timeout_s: float = 30) -> dict[str, Any]:
        """Send a CDP command and wait for its response (events are skipped).

        Parameters:
            method (str): CDP method.
            params (Optional[dict]): Parameters.
            timeout_s (float): Response timeout.
        Return Value:
            dict: The "result" object.
        Exceptions/Errors:
            RuntimeError: CDP error response or timeout.
        """
        self._id += 1
        msg_id = self._id
        self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            self.ws.settimeout(max(0.1, deadline - time.time()))
            data = json.loads(self.ws.recv())
            if data.get("id") == msg_id:
                if "error" in data:
                    raise RuntimeError(f"{method}: {data['error']}")
                return data.get("result", {})
        raise RuntimeError(f"{method}: timeout")

    def eval(self, expression: str) -> Any:
        """Evaluate JavaScript in the target and return the JSON value.

        Parameters:
            expression (str): JS expression.
        Return Value:
            Any: Value, or None if undefined/not serializable.
        Exceptions/Errors:
            RuntimeError: Evaluation exceptions are re-raised with their description.
        """
        result = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                                "awaitPromise": True})
        if result.get("exceptionDetails"):
            raise RuntimeError(str(result["exceptionDetails"])[:300])
        return result.get("result", {}).get("value")

    def ui_text(self) -> str:
        """Return the visible text of the Antigravity UI document."""
        return self.eval(f"(() => {{ const d = {UI_DOC_JS}; return d.body ? d.body.innerText : ''; }})()") or ""

    def find(self, text: str = "", selector: str = "", exact: bool = False) -> list[dict[str, Any]]:
        """Find visible elements in the UI document by text/label or CSS selector.

        Parameters:
            text (str): Case-insensitive text or aria-label/title/placeholder substring.
            selector (str): CSS selector (defaults to interactive elements).
            exact (bool): Require an exact (case-insensitive) text/label match.
        Return Value:
            list[dict]: {tag, text, label, x, y, w, h, disabled} in page coordinates.
        Exceptions/Errors:
            RuntimeError: JS evaluation errors.
        """
        opts = json.dumps({"text": text.lower(), "selector": selector, "exact": exact})
        js = f"""
        ((opts) => {{
          const af = document.getElementById('active-frame');
          const doc = (af && af.contentDocument) ? af.contentDocument : document;
          const win = (af && af.contentWindow) ? af.contentWindow : window;
          const off = af ? af.getBoundingClientRect() : {{x: 0, y: 0}};
          const sel = opts.selector || 'button, a, [role="button"], textarea, input, [contenteditable="true"], [aria-label]';
          const out = [];
          for (const e of doc.querySelectorAll(sel)) {{
            const r = e.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) continue;
            const st = win.getComputedStyle(e);
            if (st.visibility === 'hidden' || st.display === 'none') continue;
            const txt = (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim();
            const lbl = (e.getAttribute('aria-label') || e.getAttribute('title') || e.getAttribute('placeholder') || e.getAttribute('data-placeholder') || '').trim();
            const t = txt.toLowerCase(), l = lbl.toLowerCase();
            if (opts.text) {{
              const hit = opts.exact ? (t === opts.text || l === opts.text) : (t.includes(opts.text) || l.includes(opts.text));
              if (!hit) continue;
            }}
            out.push({{tag: e.tagName.toLowerCase(), text: txt.slice(0, 120), label: lbl.slice(0, 120),
                       x: Math.round(off.x + r.x + r.width / 2), y: Math.round(off.y + r.y + r.height / 2),
                       w: Math.round(r.width), h: Math.round(r.height),
                       disabled: !!(e.disabled || e.getAttribute('aria-disabled') === 'true')}});
          }}
          return out;
        }})({opts})"""
        return self.eval(js) or []

    def click(self, x: float, y: float) -> None:
        """Dispatch a left click at page coordinates."""
        for kind in ("mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left",
                                                   "clickCount": 1})

    def insert_text(self, text: str) -> None:
        """Insert text at the current focus (IME-style, works for contenteditable)."""
        self.call("Input.insertText", {"text": text})

    def key(self, key: str, code: str, key_code: int, modifiers: int = 0) -> None:
        """Press and release one key.

        Parameters:
            key (str): DOM key value (e.g. "Enter").
            code (str): DOM code (e.g. "Enter").
            key_code (int): Windows virtual key code (Enter=13).
            modifiers (int): CDP modifier bitmask.
        Return Value:
            None.
        Exceptions/Errors:
            RuntimeError: CDP errors.
        """
        base = {"key": key, "code": code, "windowsVirtualKeyCode": key_code, "modifiers": modifiers}
        self.call("Input.dispatchKeyEvent", {"type": "rawKeyDown", **base})
        if key == "Enter":
            self.call("Input.dispatchKeyEvent", {"type": "char", "text": "\r", **base})
        self.call("Input.dispatchKeyEvent", {"type": "keyUp", **base})

    def screenshot(self, path: str) -> None:
        """Save a PNG of the target's viewport."""
        data = self.call("Page.captureScreenshot", {"format": "png"}).get("data", "")
        with open(path, "wb") as handle:
            handle.write(base64.b64decode(data))
