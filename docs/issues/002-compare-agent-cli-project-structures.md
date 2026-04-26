# Issue: Claude Code, Gemini CLI, Codex, Qwen Code 프로젝트 구조 비교

## 요약

Claude Code, Gemini CLI, Codex, Qwen Code 네 프로젝트의 공개 GitHub 저장소 구조를 비교해 Monix 구조 개선에 참고할 수 있는 패턴을 정리합니다.

- 확인일: 2026-04-26 KST
- 기준 브랜치: 각 저장소의 `main`
- 대상 저장소:
  - https://github.com/anthropics/claude-code
  - https://github.com/google-gemini/gemini-cli
  - https://github.com/openai/codex
  - https://github.com/QwenLM/qwen-code

## 1. Claude Code

### 구조 요약

```text
anthropics/claude-code
├── .claude-plugin/
├── .claude/
├── .devcontainer/
├── .github/
├── .vscode/
├── Script/
├── examples/
├── plugins/
├── scripts/
├── CHANGELOG.md
├── LICENSE.md
├── README.md
├── SECURITY.md
└── demo.gif
```

### 특징

- 공개 저장소는 핵심 CLI 구현 전체보다 설치, 예제, 플러그인, 문서성 자산 중심으로 구성되어 있습니다.
- `plugins/`가 매우 중요한 축입니다. 공식 플러그인들이 독립 디렉터리로 나뉘고, 각 플러그인은 표준 구조를 따릅니다.
- `plugins/README.md` 기준 플러그인 표준 구조는 다음과 같습니다.

```text
plugin-name/
├── .claude-plugin/
│   └── plugin.json
├── commands/
├── agents/
├── skills/
├── hooks/
├── .mcp.json
└── README.md
```

### 구조적 시사점

- 핵심 기능이 커지기 전에 확장 지점을 명시하는 구조가 중요합니다.
- 명령, agent, skill, hook, MCP 설정처럼 확장 요소를 서로 다른 책임 단위로 나누고 있습니다.
- Monix가 향후 플러그인이나 명령 확장을 지원한다면 `monix/plugins/`, `monix/commands/`, `monix/hooks/` 같은 경계를 미리 설계할 수 있습니다.

## 2. Gemini CLI

### 구조 요약

```text
google-gemini/gemini-cli
├── .allstar/
├── .gcp/
├── .gemini/
├── .github/
├── .husky/
├── .vscode/
├── docs/
├── evals/
├── integration-tests/
├── memory-tests/
├── packages/
│   ├── a2a-server/
│   ├── cli/
│   ├── core/
│   ├── devtools/
│   ├── sdk/
│   ├── test-utils/
│   └── vscode-ide-companion/
├── perf-tests/
├── schemas/
├── scripts/
├── sea/
├── third_party/
├── tools/
├── package.json
├── package-lock.json
├── tsconfig.json
├── Dockerfile
├── Makefile
├── README.md
├── ROADMAP.md
└── SECURITY.md
```

### 특징

- TypeScript/Node 기반 모노레포 구조입니다.
- 핵심 제품 코드는 `packages/` 아래에 `cli`, `core`, `sdk`, `devtools`, `test-utils`, IDE companion 등으로 분리되어 있습니다.
- 테스트가 목적별로 분리되어 있습니다.
  - `integration-tests/`: 통합 테스트
  - `memory-tests/`: 메모리 관련 테스트
  - `perf-tests/`: 성능 테스트
  - `packages/test-utils/`: 패키지 테스트 헬퍼
- `docs/`, `schemas/`, `scripts/`, `tools/`, `third_party/`가 제품 코드와 분리되어 있습니다.

### 구조적 시사점

- CLI 표면과 핵심 agent 로직을 분리하는 `packages/cli` + `packages/core` 패턴이 뚜렷합니다.
- SDK, IDE companion, A2A server처럼 외부 연동 표면을 별도 패키지로 분리합니다.
- 테스트도 단순 `tests/` 하나가 아니라 통합, 성능, 메모리 등 목적별 디렉터리로 확장합니다.
- Monix가 커질 경우 현재 `monix/cli.py`와 `monix/core/` 분리는 유지하되, 외부 API/SDK/IDE 연동은 별도 패키지 또는 하위 모듈로 분리하는 방향이 자연스럽습니다.

## 3. Codex

### 구조 요약

```text
openai/codex
├── .codex/
├── .devcontainer/
├── .github/
├── .vscode/
├── codex-cli/
│   ├── bin/
│   ├── scripts/
│   └── package.json
├── codex-rs/
│   ├── cli/
│   ├── core/
│   ├── tui/
│   ├── protocol/
│   ├── tools/
│   ├── exec/
│   ├── exec-server/
│   ├── execpolicy/
│   ├── sandboxing/
│   ├── mcp-server/
│   ├── codex-mcp/
│   ├── config/
│   ├── login/
│   ├── model-provider/
│   ├── model-provider-info/
│   ├── rollout/
│   ├── thread-store/
│   ├── state/
│   ├── skills/
│   ├── core-skills/
│   ├── core-plugins/
│   ├── connectors/
│   ├── hooks/
│   ├── file-search/
│   ├── git-utils/
│   ├── shell-command/
│   ├── shell-escalation/
│   ├── secrets/
│   ├── analytics/
│   ├── feedback/
│   └── Cargo.toml
├── docs/
├── patches/
├── scripts/
├── sdk/
│   ├── python-runtime/
│   ├── python/
│   └── typescript/
├── third_party/
├── tools/
├── BUILD.bazel
├── MODULE.bazel
├── package.json
├── pnpm-workspace.yaml
├── justfile
├── README.md
└── SECURITY.md
```

