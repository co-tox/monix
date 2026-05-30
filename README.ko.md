# Monix

**[English](./README.md) | [한국어](./README.ko.md)**

## 개요
<img width="800" height="450" alt="Image" src="https://github.com/user-attachments/assets/e49b62f6-fdd6-4e33-b30d-987be4c2696b" />


Monix는 서버 모니터링을 위한 터미널 네이티브 **읽기 전용** AI 어시스턴트입니다. 슬래시 커맨드 CLI와 provider 기반 대화형 에이전트를 결합하여, 운영자가 셸을 떠나지 않고 — 그리고 어떠한 파괴적 명령도 실행하지 않고 — CPU, 메모리, 디스크, 프로세스, 서비스, 로그(일반 파일, Nginx, Docker), 웹훅 알림을 점검할 수 있게 합니다.

- **두 개의 인터페이스, 하나의 멘탈 모델** — 알려진 의도에는 빠른 `/슬래시` 명령을, 그 외에는 자연어 채팅을 사용합니다. 둘 다 동일한 기반 도구를 공유합니다.
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

> 옛 소스 설치에서 업그레이드하는 경우 잔여 실행 파일을 먼저 지우세요.
>
> ```bash
> rm -f ~/.local/bin/monix ~/.local/bin/monix-mcp
> ```

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
| `MONIX_LLM_MODEL` | 선택한 provider 모델 | provider 기본값 |
| `MONIX_MODEL` | 레거시 Gemini 모델 재정의 | `gemini-2.5-flash` |
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
| `MONIX_PLATFORM` | 플랫폼 재정의 (`linux`/`mac`) | 자동 |

현재 작업 디렉토리의 `.env` 파일은 자동으로 로드됩니다.

### 웹훅 알림 (앱 내 설정)

```
/notify set discord https://discord.com/api/webhooks/...
/notify set slack https://hooks.slack.com/services/...
/notify status
```

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
```

---

## 에이전트 대화 (멀티턴 내부 동작)

Monix의 대화 모드는 **2차원 멀티턴 루프**이며, `monix/core/assistant.py` 와 `monix/llm/` 에 구현되어 있습니다.

| 차원 | 의미 | 상태 |
| --- | --- | --- |
| **A. 대화 턴** | 이전 컨텍스트를 가지고 이어지는 사용자 프롬프트들 | 호출자 소유 `history: list[dict]`, REPL 턴에 걸쳐 누적 |
| **B. 도구 호출 턴** | 한 사용자 프롬프트 내에서 모델은 답변 전에 도구를 반복 호출할 수 있음 | `answer()` 내부 루프 — `_MAX_TOOL_ROUNDS = 5`로 제한 |

### 프롬프트별 루프

```
1. 새로운 스냅샷(CPU/메모리/디스크/프로세스/알림)을 찍어
   등록된 로그 별칭 테이블과 함께 사용자 텍스트에 추가 —
   모델에게 현재 "세계관"을 미리 제공한다.

2. 작업 이력 + 도구 스키마를 선택된 provider로 전송.

3. 응답 부분을 검사:
     • 텍스트만             → 종료 상태, (user, model)을
                              호출자 이력에 추가하고 반환.
     • functionCall(들)     → call_tool()로 각각 실행하고,
                              모델 후보(thought_signature를
                              보존한 원본 그대로)와
                              functionResponse 부분들을
                              작업 이력에 추가한 뒤 다시 루프.

4. 5턴 후에는 도구가 비활성화된 요약 호출로 루프가
   종료되어, 모델이 이미 본 정보로 답변하도록 강제된다.
```
