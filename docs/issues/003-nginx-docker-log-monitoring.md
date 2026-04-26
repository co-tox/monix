# #003 Nginx / Docker 로그 모니터링 방안

## 개요

PRD §3.2.2 및 AGENDT.md §3.2에 명시된 Nginx·Docker 로그 모니터링을 Monix에 통합하기 위한
기술 옵션을 정리한다. 두 기능 모두 **읽기 전용** 원칙을 엄격히 준수하며 구현한다.

---

## 1. Nginx 로그 모니터링

### 1-A. 파일 직접 파싱 (권장 ✅)

Nginx가 기록하는 Access Log / Error Log 파일을 직접 읽어 분석한다.

**장점**
- Nginx 설정 변경 불필요 — 완전한 Read-only
- 표준 로그 포맷이므로 별도 모듈 설치 없이 정규식으로 파싱 가능
- macOS / Linux 모두 동일하게 동작

**구현 위치**: `monix/tools/logs/nginx.py`

#### Access Log 파싱 (Combined Log Format)

```
$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent"
```

파싱 목표:
- HTTP 상태 코드 분포: 2xx / 3xx / 4xx / 5xx 카운트
- 상위 요청 URL (빈도 기준)
- 상위 클라이언트 IP
- 느린 응답 (upstream 타임이 포함된 경우 `$request_time` 기준)

예시 정규식:
```python
_NGINX_ACCESS_RE = re.compile(
    r'(?P<ip>[\d.]+) - \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<method>\S+) (?P<path>\S+) \S+" (?P<status>\d{3}) (?P<bytes>\d+)'
)
```

#### Error Log 파싱

```
YYYY/MM/DD HH:MM:SS [level] PID#TID: *CID message, client: IP, server: DOMAIN, request: "...", host: "..."
```

파싱 목표: `[error]` / `[crit]` / `[alert]` 레벨 라인 필터링 및 집계

#### 등록 명령어
```
/log add @nginx-access -nginx /var/log/nginx/access.log
/log add @nginx-error  -nginx /var/log/nginx/error.log
```

#### 계획 기능 (Phase 2)
- `monix/tools/logs/nginx.py` 모듈 신규 개발
- `parse_access_line()` — 단일 라인 구조화
- `summarize_access_log()` — 상태코드 분포, 상위 URL 집계
- `tail_nginx_error()` — error 레벨 라인만 필터링

---

### 1-B. nginx stub_status 모듈 (비권장 ❌)

```
location /nginx_status {
    stub_status;
    allow 127.0.0.1;
    deny all;
}
```

- Active connections, requests/sec 등 실시간 메트릭 제공
- **단점**: nginx 설정 변경 필요, 관리자 권한 필요, 포트 노출
- Monix의 Read-only / 최소 설정 원칙과 맞지 않음

---

## 2. Docker 컨테이너 로그 모니터링

### 2-A. `docker logs` 명령어 래핑 (권장 ✅)

Docker CLI가 제공하는 `docker logs` 명령을 subprocess로 래핑한다.

**장점**
- Docker 설치만 있으면 바로 동작 — 파일 경로나 권한 불필요
- `--tail N` 으로 스냅샷, `-f` 플래그로 실시간 스트리밍 모두 지원
- stdout/stderr를 통합해서 읽을 수 있어 애플리케이션 출력 전체 커버

**구현 위치**: `monix/tools/logs/docker.py`

#### 등록 및 사용 명령어
```
/log add @web   -docker web_container
/log add @db    -docker postgres_db
/log @web               # 마지막 80줄
/log @web -n 200        # 마지막 200줄
/log @web --live        # 실시간 스트리밍 (Ctrl-C 종료)
```

#### 컨테이너 자동 탐색 (Phase 2)
```bash
docker ps --format "{{.Names}}\t{{.Status}}\t{{.Image}}"
```
→ `monix/tools/logs/docker.py:list_containers()` 로 구현, `/log docker-list` 명령어 추가

#### 계획 기능 (Phase 2)
- `monix/tools/logs/docker.py` 모듈 신규 개발
- `tail_container(container, lines)` — 스냅샷
- `follow_container(container, initial_lines)` — 실시간 스트리밍
- `list_containers()` — 실행 중 컨테이너 목록 조회
- 컨테이너 자원 사용량 (`docker stats --no-stream`) 은 `/status` 확장으로 별도 구현

---

### 2-B. Docker JSON 로그 파일 직접 읽기 (비권장 ❌)

```
/var/lib/docker/containers/<container-id>/<container-id>-json.log
```

- **단점**: root 권한 필요, container ID를 별도로 파악해야 함, 이식성 낮음
- `docker logs` 래핑이 훨씬 간단하고 안전

---

## 3. 단계별 구현 로드맵

| Phase | 내용 | 파일 |
|-------|------|------|
| **1 (현재)** | 앱 로그 등록·조회·실시간 스트리밍 | `tools/logs/app.py`, `tools/logs/registry.py` |
| **2** | Nginx Access/Error 로그 파싱·집계 | `tools/logs/nginx.py` |
| **2** | Docker 컨테이너 로그 래핑·탐색 | `tools/logs/docker.py` |
| **3** | LLM 연동 — 에러 패턴 자동 요약 | `core/assistant.py` 확장 |
| **3** | 알림 임계치 — 에러율 초과 시 경고 | `config/settings.py` 확장 |

---

## 4. 공통 설계 원칙

- **Read-only**: `docker logs`, `tail`, 파일 읽기만 사용. 컨테이너 정지·재시작 없음
- **실패 허용**: Docker 미설치, 파일 권한 없음 등 환경 문제는 `status: error` 로 graceful 처리
- **크로스 플랫폼**: Linux(`/proc`, `journalctl`)와 macOS(`/var/log`, Docker Desktop) 모두 고려
- **표준 라이브러리만**: `subprocess`, `re`, `pathlib`, `json` — 외부 의존성 추가 없음
