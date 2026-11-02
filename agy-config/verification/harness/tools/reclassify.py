#!/usr/bin/env python3
"""
==============================================================================
FILE HEADER: reclassify.py — Re-judge finished rounds with the current classifier
==============================================================================
Purpose:
    Re-evaluates every finished round of a matrix run (per surface) using the
    current probe definitions, the surface transcript stored in the round
    HOME, and the side effects still on disk. Used when a classifier or probe
    bug is fixed after a run, so long runs don't have to be repeated.

Architecture / Context:
    Offline companion to run_matrix.py. Reads round folders written by
    agyv.runner (rounds/<run>/<surface>/r<NNN>/ with case.txt and
    evidence/record.json) and writes results/<run>/reclassified_<surface>.jsonl
    plus a Markdown table, leaving the original results untouched.

Dependencies / Side Effects:
    Python 3.10+ standard library and the harness package. Read-only on round
    folders; writes two files under <WORK_ROOT>/results/<run>/.
==============================================================================
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agyv import transcript  # noqa: E402
from agyv.cases import all_cases  # noqa: E402
from agyv.env import WORK_ROOT  # noqa: E402
from agyv.probes import PROBES, RoundPaths, SurfaceResult, classify  # noqa: E402

LOG = logging.getLogger("agyv.reclassify")
RESULT_FIELDS = ("tool_calls", "steps", "prompts", "denied", "response", "tools_offered", "exit_code", "error",
                 "raw_paths")


def _verdict(case, outcome: str) -> str:
    """Map an outcome to the run_matrix verdict vocabulary.

    Parameters:
        case (Case): Case definition.
        outcome (str): Outcome label.
    Return Value:
        str: BASELINE_OK / BASELINE_UNEXPECTED / HONORED / IGNORED / OTHER.
    Exceptions/Errors:
        None.
    """
    if case.placement == "control":
        return "BASELINE_OK" if outcome == case.expect_if_honored else "BASELINE_UNEXPECTED"
    if outcome == case.expect_if_honored:
        return "HONORED"
    if outcome == case.expect_if_ignored:
        return "IGNORED"
    return "OTHER"


def reclassify(run_id: str, surface: str) -> list[dict]:
    """Re-judge every round of one run/surface.

    Parameters:
        run_id (str): Matrix run id.
        surface (str): Surface folder name (cli, acp, app, web, vscode).
    Return Value:
        list[dict]: One row per round (case, old/new outcome and verdict, reason).
    Exceptions/Errors:
        FileNotFoundError: If the run/surface folder doesn't exist.
    """
    root = WORK_ROOT / "rounds" / run_id / surface
    if not root.is_dir():
        raise FileNotFoundError(f"no rounds at {root}")
    cases = {c.id: c for c in all_cases()}
    rows = []
    for base in sorted(p for p in root.iterdir() if p.is_dir()):
        record_path = base / "evidence" / "record.json"
        case_file = base / "case.txt"
        if not record_path.exists() or not case_file.exists():
            continue
        case_id = case_file.read_text(encoding="utf-8").splitlines()[0].strip()
        case = cases.get(case_id)
        if case is None:
            LOG.warning("unknown case %s in %s", case_id, base)
            continue
        record = json.loads(record_path.read_text(encoding="utf-8"))
        evidence = record.get("evidence", {})
        res = SurfaceResult(**{k: evidence.get(k, SurfaceResult.__dataclass_fields__[k].default_factory()
                                               if callable(getattr(SurfaceResult.__dataclass_fields__[k],
                                                                   "default_factory", None)) else None)
                               for k in RESULT_FIELDS})
        res.response = res.response or ""
        res.error = res.error or ""
        rp = RoundPaths(home=base / "home", workspace=base / "home" / "ws", outside=base / "out",
                        evidence=base / "evidence")
        if not res.steps:
            path = transcript.find_latest(rp.home)
            if path:
                res.steps, final_text = transcript.parse(path)
                res.response = res.response or final_text
        outcome, reason = classify(PROBES[case.probe], rp, res, case.approvals)
        rows.append({"case": case_id, "round": base.name, "placement": case.placement,
                     "old_outcome": record.get("outcome"), "old_verdict": record.get("verdict"),
                     "outcome": outcome, "verdict": _verdict(case, outcome), "reason": reason})
    return rows


def main(argv: list[str]) -> int:
    """CLI entry point.

    Parameters:
        argv (list[str]): Arguments without the program name.
    Return Value:
        int: 0 on success, 1 on errors.
    Exceptions/Errors:
        None (errors are logged).
    """
    parser = argparse.ArgumentParser(description="Re-judge finished rounds with the current classifier.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--surface", required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        rows = reclassify(args.run_id, args.surface)
    except FileNotFoundError as exc:
        LOG.error("%s", exc)
        return 1
    out_dir = WORK_ROOT / "results" / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"reclassified_{args.surface}.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    lines = ["| case | placement | outcome | verdict | was | reason |", "|---|---|---|---|---|---|"]
    for r in rows:
        was = "" if (r["old_outcome"], r["old_verdict"]) == (r["outcome"], r["verdict"]) else \
            f"{r['old_outcome']}/{r['old_verdict']}"
        lines.append(f"| {r['case']} | {r['placement']} | {r['outcome']} | {r['verdict']} | {was} | "
                     f"{r['reason'][:110].replace('|', '/')} |")
    table = "\n".join(lines) + "\n"
    (out_dir / f"reclassified_{args.surface}.md").write_text(table, encoding="utf-8")
    print(table)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
