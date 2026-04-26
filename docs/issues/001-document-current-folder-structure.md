# Issue: 현재 Monix 폴더 구조 문서화

## 요약

현재 Monix 저장소의 폴더 구조와 각 모듈의 역할을 문서화합니다. CLI 진입점, 터미널 렌더링, assistant 핵심 로직, LLM 연동, 모니터링 도구, 설정, 안전 정책의 책임 범위를 명확히 남겨 이후 변경 시 구조적 기준으로 사용할 수 있게 합니다.

## 현재 구조

```text
.
├── README.md
├── pyproject.toml
├── docs/
│   ├── server-install.md
│   └── issues/
│       └── 001-document-current-folder-structure.md
├── monix/
│   ├── __init__.py
│   ├── cli.py
│   ├── render.py
│   ├── assistant.py
│   ├── monitor.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py
│   ├── core/
│   │   ├── __init__.py
│   │   └── assistant.py
│   ├── llm/
│   │   ├── __init__.py
│   │   └── anthropic.py
│   ├── safety/
│   │   ├── __init__.py
│   │   └── policy.py
│   └── tools/
│       ├── __init__.py
│       ├── system.py
│       ├── processes.py
│       ├── logs.py
│       └── services.py
└── tests/
    └── test_monitor.py
```

로컬 개발 환경의 `.venv/`, `__pycache__/` 같은 생성물은 구조 설명 대상에서 제외합니다.

## 폴더 및 모듈 역할

### 루트

- `README.md`: 프로젝트 소개, 설치 방법, 사용법, 설정값, 구조 개요를 설명합니다.
- `pyproject.toml`: 패키지 메타데이터, 빌드 설정, `monix` CLI 엔트리포인트, 개발 의존성을 정의합니다.

### `docs/`

- `docs/server-install.md`: 서버 설치와 운영 관련 문서입니다.
- `docs/issues/`: 로컬 이슈나 작업 메모를 보관하는 문서 영역입니다.

### `monix/`

Monix의 실제 애플리케이션 패키지입니다.

- `cli.py`: CLI 엔트리포인트와 인터랙티브 REPL을 담당합니다. `monix status`, `monix top`, `monix logs`, `monix service`, `monix ask` 같은 명령과 `/status`, `/top`, `/logs`, `/service`, `/ask`, `/watch`, `/exit` 같은 slash command를 처리합니다.
- `render.py`: 터미널 UI 렌더링 계층입니다. 대시보드, 결과 패널, 상태 표시, 로그, 서비스 출력, 프로세스 테이블, ANSI 색상 및 no-color fallback을 담당합니다.
- `assistant.py`: 이전 import 경로를 유지하기 위한 호환 facade입니다. 실제 구현은 `monix.core` 및 `monix.llm` 쪽으로 위임합니다.
- `monitor.py`: 기존 모니터링 import 경로를 유지하기 위한 호환 facade입니다. `monix.tools`와 `monix.config`의 기능을 재노출합니다.

### `monix/config/`

환경 변수 기반 설정 계층입니다.

- `settings.py`: `ANTHROPIC_API_KEY`, `MONIX_MODEL`, `MONIX_LOG_FILE`, `MONIX_CPU_WARN`, `MONIX_MEM_WARN`, `MONIX_DISK_WARN` 등을 읽고 기본 로그 파일과 경고 임계값을 결정합니다.

### `monix/core/`

assistant의 핵심 의도 처리와 응답 생성 계층입니다.

- `assistant.py`: 일반적인 모니터링 질문에 대한 로컬 응답을 만들고, Claude 설정이 있으면 LLM 분석으로 라우팅하며, 설정이 없을 때는 로컬 규칙 기반 요약으로 fallback합니다.

### `monix/llm/`

외부 LLM 연동 계층입니다.

- `anthropic.py`: Anthropic Messages API 요청을 구성하고, 현재 서버 스냅샷을 Claude에 전달한 뒤 텍스트 응답을 반환합니다. API 및 모델 세부 사항을 CLI와 core 로직에서 분리합니다.

### `monix/tools/`

읽기 전용 서버 모니터링 도구 모음입니다.

- `system.py`: CPU, 메모리, 디스크, uptime, load average, threshold 기반 alert 등 호스트 스냅샷을 수집합니다.
- `processes.py`: `ps` 기반 top process 정보를 읽고 Linux/macOS 출력을 정규화합니다.
- `logs.py`: 지정 로그 파일의 마지막 N줄을 읽고, 누락/잘못된 경로/권한 문제를 구조화된 상태로 반환합니다.
- `services.py`: `systemctl` 기반 서비스 상태를 읽고, systemd가 없는 환경에서도 구조화된 상태를 반환합니다.

### `monix/safety/`

안전 정책 정의 계층입니다.

- `policy.py`: 현재 읽기 전용 도구 allowlist를 정의하고, 향후 쓰기 작업이나 승인 흐름을 추가할 때 사용할 정책 hook을 제공합니다.

### `tests/`

테스트 코드 영역입니다.

- `test_monitor.py`: 현재 모니터링 facade 및 도구 동작을 검증하는 테스트입니다.

## 구조 유지 규칙

- CLI 코드는 모니터링 수집 로직을 직접 구현하지 않습니다.
- 렌더링 코드는 외부 명령 실행을 담당하지 않습니다.
- LLM 클라이언트는 CLI 인자 파싱이나 터미널 출력을 담당하지 않습니다.
- 도구 계층은 렌더링된 문자열보다 구조화된 dict/list를 반환하는 방향을 유지합니다.
- 안전 정책은 개별 도구 구현과 독립적으로 유지합니다.
- `assistant.py`와 `monitor.py`는 얇은 호환 facade로 유지합니다.

## 후속 작업 제안

- 각 `monix/tools/*` 모듈에 대한 직접 단위 테스트를 추가합니다.
- `render.py`가 커지면 렌더링 하위 모듈로 분리합니다.
- 세션 기록이 필요해지면 `monix/storage/` 같은 별도 패키지를 추가합니다.
- 플러그인 로딩이 필요해지면 `monix/plugins/` 같은 별도 패키지를 추가합니다.
- 쓰기 작업을 지원하게 되면 승인 게이트를 `monix/safety/`에 확장합니다.
