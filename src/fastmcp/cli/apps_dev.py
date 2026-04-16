"""Dev server for previewing FastMCPApp UIs locally.

Starts the user's MCP server on a configurable port, then starts a lightweight
Starlette dev server that:

  - Serves a Prefab-based tool picker at GET /
  - Proxies /mcp to the user's server (avoids browser CORS restrictions)
  - Serves the AppBridge host page at GET /launch

The host page uses @modelcontextprotocol/ext-apps to connect to the MCP server
and render the selected UI tool inside an iframe.

Startup sequence
----------------
1. Download ext-apps app-bridge.js from npm and patch its bare
   ``@modelcontextprotocol/sdk/…`` imports to use concrete esm.sh URLs.
2. Detect the exact Zod v4 module URL that esm.sh serves for that SDK version
   and build an import-map entry that redirects the broken ``v4.mjs`` (which
   only re-exports ``{z, default}``) to ``v4/classic/index.mjs`` (which
   correctly exports every named Zod v4 function).  Import maps apply to the
   full module graph in the document, including cross-origin esm.sh modules.
3. Serve both the patched JS and the import-map JSON from the dev server.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import os
import re
import signal
import sys
import tarfile
import tempfile
import time
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpcore
import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response, StreamingResponse
from starlette.routing import Route

from fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# MCP message log (captures proxy traffic for the dev UI log panel)
# ---------------------------------------------------------------------------


class _MessageLog:
    """In-memory buffer of MCP JSON-RPC messages flowing through the proxy."""

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []
        self._counter = 0
        self._request_methods: dict[int | str, str] = {}
        self._request_times: dict[int | str, float] = {}

    def log_request(self, body: dict[str, Any]) -> None:
        pass

    def log_response(self, body: dict[str, Any]) -> None:
        # Server-initiated notifications have "method" but no "id"
        pass

    def get_since(self, since_id: int = 0) -> list[dict[str, Any]]:
        pass

    def log_bridge(self, body: dict[str, Any]) -> None:
        pass

    def clear(self) -> None:
        self._entries.clear()
        self._request_methods.clear()
        self._request_times.clear()


def _log_response_bytes(log: _MessageLog, raw: bytes, content_type: str) -> None:
    """Parse accumulated proxy response bytes and log as message entries."""
    pass


_EXT_APPS_VERSION = "1.0.1"
# Pin to the SDK version ext-apps 1.0.1 was compiled against so the client
# and transport modules are API-compatible with the app-bridge internals.
_MCP_SDK_VERSION = "1.25.2"

# ---------------------------------------------------------------------------
# Shared AppBridge host shell
# ---------------------------------------------------------------------------

# Both the picker and the app launcher use the same host-page structure: an
# iframe that hosts a Prefab renderer, wired to the MCP server via AppBridge.
# The only differences are (a) which URL loads in the iframe and (b) what
# oninitialized does.
#
# app-bridge.js is served locally (see _fetch_app_bridge_bundle).
# Client/Transport are loaded from esm.sh.
# The import map (injected as {import_map_tag}) patches the broken esm.sh
# Zod v4 module so all Zod named exports are visible to the SDK at runtime.

_HOST_SHELL = """\
<!doctype html>
<html>
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
{import_map_tag}
  <style>
    html, body {{ margin: 0; padding: 0; width: 100%; height: 100vh; overflow: hidden; }}
    #app-frame {{ width: 100%; height: 100%; border: none; display: none; }}
    #status {{
      display: flex; align-items: center; justify-content: center; height: 100vh;
      font-family: system-ui, sans-serif; color: #666; font-size: 1rem;
    }}
  </style>
