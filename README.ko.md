# Monix

**[English](./README.md) | [한국어](./README.ko.md)**

## 개요
<img width="800" height="450" alt="Image" src="https://github.com/user-attachments/assets/e49b62f6-fdd6-4e33-b30d-987be4c2696b" />


Monix는 서버 모니터링을 위한 터미널 네이티브 AI 어시스턴트입니다. 슬래시 커맨드 CLI와 provider 기반 대화형 에이전트를 결합하여, 운영자가 셸을 떠나지 않고 CPU, 메모리, 디스크, 프로세스, 서비스, 로그(일반 파일, Nginx, Docker), 웹훅 알림을 점검할 수 있게 합니다.

- **두 개의 인터페이스, 하나의 멘탈 모델** — 알려진 의도에는 빠른 `/슬래시` 명령을, 그 외에는 자연어 채팅을 사용합니다. 둘 다 동일한 기반 도구를 공유합니다.
- **자연어 설정** — 로그 등록, 웹훅 설정, 알림 토글을 자연어로 요청하면 에이전트가 직접 실행하고 결과를 알려줍니다.
- **서버 안전** — 서버 상태를 변경하는 명령(`rm`, `kill`, `systemctl restart` 등)은 절대 실행하지 않습니다. `~/.monix/` 아래의 Monix 자체 설정 파일만 쓸 수 있습니다.
- **런타임 의존성 0** — 표준 라이브러리만 사용 (`urllib`, `json`, `inspect`, `subprocess`, …).
- **크로스 플랫폼** — Linux (procfs) 및 macOS (vm_stat / sysctl).

---

## 설치

### macOS

```bash
pip install monix
```

### Ubuntu / Debian

```bash
sudo apt install pipx && pipx install monix && pipx ensurepath && source ~/.bashrc
```

### MCP 서버 지원 포함

```bash
pip install "monix[mcp]"
# 또는
pipx install "monix[mcp]"
```

---

## 시작하기

### 1. Provider 준비

