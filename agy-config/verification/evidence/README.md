# Evidence (redacted)

Result tables from the November 2026 live verification. The harness redacts the gateway key and URL (`<REDACTED_GATEWAY_KEY>`, `<GATEWAY_URL>`). Each folder was scanned for both before commit. Raw round folders, transcripts and screenshots stayed on the disposable VMs and are git-ignored (`evidence/raw/`).

## How to read a row

Each `results.jsonl` line is one case on one surface. `reclassified_*.md` re-judges finished rounds with the final classifier (`harness/tools/reclassify.py`). When a run has both, the reclassified table is the authoritative one.

Fields in each line:

- `case`: the case id (see `harness/agyv/cases.py`).
- `placement`: which file carried the setting.
- `outcome`: `EXECUTED`, `BLOCKED`, `ASKED`, `SANDBOXED`, `NOT_ATTEMPTED`, `GATEWAY_BLOCKED`, `GATEWAY_LOST` or `ERROR`.
- `verdict`:
  - `HONORED` or `IGNORED`: the surface obeyed or skipped the placed setting.
  - `BASELINE_OK`: the control case behaved as expected.
  - `OTHER`: the outcome needs reading. For example, a built-in boundary blocked the action first.

## Runs

| Folder | OS | Surfaces | What it covers |
|---|---|---|---|
| `linux/l5` | Ubuntu 22.04 | CLI, ACP | Full placement matrix (D3–D11, D1 user file, D14 CLI tamper); final classifier in `reclassified_*` |
| `linux/l6`, `linux/l7`, `linux/l8` | Ubuntu 22.04 | CLI, ACP | Sandbox and egress (D6, with prompts rejected), `--dangerously-skip-permissions` isolation, read_url egress allowlist, repo hooks.json shape |
| `linux/l9` | Ubuntu 22.04 | ACP | Admin-file cases on Linux ACP (malformed / bad enum / governance) |
| `linux/b1` | Ubuntu 22.04 | CLI, ACP, App, web, VS Code | P4 minimal baseline, deployed and locked (`reclassified_*` across all 5 surfaces) |
| `linux/h1`, `linux/h2`, `linux/h3` | Ubuntu 22.04 | App, web hub, VS Code | Full placement matrix on the hub surfaces (CDP-driven), plus repo hooks.json shape and admin-file failure/governance cases |
| `linux/explore` | Ubuntu 22.04 | App, web hub, VS Code | UI settings inspection and VS Code `.vscode/settings.json` `antigravity.serverArgs` `--gemini_dir` relocation proofs (`q4a`–`q4e`, with and without Workspace Trust) |
| `linux/cli-w3` | Ubuntu 22.04 | CLI | Admin-file cases (malformed / bad enum → Google sign-in) |
| `windows/win-w1` | Server 2022 | CLI | Full matrix with literal `command(New-Item)` rules (they don't match on Windows) |
| `windows/w6`, `windows/w7` | Server 2022 | CLI, ACP | Regex command rules, tamper cases, sandbox (none on Server 2022) |
| `windows/w8`, `windows/w9` | Server 2022 | ACP, CLI | ACP matrix; hooks with backslash paths (fail) vs forward slashes (work); admin cases on ACP |
| `windows/b1` | Server 2022 | CLI, ACP | P4 minimal baseline, deployed and locked |
