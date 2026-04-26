# Server Install Guide

## 1. Install Python Package

Copy this repository to the server, then run:

```bash
python3 -m pip install .
```

If the server blocks global package installs, use a virtual environment:

```bash
python3 -m venv /opt/monix/venv
/opt/monix/venv/bin/python -m pip install .
ln -s /opt/monix/venv/bin/monix /usr/local/bin/monix
```

## 2. Optional Claude Analysis

To enable Claude-backed analysis:

```bash
export ANTHROPIC_API_KEY="..."
export MONIX_MODEL="claude-sonnet-4-5-20250929"
```

For persistent configuration, put these values in the service user's shell profile or environment manager.

## 3. Run

Interactive mode:

```bash
monix
```

This opens the terminal UI immediately. If the server does not already use the real Claude Code CLI and you want the same launch command shape, add:

```bash
alias claude='monix'
```

Persist it in the shell profile for the server user:

```bash
echo "alias claude='monix'" >> ~/.bashrc
source ~/.bashrc
```

Non-interactive checks:

```bash
monix status
monix top --limit 20
monix service nginx
monix logs /var/log/syslog --lines 100
```

## 4. Thresholds

Defaults:

```bash
MONIX_CPU_WARN=85
MONIX_MEM_WARN=85
MONIX_DISK_WARN=90
```

Set stricter thresholds for smaller production hosts:

```bash
export MONIX_CPU_WARN=75
export MONIX_MEM_WARN=80
export MONIX_DISK_WARN=85
```

## Operational Notes

- Monix is read-only by design.
- `/service` requires `systemctl`; on non-systemd hosts it reports that service status is unavailable.
- `/logs` can only read files permitted for the current user. Use a monitoring user with the minimum log read permissions needed.
- Claude analysis sends the current snapshot JSON to Anthropic when `ANTHROPIC_API_KEY` is configured.