</head>
<body>
  <div id="status" style="display:{status_display}">{status_text}</div>
  <iframe id="app-frame" style="display:{frame_display}"></iframe>
  <script type="module">
    import {{ AppBridge, PostMessageTransport }}
      from "/js/app-bridge.js";
    import {{ Client }}
      from "https://esm.sh/@modelcontextprotocol/sdk@{mcp_sdk_version}/client/index.js";
    import {{ StreamableHTTPClientTransport }}
      from "https://esm.sh/@modelcontextprotocol/sdk@{mcp_sdk_version}/client/streamableHttp.js";

    const status = document.getElementById("status");
    const iframe  = document.getElementById("app-frame");

    async function main() {{
      const client = new Client({{ name: "fastmcp-dev", version: "1.0.0" }});
      await client.connect(
        new StreamableHTTPClientTransport(new URL("/mcp", window.location.origin))
      );
      const serverCaps = client.getServerCapabilities();

      // Set iframe src after adding load listener to avoid race condition
      const loaded = new Promise(r => iframe.addEventListener("load", r, {{ once: true }}));
      iframe.src = {iframe_src_json};
      await loaded;

      const transport = new PostMessageTransport(
        iframe.contentWindow,
        iframe.contentWindow,
      );
      const bridge = new AppBridge(
        client,
        {{ name: "fastmcp-dev", version: "1.0.0" }},
        {{
          openLinks: {{}},
          serverTools: serverCaps?.tools,
          serverResources: serverCaps?.resources,
        }},
        {{
          hostContext: {{
            theme: window.matchMedia("(prefers-color-scheme: dark)").matches
              ? "dark" : "light",
            platform: "web",
            containerDimensions: {{ maxHeight: 8000 }},
            displayMode: "inline",
            availableDisplayModes: ["inline", "fullscreen"],
          }},
        }},
      );

      bridge.onmessage = async () => ({{}});
      {on_open_link}
      {on_initialized}

      await bridge.connect(transport);
    }}

    main().catch(err => {{
      console.error(err);
      if (status) {{
        status.style.display = "flex";
        status.textContent = "Error: " + err.message;
      }}
    }});
  </script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Host page HTML
# ---------------------------------------------------------------------------

