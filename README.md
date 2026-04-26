# Monix

**[English](./README.md) | [한국어](./README.ko.md)**

## Overview
<img width="800" height="450" alt="Image" src="https://github.com/user-attachments/assets/e49b62f6-fdd6-4e33-b30d-987be4c2696b" />
Monix is a terminal-native, **read-only** AI assistant for server monitoring. It pairs a slash-command CLI with a Gemini-backed conversational agent so operators can inspect CPU, memory, disk, processes, services, and logs (plain files, Nginx, Docker) without leaving the shell — and without ever issuing destructive commands.

- **Two interfaces, one mental model** — fast `/slash` commands for known intents, natural-language chat for everything else. Both share the same underlying tools.
- **Zero runtime dependencies** — standard library only (`urllib`, `json`, `inspect`, `subprocess`, …).
- **Cross-platform** — Linux (procfs) and macOS (vm_stat / sysctl).

---

## Quick Start

### Install

```bash
uv venv
uv pip install -e ".[dev]"
```

### Launch the interactive REPL

```bash
uv run monix
```

On first launch, Monix prompts for a Gemini API key (paste-friendly, hidden input). Skip with Enter to run in local-only mode.

### One-shot mode

```bash
uv run monix /stat cpu
uv run monix /log /var/log/syslog 100
uv run monix "why is memory so high?"
```

---



### Examples

```text
> /stat cpu
  CPU 23.4%   load 0.41 / 0.38 / 0.30

> /log @api --search timeout
  [3 matches in last 500 lines]
  2026-04-26 12:14:02  ERROR  upstream timeout (10s) on /v1/orders
  ...

> show me containers using the most memory
  → tool: list_containers
  → tool: ... (correlates with snapshot)
  Top container by RSS is `payments-api` (1.2 GB / 2 GB cap).
  Recent restarts: 0.  Suggested follow-up: /docker logs payments-api
```

---

## Slash Commands

### Snapshots and live monitoring

| Command | Purpose |
| --- | --- |
| `/stat [cpu\|memory\|disk\|swap\|net\|io\|all]` | Current snapshot, or `/stat cpu 24h` for collected history |
| `/watch [metric] [sec]` | Real-time refreshing dashboard (Ctrl-C to stop) |
| `/cpu` `/memory` `/disk` `/swap` `/net` `/io` | Single-metric shortcuts |
| `/top [N]` | Top-N processes by CPU |

### Logs

| Command | Purpose |
| --- | --- |
| `/log add @alias -app <path>` | Register an application log under an alias |
| `/log add @alias -nginx <path>` | Register an Nginx log |
| `/log add @alias -docker <name>` | Register a Docker container log |
| `/log list` | Show all registered aliases |
| `/log @alias [-n N]` | Tail a registered log |
| `/log @alias --search [pattern]` | Filter for errors / a regex pattern |
| `/log @alias --live` | Stream live |
| `/log /path [-n N] [--live]` | Direct path access (no registration) |
| `/log remove @alias` | Unregister |
| `/logs <path> [N]` | One-shot tail (legacy form) |

### Docker

| Command | Purpose |
| --- | --- |
| `/docker ps` | List running containers |
| `/docker add @alias <name>` | Register a container alias |
| `/docker @alias [-n N] [--search] [--live]` | Tail / search / stream |
| `/docker logs\|search\|live <name>` | Direct (no alias) |
| `/docker remove @alias` | Unregister |

### Services and AI

| Command | Purpose |
| --- | --- |
| `/service <name>` | systemd service status |
| `/ask <question>` | Force routing to Gemini |
| `/clear` | Clear current conversation history |
| `/help` | Show full command reference |
| `/exit` | Quit |

### Background metrics collector

| Command | Purpose |
| --- | --- |
| `/collect set <interval> <retention> <folder>` | Start periodic snapshot collection (e.g. `1h 30d ./metrics`) |
| `/collect list` | Show config and run state |
| `/collect remove` | Disable and delete config |

---

## Agent Conversation (Multi-Turn Internals)

Monix's conversational mode is a **two-dimensional multi-turn loop**, implemented in `monix/core/assistant.py` and `monix/llm/`.

| Dimension | Meaning | State |
| --- | --- | --- |
| **A. Conversation turns** | Successive user prompts, each carrying prior context | Caller-owned `history: list[dict]`, accumulated across REPL turns |
| **B. Tool-calling rounds** | Within one user prompt, the model may call tools repeatedly before answering | Loop inside `answer()` — bounded by `_MAX_TOOL_ROUNDS = 5` |

### Per-prompt loop

```
1. Take a fresh snapshot (CPU/mem/disk/processes/alerts) and
   append it, plus the registered log alias table, to the user
   text — gives the model a current "world view" up front.

2. Send working history + tool schemas → Gemini.

3. Inspect response parts:
     • text only          → terminal state, append (user, model)
                            to caller history and return.
     • functionCall(s)    → execute each via call_tool(),
                            append the model candidate (verbatim,
                            preserving thought_signature) and the
                            functionResponse parts to the working
                            history, then loop.

4. After 5 rounds the loop exits with a tools-disabled summary
   call so the model is forced to answer with what it already saw.
```
