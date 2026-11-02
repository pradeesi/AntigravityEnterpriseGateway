#!/usr/bin/env python3
"""
==============================================================================
FILE HEADER: run_matrix.py — Command-line entry point for the verification matrix
==============================================================================
Purpose:
    Selects cases and surfaces, runs every (case, surface) pair through
    runner.run_case, appends each record to results.jsonl, and prints a
    compact table so an operator can see which file each surface honored.

Architecture / Context:
    Lives in agy-config/verification/harness/ and is copied to the test VM at
    /opt/agy-verify/harness (Linux) or C:\\ProgramData\\agy-verify\\harness
    (Windows). Run it as root/administrator from that folder:
        python3 run_matrix.py --surfaces cli --cases 'D3.*' --run-id cli-001

Dependencies / Side Effects:
    Python 3.10+; the agyv package next to this file. Writes
    <WORK_ROOT>/results/<run_id>/results.jsonl and summary.md.
==============================================================================
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agyv.cases import ALL_SURFACES, all_cases  # noqa: E402
from agyv.env import WORK_ROOT, load_gateway  # noqa: E402
from agyv.runner import run_case  # noqa: E402

LOG = logging.getLogger("agyv.matrix")


def main() -> int:
    """Parse arguments, run the selected matrix slice, and write results.

    Return Value:
        int: 0 when every selected pair ran (verdicts may still be IGNORED/OTHER), 1 on setup errors.
    Exceptions/Errors:
        Logs and returns 1 if the gateway configuration can't be loaded.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surfaces", default="cli", help=f"comma list from {','.join(ALL_SURFACES)}")
    parser.add_argument("--cases", default="*", help="comma list of fnmatch patterns on case ids")
    parser.add_argument("--run-id", default=time.strftime("run-%Y%m%d-%H%M%S"))
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--list", action="store_true", help="list matching cases and exit")
    args = parser.parse_args()

    patterns = [p.strip() for p in args.cases.split(",") if p.strip()]
    surfaces = [s.strip() for s in args.surfaces.split(",") if s.strip()]
    selected = [c for c in all_cases() if any(fnmatch.fnmatch(c.id, p) for p in patterns)]
    if args.list:
        for case in selected:
            print(f"{case.id:40s} {case.placement:14s} {','.join(case.surfaces)}  {case.note}")
        return 0
    try:
        gateway = load_gateway()
    except RuntimeError as exc:
        LOG.error("%s", exc)
        return 1

    out_dir = WORK_ROOT / "results" / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"
    rows = []
    for surface in surfaces:
        for case in selected:
            if surface not in case.surfaces:
                continue
            LOG.info("running %s on %s", case.id, surface)
            record = run_case(args.run_id, case, surface, gateway, retries=args.retries)
            with results_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
            rows.append(record)
            LOG.info("  -> %s (%s) %s", record["outcome"], record["verdict"], record["reason"])

    lines = ["| case | surface | placement | outcome | verdict | reason |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['case']} | {r['surface']} | {r['placement']} | {r['outcome']} | "
                     f"{r['verdict']} | {r['reason'][:80]} |")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
