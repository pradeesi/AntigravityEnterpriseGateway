"""
==============================================================================
FILE HEADER: agyv/surfaces/__init__.py — Surface drivers
==============================================================================
Purpose:
    Package marker for the per-surface drivers (cli, acp, hub). Each module
    exposes run(...) -> probes.SurfaceResult.

Architecture / Context:
    Imported lazily by runner._driver so a CLI-only run doesn't need the CDP
    or ACP dependencies.

Dependencies / Side Effects:
    None at import time.
==============================================================================
"""
