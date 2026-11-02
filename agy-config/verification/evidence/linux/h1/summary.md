| case | surface | placement | outcome | verdict | reason |
|---|---|---|---|---|---|
| D3.cmd.control | vscode | control | EXECUTED | BASELINE_OK | side effect observed |
| D3.cmd.deny.cli_settings | vscode | cli_settings | EXECUTED | IGNORED | side effect observed |
| D3.cmd.deny.shared_config | vscode | shared_config | BLOCKED | HONORED | permission check failed for command "touch /var/tmp/agyv/rounds/h1/vscode/r003/h |
| D3.cmdre.control | vscode | control | EXECUTED | BASELINE_OK | side effect observed |
| D3.cmdre.deny.cli_settings | vscode | cli_settings | EXECUTED | IGNORED | side effect observed |
| D3.cmdre.deny.shared_config | vscode | shared_config | BLOCKED | HONORED | permission check failed for command "touch /var/tmp/agyv/rounds/h1/vscode/r006/h |
| D3.cmd.ask.control | vscode | control | EXECUTED | BASELINE_OK | side effect observed |
| D3.cmd.ask.cli_settings | vscode | cli_settings | EXECUTED | IGNORED | side effect observed |
| D3.cmd.ask.shared_config | vscode | shared_config | ASKED | HONORED | 1 permission prompt(s) raised |
| D3.cmd.allow.control | vscode | control | ASKED | BASELINE_OK | 1 permission prompt(s) raised |
| D3.cmd.allow.cli_settings | vscode | cli_settings | ASKED | IGNORED | 1 permission prompt(s) raised |
| D3.cmd.allow.shared_config | vscode | shared_config | EXECUTED | HONORED | side effect observed |
| D3.cmd.askwins.cli_settings | vscode | cli_settings | ASKED | HONORED | 1 permission prompt(s) raised |
| D3.cmd.askwins.shared_config | vscode | shared_config | EXECUTED | IGNORED | side effect observed |
| D7.outside.default | vscode | control | ASKED | BASELINE_OK | 1 permission prompt(s) raised |
| D7.outside.allow.cli_settings | vscode | cli_settings | ASKED | IGNORED | 1 permission prompt(s) raised |
| D7.outside.allow.shared_config | vscode | shared_config | EXECUTED | HONORED | side effect observed |
| D7.readpath.control | vscode | control | EXECUTED | BASELINE_OK | side effect observed |
| D7.readpath.deny.cli_settings | vscode | cli_settings | EXECUTED | IGNORED | side effect observed |
| D7.readpath.deny.shared_config | vscode | shared_config | BLOCKED | HONORED | permission check failed for read_file "/var/tmp/agyv/rounds/h1/vscode/r020/out/c |
| D7.writepath.control | vscode | control | EXECUTED | BASELINE_OK | side effect observed |
| D7.writepath.deny.cli_settings | vscode | cli_settings | EXECUTED | IGNORED | side effect observed |
| D7.writepath.deny.shared_config | vscode | shared_config | BLOCKED | HONORED | permission check failed for write_file "/var/tmp/agyv/rounds/h1/vscode/r023/home |
| D8.url.control | vscode | control | NOT_ATTEMPTED | BASELINE_UNEXPECTED | agent did not call a matching tool |
| D8.url.deny.cli_settings | vscode | cli_settings | NOT_ATTEMPTED | OTHER | agent did not call a matching tool |
| D8.url.deny.shared_config | vscode | shared_config | NOT_ATTEMPTED | OTHER | agent did not call a matching tool |
| D10.mcp.control | vscode | control | EXECUTED | BASELINE_OK | side effect observed |
| D10.mcp.deny.cli_settings | vscode | cli_settings | EXECUTED | IGNORED | side effect observed |
| D10.mcp.deny.shared_config | vscode | shared_config | BLOCKED | HONORED | permission check failed for mcp "agyprobe/probe_echo": Permission denied for mcp |
| D10.mcp.extra.control | vscode | control | EXECUTED | BASELINE_OK | side effect observed |
| D10.mcp.disabledTools | vscode | mcp_config | BLOCKED | OTHER | tool error: declaring permissions: cortex tool call_mcp_tool: convert tool call  |
| D10.mcp.in_cli_settings | vscode | cli_settings | ASKED | OTHER | 4 permission prompt(s) raised |
| D11.hook.control | vscode | control | EXECUTED | BASELINE_OK | side effect observed |
| D11.hook.hooks_json | vscode | hooks | BLOCKED | HONORED | tool call denied by pre-tool hook: agy-verify guard: token 'hookblock' is blocke |
| D11.hook.in_cli_settings | vscode | cli_settings | EXECUTED | IGNORED | side effect observed |
| D11.hook.workspace | vscode | workspace | BLOCKED | HONORED | tool call denied by pre-tool hook: agy-verify guard: token 'hookblock' is blocke |
| D4.mode.always.cli_settings | vscode | cli_settings | EXECUTED | HONORED | side effect observed |
| D4.mode.eager.shared_config | vscode | shared_config | EXECUTED | HONORED | side effect observed |
| D5.plan.cli_settings | vscode | cli_settings | EXECUTED | IGNORED | side effect observed |
| D6.sandbox.control | vscode | control | EXECUTED | BASELINE_OK | side effect observed |
| D6.sandbox.cli_settings | vscode | cli_settings | EXECUTED | IGNORED | side effect observed |
| D6.sandbox.shared_config | vscode | shared_config | SANDBOXED | HONORED | command ran without network access (sandbox egress block) |
| D6.sandbox.urlallow.cli_settings | vscode | cli_settings | EXECUTED | HONORED | side effect observed |
| D6.sandbox_fs.cli_settings | vscode | cli_settings | EXECUTED | IGNORED | side effect observed |
| D6.sandbox_fs.shared_config | vscode | shared_config | SANDBOXED | HONORED | command ran but couldn't write outside the sandbox mounts |
| D6.egress.default | vscode | control | SANDBOXED | BASELINE_OK | command ran without network access (sandbox egress block) |
| D6.egress.cli_settings | vscode | cli_settings | SANDBOXED | HONORED | command ran without network access (sandbox egress block) |
| D6.egress.shared_config | vscode | shared_config | SANDBOXED | HONORED | command ran without network access (sandbox egress block) |
| D1.gateway.user_file_ignored | vscode | user_gateway | EXECUTED | IGNORED | side effect observed |
