# monix/tools/logs — 로그 모니터링 모듈

## 개요

서버 애플리케이션 로그, Nginx 로그, Docker 컨테이너 로그를 조회·스트리밍하는 도구 모음.
모든 기능은 **읽기 전용(Read-only)** 원칙을 준수하며, Python 표준 라이브러리만 사용한다.

---

## 디렉토리 구조

```
monix/tools/logs/
├── README.md          # 이 문서
├── __init__.py        # 공개 API (패키지 진입점)
├── app.py             # 파일 기반 로그 조회·스트리밍 (Phase 1 ✅)
├── registry.py        # 로그 등록 영속 관리 (Phase 1 ✅)
├── docker.py          # Docker 컨테이너 로그 래핑 (Phase 2 🔲)
└── nginx.py           # Nginx 로그 파싱·집계 (Phase 2 🔲, 미생성)
```

---

## 모듈 설명

### `app.py` — 앱 로그 핵심 함수

| 함수 | 시그니처 | 설명 |
|------|----------|------|
| `tail_log` | `(path, lines=80) → dict` | 파일 마지막 N줄 읽기 |
| `filter_errors` | `(lines) → list[str]` | ERROR·WARN 패턴 라인만 필터 |
| `classify_line` | `(line) → 'error'\|'warn'\|'normal'` | 단일 줄 심각도 분류 |
| `follow_log` | `(path, initial_lines=20) → Iterator[str]` | `tail -f` 실시간 스트리밍 제너레이터 |

**`tail_log` 반환 형식**
```python
{
    "path": "/var/log/app.log",
    "status": "ok" | "missing" | "not_file" | "error",
    "lines": ["line1", "line2", ...]
}
```

**에러 감지 패턴** (`_ERROR_RE`)
```
ERROR, FATAL, CRITICAL, Exception, Traceback  (대소문자 무관)
```

**경고 감지 패턴** (`_WARN_RE`)
```
WARN, WARNING  (대소문자 무관)
```

---

### `registry.py` — 로그 등록 관리

등록 정보는 `~/.monix/log_registry.json` 에 영속 저장된다.

**`LogEntry` 데이터 모델**
```python
@dataclass
class LogEntry:
    alias: str                          # @alias 참조명
    type: Literal["app", "nginx", "docker"]
    path: str | None = None             # 파일 경로 (app·nginx)
    container: str | None = None        # 컨테이너 이름 (docker)
```

**공개 함수**

| 함수 | 시그니처 | 설명 |
|------|----------|------|
| `load` | `() → list[LogEntry]` | 전체 목록 로드 |
| `add` | `(alias, type, path, container) → (LogEntry, is_new)` | 등록 또는 업데이트 |
| `remove` | `(alias) → bool` | 등록 해제 |
| `get` | `(alias) → LogEntry \| None` | 단건 조회 |
| `aliases` | `() → list[str]` | alias 이름 목록 |

**저장 파일 예시** (`~/.monix/log_registry.json`)
```json
[
  {
    "alias": "api",
    "type": "app",
    "path": "/var/log/myapp/api.log",
    "container": null
  },
  {
    "alias": "web",
    "type": "docker",
    "path": null,
    "container": "web_container"
  }
]
```

---

### `docker.py` — Docker 컨테이너 로그 (Phase 2)

`docker logs` 명령을 subprocess로 래핑한다. Docker CLI가 설치된 환경에서만 동작하며,
미설치 시 `status: error` 로 graceful 처리된다.

| 함수 | 시그니처 | 설명 |
|------|----------|------|
| `tail_container` | `(container, lines=80) → dict` | 컨테이너 로그 마지막 N줄 |
| `follow_container` | `(container, initial_lines=20) → Iterator[str]` | 컨테이너 로그 실시간 스트리밍 |
| `list_containers` | `() → list[dict]` | 실행 중 컨테이너 목록 조회 |

> **현재 상태**: 함수 구현 완료, CLI 명령어(`/log add @alias -docker`)와 연결됨.
> 향후 `list_containers()`를 활용한 `/log docker-list` 명령어 추가 예정.

---

## CLI 명령어 레퍼런스

### 등록 관리

```bash
# 앱 로그 등록
/log add @api    -app    /var/log/myapp/api.log
/log add @nginx  -nginx  /var/log/nginx/access.log
/log add @web    -docker web_container

# 목록 확인
/log list

# alias 빠른 조회 (코딩 에이전트 스타일)
/log @

# 등록 해제
/log remove @api
```

### 로그 조회

```bash
# 등록된 alias 사용
/log @api                   # 기본 80줄
/log @api -n 200            # 200줄

# 경로 직접 지정 (등록 불필요)
/log /var/log/app.log
/log /var/log/app.log -n 50
/log @/var/log/app.log -n 50   # @ 접두사도 허용
```

### 실시간 스트리밍 (`tail -f`)

```bash
# 등록된 alias
/log @api --live
/log @api --live -n 100       # 초기 100줄 출력 후 스트리밍

# 경로 직접 지정
/log /var/log/app.log --live
/log /var/log/app.log --live -n 50
```

> Ctrl-C 로 종료. ERROR 줄은 빨간색, WARN 줄은 노란색으로 표시된다.

---

## 렌더링 연동

`render.py` 에 아래 함수가 추가되어 있다.

| 함수 | 설명 |
|------|------|
| `render_logs(result)` | tail_log 결과 출력 (ERROR/WARN 줄 컬러화) |
| `render_log_list(entries)` | 등록 목록 테이블 출력 |
| `render_log_aliases(aliases)` | alias 목록 출력 |
| `colorize_log_line(line)` | 단일 줄 컬러화 (실시간 스트리밍에 사용) |

---

## 향후 계획

| Phase | 기능 | 파일 |
|-------|------|------|
| 2 | Nginx Access Log 파싱 (상태코드 분포, 상위 URL) | `nginx.py` 신규 |
| 2 | Nginx Error Log 필터링 | `nginx.py` 신규 |
| 2 | `docker ps` 연동 컨테이너 자동 탐색 | `docker.py` 확장 |
| 3 | 에러 패턴 집계 ("최근 10분간 DB 타임아웃 15회") | `app.py` 확장 |
| 3 | LLM 연동 — 에러 로그 자동 요약 (`/ask` 확장) | `core/assistant.py` |

자세한 방안은 [`docs/issues/003-nginx-docker-log-monitoring.md`](../../../docs/issues/003-nginx-docker-log-monitoring.md) 참고.
