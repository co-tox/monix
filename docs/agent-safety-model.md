# Agent Safety Model

Monix의 자연어 에이전트가 실행할 수 있는 액션의 범위와 안전 경계를 정의합니다.

---

## 3-Tier 구조

모든 tool calling 액션은 가역성(reversibility)과 부수효과(side effect) 범위를 기준으로 세 단계로 분류됩니다.

### Tier 1 — 자동 실행 (읽기 전용)

서버 상태를 변경하지 않는 순수 조회 도구입니다. 에이전트가 자율적으로 호출하며 사용자 확인이 필요 없습니다.

| Tool | 용도 |
| --- | --- |
| `cpu_info` | CPU 사용률, 로드 평균, 코어별 사용률 |
| `memory_info` | 메모리 사용량 |
| `disk_info` | 디스크 사용량 |
| `swap_info` | 스왑 사용량 |
| `network_io` | 네트워크 I/O 속도 |
| `disk_io` | 디스크 I/O 속도 |
| `collect_snapshot` | 서버 전체 스냅샷 |
| `top_processes` | CPU 상위 프로세스 |
| `all_processes` | 전체 프로세스 목록 |
| `list_services` | 서비스 목록 |
| `service_status` | 서비스 상태 |
| `list_containers` | Docker 컨테이너 목록 |
| `container_stats` | 컨테이너 리소스 사용량 |
| `container_processes` | 컨테이너 내부 프로세스 |
| `container_inspect` | 컨테이너 상세 설정 |
| `tail_log` | 로그 파일 tail |
| `search_log` | 로그 파일 검색 |
| `tail_nginx_access` | Nginx 액세스 로그 |
| `tail_container` | 컨테이너 로그 tail |
| `search_container` | 컨테이너 로그 검색 |

단일 Tier 1 도구 호출은 LLM 텍스트 응답을 거치지 않고 슬래시 커맨드와 동일한 Rich 패널로 직접 렌더링됩니다.

---

### Tier 2 — 자동 실행 (되돌릴 수 있는 쓰기)

Monix 자체 설정 파일(`~/.monix/`)만 변경하는 도구입니다. 서버 상태에는 전혀 영향을 주지 않으며, 언제든 다시 설정하거나 되돌릴 수 있습니다. 에이전트가 실행 후 완료 메시지를 반환합니다.

| Tool | 용도 | 되돌리는 방법 |
| --- | --- | --- |
| `log_add` | 로그 소스 등록/업데이트 | `/log remove @alias` |
| `notify_set_webhook` | Discord/Slack URL 설정 | 같은 tool에 url=null 전달 |
| `notify_set_metric_alert` | 메트릭 알림 on/off | 같은 tool로 반전 |
| `notify_set_cooldown` | 메트릭 알림 쿨다운 설정 | 같은 tool로 재설정 |
| `notify_set_log_errors` | 로그 에러 알림 on/off | 같은 tool로 반전 |
| `notify_set_log_severity` | 로그 알림 심각도 설정 | 같은 tool로 재설정 |
| `notify_set_log_cooldown` | 로그 알림 쿨다운 설정 | 같은 tool로 재설정 |
| `notify_add_log_ignore` | 알림 무시 패턴 추가 | `/notify set log-ignore remove <pattern>` |
| `collect_set_config` | 히스토리 수집 설정 | `/collect remove` |

---

### Tier 3 — 실행 금지 (CLI 안내만)

되돌리기 어렵거나 외부 부수효과가 있는 액션입니다. 에이전트는 해당 CLI 명령을 설명하고 사용자가 직접 실행하도록 안내합니다. tool로 등록되지 않습니다.

| CLI 명령 | 이유 |
| --- | --- |
| `/log remove @alias` | 등록 삭제 — 되돌릴 수 없음 |
| `/notify set reset` | 전체 알림 설정 초기화 — 대량 삭제 |
| `/notify set log-ignore remove <pattern>` | 무시 패턴 삭제 |
| `/notify set log-ignore clear` | 무시 패턴 전체 삭제 |
| `/notify test [discord\|slack]` | 외부 웹훅 실제 발송 — 외부 부수효과 |
| `/collect remove` | 수집 설정 삭제 |

---

## 절대 불가 액션

Tier 분류와 무관하게 다음 액션은 자연어 및 슬래시 커맨드 어느 경로로도 실행되지 않습니다.

- 서버 프로세스 조작: `kill`, `pkill`, `systemctl restart/stop`, `docker stop/rm`
- 파일 시스템 변경: `rm`, `chmod`, `chown`, 임의 파일 쓰기
- 네트워크 설정 변경: `iptables`, `ufw`, 방화벽 규칙

이 원칙은 `monix/llm/prompts.py`의 `[Core Principles]` 섹션에 시스템 프롬프트로 고정되어 있습니다.

---

## 판단 기준

새로운 tool을 추가할 때 아래 기준으로 Tier를 결정합니다.

| 기준 | Tier 1 | Tier 2 | Tier 3 |
| --- | --- | --- | --- |
| 서버 상태 변경 | 없음 | 없음 | — |
| Monix 설정 변경 | 없음 | 있음 | 있음 |
| 되돌릴 수 있는가 | 해당 없음 | 가능 | 불가 또는 외부 부수효과 |
| Tool 등록 여부 | 등록 | 등록 | 미등록 |
