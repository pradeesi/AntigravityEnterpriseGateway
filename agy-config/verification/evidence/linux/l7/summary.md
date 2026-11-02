| case | surface | placement | outcome | verdict | reason |
|---|---|---|---|---|---|
| D6.egress.default | cli | control | ASKED | BASELINE_UNEXPECTED | headless mode auto-denied an action that needed a prompt |
| D6.egress.cli_settings | cli | cli_settings | SANDBOXED | HONORED | command ran without network access (sandbox egress block) |
| D6.egress.cli_settings.approved | cli | cli_settings | EXECUTED | IGNORED | side effect observed |
| D6.egress.shared_config | cli | shared_config | ASKED | OTHER | headless mode auto-denied an action that needed a prompt |
