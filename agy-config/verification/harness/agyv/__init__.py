"""
==============================================================================
FILE HEADER: agyv/__init__.py — Antigravity settings-scope verification harness
==============================================================================
Purpose:
    Package marker for the harness that proves, on live test VMs, which
    Antigravity settings file each surface (CLI, desktop App, web UI, VS Code,
    JetBrains/Zed via ACP) honors for each security control.

Architecture / Context:
    Modules: env (paths, gateway), files (settings writers), probes (prompts
    and oracles), cases (matrix catalog), runner (one round), surfaces/*
    (per-surface drivers). Entry point: ../run_matrix.py.

Dependencies / Side Effects:
    None at import time.
==============================================================================
"""
