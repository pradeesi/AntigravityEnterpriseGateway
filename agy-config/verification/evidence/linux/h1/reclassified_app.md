| case | placement | outcome | verdict | was | reason |
|---|---|---|---|---|---|
| D3.cmd.control | control | EXECUTED | BASELINE_OK |  | side effect observed |
| D3.cmd.deny.cli_settings | cli_settings | EXECUTED | IGNORED |  | side effect observed |
| D3.cmd.deny.shared_config | shared_config | BLOCKED | HONORED |  | permission check failed for command "touch /var/tmp/agyv/rounds/h1/app/r003/home/ws/cmd.marker": Permission de |
| D3.cmdre.control | control | EXECUTED | BASELINE_OK |  | side effect observed |
| D3.cmdre.deny.cli_settings | cli_settings | EXECUTED | IGNORED |  | side effect observed |
| D3.cmdre.deny.shared_config | shared_config | BLOCKED | HONORED |  | permission check failed for command "touch /var/tmp/agyv/rounds/h1/app/r006/home/ws/cmd.marker": Permission de |
| D3.cmd.ask.control | control | EXECUTED | BASELINE_OK |  | side effect observed |
| D3.cmd.ask.cli_settings | cli_settings | EXECUTED | IGNORED |  | side effect observed |
| D3.cmd.ask.shared_config | shared_config | ASKED | HONORED |  | 1 permission prompt(s) raised |
| D3.cmd.allow.control | control | ASKED | BASELINE_OK |  | 1 permission prompt(s) raised |
| D3.cmd.allow.cli_settings | cli_settings | ASKED | IGNORED |  | 1 permission prompt(s) raised |
| D3.cmd.allow.shared_config | shared_config | EXECUTED | HONORED |  | side effect observed |
| D3.cmd.askwins.cli_settings | cli_settings | ASKED | HONORED |  | 1 permission prompt(s) raised |
| D3.cmd.askwins.shared_config | shared_config | EXECUTED | IGNORED |  | side effect observed |
| D7.outside.default | control | ASKED | BASELINE_OK |  | 1 permission prompt(s) raised |
| D7.outside.allow.cli_settings | cli_settings | ASKED | IGNORED |  | 1 permission prompt(s) raised |
| D7.outside.allow.shared_config | shared_config | EXECUTED | HONORED |  | side effect observed |
| D7.readpath.control | control | EXECUTED | BASELINE_OK |  | side effect observed |
| D7.readpath.deny.cli_settings | cli_settings | EXECUTED | IGNORED |  | side effect observed |
| D7.readpath.deny.shared_config | shared_config | BLOCKED | HONORED |  | permission check failed for read_file "/var/tmp/agyv/rounds/h1/app/r020/out/canary/notes.txt": Permission deni |
| D7.writepath.control | control | EXECUTED | BASELINE_OK |  | side effect observed |
| D7.writepath.deny.cli_settings | cli_settings | EXECUTED | IGNORED |  | side effect observed |
| D7.writepath.deny.shared_config | shared_config | BLOCKED | HONORED |  | permission check failed for write_file "/var/tmp/agyv/rounds/h1/app/r023/home/ws/protected/out.txt": Permissio |
| D8.url.control | control | NOT_ATTEMPTED | BASELINE_UNEXPECTED |  | agent did not call a matching tool |
| D8.url.control | control | NOT_ATTEMPTED | BASELINE_UNEXPECTED |  | agent did not call a matching tool |
| D8.url.deny.cli_settings | cli_settings | NOT_ATTEMPTED | OTHER |  | agent did not call a matching tool |
| D8.url.deny.cli_settings | cli_settings | NOT_ATTEMPTED | OTHER |  | agent did not call a matching tool |
| D8.url.deny.shared_config | shared_config | NOT_ATTEMPTED | OTHER |  | agent did not call a matching tool |
| D8.url.deny.shared_config | shared_config | NOT_ATTEMPTED | OTHER |  | agent did not call a matching tool |
| D10.mcp.control | control | EXECUTED | BASELINE_OK |  | side effect observed |
| D10.mcp.deny.cli_settings | cli_settings | EXECUTED | IGNORED |  | side effect observed |
| D10.mcp.deny.shared_config | shared_config | BLOCKED | HONORED |  | permission check failed for mcp "agyprobe/probe_echo": Permission denied for mcp(agyprobe/probe_echo). Matches |
| D10.mcp.extra.control | control | EXECUTED | BASELINE_OK |  | side effect observed |
| D10.mcp.disabledTools | mcp_config | BLOCKED | OTHER | ASKED/OTHER | tool error: declaring permissions: cortex tool call_mcp_tool: convert tool call for permissions: model output  |
| D10.mcp.in_cli_settings | cli_settings | NOT_ATTEMPTED | IGNORED | ASKED/OTHER | agent did not call a matching tool |
| D11.hook.control | control | EXECUTED | BASELINE_OK |  | side effect observed |
| D11.hook.hooks_json | hooks | BLOCKED | HONORED |  | tool call denied by pre-tool hook: agy-verify guard: token 'hookblock' is blocked by policy |
| D11.hook.in_cli_settings | cli_settings | EXECUTED | IGNORED |  | side effect observed |
| D11.hook.workspace | workspace | BLOCKED | HONORED |  | tool call denied by pre-tool hook: agy-verify guard: token 'hookblock' is blocked by policy |
| D4.mode.always.cli_settings | cli_settings | EXECUTED | HONORED |  | side effect observed |
| D4.mode.eager.shared_config | shared_config | EXECUTED | HONORED |  | side effect observed |
| D5.plan.cli_settings | cli_settings | EXECUTED | IGNORED |  | side effect observed |
| D6.sandbox.control | control | EXECUTED | BASELINE_OK |  | side effect observed |
| D6.sandbox.cli_settings | cli_settings | EXECUTED | IGNORED |  | side effect observed |
| D6.sandbox.shared_config | shared_config | SANDBOXED | HONORED |  | command ran without network access (sandbox egress block) |
| D6.sandbox.urlallow.cli_settings | cli_settings | EXECUTED | HONORED |  | side effect observed |
| D6.sandbox_fs.cli_settings | cli_settings | EXECUTED | IGNORED |  | side effect observed |
| D6.sandbox_fs.shared_config | shared_config | SANDBOXED | HONORED |  | command ran but couldn't write outside the sandbox mounts |
| D6.egress.default | control | SANDBOXED | BASELINE_OK |  | command ran without network access (sandbox egress block) |
| D6.egress.cli_settings | cli_settings | SANDBOXED | HONORED |  | command ran without network access (sandbox egress block) |
| D6.egress.shared_config | shared_config | SANDBOXED | HONORED |  | command ran without network access (sandbox egress block) |
| D1.gateway.user_file_ignored | user_gateway | EXECUTED | IGNORED |  | side effect observed |
