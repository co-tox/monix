# Log Tools 개선 작업 목록

> 기준: `monix/tools/logs/` 코드 리뷰 (2026-04-26)
> 완료된 수정 사항은 하단 참조.

---

## 남은 작업

### 🟢 Low

#### 1. `follow_log()` — 로그 로테이션 재연결 미지원
**파일:** `app.py:follow_log`

현재 구현은 `tail -f`가 종료되면 `None` sentinel을 yield하고 멈춤. 로그 파일이 rotate된 경우 자동으로 새 파일에 재연결하지 않음.

**권장 조치:** 파일 변경 감지 후 새 경로로 재연결하는 루프 구현. Linux는 `inotify`, macOS는 `kqueue` 또는 polling 방식.

---

#### 2. nginx — 커스텀 로그 포맷 미지원
**파일:** `nginx.py`

`_ACCESS_RE`는 nginx Combined Log Format만 처리. nginx 설정에서 `log_format` 커스터마이징 시 `parse_access_line()`이 항상 `None` 반환.

**권장 조치:** `tail_nginx_access()` / `parse_access_line()`에 커스텀 정규식 파라미터 추가, 또는 자동 포맷 감지 로직.

---

## 완료된 수정 (2026-04-26)

| # | 파일 | 내용 |
|---|---|---|
| ✅ | `app.py` | `assert proc.stdout` → `if not proc.stdout: raise RuntimeError(...)` |
| ✅ | `docker/containers.py` | `assert proc.stdout` → `if not proc.stdout: raise RuntimeError(...)` |
| ✅ | `docker/containers.py` | bare `Exception` catch → 구체적 예외 목록으로 교체 |
| ✅ | `app.py` | `tail_log()`, `search_log()`에 `lines < 1` 입력 검증 추가 |
| ✅ | `docker/containers.py` | `tail_container()`에 `lines < 1` 입력 검증 추가 |
| ✅ | `app.py` | 잘못된 regex fallback 시 결과에 `"warning"` 키 추가 |
| ✅ | `registry.py` | JSON 파싱 실패 / 잘못된 타입 시 `warnings.warn()` 발생 |
| ✅ | `_types.py` | `TailResult`, `SearchResult`, `NginxTailResult` 등 TypedDict 스키마 정의 |
| ✅ | `app.py`, `docker/containers.py`, `nginx.py` | TypedDict 반환 타입 적용으로 스키마 통일 |
| ✅ | `app.py`, `docker/containers.py` | `follow_log()` / `follow_container()` EOF 시 `None` sentinel yield |
| ✅ | `registry.py` | 모듈 수준 캐시 추가, 중복 파일 I/O 제거 |
| ✅ | `registry.py` | `add()`에 alias/log_type 입력 검증 추가 |
| ✅ | `docker/containers.py` | `_pipe_ready()` + `_FOLLOW_CONNECT_TIMEOUT`으로 connect timeout 추가 |
| ✅ | `app.py` | 에러 처리 명시적 예외로 통일 (`FileNotFoundError`, `CalledProcessError`, `TimeoutExpired`, `OSError`) |
| ✅ | `app.py`, `docker/containers.py`, `nginx.py` | 매직 넘버 상수화 (`DEFAULT_TAIL_LINES` 등) |
| ✅ | `app.py` | `.gz`, `.bz2`, `.xz` 압축 로그 파일 지원 (`_open_compressed`) |
| ✅ | `app.py` | 압축 파일을 `follow_log()`에 전달 시 명시적 `ValueError` 발생 |
| ✅ | `nginx.py` | Combined Log Format 가정을 정규식 주석 및 docstring에 명시 |
| ✅ | `cli.py` | `follow_log()` / `follow_container()` 호출부에 `None` sentinel 처리 추가 |
| ✅ | `docker/` | `docker.py` → `docker/` 패키지로 재구성 (`containers.py` 분리) |
| ✅ | `docker/containers.py` | `search_container()` 추가 — Docker 컨테이너 로그 패턴 검색 |
