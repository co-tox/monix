# monix/tools/logs — Log Monitoring Module / 로그 모니터링 모듈

## Overview / 개요

A collection of tools to view and stream server application logs, Nginx logs, and Docker container logs.
All features adhere to the **Read-only** principle and use only the Python standard library.

서버 애플리케이션 로그, Nginx 로그, Docker 컨테이너 로그를 조회·스트리밍하는 도구 모음.
모든 기능은 **읽기 전용(Read-only)** 원칙을 준수하며, Python 표준 라이브러리만 사용한다.

---

## 디렉토리 구조

```
monix/tools/logs/
├── README.md          # 이 문서
├── __init__.py        # 공개 API (패키지 진입점)
├── _types.py          # 공유 타입 정의 (TypedDict)
├── app.py             # 파일 기반 로그 조회·스트리밍 (압축 파일 지원 ✅)
├── registry.py        # 로그 등록 영속 관리 (캐싱 및 유효성 검사 추가 ✅)
├── nginx.py           # Nginx 로그 파싱·집계 (Phase 2 ✅)
└── docker/            # Docker 컨테이너 로그 모듈화 (Phase 2 ✅)
    ├── __init__.py
    └── containers.py  # 컨테이너 로그 래핑 및 검색
```

---

## 모듈 설명

### `app.py` — 앱 로그 핵심 함수

| 함수 | 시그니처 | 설명 |
|------|----------|------|
| `tail_log` | `(path, lines=80) → TailResult` | 파일 마지막 N줄 읽기 (압축 파일 지원) |
| `search_log` | `(path, pattern=None, lines=500) → SearchResult` | 키워드 검색 또는 에러 필터링 조회 |
| `filter_errors` | `(lines) → list[str]` | ERROR·WARN 패턴 라인만 필터 |
| `classify_line` | `(line) → Severity` | 단일 줄 심각도 분류 (`error`, `warn`, `normal`) |
| `follow_log` | `(path, initial_lines=20) → Iterator[str\|None]` | `tail -f` 실시간 스트리밍 제너레이터 |

**주요 특징**
- **압축 파일 지원**: `.gz`, `.bz2`, `.xz`, `.lzma` 확장자를 자동으로 감지하여 해제 후 읽습니다.
- **검색 강화**: `search_log` 시 정규표현식이 유효하지 않으면 리터럴 검색으로 자동 전환됩니다.
- **스트리밍**: `follow_log`는 파일이 회전하거나 삭제되어 `tail`이 종료되면 `None`을 반환합니다.

---

### `nginx.py` — Nginx 로그 분석

Nginx Access/Error 로그 형식을 이해하고 통계를 추출한다. (Combined Log Format 기준)

| 함수 | 시그니처 | 설명 |
|------|----------|------|
| `tail_nginx_access` | `(path, lines=200) → NginxTailResult` | Access 로그 tail 및 통계 요약 포함 |
| `summarize_access_log` | `(lines) → NginxSummary` | 상태 코드 분포, Top Path/IP 집계 |
| `parse_access_line` | `(line) → dict \| None` | Access 로그 한 줄 파싱 |
| `filter_nginx_errors` | `(lines) → list[str]` | Error 로그에서 심각도(error 이상) 필터 |
| `parse_error_line` | `(line) → dict \| None` | Error 로그 한 줄 파싱 |

---

### `registry.py` — 로그 등록 관리

등록 정보는 `~/.monix/log_registry.json` 에 영속 저장되며, 모듈 레벨 캐싱을 통해 성능을 최적화합니다.

**공개 함수**

| 함수 | 시그니처 | 설명 |
|------|----------|------|
| `load` | `() → list[LogEntry]` | 전체 목록 로드 (캐시 활용) |
| `add` | `(alias, type, path, container) → (LogEntry, is_new)` | 유효성 검사 후 등록 또는 업데이트 |
| `remove` | `(alias) → bool` | 등록 해제 |
| `get` | `(alias) → LogEntry \| None` | 단건 조회 |
| `aliases` | `() → list[str]` | alias 이름 목록 |

---

### `docker/` — Docker 컨테이너 로그

Docker CLI를 호출하여 로그를 가져옵니다. 컨테이너별 검색 기능이 추가되었습니다.

| 함수 | 시그니처 | 설명 |
|------|----------|------|
| `tail_container` | `(container, lines=80) → TailResult` | 컨테이너 로그 마지막 N줄 |
| `search_container` | `(container, pattern, lines=500) → SearchResult` | 컨테이너 로그 패턴 검색 |
| `follow_container` | `(container, lines=20) → Iterator[str\|None]` | 실시간 스트리밍 (타임아웃 감지) |
| `list_containers` | `() → list[dict]` | 실행 중인 컨테이너 목록 (`docker ps`) |

---

## CLI 명령어 레퍼런스

### 등록 관리

```bash
# 앱 로그 등록
/log add @api    -app    /var/log/myapp/api.log
/log add @nginx  -nginx  /var/log/nginx/access.log
/log add @web    -docker web_container

# Docker 전용 단축 명령어
/docker add @web web_container
```

### 로그 조회 및 검색

```bash
# 등록된 alias 사용
/log @api                   # 기본 80줄
/log @api --search "pattern" # 패턴 검색

# Docker 전용 조회
/docker logs @web
/docker search @web "error"
```

---

## 향후 계획

| Phase | 기능 | 파일 |
|-------|------|------|
| 3 | 에러 패턴 집계 ("최근 10분간 DB 타임아웃 15회") | `app.py` 확장 |
| 3 | LLM 연동 — 에러 로그 자동 요약 (`/ask` 확장) | `core/assistant.py` |

자세한 방안은 [`docs/issues/004-log-tools-improvements.md`](../../../docs/issues/004-log-tools-improvements.md) 참고.