### 특징

- 현재 유지되는 CLI 구현은 `codex-rs/` 중심의 Rust workspace입니다.
- 루트는 배포, 문서, SDK, legacy/launcher 성격의 `codex-cli/`, Rust 구현체 `codex-rs/`를 함께 관리합니다.
- `codex-rs/` 내부는 매우 세분화되어 있습니다.
  - 사용자 표면: `cli/`, `tui/`
  - 핵심 agent 로직: `core/`
  - 실행 계층: `exec/`, `exec-server/`, `execpolicy/`, `sandboxing/`
  - 외부 통신/프로토콜: `protocol/`, `mcp-server/`, `codex-mcp/`, `connectors/`
  - 설정/인증/모델: `config/`, `login/`, `model-provider/`
  - 작업 상태와 기록: `state/`, `thread-store/`, `rollout/`
  - 확장성: `skills/`, `core-skills/`, `core-plugins/`, `hooks/`
  - 도구와 유틸리티: `tools/`, `file-search/`, `git-utils/`, `shell-command/`
- SDK는 `sdk/python-runtime`, `sdk/python`, `sdk/typescript`로 언어별 표면을 분리합니다.

### 구조적 시사점

- CLI, TUI, core, tool execution, sandbox/policy, protocol, state, extension system을 강하게 분리합니다.
- shell 실행, escalation, sandboxing, secrets 같은 위험 영역을 별도 모듈로 격리합니다.
- agent 제품이 커질수록 “도구 실행”과 “정책/권한”을 같은 파일에 두지 않는 것이 중요합니다.
- Monix가 읽기 전용 모니터링을 넘어 쓰기 작업이나 승인 흐름을 지원한다면 `monix/safety/`, `monix/tools/`, `monix/core/` 사이의 책임 경계를 더 강하게 유지해야 합니다.

## 4. Qwen Code

### 구조 요약

```text
QwenLM/qwen-code
├── .github/
├── .husky/
├── .qwen/
├── .vscode/
├── docs-site/
├── docs/
├── eslint-rules/
├── integration-tests/
├── packages/
│   ├── channels/
│   ├── cli/
│   ├── core/
│   ├── sdk-java/
│   ├── sdk-python/
│   ├── sdk-typescript/
│   ├── vscode-ide-companion/
│   ├── web-templates/
│   ├── webui/
│   └── zed-extension/
├── scripts/
├── AGENTS.md
├── CONTRIBUTING.md
├── Dockerfile
├── LICENSE
├── Makefile
├── README.md
├── SECURITY.md
├── package.json
├── package-lock.json
├── tsconfig.json
└── vitest.config.ts
```

### 특징

- TypeScript/Node 기반 모노레포 구조이며, Gemini CLI와 매우 유사하게 `packages/cli`와 `packages/core`를 분리합니다.
- Qwen 모델에 최적화되어 있지만, README 기준 OpenAI-compatible, Anthropic, Gemini 등 여러 provider/protocol을 설정할 수 있습니다.
- 확장 표면이 넓습니다.
  - `packages/sdk-java`, `packages/sdk-python`, `packages/sdk-typescript`: 언어별 SDK
  - `packages/vscode-ide-companion`, `packages/zed-extension`: IDE 연동
  - `packages/webui`, `packages/web-templates`: 웹 UI 및 템플릿
  - `packages/channels`: 배포/채널 또는 런타임 채널 관련 영역으로 보이는 별도 패키지
- 루트에 `docs/`와 `docs-site/`가 함께 있어 문서 원본과 문서 사이트를 분리합니다.
- `integration-tests/`, `eslint-rules/`, `vitest.config.ts`처럼 테스트와 품질 규칙이 루트 레벨에서 관리됩니다.

### 구조적 시사점

- Gemini CLI처럼 CLI와 core를 분리하면서도 SDK, IDE, Web UI까지 제품 표면을 여러 패키지로 확장합니다.
- provider 설정을 유연하게 가져가는 구조는 Monix의 `llm/` 계층을 키울 때 참고할 만합니다.
- 현재 Monix의 `monix/llm/anthropic.py`가 단일 provider 중심이라면, 장기적으로는 `monix/llm/providers/` 또는 `monix/providers/`처럼 provider별 구현을 분리할 수 있습니다.
- IDE, 웹 UI, SDK 같은 별도 사용자 표면이 생기면 core 로직을 재사용 가능한 패키지로 유지하는 것이 중요합니다.

## 비교 요약

