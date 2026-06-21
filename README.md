# Monix

**[English](./README.md) | [한국어](./README.ko.md)**

## Overview
<img width="800" height="450" alt="Image" src="https://github.com/user-attachments/assets/e49b62f6-fdd6-4e33-b30d-987be4c2696b" />


Monix is a terminal-native AI assistant for server monitoring. It pairs a slash-command CLI with a provider-backed conversational agent so operators can inspect CPU, memory, disk, processes, services, logs (plain files, Nginx, Docker), and webhook alerts without leaving the shell.

- **Two interfaces, one mental model** — fast `/slash` commands for known intents, natural-language chat for everything else. Both share the same underlying tools.
- **Natural language configuration** — ask Monix to register logs, configure webhooks, and toggle alerts; it calls the right tool and confirms what it did.
- **Server-safe** — never executes destructive server commands (`rm`, `kill`, `systemctl restart`, etc.). Only reads system state and writes to Monix's own config files under `~/.monix/`.
- **Zero runtime dependencies** — standard library only (`urllib`, `json`, `inspect`, `subprocess`, …).
- **Cross-platform** — Linux (procfs) and macOS (vm_stat / sysctl).

---

## Installation

### macOS

```bash
pip install monix
```

### Ubuntu / Debian

```bash
sudo apt install pipx && pipx install monix && pipx ensurepath && source ~/.bashrc
```

### With MCP server support

```bash
pip install "monix[mcp]"
# or
pipx install "monix[mcp]"
```

---

## Setup

### 1. Prepare a provider

