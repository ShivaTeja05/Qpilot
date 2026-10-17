# Security policy

qPilot is research software for analysing qPCR data on your own computer. **It is for research use only and is not intended for clinical or diagnostic use.**

## Supported versions
| Version | Supported |
|---|---|
| 0.1.x | Yes |

## Reporting a vulnerability
Please report vulnerabilities privately through GitHub's **"Report a vulnerability"** button on this repository's **Security** tab (private vulnerability reporting). Do not open a public issue for a security problem.

We follow **coordinated disclosure**: we aim to acknowledge a report within 5 working days and to publish a fix or mitigation within 90 days, after which the reporter may disclose publicly. We will credit reporters who wish to be credited.

## Scope
In scope: the `qpilot` Python package, its command-line interface, the local web app, and the MCP server. The one-page threat model, with the test that backs each control, is in [`THREAT_MODEL.md`](THREAT_MODEL.md).

Out of scope: a compromised host, multi-user hosting, and clinical or diagnostic use.

## What we claim, and what backs it
- **Offline by default:** with provider `none`, the headless analysis path runs with network sockets disabled (`tests/core/test_offline.py`).
- **Agents cannot make conclusion-changing decisions through MCP:** the tool returns `pending_human`, enforced in code (`tests/core/test_decisions.py`, `tests/core/test_mcp_server.py`). An agent that can run commands in your shell can act as you, so give agents MCP access, not your shell.
- **Records are tamper-evident, not tamper-proof:** `qpilot verify` detects changed files, the first broken link in the decision chain, and card states the chain does not support (`tests/core/test_record.py`). Nothing is signed: a consistent rewrite of the whole record still passes.