_HOST_HTML_TEMPLATE = """\
<!doctype html>
<html>
<head>
  <meta charset="UTF-8">
  <title>FastMCP Dev — {tool_name}</title>
{import_map_tag}
  <style>
    html, body {{ margin: 0; padding: 0; width: 100%; height: 100vh; overflow: hidden; }}
    #app-frame {{ width: 100%; height: 100%; border: none; display: none; }}
    #status {{
      display: flex; align-items: center; justify-content: center; height: 100vh;
      font-family: system-ui, sans-serif; color: #666; font-size: 1rem;
    }}
  </style>
</head>
<body>
  <div id="status">Launching {tool_name}…</div>
  <iframe id="app-frame"></iframe>
  <script type="module">
    import {{ AppBridge, PostMessageTransport, getToolUiResourceUri }}
      from "/js/app-bridge.js";
    import {{ Client }}
      from "https://esm.sh/@modelcontextprotocol/sdk@{mcp_sdk_version}/client/index.js";
    import {{ StreamableHTTPClientTransport }}
      from "https://esm.sh/@modelcontextprotocol/sdk@{mcp_sdk_version}/client/streamableHttp.js";

    const toolName = {tool_name_json};
    const toolArgs = {tool_args_json};
    const status = document.getElementById("status");
    const iframe  = document.getElementById("app-frame");

    async function main() {{
      // Connect to the proxied MCP server (same-origin, no CORS needed)
      const client = new Client({{ name: "fastmcp-dev", version: "1.0.0" }});
      await client.connect(
        new StreamableHTTPClientTransport(new URL("/mcp", window.location.origin))
      );

      // Find the tool and its UI resource URI
      const {{ tools }} = await client.listTools();
      const tool = tools.find(t => t.name === toolName);
      if (!tool) throw new Error("Tool not found: " + toolName);

      const uiUri = getToolUiResourceUri(tool);
      if (!uiUri) throw new Error("Tool has no UI resource: " + toolName);

      // The Prefab renderer calls earlyBridge.connect() at module-load time
      // (synchronously, before React mounts) so it sends its ui/initialize
      // request very early — potentially before the iframe's load event fires.
      // Fix: create the AppBridge and call bridge.connect() BEFORE loading the
      // iframe so our window.addEventListener is registered first.  We pass
      // null as the PostMessageTransport source so early messages from the
      // not-yet-known renderer window are not filtered out.  After the iframe
      // loads we update transport.eventTarget / .eventSource to the real
      // renderer window; the load-event microtask always runs before the
      // message macrotask, so the response reaches the correct window.
      const serverCaps = client.getServerCapabilities();
      const transport = new PostMessageTransport(iframe.contentWindow, null);
      const bridge = new AppBridge(
        client,
        {{ name: "fastmcp-dev", version: "1.0.0" }},
        {{
          openLinks: {{}},
          serverTools: serverCaps?.tools,
          serverResources: serverCaps?.resources,
        }},
        {{
          hostContext: {{
            theme: window.matchMedia("(prefers-color-scheme: dark)").matches
              ? "dark" : "light",
            platform: "web",
            containerDimensions: {{ maxHeight: 8000 }},
            displayMode: "inline",
            availableDisplayModes: ["inline", "fullscreen"],
          }},
        }},
      );

      bridge.onopenlink = async ({{ url }}) => {{
        window.open(url, "_blank", "noopener,noreferrer");
        return {{}};
      }};
      bridge.onmessage = async () => ({{}});

      // When the View initializes: send input args, call the tool, send result
      bridge.oninitialized = async () => {{
        await bridge.sendToolInput({{ arguments: toolArgs }});
        const result = await client.callTool({{ name: toolName, arguments: toolArgs }});
        await bridge.sendToolResult(result);
        status.style.display = "none";
        iframe.style.display = "block";
        // Prevent horizontal scrollbar when vertical scrollbar appears
        try {{ iframe.contentDocument.documentElement.style.overflowX = "hidden"; }} catch(e) {{}}
      }};

      // Start listening before the iframe loads
      await bridge.connect(transport);

      // Now load the renderer HTML via the server-side proxy
      const frameUrl = "/ui-resource?uri=" + encodeURIComponent(uiUri);
      const loaded = new Promise(r => {{ iframe.addEventListener("load", r, {{ once: true }}); }});
      iframe.src = frameUrl;
      await loaded;

      // Update transport to the real renderer window.  This microtask runs
      // before the ui/initialize message macrotask, ensuring the response
      // is dispatched to the correct window.
      transport.eventTarget = iframe.contentWindow;
      transport.eventSource = iframe.contentWindow;
    }}

    main().catch(err => {{
      status.textContent = "Error: " + err.message;
      console.error(err);
    }});
  </script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Dev log panel (injected into host pages)
# ---------------------------------------------------------------------------

_LOG_PANEL_HTML = """\
<style>
  #mcp-log-panel {
    position: fixed; top: 0; left: 0; bottom: 0; width: 360px;
    z-index: 10000;
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
    font-size: 12px; background: #1e1e2e; color: #cdd6f4;
    border-right: 1px solid #45475a;
    display: flex; flex-direction: column;
  }
  #mcp-log-panel.hidden { display: none; }
  #app-frame {
    width: 100% !important; height: 100% !important;
    margin-left: 0 !important;
  }
  #mcp-log-resize {
    position: absolute; right: -3px; top: 0; bottom: 0; width: 6px;
    cursor: col-resize; z-index: 1;
  }
  #mcp-log-resize:hover, #mcp-log-resize.active { background: #585b70; }
  #mcp-log-header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 10px 12px; background: #181825;
    border-bottom: 1px solid #45475a; flex-shrink: 0;
  }
  #mcp-log-brand {
    display: flex; align-items: center; gap: 8px;
  }
  #mcp-log-brand svg { flex-shrink: 0; }
  #mcp-log-brand-text {
    font-weight: 700; font-size: 13px; color: #cdd6f4;
    letter-spacing: -0.3px;
  }
  #mcp-log-count-badge {
    font-size: 11px; color: #6c7086; font-weight: 400;
  }
  #mcp-log-actions { display: flex; gap: 6px; }
  #mcp-log-actions button {
    background: #313244; color: #cdd6f4; border: 1px solid #45475a;
    padding: 2px 8px; border-radius: 3px; cursor: pointer;
    font-size: 11px; font-family: inherit;
  }
  #mcp-log-actions button:hover { background: #45475a; }
  #mcp-log-entries { flex: 1; overflow-y: auto; }
  .log-entry {
    padding: 6px 12px; border-bottom: 1px solid #232334; cursor: pointer;
  }
  .log-entry:hover { background: #313244; }
  .log-entry.error { background: rgba(243, 139, 168, 0.08); }
  .log-entry.error:hover { background: rgba(243, 139, 168, 0.14); }
  .log-entry.error .log-method { color: #f38ba8; }
  .log-primary {
    display: flex; justify-content: space-between;
    align-items: baseline; gap: 8px;
  }
  .log-left {
    display: flex; gap: 6px; align-items: baseline; min-width: 0;
  }
  .log-dir { flex-shrink: 0; }
  .log-dir.request { color: #89b4fa; }
  .log-dir.response { color: #a6e3a1; }
  .log-dir.error { color: #f38ba8; }
  .log-dir.bridge { color: #cba6f7; }
  .log-dir.notification { color: #fab387; }
  .log-method {
    color: #f9e2af; font-weight: 600;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .log-meta { color: #6c7086; font-size: 11px; white-space: nowrap; flex-shrink: 0; }
  .log-subtitle {
    color: #a6adc8; font-size: 11px; padding-left: 22px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    margin-top: 1px;
  }
  .log-detail {
    display: none; padding: 8px 12px 4px 22px; background: #11111b;
    white-space: pre-wrap; word-break: break-all;
    color: #bac2de; font-size: 11px; line-height: 1.4;
    margin-top: 4px; border-radius: 4px;
  }
  .log-entry.expanded .log-detail { display: block; }
  @keyframes log-flash {
    from { background: rgba(137, 180, 250, 0.22); }
    to { background: transparent; }
  }
  @keyframes log-flash-error {
    from { background: rgba(243, 139, 168, 0.25); }
    to { background: rgba(243, 139, 168, 0.08); }
  }
  .log-entry.new { animation: log-flash 2s ease-out; }
  .log-entry.error.new { animation: log-flash-error 2s ease-out; }
  .log-copy {
    opacity: 0; transition: opacity 0.15s;
    background: #313244; color: #a6adc8; border: 1px solid #45475a;
    padding: 1px 6px; border-radius: 3px; cursor: pointer;
    font-size: 10px; font-family: inherit; flex-shrink: 0;
  }
  .log-entry:hover .log-copy { opacity: 1; }
  .log-copy:hover { background: #45475a; color: #cdd6f4; }
  #mcp-log-open {
    position: fixed; bottom: 12px; left: 12px; z-index: 10000;
    background: #181825; color: #cdd6f4; border: 1px solid #45475a;
    padding: 6px 12px; border-radius: 6px; cursor: pointer;
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
    font-size: 11px; display: block;
  }
  #mcp-log-open:hover { background: #313244; }
  #mcp-log-filters {
    display: flex; gap: 8px; align-items: center;
    padding: 6px 12px; border-bottom: 1px solid #45475a; flex-shrink: 0;
  }
  .log-seg {
    display: inline-flex; border: 1px solid #45475a; border-radius: 6px;
    overflow: hidden;
  }
  .log-seg button {
    background: transparent; color: #6c7086; border: none;
    border-right: 1px solid #45475a; padding: 3px 10px; cursor: pointer;
    font-size: 10px; font-family: inherit; transition: all 0.15s;
  }
  .log-seg button:last-child { border-right: none; }
  .log-seg button:hover { background: rgba(205, 214, 244, 0.06); }
  .log-seg button.active[data-filter="tools"] { background: rgba(137, 180, 250, 0.15); color: #89b4fa; }
  .log-seg button.active[data-filter="notifications"] { background: rgba(250, 179, 135, 0.15); color: #fab387; }
  .log-seg button.active[data-filter="bridge"] { background: rgba(203, 166, 247, 0.15); color: #cba6f7; }
  .log-seg button.active[data-filter="errors"] { background: rgba(243, 139, 168, 0.15); color: #f38ba8; }
  #mcp-log-filters-label {
    font-size: 9px; color: #6c7086; text-transform: uppercase;
    letter-spacing: 0.5px; font-weight: 600;
  }
  #mcp-log-level-select {
    background: #313244; color: #cdd6f4; border: 1px solid #45475a;
    border-radius: 6px; padding: 3px 8px; cursor: pointer;
    font-size: 10px; font-family: inherit;
  }
  #mcp-log-level-select option { background: #1e1e2e; }
  .log-level {
    font-size: 9px; padding: 0 5px; border-radius: 3px;
    font-weight: 600; text-transform: uppercase; letter-spacing: 0.3px;
    flex-shrink: 0; line-height: 16px;
  }
  .log-level-debug { background: #313244; color: #6c7086; }
  .log-level-info { background: rgba(137, 180, 250, 0.15); color: #89b4fa; }
  .log-level-warning { background: rgba(249, 226, 175, 0.15); color: #f9e2af; }
  .log-level-error { background: rgba(243, 139, 168, 0.15); color: #f38ba8; }
  .log-level-notice { background: rgba(148, 226, 213, 0.15); color: #94e2d5; }
  .log-level-critical { background: rgba(243, 139, 168, 0.2); color: #f38ba8; }
  .log-level-alert { background: rgba(243, 139, 168, 0.25); color: #f38ba8; }
  .log-level-emergency { background: rgba(243, 139, 168, 0.3); color: #f38ba8; }
</style>
<div id="mcp-log-panel" class="hidden">
  <div id="mcp-log-resize"></div>
  <div id="mcp-log-header">
    <div id="mcp-log-brand">
      <svg width="20" height="20" viewBox="0 0 196 196" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M145.747 44.611L145.355 44.3877L144.96 44.611L86.0283 78.5276V171.267L86.4014 171.499L99.6674 179.667V86.3859L159 52.2379L145.747 44.611Z" fill="#cdd6f4"/><path d="M121.616 30.2714L121.224 30.0454L120.832 30.2714L61.8975 64.188V156.928L62.2732 157.156L75.5393 165.325V72.0463L134.869 37.8983L121.616 30.2714Z" fill="#cdd6f4"/><path d="M97.4894 16.3818L97.0973 16.1558L96.7025 16.3818L37.7705 50.3038V142.066L51.4096 150.463V58.1567L110.742 24.0086L97.4894 16.3818Z" fill="#cdd6f4"/><path d="M131.23 113.671L124.979 117.266L124.584 117.494V117.5L116.796 121.987L110.547 125.581L110.152 125.807V141.51L144.564 121.709V121.698L158.999 113.394V97.6851L139.277 109.034L131.23 113.671Z" fill="#cdd6f4"/></svg>
      <span id="mcp-log-brand-text">FastMCP Apps</span>
      <span id="mcp-log-count-badge">\u00b7 <span id="mcp-log-count">0</span></span>
    </div>
    <div id="mcp-log-actions">
      <button id="mcp-log-reset" onclick="window.location.href='/'">&#8592; Back</button>
      <script>if (window.location.pathname === "/") document.getElementById("mcp-log-reset").style.display = "none";</script>
      <button id="mcp-log-clear">Clear</button>
      <button id="mcp-log-close">\u00d7</button>
    </div>
  </div>
  <div id="mcp-log-filters">
    <span id="mcp-log-filters-label">Show</span>
    <div class="log-seg">
      <button class="active" data-filter="tools">Tools</button>
      <button class="active" data-filter="notifications">Logs</button>
      <button class="active" data-filter="bridge">Host</button>
      <button class="active" data-filter="errors">Errors</button>
    </div>
    <select id="mcp-log-level-select">
      <option value="debug">Debug+</option>
      <option value="info">Info+</option>
      <option value="warning">Warn+</option>
      <option value="error">Error+</option>
      <option value="critical">Critical+</option>
    </select>
  </div>
  <div id="mcp-log-entries"></div>
</div>
<button id="mcp-log-open">MCP Log</button>
<script>
(function() {
  var lastId = 0, totalCount = 0, panelWidth = 360;
  var panel = document.getElementById("mcp-log-panel");
  var entries = document.getElementById("mcp-log-entries");
  var countEl = document.getElementById("mcp-log-count");
  var openBtn = document.getElementById("mcp-log-open");
  var resizeHandle = document.getElementById("mcp-log-resize");
  var allFilterKeys = ["tools", "notifications", "bridge", "errors"];

  function syncURL() {
    var params = new URLSearchParams(window.location.search);
    if (!panel.classList.contains("hidden")) {
      params.set("log", "open");
    } else {
      params.delete("log");
    }
    var on = [];
    for (var i = 0; i < allFilterKeys.length; i++) {
      if (activeFilters[allFilterKeys[i]]) on.push(allFilterKeys[i]);
    }
    if (on.length === allFilterKeys.length) {
      params.delete("filters");
    } else {
      params.set("filters", on.join(","));
    }
    if (minLevel === 0) {
      params.delete("level");
    } else {
      params.set("level", levelOrder[minLevel]);
    }
    var qs = params.toString();
    var url = window.location.pathname + (qs ? "?" + qs : "");
    history.replaceState(null, "", url);
  }

  function setFrameLayout(w) {
    var frame = document.getElementById("app-frame");
    if (!frame) return;
    frame.style.setProperty("width", w, "important");
    frame.style.setProperty("margin-left", w === "100%" ? "0" : panelWidth + "px", "important");
  }

  document.getElementById("mcp-log-close").addEventListener("click", function() {
    panel.classList.add("hidden");
    openBtn.style.display = "block";
    setFrameLayout("100%");
    syncURL();
  });

  openBtn.addEventListener("click", function() {
    panel.classList.remove("hidden");
    openBtn.style.display = "none";
    setFrameLayout("calc(100% - " + panelWidth + "px)");
    entries.scrollTop = entries.scrollHeight;
    syncURL();
  });

  resizeHandle.addEventListener("mousedown", function(e) {
    e.preventDefault();
    resizeHandle.classList.add("active");
    var frame = document.getElementById("app-frame");
    if (frame) frame.style.pointerEvents = "none";
    document.addEventListener("mousemove", onResize);
    document.addEventListener("mouseup", stopResize);
  });

  function onResize(e) {
    var w = Math.max(200, Math.min(e.clientX, window.innerWidth * 0.8));
    panelWidth = w;
    panel.style.width = w + "px";
    setFrameLayout("calc(100% - " + w + "px)");
  }

  function stopResize() {
    resizeHandle.classList.remove("active");
    var frame = document.getElementById("app-frame");
    if (frame) frame.style.pointerEvents = "";
    document.removeEventListener("mousemove", onResize);
    document.removeEventListener("mouseup", stopResize);
  }

  document.getElementById("mcp-log-clear").addEventListener("click", function() {
    entries.innerHTML = "";
    totalCount = 0;
    countEl.textContent = "0";
    fetch("/api/logs/clear", { method: "POST" });
  });

  var activeFilters = {tools: true, notifications: true, bridge: true, errors: true};
  var levelOrder = ["debug", "info", "notice", "warning", "error", "critical", "alert", "emergency"];
  var minLevel = 0;

  // Restore state from URL params
  (function restoreURL() {
    var params = new URLSearchParams(window.location.search);
    if (params.get("log") === "open") {
      panel.classList.remove("hidden");
      openBtn.style.display = "none";
      setFrameLayout("calc(100% - " + panelWidth + "px)");
    }
    var fp = params.get("filters");
    if (fp !== null) {
      var on = fp ? fp.split(",") : [];
      for (var i = 0; i < allFilterKeys.length; i++) {
        var k = allFilterKeys[i];
        activeFilters[k] = on.indexOf(k) !== -1;
        var btn = document.querySelector("[data-filter='" + k + "']");
        if (btn) btn.classList.toggle("active", activeFilters[k]);
      }
    }
    var lp = params.get("level");
    if (lp) {
      var idx = levelOrder.indexOf(lp);
      if (idx >= 0) {
        minLevel = idx;
        document.getElementById("mcp-log-level-select").value = lp;
      }
    }
  })();

  document.getElementById("mcp-log-filters").addEventListener("click", function(e) {
    var btn = e.target.closest("[data-filter]");
    if (!btn) return;
    var f = btn.dataset.filter;
    activeFilters[f] = !activeFilters[f];
    btn.classList.toggle("active", activeFilters[f]);
    applyFilters();
    syncURL();
  });

  document.getElementById("mcp-log-level-select").addEventListener("change", function(e) {
    minLevel = levelOrder.indexOf(e.target.value);
    applyFilters();
    syncURL();
  });

  function shouldShow(el) {
    var cat = el.dataset.category || "";
    if (activeFilters[cat] === false) return false;
    var lv = el.dataset.level;
    if (lv && levelOrder.indexOf(lv) < minLevel) return false;
    return true;
  }

  function applyFilters() {
    var items = entries.querySelectorAll(".log-entry");
    for (var i = 0; i < items.length; i++) {
      items[i].style.display = shouldShow(items[i]) ? "" : "none";
    }
  }

  function summarize(entry) {
    var b = entry.body;
    if (!b) return "";
    if (entry.direction === "request" || entry.direction === "notification") {
      if (b.method === "tools/call" && b.params) return b.params.name || "";
      if (b.method === "resources/read" && b.params) return b.params.uri || "";
      if (b.method === "notifications/message" && b.params) {
        var d = b.params.data;
        if (d && typeof d === "object") return d.msg || d.message || JSON.stringify(d);
        return d || b.params.level || "";
      }
      return "";
    }
    if (b.error) return "error: " + (b.error.message || JSON.stringify(b.error));
    if (b.result && typeof b.result === "object") {
      if (Array.isArray(b.result.tools)) return b.result.tools.length + " tools";
      if (Array.isArray(b.result.resources)) return b.result.resources.length + " resources";
      if (Array.isArray(b.result.prompts)) return b.result.prompts.length + " prompts";
      if (b.result.content) {
        var first = b.result.content[0];
        if (first && first.text) {
          return first.text.length > 60 ? first.text.slice(0, 60) + "\u2026" : first.text;
        }
        return b.result.content.length + " content item(s)";
      }
    }
    return "";
  }

  function formatTime(ts) {
    var d = new Date(ts * 1000);
    return String(d.getHours()).padStart(2, "0") + ":"
      + String(d.getMinutes()).padStart(2, "0") + ":"
      + String(d.getSeconds()).padStart(2, "0");
  }

  function renderEntry(entry) {
    var div = document.createElement("div");
    var isError = entry.direction === "response" && entry.body
      && (entry.body.error || (entry.body.result && entry.body.result.isError));
    div.className = "log-entry" + (isError ? " error" : "");
    var dirClass = isError ? "error" : entry.direction;
    var arrows = {request: "\u2192", response: "\u2190", bridge: "\u2191", notification: "\u2193"};

    // Categorize for filtering
    if (isError) div.dataset.category = "errors";
    else if (entry.direction === "bridge") div.dataset.category = "bridge";
    else if (entry.direction === "notification") div.dataset.category = "notifications";
    else div.dataset.category = "tools";

    var primary = document.createElement("div");
    primary.className = "log-primary";

    var left = document.createElement("div");
    left.className = "log-left";

    var dirEl = document.createElement("span");
    dirEl.className = "log-dir " + dirClass;
    dirEl.textContent = arrows[entry.direction] || "\u2190";

    var methodEl = document.createElement("span");
    methodEl.className = "log-method";
    methodEl.textContent = entry.method || "";

    left.appendChild(dirEl);
    left.appendChild(methodEl);

    // Log level badge for notifications
    if (entry.direction === "notification" && entry.body && entry.body.params) {
      var level = (entry.body.params.level || "").toLowerCase();
      if (level) {
        div.dataset.level = level;
        var lvl = document.createElement("span");
        lvl.className = "log-level log-level-" + level;
        lvl.textContent = level;
        left.appendChild(lvl);
      }
    }

    var metaEl = document.createElement("span");
    metaEl.className = "log-meta";
    metaEl.textContent = entry.duration_ms != null
      ? entry.duration_ms + "ms"
      : formatTime(entry.timestamp);

    var copyBtn = document.createElement("button");
    copyBtn.className = "log-copy";
    copyBtn.textContent = "Copy";
    copyBtn.addEventListener("click", function(e) {
      e.stopPropagation();
      navigator.clipboard.writeText(JSON.stringify(entry.body, null, 2));
      copyBtn.textContent = "Copied";
      setTimeout(function() { copyBtn.textContent = "Copy"; }, 1000);
    });

    primary.appendChild(left);
    primary.appendChild(metaEl);
    primary.appendChild(copyBtn);
    div.appendChild(primary);

    var summary = summarize(entry);
    if (summary) {
      var subtitle = document.createElement("div");
      subtitle.className = "log-subtitle";
      subtitle.textContent = summary;
      div.appendChild(subtitle);
    }

    var detail = document.createElement("div");
    detail.className = "log-detail";
    detail.textContent = JSON.stringify(entry.body, null, 2);
    div.appendChild(detail);

    div.addEventListener("click", function() { div.classList.toggle("expanded"); });
    return div;
  }

  var polling = false;
  var firstPoll = true;
  function poll() {
    if (polling) return;
    polling = true;
    fetch("/api/logs?since=" + lastId)
      .then(function(r) { return r.ok ? r.json() : []; })
      .then(function(data) {
        if (!data || !data.length) return;
        lastId = data[data.length - 1].id;
        totalCount += data.length;
        countEl.textContent = String(totalCount);
        var panelVisible = !panel.classList.contains("hidden");
        var atBottom = !panelVisible || entries.scrollHeight - entries.scrollTop - entries.clientHeight < 40;
        for (var i = 0; i < data.length; i++) {
          var el = renderEntry(data[i]);
          el.classList.add("new");
          if (!shouldShow(el)) el.style.display = "none";
          entries.appendChild(el);
        }
        if (atBottom || (firstPoll && panelVisible)) entries.scrollTop = entries.scrollHeight;
        firstPoll = false;
      })
      .catch(function() {})
      .finally(function() { polling = false; });
  }

  window.addEventListener("message", function(event) {
    var data = event.data;
    if (typeof data === "string") {
      try { data = JSON.parse(data); } catch(e) { return; }
    }
    if (!data || typeof data !== "object") return;
    if (!data.jsonrpc && !data.method) return;
    fetch("/api/logs/bridge", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({body: data})
    });
  });

  setInterval(poll, 500);
  poll();
})();
</script>
"""


def _inject_log_panel(html: str) -> str:
    """Inject the MCP message log panel before </body>."""
    pass


# ---------------------------------------------------------------------------
# Picker UI (Prefab-based, built in Python)
# ---------------------------------------------------------------------------


def _has_ui_resource(tool: dict[str, Any]) -> bool:
    """Return True if the tool has a UI resourceUri in its metadata."""
    pass


def _model_from_schema(tool_name: str, input_schema: dict[str, Any]) -> type[Any]:
    """Dynamically create a Pydantic model from a JSON Schema for form generation."""
    pass


def _build_picker_html(tools: list[dict[str, Any]]) -> str:
    """Build Prefab picker page: dropdown selector with per-tool forms."""
    pass


# ---------------------------------------------------------------------------
# MCP tool listing helper
# ---------------------------------------------------------------------------


async def _list_tools(mcp_url: str) -> list[dict[str, Any]]:
    """Return raw tool dicts from the MCP server at mcp_url."""
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except ImportError:
        return []

    try:
        async with streamable_http_client(mcp_url) as (read, write, _):  # noqa: SIM117
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [t.model_dump() for t in result.tools]
    except Exception as exc:
        logger.debug(f"Could not list tools from {mcp_url}: {exc}")
        return []


async def _read_mcp_resource(mcp_url: str, uri: str) -> str | None:
    """Read an MCP resource by URI and return its text content."""
    pass


# ---------------------------------------------------------------------------
# app-bridge.js download, patch, and Zod import-map generation
# ---------------------------------------------------------------------------


def _fetch_app_bridge_bundle_sync(
    version: str,
    sdk_version: str,
) -> tuple[str, str]:
    """Download app-bridge.js and build an import-map that fixes Zod v4 on esm.sh.

    Returns ``(app_bridge_js, import_map_json)`` where *import_map_json* is a
    JSON string ready to embed in a ``<script type="importmap">`` tag.

    Background
    ----------
    esm.sh's ``zod@x.y.z/es2022/v4.mjs`` only re-exports ``{z, default}``,
    losing all individual named exports (``custom``, ``string``, etc.).  The
    MCP SDK does ``import * as t from "zod/v4"`` and calls ``t.custom(…)``
    which fails.  ``zod@x.y.z/es2022/v4/classic/index.mjs`` exports everything
    correctly.  An import-map that remaps the broken URL to the working one
    fixes all modules in the page's graph, including those loaded cross-origin
    from esm.sh.

    ext-apps app-bridge.js imports the SDK via bare specifiers
    (``@modelcontextprotocol/sdk/types.js`` etc.) that the browser cannot
    resolve.  We rewrite them to concrete esm.sh URLs before serving.
    """
    pass


async def _fetch_app_bridge_bundle(
    version: str,
    sdk_version: str,
) -> tuple[str, str]:
    """Async wrapper around _fetch_app_bridge_bundle_sync."""
    pass


# ---------------------------------------------------------------------------
# FastAPI dev server
# ---------------------------------------------------------------------------


def _make_dev_app(
    mcp_url: str,
    app_bridge_js: str,
    import_map_tag: str,
    message_log: _MessageLog,
) -> Starlette:
    """Build the Starlette dev server application."""
    pass


# ---------------------------------------------------------------------------
# Launch helpers
# ---------------------------------------------------------------------------


async def _start_user_server(
    server_spec: str,
    mcp_port: int,
    *,
    reload: bool = True,
) -> asyncio.subprocess.Process:
    """Start the user's MCP server as a subprocess on mcp_port."""
    pass


async def _wait_for_server(url: str, timeout: float = 15.0) -> bool:
    """Poll until the server is accepting connections."""
    pass


async def run_dev_apps(
    server_spec: str,
    *,
    mcp_port: int = 8000,
    dev_port: int = 8080,
    reload: bool = True,
) -> None:
    """Start the full dev environment for a FastMCPApp server.

    Starts the user's MCP server on *mcp_port*, starts the Prefab dev UI
    on *dev_port* (with an /mcp proxy to the user's server), then opens
    the browser.
    """
    pass