- Gemini: get an API key at [Google AI Studio](https://aistudio.google.com/app/apikey).
- OpenAI Codex: install Codex CLI in the same user environment, then run `codex login`.

### 2. Run monix

```bash
monix
```

On first launch, Monix asks whether to use Gemini or OpenAI Codex. Gemini setup prompts for a hidden API key when one is not already configured. The experimental OpenAI Codex provider reuses the current user's Codex CLI login and asks you to run `codex login` first when that auth is missing.

### 3. One-shot mode

```bash
monix /stat cpu
monix /log /var/log/syslog 100
monix "why is memory so high?"
```

### MCP server

```bash
monix-mcp
```

---

## Configuration

### Change API key

```bash
monix --setup
```

### Change platform (if auto-detection is wrong)

```bash
monix --set-platform
```

### Environment variables

| Variable | Description | Default |
| --- | --- | --- |
| `MONIX_LLM_PROVIDER` | LLM provider (`gemini` or `openai-codex`) | saved provider or Gemini legacy fallback |
| `GEMINI_API_KEY` | Gemini API key (overrides saved key) | — |
| `MONIX_LLM_MODEL` | Selected provider model | `gemini-3.1-flash-preview` |
| `MONIX_MODEL` | Legacy Gemini model override | `gemini-3.1-flash-preview` |
| `MONIX_LOG_FILE` | Default log file path | auto-detected |
| `MONIX_CPU_WARN` | CPU alert threshold (%) | `85.0` |
| `MONIX_MEM_WARN` | Memory alert threshold (%) | `85.0` |
| `MONIX_DISK_WARN` | Disk alert threshold (%) | `90.0` |
| `MONIX_DISCORD_WEBHOOK` | Discord webhook URL | — |
| `MONIX_SLACK_WEBHOOK` | Slack webhook URL | — |
| `MONIX_NOTIFY_COOLDOWN` | Alert cooldown (seconds) | `3600` |
| `MONIX_NOTIFY_CPU` | CPU alerts (`0`/`false` to disable) | `1` |
| `MONIX_NOTIFY_MEM` | Memory alerts | `1` |
| `MONIX_NOTIFY_DISK` | Disk alerts | `1` |
| `MONIX_NOTIFY_LOG_ERRORS` | Enable log error alerts (`0`/`false` to disable) | `0` |
| `MONIX_NOTIFY_LOG_SEVERITY` | Minimum log severity to alert on (`error` or `warn`) | `error` |
| `MONIX_NOTIFY_LOG_COOLDOWN` | Log alert cooldown (seconds) | `300` |
| `MONIX_PLATFORM` | Override platform (`linux`/`mac`) | auto |

A `.env` file in the current directory is loaded automatically.

### Webhook alerts (in-app)

```
/notify set discord https://discord.com/api/webhooks/...
/notify set slack https://hooks.slack.com/services/...
/notify status
```

### Log error alerts

Monix can send a webhook notification when an error pattern is detected while streaming logs with `--live`. Triggered by `ERROR`, `FATAL`, `CRITICAL`, `Exception`, `Traceback` and similar patterns.

```
# Enable log error alerts
/notify set log-errors on

# Minimum severity: only ERROR (default) or also WARN
/notify set log-severity error

# Cooldown between repeated alerts for the same source (seconds)
/notify set log-cooldown 300

# Ignore lines containing a specific pattern (case-insensitive)
/notify set log-ignore add ConnectionRefused
/notify set log-ignore add "404 Not Found"
/notify set log-ignore list
/notify set log-ignore remove ConnectionRefused
/notify set log-ignore clear
```

Once enabled, any `--live` stream (`/log @alias --live`, `/docker @alias --live`) will automatically send webhook alerts for matching error lines while skipping ignored patterns.

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

## Natural Language Interface

All free-text input is routed to the configured LLM provider. The model selects from monitoring tools (read-only server inspection) and configuration tools (write to Monix's own config). Both produce the same Rich panel output as the equivalent slash command.

### Monitoring queries

```text
> why is CPU so high?
> show disk I/O
> check the nginx service
> tail the @api log
> find errors in the payments container
```

### Configuration via natural language

Instead of memorising slash-command syntax, you can describe what you want:

```text
> register /var/log/api.log as @api
  [Registered] app log: @api -> /var/log/api.log

> set Discord webhook to https://discord.com/api/webhooks/...
  Discord webhook URL saved.

> enable log error alerts with warn severity
  Log error alerts enabled.
  Minimum log alert severity set to 'warn'.

> ignore healthcheck lines in log alerts
  Ignore pattern added: 'healthcheck'

> set metrics collection every 1 hour, keep 30 days, store in ~/metrics
  Metrics collector configured
    Interval: 1.0h  /  Retention: 30.0d  /  Folder: ~/metrics
```

### Safety boundary

| Action | Natural language | Slash command |
| --- | --- | --- |
| Read server metrics / logs / services | Yes | Yes |
| Register logs, set webhooks, toggle alerts | Yes (tool call) | Yes |
| Remove / reset configuration | CLI guidance only | Yes |
| Destructive server commands | Never | Never |

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

### Notifications

| Command | Purpose |
| --- | --- |
| `/notify test [discord\|slack]` | Send a test alert to the configured webhook; sends to both if omitted |
| `/notify status` | Show webhook configuration, cooldown, metric toggles, and last sent state |
| `/notify help` | Show notification command and environment variable reference |

### Services and AI

| Command | Purpose |
| --- | --- |
| `/service <name>` | systemd service status |
| `/ask <question>` | Force routing to the configured LLM provider |
| `/clear` | Clear current conversation history |
| `/help` | Show full command reference |
| `/exit` | Quit |

### Background metrics collector

| Command | Purpose |
| --- | --- |
| `/collect set <interval> <retention> <folder>` | Start periodic snapshot collection (e.g. `1h 30d ./metrics`) |
| `/collect list` | Show config and run state |
| `/collect remove` | Disable and delete config |

### Webhook alert configuration

Monix can format threshold alerts for Discord and Slack webhooks. Repeated identical alerts are rate-limited with a local state file at `~/.monix/notify_state.json`.

```bash
export MONIX_DISCORD_WEBHOOK="https://discord.com/api/webhooks/..."
export MONIX_SLACK_WEBHOOK="https://hooks.slack.com/services/..."
export MONIX_NOTIFY_COOLDOWN=3600

# Per-metric notification toggles. Use 0, false, or no to disable.
export MONIX_NOTIFY_CPU=1
export MONIX_NOTIFY_MEM=1
export MONIX_NOTIFY_DISK=1

# Log error alert settings (--live mode)
export MONIX_NOTIFY_LOG_ERRORS=1       # Enable (default: 0=off)
export MONIX_NOTIFY_LOG_SEVERITY=error # error | warn
export MONIX_NOTIFY_LOG_COOLDOWN=300   # Cooldown between alerts per source (seconds)
```

---

## Agent Conversation (Multi-Turn Internals)

Monix's conversational mode is a **two-dimensional multi-turn loop**, implemented in `monix/core/assistant.py` and `monix/llm/`.

| Dimension | Meaning | State |
| --- | --- | --- |
| **A. Conversation turns** | Successive user prompts, each carrying prior context | Caller-owned `history: list[dict]`, accumulated across REPL turns |
| **B. Tool-calling rounds** | Within one user prompt, the model may call tools repeatedly before answering | Loop inside `answer_stream()` — bounded by `_MAX_TOOL_ROUNDS = 5` |

Text responses are streamed incrementally via SSE (`stream_round` / `chat_stream` on `GeminiClient`), so output appears token-by-token while tool-specific Rich panels are preserved. Tool calls themselves are still executed synchronously within each round.

### Tool categories

| Category | Tools | Effect |
| --- | --- | --- |
| Metrics | `cpu_info`, `cpu_usage_percent`, `memory_info`, `disk_info`, `swap_info`, `network_io`, `disk_io`, `collect_snapshot`, `top_processes`, `all_processes` | Read-only |
| Services | `list_services`, `service_status` | Read-only |
| Docker | `list_containers`, `container_stats`, `container_processes`, `container_inspect` | Read-only |
| Logs | `tail_log`, `search_log`, `tail_nginx_access`, `tail_container`, `search_container` | Read-only |
| Config writes | `log_add`, `notify_set_webhook`, `notify_set_metric_alert`, `notify_set_cooldown`, `notify_set_log_errors`, `notify_set_log_severity`, `notify_set_log_cooldown`, `notify_add_log_ignore`, `collect_set_config` | Writes to `~/.monix/` only |

When a single read tool is called, its result is rendered directly as a Rich panel (same as the equivalent slash command). Config write tools return a confirmation message. Destructive actions (`/log remove`, `/notify reset`, etc.) are never executed by the model — it explains the CLI command instead.

### Per-prompt loop

```
1. Take a fresh snapshot (CPU/mem/disk/processes/alerts) and
   append it, plus the registered log alias table, to the user
   text — gives the model a current "world view" up front.

2. Send working history + tool schemas → selected provider
   via streaming (stream_round).

3. Consume the SSE stream:
     • text chunks        → printed incrementally to the terminal.
     • functionCall(s)    → execute each via call_tool(),
                            append the model candidate (verbatim,
                            preserving thought_signature) and the
                            functionResponse parts to the working
                            history, then loop.
     • text only (no fc)  → terminal state, append (user, model)
                            to caller history and return.

4. After 5 rounds the loop exits with a tools-disabled streaming
   summary call (chat_stream) so the model is forced to answer
   with what it already saw.
```