- Gemini: [Google AI Studio](https://aistudio.google.com/app/apikey)에서 API 키를 발급받습니다.
- OpenAI Codex: Monix와 같은 사용자 환경에 Codex CLI를 설치한 뒤 `codex login`을 실행합니다.

### 2. monix 실행

```bash
monix
```

최초 실행 시 Gemini 또는 OpenAI Codex provider를 선택합니다. Gemini는 API 키가 없으면 숨김 입력과 유효성 검사를 진행합니다. 실험적 OpenAI Codex provider는 현재 사용자의 Codex CLI 로그인 상태를 재사용하며, 인증이 없으면 먼저 `codex login`을 실행하라고 안내합니다.

### 3. 원샷 모드

```bash
monix /stat cpu
monix /log /var/log/syslog 100
monix "왜 메모리 사용량이 이렇게 높지?"
```

### MCP 서버

```bash
monix-mcp
```

---

## 설정

### API 키 변경

```bash
monix --setup
```

### 플랫폼 변경 (자동 감지가 틀렸을 때)

```bash
monix --set-platform
```

### 환경 변수

| 변수 | 설명 | 기본값 |
| --- | --- | --- |
| `MONIX_LLM_PROVIDER` | LLM provider (`gemini` 또는 `openai-codex`) | 저장된 provider 또는 Gemini 호환 경로 |
| `GEMINI_API_KEY` | Gemini API 키 (저장된 키를 덮어씀) | — |
| `MONIX_LLM_MODEL` | 선택한 provider 모델 | `gemini-3.1-flash-preview` |
| `MONIX_MODEL` | 레거시 Gemini 모델 재정의 | `gemini-3.1-flash-preview` |
| `MONIX_LOG_FILE` | 기본 로그 파일 경로 | 자동 탐지 |
| `MONIX_CPU_WARN` | CPU 경고 임계값 (%) | `85.0` |
| `MONIX_MEM_WARN` | 메모리 경고 임계값 (%) | `85.0` |
| `MONIX_DISK_WARN` | 디스크 경고 임계값 (%) | `90.0` |
| `MONIX_DISCORD_WEBHOOK` | Discord 웹훅 URL | — |
| `MONIX_SLACK_WEBHOOK` | Slack 웹훅 URL | — |
| `MONIX_NOTIFY_COOLDOWN` | 알림 쿨다운 (초) | `3600` |
| `MONIX_NOTIFY_CPU` | CPU 알림 (`0`/`false`로 비활성화) | `1` |
| `MONIX_NOTIFY_MEM` | 메모리 알림 | `1` |
| `MONIX_NOTIFY_DISK` | 디스크 알림 | `1` |
| `MONIX_NOTIFY_LOG_ERRORS` | 로그 오류 알림 활성화 (`0`/`false`로 비활성화) | `0` |
| `MONIX_NOTIFY_LOG_SEVERITY` | 알림 최소 로그 심각도 (`error` 또는 `warn`) | `error` |
| `MONIX_NOTIFY_LOG_COOLDOWN` | 로그 알림 쿨다운 (초) | `300` |
| `MONIX_PLATFORM` | 플랫폼 재정의 (`linux`/`mac`) | 자동 |

현재 작업 디렉토리의 `.env` 파일은 자동으로 로드됩니다.

### 웹훅 알림 (앱 내 설정)

```
/notify set discord https://discord.com/api/webhooks/...
/notify set slack https://hooks.slack.com/services/...
/notify status
```

### 로그 오류 알림

`--live` 모드로 로그를 스트리밍하는 중 오류 패턴이 감지되면 웹훅 알림을 발송합니다. `ERROR`, `FATAL`, `CRITICAL`, `Exception`, `Traceback` 등의 패턴에 반응합니다.

```
# 로그 오류 알림 활성화
/notify set log-errors on

# 최소 심각도: ERROR만 (기본값) 또는 WARN 이상도 포함
/notify set log-severity error

# 동일 소스에서 반복 알림 간격 (초)
/notify set log-cooldown 300

# 특정 패턴을 포함한 줄은 알림에서 제외 (대소문자 구분 없음)
/notify set log-ignore add ConnectionRefused
/notify set log-ignore add "404 Not Found"
/notify set log-ignore list
/notify set log-ignore remove ConnectionRefused
/notify set log-ignore clear
```

활성화 이후 `/log @alias --live`, `/docker @alias --live` 등 모든 `--live` 스트림에서 일치하는 오류 줄을 자동으로 웹훅으로 발송하며, 무시 패턴에 해당하는 줄은 건너뜁니다.

---



### 예시

```text
> /stat cpu
  CPU 23.4%   load 0.41 / 0.38 / 0.30

> /log @api --search timeout
  [최근 500줄에서 3건 일치]
  2026-04-26 12:14:02  ERROR  upstream timeout (10s) on /v1/orders
  ...

> 메모리를 가장 많이 쓰는 컨테이너를 보여줘
  → tool: list_containers
  → tool: ... (스냅샷과 상관관계 분석)
  RSS 기준 최상위 컨테이너는 `payments-api` (1.2 GB / 2 GB cap).
  최근 재시작: 0회.  추천 후속 작업: /docker logs payments-api
```

---

## 자연어 인터페이스

자유 텍스트 입력은 모두 설정된 LLM provider로 전달됩니다. 모델은 서버 모니터링 도구(읽기 전용)와 설정 도구(Monix 자체 config 쓰기)를 선택해 호출하며, 결과는 동등한 슬래시 커맨드와 동일한 Rich 패널로 출력됩니다.

### 모니터링 질의

```text
> CPU가 왜 이렇게 높지?
> 디스크 I/O 보여줘
> nginx 서비스 상태 확인해줘
> @api 로그 tail 해줘
> payments 컨테이너에서 에러 찾아줘
```

### 자연어로 설정 변경

슬래시 커맨드 문법을 외우지 않아도 원하는 것을 말하면 됩니다.

```text
> /var/log/api.log 를 @api 로 등록해줘
  [등록] app 로그: @api -> /var/log/api.log

> Discord 웹훅을 https://discord.com/api/webhooks/... 로 설정해줘
  Discord 웹훅 URL 저장됨.

> 로그 에러 알림 켜고 심각도 warn 이상으로 설정해줘
  로그 에러 알림 활성화됨.
  로그 알림 최소 심각도가 'warn'으로 설정됨.

> healthcheck 포함 줄은 로그 알림에서 제외해줘
  무시 패턴 추가됨: 'healthcheck'

> 메트릭 수집을 1시간 간격, 30일 보관, ~/metrics 폴더로 설정해줘
  히스토리 수집 설정 완료
    수집 간격: 1.0h  /  보존 기간: 30.0d  /  저장 폴더: ~/metrics
```

### 안전 경계

| 동작 | 자연어 | 슬래시 커맨드 |
| --- | --- | --- |
| 서버 메트릭 / 로그 / 서비스 조회 | 가능 | 가능 |
| 로그 등록, 웹훅 설정, 알림 토글 | 가능 (tool 호출) | 가능 |
| 설정 삭제 / 초기화 | CLI 안내만 | 가능 |
| 서버 파괴적 명령 | 절대 불가 | 절대 불가 |

---

## 슬래시 커맨드

### 스냅샷 및 실시간 모니터링

| 명령어 | 용도 |
| --- | --- |
| `/stat [cpu\|memory\|disk\|swap\|net\|io\|all]` | 현재 스냅샷, 또는 수집된 이력은 `/stat cpu 24h` |
| `/watch [metric] [sec]` | 실시간 갱신 대시보드 (Ctrl-C로 중지) |
| `/cpu` `/memory` `/disk` `/swap` `/net` `/io` | 단일 메트릭 단축키 |
| `/top [N]` | CPU 기준 상위 N개 프로세스 |

### 로그

| 명령어 | 용도 |
| --- | --- |
| `/log add @alias -app <path>` | 애플리케이션 로그를 별칭으로 등록 |
| `/log add @alias -nginx <path>` | Nginx 로그 등록 |
| `/log add @alias -docker <name>` | Docker 컨테이너 로그 등록 |
| `/log list` | 등록된 모든 별칭 표시 |
| `/log @alias [-n N]` | 등록된 로그 tail |
| `/log @alias --search [pattern]` | 에러 / 정규식 패턴 필터링 |
| `/log @alias --live` | 라이브 스트리밍 |
| `/log /path [-n N] [--live]` | 직접 경로 접근(등록 불필요) |
| `/log remove @alias` | 등록 해제 |
| `/logs <path> [N]` | 일회성 tail (레거시 형식) |

### Docker

| 명령어 | 용도 |
| --- | --- |
| `/docker ps` | 실행 중인 컨테이너 목록 |
| `/docker add @alias <name>` | 컨테이너 별칭 등록 |
| `/docker @alias [-n N] [--search] [--live]` | tail / 검색 / 스트림 |
| `/docker logs\|search\|live <name>` | 직접 호출 (별칭 없이) |
| `/docker remove @alias` | 등록 해제 |

### 알림

| 명령어 | 용도 |
| --- | --- |
| `/notify test [discord\|slack]` | 설정된 웹훅으로 테스트 알림 발송. 대상 생략 시 둘 다 발송 |
| `/notify status` | 웹훅 설정, 쿨다운, 메트릭별 토글, 마지막 발송 상태 표시 |
| `/notify help` | 알림 명령어와 환경변수 레퍼런스 표시 |

### 서비스 및 AI

| 명령어 | 용도 |
| --- | --- |
| `/service <name>` | systemd 서비스 상태 |
| `/ask <question>` | 설정된 LLM provider로 강제 라우팅 |
| `/clear` | 현재 대화 이력 삭제 |
| `/help` | 전체 커맨드 레퍼런스 표시 |
| `/exit` | 종료 |

### 백그라운드 메트릭 수집기

| 명령어 | 용도 |
| --- | --- |
| `/collect set <interval> <retention> <folder>` | 주기적 스냅샷 수집 시작 (예: `1h 30d ./metrics`) |
| `/collect list` | 설정 및 실행 상태 표시 |
| `/collect remove` | 비활성화 및 설정 삭제 |

### 웹훅 알림 설정

Monix는 임계치 알림을 Discord와 Slack 웹훅 포맷으로 만들 수 있습니다. 동일한 알림의 반복 발송은 `~/.monix/notify_state.json` 상태 파일을 기준으로 제한됩니다.

```bash
export MONIX_DISCORD_WEBHOOK="https://discord.com/api/webhooks/..."
export MONIX_SLACK_WEBHOOK="https://hooks.slack.com/services/..."
export MONIX_NOTIFY_COOLDOWN=3600

# 메트릭별 알림 토글. 0, false, no로 비활성화합니다.
export MONIX_NOTIFY_CPU=1
export MONIX_NOTIFY_MEM=1
export MONIX_NOTIFY_DISK=1

# 로그 오류 알림 설정 (--live 모드)
export MONIX_NOTIFY_LOG_ERRORS=1       # 활성화 (기본값: 0=비활성화)
export MONIX_NOTIFY_LOG_SEVERITY=error # error | warn
export MONIX_NOTIFY_LOG_COOLDOWN=300   # 소스별 알림 간격 (초)
```

---

## 에이전트 대화 (멀티턴 내부 동작)

Monix의 대화 모드는 **2차원 멀티턴 루프**이며, `monix/core/assistant.py` 와 `monix/llm/` 에 구현되어 있습니다.

| 차원 | 의미 | 상태 |
| --- | --- | --- |
| **A. 대화 턴** | 이전 컨텍스트를 가지고 이어지는 사용자 프롬프트들 | 호출자 소유 `history: list[dict]`, REPL 턴에 걸쳐 누적 |
| **B. 도구 호출 턴** | 한 사용자 프롬프트 내에서 모델은 답변 전에 도구를 반복 호출할 수 있음 | `answer_stream()` 내부 루프 — `_MAX_TOOL_ROUNDS = 5`로 제한 |

텍스트 응답은 SSE(`GeminiClient`의 `stream_round` / `chat_stream`)를 통해 토큰 단위로 스트리밍되어 터미널에 점진적으로 출력됩니다. 도구 호출 자체는 각 라운드 내에서 동기적으로 실행됩니다.

### 도구 분류

| 분류 | 도구 | 효과 |
| --- | --- | --- |
| 메트릭 | `cpu_info`, `cpu_usage_percent`, `memory_info`, `disk_info`, `swap_info`, `network_io`, `disk_io`, `collect_snapshot`, `top_processes`, `all_processes` | 읽기 전용 |
| 서비스 | `list_services`, `service_status` | 읽기 전용 |
| Docker | `list_containers`, `container_stats`, `container_processes`, `container_inspect` | 읽기 전용 |
| 로그 | `tail_log`, `search_log`, `tail_nginx_access`, `tail_container`, `search_container` | 읽기 전용 |
| 설정 쓰기 | `log_add`, `notify_set_webhook`, `notify_set_metric_alert`, `notify_set_cooldown`, `notify_set_log_errors`, `notify_set_log_severity`, `notify_set_log_cooldown`, `notify_add_log_ignore`, `collect_set_config` | `~/.monix/` 에만 씀 |

읽기 도구가 단독으로 호출되면 결과는 슬래시 커맨드와 동일한 Rich 패널로 직접 렌더링됩니다. 설정 쓰기 도구는 완료 메시지를 반환합니다. 파괴적 액션(`/log remove`, `/notify reset` 등)은 절대 실행하지 않고 CLI 명령을 안내합니다.

### 프롬프트별 루프

```
1. 새로운 스냅샷(CPU/메모리/디스크/프로세스/알림)을 찍어
   등록된 로그 별칭 테이블과 함께 사용자 텍스트에 추가 —
   모델에게 현재 "세계관"을 미리 제공한다.

2. 작업 이력 + 도구 스키마를 스트리밍으로 선택된 provider에 전송
   (stream_round).

3. SSE 스트림 소비:
     • 텍스트 청크          → 터미널에 점진적으로 출력.
     • functionCall(들)     → call_tool()로 각각 실행하고,
                              모델 후보(thought_signature를
                              보존한 원본 그대로)와
                              functionResponse 부분들을
                              작업 이력에 추가한 뒤 다시 루프.
     • 텍스트만(fc 없음)    → 종료 상태, (user, model)을
                              호출자 이력에 추가하고 반환.

4. 5턴 후에는 도구가 비활성화된 스트리밍 요약 호출(chat_stream)로
   루프가 종료되어, 모델이 이미 본 정보로 답변하도록 강제된다.
```
