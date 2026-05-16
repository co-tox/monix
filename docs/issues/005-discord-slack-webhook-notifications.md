# Issue: Discord / Slack 웹훅 알림 기능

## 요약

서버 메트릭이 임계치를 초과하거나 로그에서 에러 패턴이 감지되었을 때 Discord 또는 Slack
채널로 자동 알림을 발송하는 웹훅 기능을 추가합니다.

---

## 트리거 조건

알림을 발송할 상황은 두 가지입니다.

### 1. 메트릭 임계치 초과
기존 `build_alerts(snapshot, thresholds)` (`monix/tools/system/metrics.py:37`)가
이미 알림 문자열 목록을 반환합니다. 이 결과가 비어있지 않을 때 웹훅을 호출합니다.

| 조건 | 기본 임계치 |
|------|-----------|
| CPU 사용률 초과 | 85% (`MONIX_CPU_WARN`) |
| 메모리 사용률 초과 | 85% (`MONIX_MEM_WARN`) |
| 디스크 사용률 초과 | 90% (`MONIX_DISK_WARN`) |

### 2. 로그 에러 감지 (선택 확장)
`tail_log()` / `follow_log()` 스트리밍 중 `error`, `critical`, `FATAL` 키워드가 포함된
줄이 감지될 때 알림을 발송합니다. (1차 구현에서는 메트릭 알림만 포함 권장)

---

## 아키텍처

### 신규 모듈: `monix/tools/notify/`

```
monix/tools/notify/
├── __init__.py       # send_alert() 공개 API
├── _types.py         # TypedDict: AlertPayload, NotifyConfig
├── webhook.py        # HTTP POST 공통 로직 (urllib 전용, 외부 의존성 없음)
├── discord.py        # Discord Embed 포맷 조립
└── slack.py          # Slack Block Kit 포맷 조립
```

외부 라이브러리를 추가하지 않고 표준 라이브러리 `urllib.request`만 사용합니다.

### 핵심 공개 API

```python
# monix/tools/notify/__init__.py
def send_alert(
    alerts: list[str],
    host: str,
    config: NotifyConfig,
) -> list[str]:
    """alerts를 설정된 웹훅(들)로 발송. 실패한 채널 이름 목록을 반환."""
```

### TypedDict 스키마 (`_types.py`)

```python
class AlertFilter(TypedDict, total=False):
    cpu: bool     # CPU 임계치 알림 발송 여부 (기본 True)
    memory: bool  # 메모리 임계치 알림 발송 여부 (기본 True)
    disk: bool    # 디스크 임계치 알림 발송 여부 (기본 True)

class NotifyConfig(TypedDict, total=False):
    discord_url: str | None      # Discord 웹훅 URL
    slack_url: str | None        # Slack 웹훅 URL
    cooldown_seconds: int        # 동일 알림 재발송 대기 시간 (기본 3600)
    state_path: str              # 쿨다운 상태 파일 경로
    alert_filter: AlertFilter    # 메트릭별 알림 on/off
```

`AlertFilter`의 모든 필드는 기본값이 `True`입니다. 명시적으로 `False`를 설정한 경우에만 해당 메트릭 알림을 건너뜁니다.

---

## 설정 연동

### 환경 변수 추가 (`Settings.from_env()`)

```
MONIX_DISCORD_WEBHOOK=https://discord.com/api/webhooks/...
MONIX_SLACK_WEBHOOK=https://hooks.slack.com/services/...
MONIX_NOTIFY_COOLDOWN=3600       # 초 단위, 기본값 1시간

# 메트릭별 알림 토글 (1=활성, 0=비활성, 기본값 모두 1)
MONIX_NOTIFY_CPU=1
MONIX_NOTIFY_MEM=1
MONIX_NOTIFY_DISK=1
```

`monix/config/settings.py`의 `Settings` dataclass에 필드 추가:

```python
discord_webhook: str | None
slack_webhook: str | None
notify_cooldown: int  # seconds
notify_cpu: bool      # CPU 알림 활성화
notify_mem: bool      # 메모리 알림 활성화
notify_disk: bool     # 디스크 알림 활성화
```

세 토글은 `_env_bool()` 헬퍼로 읽습니다. `"0"`, `"false"`, `"no"` (대소문자 무관)이면 `False`, 나머지는 `True`입니다.

### 쿨다운 / 중복 방지

같은 알림이 반복 발송되는 것을 막기 위해 상태 파일을 사용합니다.

- 위치: `~/.monix/notify_state.json`
- 구조: `{ "<alert_key>": "<ISO timestamp of last sent>" }`
- `alert_key`는 알림 문자열을 해시한 값 (예: `hashlib.sha1(alert.encode()).hexdigest()[:8]`)
- 마지막 발송 후 `cooldown_seconds` 미만이면 스킵

---

## 메시지 포맷

### Discord (Embed)

```json
{
  "embeds": [{
    "title": "⚠ Monix Alert — app-server-1",
    "color": 16711680,
    "fields": [
      { "name": "CPU", "value": "CPU usage is high: 92% >= 85%", "inline": false }
    ],
    "footer": { "text": "monix" },
    "timestamp": "2026-05-16T10:00:00"
  }]
}
```

