| case | placement | outcome | verdict | was | reason |
|---|---|---|---|---|---|
| D10.mcp.disabledTools | mcp_config | EXECUTED | IGNORED |  | side effect observed |
| D11.hook.workspace | workspace | BLOCKED | HONORED | ASKED/OTHER | denied by pre-tool hook: agy-verify guard: token 'hookblock' is blocked by policy |
| D6.sandbox.control | control | EXECUTED | BASELINE_OK |  | side effect observed |
| D6.sandbox.cli_settings | cli_settings | EXECUTED | IGNORED |  | side effect observed |
| D6.sandbox.shared_config | shared_config | EXECUTED | IGNORED |  | side effect observed |
| D6.sandbox.urlallow.cli_settings | cli_settings | EXECUTED | HONORED |  | side effect observed |
| D6.sandbox_fs.cli_settings | cli_settings | EXECUTED | IGNORED |  | side effect observed |
| D6.sandbox_fs.shared_config | shared_config | EXECUTED | IGNORED |  | side effect observed |
| D6.egress.default | control | ASKED | BASELINE_UNEXPECTED |  | 1 permission prompt(s) raised |
| D6.egress.cli_settings | cli_settings | ASKED | OTHER |  | 1 permission prompt(s) raised |
| D6.egress.shared_config | shared_config | ASKED | OTHER |  | 1 permission prompt(s) raised |
