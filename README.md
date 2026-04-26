# Monix

Monix is a terminal assistant for operating servers from the CLI. It gives you a conversational shell for read-only monitoring tasks such as status checks, process inspection, log tailing, and service health review.

It works without runtime dependencies. If `GEMINI_API_KEY` is set, Monix can ask Gemini to analyze the current server snapshot; otherwise it falls back to local intent handling.

## Install

From this directory:

```bash
uv venv
uv pip install -e ".[dev]"
```

Activate the virtual environment if you want to call `monix` directly:

```bash
source .venv/bin/activate
monix
```

## Usage

Start the interactive CLI:

```bash
uv run monix
```

This opens the terminal UI with a live server summary and a prompt:

```text
> CPU 상태 봐줘
> /top 10
> /logs /var/log/syslog 80
```

If you really want to launch it with a `claude` command on a server that does not already have Claude Code installed, add a shell alias:

```bash
alias claude='monix'
```

To keep that alias, put it in `~/.zshrc` or `~/.bashrc`.

Run one-shot checks:

```bash
uv run monix status
uv run monix top --limit 10
uv run monix logs /var/log/syslog --lines 80
uv run monix service nginx
uv run monix ask "CPU와 메모리 상태를 보고 위험한 부분을 알려줘"
```

Inside the interactive shell:

```text
/status
/watch 5
/top 15
/logs /var/log/syslog 100
/service nginx
/ask 지금 서버 상태 요약해줘
/help
/exit
```

Natural language also works for common monitoring requests:

```text
CPU 상태 보여줘
메모리랑 디스크 확인해줘
nginx 서비스 상태 알려줘
최근 로그 봐줘 /var/log/syslog
```

## Configuration

Environment variables:

- `GEMINI_API_KEY`: enables Gemini-backed analysis.
- `MONIX_MODEL`: Gemini model name. Defaults to `gemini-1.5-flash`.
- `MONIX_LOG_FILE`: default log file for `/logs`. Defaults to `/var/log/syslog` when it exists, otherwise `/var/log/messages`.
- `MONIX_CPU_WARN`: CPU warning threshold percent. Defaults to `85`.
- `MONIX_MEM_WARN`: memory warning threshold percent. Defaults to `85`.
- `MONIX_DISK_WARN`: disk warning threshold percent. Defaults to `90`.

Monix only performs read-only monitoring commands. It does not restart services, modify files, or run arbitrary shell commands.

## Project Structure

Monix follows the same broad shape used by agentic CLIs:

```text
monix/
  cli.py              # command parser and interactive REPL
  render.py           # terminal UI rendering
  config/             # environment-backed settings and thresholds
  core/               # assistant intent handling and local answers
  llm/                # Gemini API client
  tools/              # read-only monitoring tools
  safety/             # read-only policy definitions
  assistant.py        # backwards-compatible facade
  monitor.py          # backwards-compatible facade
```

The current tool layer is intentionally read-only:

- `tools/system.py`: host snapshot, CPU, memory, disk, uptime, alerts
- `tools/processes.py`: top process inspection
- `tools/logs.py`: log tailing
- `tools/services.py`: systemd service status