| 항목 | Claude Code | Gemini CLI | Codex | Qwen Code |
| --- | --- | --- | --- | --- |
| 저장소 성격 | 공개 플러그인/예제/설치 자산 중심 | TypeScript 모노레포 | Rust 중심 대형 workspace + SDK | TypeScript 모노레포 + 다중 SDK/IDE/Web UI |
| CLI 분리 | 공개 구조상 핵심 구현은 제한적으로 노출 | `packages/cli` | `codex-rs/cli`, `codex-rs/tui` | `packages/cli` |
| Core 분리 | 플러그인/agent/skill 중심 확장 구조 | `packages/core` | `codex-rs/core` | `packages/core` |
| 확장 시스템 | `plugins/`, `commands/`, `agents/`, `skills/`, `hooks/` | MCP, SDK, IDE companion, tools | skills, plugins, hooks, MCP, connectors | SDK, IDE companion, Web UI, provider 설정 |
| 도구 실행 | 플러그인 확장 관점에서 노출 | built-in tools와 core 패키지 중심 | `exec`, `tools`, `shell-command`, sandbox 계층 분리 | core/CLI 패키지 중심, agentic workflow 도구 제공 |
| 테스트 구조 | 공개 루트 기준 제한적 | integration/memory/perf/test-utils 분리 | Rust workspace 내 crate별 테스트 + 루트 도구 | integration-tests, Vitest, lint rule 분리 |
| 문서 구조 | README, CHANGELOG, plugin README | docs, ROADMAP, schemas | docs, codex-rs/docs, SDK 문서 | docs, docs-site, README, AGENTS |

## Monix에 적용할 수 있는 방향

현재 Monix는 다음처럼 간결하게 나뉘어 있습니다.

```text
monix/
├── cli.py
├── render.py
├── core/
├── llm/
├── tools/
├── config/
├── safety/
├── assistant.py
└── monitor.py
```

단기적으로는 현재 구조가 적절합니다. 다만 네 프로젝트를 기준으로 보면 다음 확장 방향을 고려할 수 있습니다.

1. CLI와 core 경계 유지
   - `cli.py`는 입력 파싱과 REPL만 담당합니다.
   - 판단, 라우팅, 응답 생성은 `core/`에 둡니다.

2. 도구와 정책 분리 강화
   - `tools/`는 서버 상태 수집만 담당합니다.
   - `safety/`는 허용 정책, 승인 규칙, 위험 명령 분류를 담당합니다.
   - 향후 쓰기 작업이 생기면 `tools/`에 바로 넣기보다 정책 계층을 먼저 통과하게 합니다.

3. 확장 지점은 별도 패키지로 준비
   - 플러그인 구조가 필요해지면 `monix/plugins/`를 추가합니다.
   - 사용자 명령 확장이 필요해지면 `monix/commands/`를 추가합니다.
   - hook 기반 이벤트 처리가 필요해지면 `monix/hooks/`를 추가합니다.

4. 세션/상태 저장은 core와 분리
   - 대화 기록, 작업 기록, 서버 스냅샷 캐시가 필요해지면 `monix/storage/` 또는 `monix/state/`를 추가합니다.
   - core 로직이 파일 시스템 저장 방식에 직접 의존하지 않도록 합니다.

5. 테스트 구조 확장
   - 지금은 `tests/test_monitor.py` 중심이지만, 기능이 늘면 다음처럼 나눌 수 있습니다.

```text
tests/
├── test_cli.py
├── test_core_assistant.py
├── test_tools_system.py
├── test_tools_processes.py
├── test_tools_logs.py
├── test_tools_services.py
└── test_safety_policy.py
```

6. provider 계층 확장
   - Qwen Code처럼 여러 provider/protocol을 지원하려면 `llm/` 아래를 provider별로 분리합니다.
   - 예: `monix/llm/anthropic.py`, `monix/llm/openai_compatible.py`, `monix/llm/gemini.py`
   - core 로직은 특정 provider API 형식보다 공통 인터페이스에 의존하게 합니다.

## 제안하는 후속 작업

- README의 Project Structure 섹션을 현재 이 비교 결과에 맞춰 보강합니다.
- `monix/tools/*`별 직접 단위 테스트를 추가합니다.
- `monix/safety/policy.py`에 읽기 전용 정책의 의도를 더 명확히 문서화합니다.
- 향후 확장 후보로 `monix/state/`, `monix/plugins/`, `monix/commands/`를 이슈로 분리합니다.

## 참고 링크

- Claude Code: https://github.com/anthropics/claude-code
- Claude Code plugins: https://github.com/anthropics/claude-code/tree/main/plugins
- Gemini CLI: https://github.com/google-gemini/gemini-cli
- Gemini CLI packages: https://github.com/google-gemini/gemini-cli/tree/main/packages
- Codex: https://github.com/openai/codex
- Codex Rust workspace: https://github.com/openai/codex/tree/main/codex-rs
- Codex SDK: https://github.com/openai/codex/tree/main/sdk
- Qwen Code: https://github.com/QwenLM/qwen-code
- Qwen Code packages: https://github.com/QwenLM/qwen-code/tree/main/packages