- `color`: 경고 주황 `16744272` / 위험 빨강 `16711680` (알림 수에 따라 구분)
- 알림이 여러 개면 각각 별도 `field`로 추가

### Slack (Block Kit)

```json
{
  "blocks": [
    {
      "type": "header",
      "text": { "type": "plain_text", "text": "⚠ Monix Alert — app-server-1" }
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "• CPU usage is high: 92% >= 85%\n• Memory usage is high: 88% >= 85%"
      }
    },
    {
      "type": "context",
      "elements": [{ "type": "mrkdwn", "text": "monix | 2026-05-16 10:00:00" }]
    }
  ]
}
```

---

## 기존 코드 연동 지점

### 필터링 로직 (`__init__.py`)

`build_alerts()`는 항상 활성화된 모든 알림을 반환합니다. 웹훅 발송 직전에 `AlertFilter`로
걸러냅니다. CLI의 `/status` 화면에는 필터 적용 전 전체 목록이 표시됩니다.

```python
# 알림 문자열과 메트릭 키를 매핑하는 접두사 테이블
_ALERT_PREFIXES: dict[str, str] = {
    "cpu":    "CPU usage",
    "memory": "Memory usage",
    "disk":   "Disk usage",
}

def filter_alerts(alerts: list[str], alert_filter: AlertFilter) -> list[str]:
    """AlertFilter에 따라 비활성화된 메트릭의 알림 문자열을 제거."""
    result = []
    for alert in alerts:
        for key, prefix in _ALERT_PREFIXES.items():
            if alert.startswith(prefix):
                if alert_filter.get(key, True):  # 기본값 True
                    result.append(alert)
                break
        else:
            result.append(alert)  # 알 수 없는 알림은 통과
    return result
```

### `collect_snapshot()` 이후 자동 발송

`monix/tools/system/metrics.py`의 `collect_snapshot()`이 `alerts` 키를 이미 반환합니다.
이를 호출하는 측(CLI의 `/status` 또는 `--watch` 루프)에서 아래 패턴으로 연동합니다.

```python
from monix.tools.notify import send_alert

snapshot = collect_snapshot(settings)
if snapshot["alerts"]:
    send_alert(
        alerts=snapshot["alerts"],
        host=snapshot["host"],
        config=NotifyConfig(
            discord_url=settings.discord_webhook,
            slack_url=settings.slack_webhook,
            cooldown_seconds=settings.notify_cooldown,
            alert_filter=AlertFilter(
                cpu=settings.notify_cpu,
                memory=settings.notify_mem,
                disk=settings.notify_disk,
            ),
        ),
    )
```

### CLI 명령 추가 (`monix/cli.py`)

| 명령 | 동작 |
|------|------|
| `/notify test discord` | Discord 웹훅 연결 테스트 메시지 발송 |
| `/notify test slack` | Slack 웹훅 연결 테스트 메시지 발송 |
| `/notify status` | 현재 설정된 웹훅 URL 및 마지막 발송 시각 출력 |

---

## 구현 순서

1. `monix/tools/notify/_types.py` — `AlertFilter`, `NotifyConfig`, `AlertPayload` TypedDict 정의
2. `monix/tools/notify/webhook.py` — `_post_json(url, payload)` 구현 (urllib, timeout 5s)
3. `monix/tools/notify/discord.py` — `build_discord_payload(alerts, host)` 구현
4. `monix/tools/notify/slack.py` — `build_slack_payload(alerts, host)` 구현
5. `monix/tools/notify/__init__.py` — `filter_alerts()` + `send_alert()` + 쿨다운 로직 구현
6. `monix/config/settings.py` — `Settings`에 웹훅·토글 필드 추가 + `_env_bool()` 헬퍼
7. `monix/cli.py` — `/notify` 명령 추가
8. `collect_snapshot()` 호출 측 연동 (CLI watch 루프 또는 `/status`)
9. 테스트: `tests/tools/test_notify.py` — 모의 HTTP 서버로 페이로드 검증, 필터 동작 검증

---

## 완료 기준

- `MONIX_DISCORD_WEBHOOK` 설정 시 임계치 초과 알림이 Discord로 발송됨
- `MONIX_SLACK_WEBHOOK` 설정 시 동일하게 Slack으로 발송됨
- 두 URL이 모두 설정되어 있으면 동시에 발송됨
- `MONIX_NOTIFY_CPU=0` 설정 시 CPU 알림이 웹훅으로 발송되지 않음 (CLI 표시는 유지)
- `MONIX_NOTIFY_MEM=0` / `MONIX_NOTIFY_DISK=0` 도 동일하게 동작
- 토글이 모두 `0`이어도 오류 없이 동작 (필터 후 빈 목록이면 웹훅 호출 자체를 스킵)
- 쿨다운 시간 내에 동일 알림은 재발송하지 않음
- `/notify test` 명령으로 웹훅 연결 확인 가능
- 웹훅 URL 미설정 시 아무 동작 없음 (오류 없이 스킵)
- 웹훅 POST 실패 시 stderr 경고만 출력, 프로그램 중단 없음
- 외부 라이브러리 추가 없음 (`urllib.request`만 사용)
