# Monix LLM 모듈 구현 스킬

## 목적

Monix의 `monix/llm/` 패키지(LLM tool-calling 루프 + 다중 턴 대화 + 컨텍스트 매니징 계층)를 구현, 디버깅, 수정할 때 사용합니다.

- **시작점:** 호출자(예: `monix/assistant.py`, `monix/core/*`)가 `monix.llm`의 공개 API에 진입하는 시점
- **종료점:** tool-calling 루프가 종료되어 정규화된 텍스트 응답이 호출자에게 반환되는 시점
- **제외 범위:** CLI 입출력/렌더링, 슬래시 명령 라우팅, 도구(`monix/tools/`) 구현 수정, 안전 정책(`monix/safety/`) 변경, 스트리밍 응답

---

## 작업 범위 제약

- **모든 작업은 `monix/llm/` 디렉토리 내부에서만 수행**합니다. 신규 파일 추가도 동일.
- `monix/tools/`는 **임포트만 가능, 수정 금지**. LLM이 호출하는 도구는 이 폴더에 정의된 함수만 사용하며, docstring/타입 힌트 보강이 필요한 경우에도 `monix/tools/` 코드를 수정하지 않고 별도 보고합니다.
- `monix/safety/`도 본 태스크에서는 임포트하지 않습니다(자체 구현 후 향후 통합).
- 외부 모듈(`monix/assistant.py`, `monix/cli.py`, `monix/core/*`, `monix/config/*`, `monix/tools/*`, `monix/safety/*`)에 의존 변경이 필요하면 직접 수정하지 않고 **변경 요청을 별도 항목으로 보고**합니다.
- LLM Provider는 **Gemini 단일 벤더**, 사용 모델은 다음 두 가지로 한정합니다.
  - `gemini-3.1-pro-preview`
  - `gemini-3.1-flash-preview`
- 환경변수로 **API 키, 모델, 도구 호출 한도, 토큰 예산, 도구 결과 크기 한도**를 결정합니다. `monix/config/settings.py`는 수정·의존하지 않습니다.

| 환경변수 | 의미 | 허용 값 | 미설정/잘못된 값 |
|---|---|---|---|
| `GEMINI_API_KEY` | API 키 | 임의 문자열 | `run_query` → `None` (예외 X) |
| `MONIX_LLM_MODEL` | 모델 선택 | `pro` \| `flash` \| 전체 모델 ID | `flash`로 폴백 |
| `MONIX_LLM_MAX_TOOL_CALLS` | 한 질의 내 도구 호출 최대 | 양의 정수 | `5`로 폴백 |
| `MONIX_LLM_INPUT_TOKEN_BUDGET` | 입력 토큰 임계값(트리밍 트리거) | 양의 정수 | `800000`로 폴백 |
| `MONIX_LLM_TOOL_RESULT_MAX_BYTES` | 도구 결과 최대 크기(UTF-8 바이트) | 양의 정수 | `16384`로 폴백 |

- 모든 환경변수 읽기는 `runner.py`의 `_resolve_*()` 함수에 **단일 출처**로 한정합니다.
- Anthropic 등 타 LLM 벤더, 응답 스트리밍은 본 태스크 범위 외.

---

## 흐름 모델 (다중 턴)

본 태스크는 **두 차원의 다중 턴**을 지원합니다.

| 차원 | 의미 | 구현 위치 |
|---|---|---|
| **A. 대화 다중 턴** | 사용자 질의가 누적되면서 이전 맥락을 이어감 | 호출자가 `history` 리스트 누적, `run_query`에 매번 전달 |
| **B. Tool-calling 다중 턴** | 한 사용자 질의 안에서 모델이 도구를 여러 번 호출 → 결과 합성 → 최종 답변 | `runner.py`가 단일 `run_query` 호출 안에서 max 회수 동안 루프 |

**8-(b) 정책: 도구 호출 파트도 외부 history에 누적합니다.**

- 한 사용자 질의가 종료되면 외부 history에 다음 메시지들이 추가됩니다.
  - `{role:"user", parts:[{text}]}` — 사용자 질문
  - `{role:"model", parts:[{functionCall:{name, args}}]}` — 모델의 도구 호출 요청 (호출 횟수만큼 반복)
  - `{role:"user", parts:[{functionResponse:{name, response 또는 error}}]}` — 도구 실행 결과 (호출 횟수만큼 반복)
  - `{role:"model", parts:[{text}]}` — 모델의 최종 텍스트 응답
- 후속 질의에서 모델이 이전 도구 호출 결과를 그대로 참조 가능 → 중복 호출 회피, 멀티턴 맥락 보존
- 호출자 history에 새로운 종류의 파트가 섞이게 됨 → 트리밍 로직 영향(별도 보고)

---

## 컨텍스트 매니징 정책

본 태스크에서 도입/미도입하는 컨텍스트 매니징 항목과 정책을 한 곳에 정리합니다.

### 도입 항목

| # | 항목 | 정책 |
|---|---|---|
| 1 | **토큰 예산 추적 + 자동 트리밍** | Gemini 응답의 `usageMetadata.totalTokenCount`로 사후 추적. 누적 토큰이 `MONIX_LLM_INPUT_TOKEN_BUDGET`을 넘으면 가장 오래된 사용자-모델 턴 페어부터 제거. 책임: `client.py`(추출) + `runner.py`(누적) + `trimmer.py`(트리밍) |
| 2 | **도구 결과 크기 잘라내기** | `executor.py`가 도구 결과 직렬화 직후 `MONIX_LLM_TOOL_RESULT_MAX_BYTES` 한도로 앞부분 보존. 잘림 시 `{..., "_truncated": true, "_original_size_bytes": <N>}` 메타 추가. 도구별 차등은 미도입 |
| 4 | **컨텍스트 신선도 표기** | `executor.py`가 `functionResponse.response`에 `measured_at`(ISO8601 UTC) 자동 부여. 도구 결과 자체에 timestamp가 있으면 그쪽 우선. 자동 무효화는 없음 — 모델이 신선도를 보고 재호출 결정 |
| 8 | **민감 정보 마스킹** | `masker.py`가 도구 결과를 history로 옮기기 전 정규식 패턴으로 마스킹. 적용 범위는 **도구 결과만** (사용자 입력·SYSTEM_PROMPT·모델 응답 미적용). 표시는 `***`. 비가역(원본 폐기). 도구별 차등 없음 |

### 마스킹 패턴 (1차)

`masker.py`에 다음 정규식들을 화이트리스트로 둡니다. 운영 후 보강.

| 패턴 종류 | 정규식 |
|---|---|
| API 키 / 비밀 / 토큰 / 비밀번호 키워드 | `(?i)(api[_-]?key\|secret\|token\|password)["'\s:=]+\S+` |
| JWT | `eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+` |
| 긴 hex 토큰 | `[a-f0-9]{32,}` |
| AWS Access Key | `AKIA[0-9A-Z]{16}` |

매칭 시 매치 부분을 `***`로 치환. 거짓 양성은 보수적으로 마스킹 처리(원본 노출보다 안전 우선).

### 미도입 항목 (명시적 "범위 외")

| # | 항목 | 미도입 이유 | 향후 도입 경로 |
|---|---|---|---|
| 3 | **컨텍스트 압축 / 요약** | 별도 LLM 호출 비용·복잡도 큼. 1번의 자동 트리밍이 1차로 충분 | `monix/llm/compactor.py` 신설, flash 모델로 요약 |
| 5 | **세션 격리 / 멀티 사용자** | Monix는 단일 사용자 CLI. 일반화는 과함 | `monix/llm`은 stateless 유지, 호출자가 history 분리하면 사실상 가능 |
| 7 | **장기 메모리 (세션 간 영속)** | 아키텍처 차원의 결정. 단순 진단 도구에서 불필요 | 별도 모듈 `monix/memory/` 신설 (현 패키지 외부) |
| 9 | **사용량 메타 노출** | 호출자 시그너처 호환성 보존 | 별도 함수 `run_query_detailed(...) -> ChatResult` 추가 |
| - | **디버그 모드 / 검증 hook** | 1차 단순화 | 환경변수 기반 활성화 |
| - | **`monix/safety/` 통합 마스킹** | 외부 모듈 의존 추가 → 작업 범위 외 | `masker.py`를 `monix/safety/policy.py`와 통합 (별도 보고) |

### 시스템 프롬프트 / 도구 스키마 전송 정책

- Gemini의 `system_instruction` 별도 파라미터 사용 (현재 방식 유지). `contents` prepend 방식 X
- 도구 스키마는 **매 호출마다 전체 전송** (Gemini 캐시 동작 비명시)
- 도구 스키마 직렬화는 `registry.py` 모듈 로드 시 1회 수행, 결과를 모듈 변수로 캐시. HTTP 호출은 매번 같은 직렬화 결과 전송
- SYSTEM_PROMPT는 정적 (사용자/세션별 동적 보강 미도입)

---

## 프로젝트 디렉토리 구조 (구현 목표)

```text
monix/llm/
├── __init__.py        # 공개 API: run_query, GeminiClient, MODEL_PRO, MODEL_FLASH, SYSTEM_PROMPT, LLMError 계열, ToolError
├── prompts.py         # SYSTEM_PROMPT 단일 출처 (tool-calling + 신선도 안내 반영)
├── registry.py        # 도구 자동 인식: monix.tools.__all__ 스캔 + 제외 목록 + 스키마 자동 생성 + 캐시
├── executor.py        # functionCall 디스패치 + 인자 검증 + 결과/에러 변환 + 잘라내기 + measured_at + 마스킹 호출
├── masker.py          # 민감 정보 마스킹 (정규식 화이트리스트)
├── trimmer.py         # 토큰 예산 도달 시 history 트리밍 (사용자-모델 턴 페어 단위)
├── runner.py          # tool-calling 루프 드라이버 + 환경변수 해석 + 토큰 누적 추적
├── client.py          # GeminiClient + MODEL_PRO/FLASH 상수, generateContent + tools + usageMetadata 추출
├── types.py           # Message/History/ToolCall/ToolResponse/ToolSchema/UsageInfo + LLMError 계열 + ToolError
└── tests/
    ├── __init__.py
    ├── test_registry.py    # __all__ 스캔, 제외 목록, 스키마 생성
    ├── test_executor.py    # 디스패치, 인자 검증, 잘라내기, measured_at, 마스킹 통합
    ├── test_masker.py      # 정규식 패턴별 마스킹 정확성
    ├── test_trimmer.py     # 토큰 한도 도달 시 턴 페어 단위 트리밍
    ├── test_runner.py      # 다중 턴 시뮬레이션, 토큰 누적, 트리밍 트리거
    ├── test_client.py      # HTTP → 예외 매핑, usageMetadata 추출
    └── test_prompts.py     # SYSTEM_PROMPT 정합성
```

`context.py`, `compactor.py`는 두지 않습니다 — 자동 컨텍스트 첨부 폐기, 압축은 1차 미도입.

**모듈별 책임**

- `__init__.py`: 외부 공개 심볼만 재노출.
- `prompts.py`: `SYSTEM_PROMPT` 단일 출처. tool-calling 안내 + `measured_at` 신선도 안내 포함.
- `registry.py`: `monix.tools.__all__` 자동 스캔 + 제외 목록 + 스키마 자동 생성 + 모듈 로드 시 1회 캐시. **`monix.tools` 임포트 유일 지점**.
- `executor.py`: 모델의 `functionCall` 처리 흐름 — registry 조회 → 인자 검증 → 함수 실행 → 결과 직렬화 → **`measured_at` 부여 → 잘라내기 → 마스킹 적용** → `functionResponse` 형식으로 변환. 마스킹은 `masker.py`에 위임.
- `masker.py`: 정규식 패턴 화이트리스트로 텍스트/JSON 직렬화 결과를 마스킹. 도구 결과만 적용.
- `trimmer.py`: history와 누적 토큰 수를 받아, 임계값 초과 시 가장 오래된 사용자-모델 턴 페어(`functionCall`/`functionResponse` 파트 포함)를 단위로 제거. SYSTEM_PROMPT와 가장 최근 N턴은 보존.
- `runner.py`: `run_query` 진입점. 환경변수 해석 + tool-calling 루프 + 토큰 누적 + `trimmer` 호출 + history 누적.
- `client.py`: Gemini `generateContent` HTTP 호출. `tools` 파라미터 전달. 응답에서 `usageMetadata.totalTokenCount` 추출하여 반환. HTTP/네트워크 실패 → `LLMError` 계열 변환.
- `types.py`: 메시지/도구/사용량 타입 + 예외 계층.

**분할 결정 근거**

- `masker.py`/`trimmer.py` 분리 — 마스킹은 보안 책임, 트리밍은 토큰 예산 책임. 단일 책임 분리.
- `executor.py`가 마스킹·잘라내기·`measured_at`을 모두 책임 — 도구 결과 가공의 단일 진입점. `monix/tools/` 수정 없이 외부에서 부여하기에 적합한 위치.
- `registry.py`와 `executor.py` 분리 — 도구 메타(정적, 모듈 로드)와 디스패치(동적, 모델 응답)는 시점이 다름.
- `providers/` 디렉토리 미도입 — 단일 벤더(Gemini).
- `messages.py`/`errors.py`는 `types.py`로 통합 — 분량 적음.

---

## 공개 API 계약

```python
def run_query(question: str, *, history: list[dict] | None = None) -> str | None: ...

class GeminiClient:
    def __init__(self, api_key: str | None, model: str) -> None: ...
    @property
    def enabled(self) -> bool: ...
    def chat(self, history: list[dict]) -> str | None: ...

MODEL_PRO: str    # "gemini-3.1-pro-preview"
MODEL_FLASH: str  # "gemini-3.1-flash-preview"
SYSTEM_PROMPT: str

class LLMError(Exception): ...
class AuthError(LLMError): ...
class RateLimitError(LLMError): ...
class NetworkError(LLMError): ...
class ResponseError(LLMError): ...
class ToolError(LLMError): ...
```

**`run_query` 동작**

- 입력: `question`, `history`(호출자 누적)
- 처리: history 끝에 사용자 질문 추가 → tool-calling 루프(max `MONIX_LLM_MAX_TOOL_CALLS`) → 매 루프마다 토큰 누적 추적 → 임계값 초과 시 `trimmer` 호출 → `functionCall` 처리/응답 텍스트 처리
- history는 호출자가 전달한 리스트를 **in-place 누적** (`functionCall`/`functionResponse` 파트 포함, 잘라내기·마스킹·`measured_at` 적용 후 형태로)
- 반환:
  - 성공: 모델의 최종 텍스트 응답
  - 비활성: API 키 미설정 → `None` (예외 X)
  - max 호출 초과: 마지막 모델 응답을 그대로 반환
  - 명시적 호출 실패: `LLMError` 계열 예외

**호환성/마이그레이션**

- 기존 공개 심볼 `GeminiClient`, `SYSTEM_PROMPT` 이름·시그너처 보존.
- 기존 `GeminiClient.chat(history) -> str | None` 메서드 유지(단순 호출용, 도구·트리밍·마스킹 미적용).
- 신규 추가: `run_query`, `MODEL_PRO`, `MODEL_FLASH`, `LLMError` 계열, `ToolError`.
- 호출자(`monix.assistant`, `monix.core.assistant`) 코드는 본 태스크에서 변경하지 않음.
- `monix/llm/anthropic.py`는 외부 임포트 없음 → **삭제**.

---

## 도구 활용 정책

LLM이 호출 가능한 도구는 **`monix/tools/`에 정의된 함수만**으로 한정. `monix/tools/` 코드는 절대 수정하지 않음. 새 도구가 추가되면 자동 인식.

**자동 인식 규칙 (`registry.py`)**

- 입력: `monix.tools.__all__`에 노출된 심볼 (현재 12개)
- **제외 목록**: `human_bytes`, `human_duration`, `build_alerts` (단순 포매터/유틸리티)
- 1차 노출 도구 9개: `collect_snapshot`, `memory_info`, `disk_info`, `top_processes`, `service_status`, `tail_log`, `follow_log`, `filter_errors`, `classify_line`
- 제외 목록은 `registry.py` 상수로 관리. `monix/tools/__init__.py`의 `__all__`에 새 도구가 추가되면 **`monix/llm/` 코드 변경 없이** 자동 인식

**스키마 자동 생성**

- `inspect.signature` → 파라미터 이름·타입·기본값
- `__doc__` → description (없으면 빈 문자열)
- 타입 힌트 → JSON 스키마 매핑 (`str` → `string`, `int` → `integer`, `bool` → `boolean`, `list` → `array`, `dict` → `object`, 기타 → `string` 폴백)
- 기본값 없는 인자는 `required` 목록 포함
- 모듈 로드 시 1회 직렬화 후 캐시

**도구 실행 (`executor.py`)**

`functionCall(name, args)` → 다음 순서로 처리:

1. `registry`에서 함수 조회 (미등록 시 `functionResponse.error`)
2. `inspect.signature` 기반 인자 검증 (누락/타입 불일치 시 `error`)
3. 함수 실행 (예외 시 메시지를 `error`로 변환)
4. 결과 직렬화 (JSON)
5. **`measured_at` 부여** (도구 결과에 자체 timestamp가 있으면 그쪽 우선)
6. **크기 검사 → `MONIX_LLM_TOOL_RESULT_MAX_BYTES` 초과 시 앞부분 보존 + `_truncated`/`_original_size_bytes` 메타 추가**
7. **`masker.py` 호출하여 마스킹**
8. `functionResponse.response`로 변환

**도구 docstring/타입 힌트 보강**

- 본 태스크 범위 외. `monix/tools/` 수정 필요 → 별도 보고.
- 1차는 현 상태로 노출, 빈약한 함수는 운영 후 식별·보고.

---

## 예외 계층

```text
LLMError (베이스)
├── AuthError       # 401, 403
├── RateLimitError  # 429
├── NetworkError    # URLError, OSError, timeout
├── ResponseError   # 5xx, 기타 4xx, 응답 파싱 실패, 토큰 한도 초과 응답
└── ToolError       # 도구 등록/실행 실패가 회복 불가능한 경우
```

**HTTP 상태 → 예외 매핑**

| 응답 상황 | 예외 |
|---|---|
| `200` + 정상 파싱 | (정상) |
| `200` + 응답 파싱 실패 | `ResponseError` |
| `401`, `403` | `AuthError` |
| `429` | `RateLimitError` |
| `5xx` / 기타 `4xx` | `ResponseError` |
| `URLError`, `OSError`, timeout | `NetworkError` |

**예외가 아닌 케이스**

- API 키 미설정 → `None` 반환
- 1회성 도구 실행 실패 → `functionResponse.error` 모델 피드백, 흐름 지속
- max 호출 초과 → 마지막 모델 응답 반환
- 미등록 도구 호출 시도 → `functionResponse.error` 피드백
- 토큰 예산 초과 → `trimmer`가 자동 트리밍 후 흐름 지속 (예외 X)

**예외 페이로드**: `status_code`, `body_excerpt`(앞 200자), `message`

---

## 운영 동작

| 항목 | 정책 |
|---|---|
| HTTP timeout | 20초 |
| 재시도 | 없음 (1차) |
| 로깅 | 미도입 (1차) |
| 모델 검증 | `_resolve_model()`만, `flash` 폴백 |
| 최대 도구 호출 횟수 | `MONIX_LLM_MAX_TOOL_CALLS` (기본 5) |
| 입력 토큰 임계값 | `MONIX_LLM_INPUT_TOKEN_BUDGET` (기본 800000) |
| 도구 결과 크기 한도 | `MONIX_LLM_TOOL_RESULT_MAX_BYTES` (기본 16384, UTF-8 바이트) |
| 도구 실행 실패 처리 | `functionResponse.error` 피드백, 흐름 지속 |
| 토큰 예산 도달 시 | `trimmer`가 사용자-모델 턴 페어 단위 자동 트리밍 |
| 도구 결과 한도 초과 시 | 앞부분 보존 + `_truncated` 메타 추가 |
| 신선도 표기 | `measured_at` ISO8601 UTC 자동 부여 |
| 마스킹 | `masker.py`가 도구 결과만 정규식 기반 마스킹, `***` 표시 |
| 자동 컨텍스트 첨부 | 없음 — 모델이 도구로 호출 |
| 도구 자동 인식 시점 | 모듈 로드 시 1회 |
| 안전 가드 | `registry.py` 제외 목록 + `masker.py` 마스킹 |

---

## SYSTEM_PROMPT 정의

`prompts.py`의 `SYSTEM_PROMPT` 구성:

1. **베이스**: 현재 `monix/llm/gemini.py`의 한국어 우선 프롬프트 이전.
2. **AGENDT.md 원칙 보강**: 절대적 읽기 전용, 민감 정보 `***` 마스킹, [현재 상태]→[원인 분석]→[추가 확인 명령] 단계별 흐름.
3. **Tool-calling 안내**: 사실 기반 답변에 필요한 데이터는 도구로 수집. 시스템 메트릭은 `collect_snapshot`, 로그는 `tail_log`/`filter_errors`, 서비스는 `service_status`. 한 번으로 부족하면 추가 호출.
4. **신선도 안내 (신규)**: 도구 결과의 `measured_at` 시각을 확인하고, 시간이 많이 지난 데이터가 부적절하면 같은 도구를 다시 호출하라.

동적 템플릿은 미도입.

---

## 실행 파이프라인

```text
호출자 (monix/core/assistant.py 등)
  → monix.llm 공개 API (run_query)
  → runner._resolve_api_key()        — GEMINI_API_KEY (없으면 None 반환 종료)
  → runner._resolve_model()          — MONIX_LLM_MODEL (기본 flash)
  → runner._resolve_max_calls()      — MONIX_LLM_MAX_TOOL_CALLS (기본 5)
  → runner._resolve_token_budget()   — MONIX_LLM_INPUT_TOKEN_BUDGET (기본 800000)
  → registry.list_tools()            — __all__ 스캔 + 제외 목록 + 스키마 캐시
  → history 끝에 사용자 질문 추가
  → tool-calling 루프 (n=0):
       │
       ├─ trimmer.maybe_trim(history, total_tokens, budget)  ※ 임계 도달 시 트리밍
       ├─ client.GeminiClient.chat(history + tools)          ※ generateContent + function_declarations
       │   → response_text + (functionCall | None) + usageMetadata
       ├─ runner가 total_tokens 누적
       │
       ├─ functionCall이 있으면:
       │      ├─ history에 model functionCall 메시지 추가
       │      ├─ executor.invoke(name, args):
       │      │      ├─ registry 조회 + 인자 검증
       │      │      ├─ 함수 실행 (또는 error 변환)
       │      │      ├─ measured_at 부여
       │      │      ├─ 크기 검사 → 잘라내기
       │      │      ├─ masker로 마스킹
       │      │      └─ functionResponse 반환
       │      ├─ history에 user functionResponse 메시지 추가
       │      ├─ n += 1
       │      └─ n < max_calls 면 루프 재진입
       │
       └─ 텍스트만이면:
              ├─ history에 model 텍스트 메시지 추가
              └─ 루프 종료
  → 최종 텍스트를 호출자에 반환
```

본 흐름은 **다중 턴 (대화 + tool-calling) + 자동 트리밍 + 결과 가공**. 응답 스트림은 처리하지 않음.

---

## 주요 컴포넌트

### 1. 공개 API (`monix/llm/__init__.py`)

`run_query`, `GeminiClient`, `MODEL_PRO`, `MODEL_FLASH`, `SYSTEM_PROMPT`, `LLMError` 계열, `ToolError` 재노출. 단일 진입점.

---

### 2. 도구 레지스트리 (`monix/llm/registry.py`)

- 임포트 대상(수정 금지): `monix.tools.*`
- `monix.tools.__all__` 자동 스캔 + 제외 목록 적용
- `inspect`로 Gemini `function_declarations` 형식 JSON 스키마 자동 생성
- 모듈 로드 시 1회 직렬화 후 캐시
- 도구 이름 → 함수 객체 조회 (`executor`가 사용)
- **`monix.tools` 임포트의 유일한 지점**

---

### 3. 도구 실행기 (`monix/llm/executor.py`)

- `functionCall(name, args)`을 `registry`에서 조회 + 인자 검증 + 실행
- 도구 결과 가공: **`measured_at` 부여 → 크기 검사·잘라내기 → 마스킹**
- 미등록 도구·인자 오류·실행 실패 → `functionResponse.error`
- 마스킹은 `masker.py`에 위임

---

### 4. 마스킹 (`monix/llm/masker.py`) [NEW]

- 정규식 패턴 화이트리스트(API 키/JWT/긴 hex/AWS 키)로 직렬화된 도구 결과 마스킹
- 매칭 부분을 `***`로 치환 (비가역)
- 사용자 입력·SYSTEM_PROMPT·모델 응답에는 적용하지 않음 (1차)
- 향후 `monix/safety/policy.py`와 통합 — 별도 보고

---

### 5. 트리머 (`monix/llm/trimmer.py`) [NEW]

- 입력: history + 누적 토큰 수 + 토큰 예산
- 임계값 초과 시 가장 오래된 사용자-모델 **턴 페어 단위**로 제거
  - 한 페어 = 사용자 메시지 + 모델 응답(중간의 `functionCall`/`functionResponse` 파트 포함)
- 가장 최근 N턴은 보존 (현재 진행 중인 tool-calling 흐름이 잘리지 않도록)
- 트리밍은 in-place로 호출자 history 리스트에 적용

---

### 6. 다중 턴 오케스트레이션 (`monix/llm/runner.py`)

- `run_query` 진입점
- `_resolve_api_key()` / `_resolve_model()` / `_resolve_max_calls()` / `_resolve_token_budget()` 환경변수 해석
- tool-calling 루프 드라이버 + 토큰 누적 추적 + `trimmer.maybe_trim` 호출
- history 누적

---

### 7. 모델 클라이언트 (`monix/llm/client.py`)

- `MODEL_PRO`, `MODEL_FLASH` 상수
- `generateContent` HTTP 호출 + `tools`(function_declarations) + `system_instruction`
- 응답에서 `usageMetadata.totalTokenCount` 추출하여 반환
- HTTP/네트워크 실패 → `LLMError` 계열 변환
- 기존 `chat(history)` 시그너처 보존(단순 호출용)

---

### 8. 프롬프트 (`monix/llm/prompts.py`)

`SYSTEM_PROMPT` 단일 출처. 베이스 + AGENDT 원칙 + tool-calling 안내 + 신선도 안내.

---

### 9. 공용 타입 및 예외 (`monix/llm/types.py`)

`Message`, `History`, `ToolCall`, `ToolResponse`, `ToolSchema`, `UsageInfo`. `LLMError` 계열 + `ToolError`.

---

## 권장 구현 순서

1. `types.py`: 예외 계층 + 도구/사용량 타입
2. `client.py`: 모델 상수, HTTP 호출, `tools` 파라미터, `usageMetadata` 추출, 예외 매핑
3. `prompts.py`: `SYSTEM_PROMPT` (베이스 + AGENDT + tool-calling + 신선도 안내)
4. `registry.py`: `__all__` 자동 스캔 + 제외 목록 + 스키마 자동 생성 + 캐시
5. `masker.py`: 정규식 패턴 마스킹
6. `executor.py`: 디스패치 + 인자 검증 + `measured_at` + 잘라내기 + 마스킹 통합
7. `trimmer.py`: 턴 페어 단위 트리밍
8. `runner.py`: `run_query` + `_resolve_*` + tool-calling 루프 + 토큰 누적 + 트리밍 호출
9. `__init__.py`: 공개 심볼 재노출
10. `tests/`: 단위 테스트 (각 모듈별 + 통합 시나리오)
11. `monix/llm/anthropic.py` 삭제

---

## 구현 원칙

- 외부 SDK 도입 금지 — 표준 라이브러리(`urllib`, `json`, `inspect`, `os`, `re`, `datetime`)만 사용
- `monix/tools/`는 임포트만, 수정 금지
- `monix/safety/`는 본 태스크에서 임포트하지 않음 (마스킹은 `monix/llm/` 자체 구현)
- 상위 모듈은 본 태스크에서 변경하지 않음. 트리밍 영향은 별도 보고
- 모델 식별자 문자열은 `client.py` 상수로만 정의 (하드코딩 금지)
- 환경변수 읽기는 `runner.py`의 `_resolve_*()`에 한정
- `monix.tools` 임포트는 `registry.py`에 한정
- 단일 책임: `prompts` / `registry` / `executor` / `masker` / `trimmer` / `runner` / `client` / `types`
- 향후 Provider 추가 시 `client.py` → `providers/` 승격 경로
- 동작 변경 시 `monix/llm/tests/` 갱신

---

## 호출자 측 영향 (별도 보고 항목)

본 태스크에서는 호출자 코드를 수정하지 않지만, 다음을 별도 작업으로 보고:

- **`monix/core/assistant.py`의 `_MAX_HISTORY = 20` 트리밍 로직**
  - 현재: 메시지 수 기준 슬라이싱
  - 영향: tool-calling 파트가 섞이고 `measured_at` 메타가 추가되어 한 사용자 질의가 여러 메시지를 차지함. 20개 한도가 빠르게 소모되며 도구 호출 결과가 도중에 잘려 일관성 깨질 수 있음
  - 권장 변경(별도): 사용자-모델 턴 페어 단위 트리밍 또는 한도 상향(60+)
- **`monix/safety/policy.py`와 마스킹 통합**
  - 현재: `masker.py` 자체 구현
  - 향후: `monix/safety/`의 보안 정책과 통합하여 일관된 마스킹 적용
- **`monix/tools/` 도구 docstring/타입 힌트 보강**
  - 빈약한 함수는 모델의 도구 선택 정확도를 떨어뜨림
  - 보강 대상은 운영 후 식별 후 보고

---

## 테스트 정책

- **위치**: `monix/llm/tests/`
- **Mock**: `unittest.mock.patch`로 `urllib.request.urlopen` 패치
- **커버 범위**
  - `_resolve_*()`: 환경변수 케이스 (미설정/정상값/잘못된 값 폴백) — 5개 변수 모두
  - `registry`: `__all__` 자동 스캔, 제외 목록, 스키마 정확성, 새 심볼 추가 시 자동 인식
  - `executor`: 등록/미등록 도구, 인자 검증, 실행 예외 → error, **`measured_at` 부여, 잘라내기, 마스킹 통합 흐름**
  - `masker`: 패턴별 마스킹 정확성, 거짓 양성 케이스, 도구 결과 외 미적용
  - `trimmer`: 토큰 임계 미달/초과, 턴 페어 단위 제거, 최근 N턴 보존, in-place 변경 검증
  - `client`: HTTP 상태 → 예외 매핑, `tools` 파라미터 전달, `usageMetadata` 추출
  - `runner`: 다중 턴 시뮬레이션 — 도구 호출 0/1/2회/max 초과, 토큰 누적, 트리밍 트리거 시나리오, 비활성(`None`) 동작

---

## 범위 외 항목

- Anthropic 등 타 LLM 벤더
- 응답 스트리밍
- 컨텍스트 압축/요약 (1차 미도입, `compactor.py` 향후 경로)
- 장기 메모리 (1차 미도입, `monix/memory/` 향후 경로)
- 멀티 세션 / 세션 격리 (단일 사용자 가정)
- 사용량 메타 정보 노출 (`run_query`는 텍스트만 반환)
- 디버그 모드, 검증 hook
- `monix/safety/` 통합 마스킹 (자체 구현 후 향후 통합)
- `monix/tools/` 코드 수정 (docstring/타입 힌트 보강 포함)
- `monix/cli.py`, `monix/core/*`, `monix/assistant.py`, `monix/config/*` 등 외부 모듈 수정 (트리밍 영향은 별도 보고)
- 호출자의 `run_query` 이행 (점진 마이그레이션은 별도)
- CLI 렌더링, UX, 슬래시 명령 라우팅
- HTTP 재시도/백오프, 구조화된 로깅
- 도구별 차등 마스킹/잘라내기 (일률 적용)

---

## 완료 기준

- [ ] `GeminiClient`가 `MODEL_PRO`, `MODEL_FLASH` 두 상수로 동작 (모델 식별자 하드코딩 X)
- [ ] `runner._resolve_model()` — `MONIX_LLM_MODEL`, `flash` 폴백
- [ ] `runner._resolve_api_key()` — `GEMINI_API_KEY` 미설정 시 `run_query` → `None`
- [ ] `runner._resolve_max_calls()` — `MONIX_LLM_MAX_TOOL_CALLS`, 기본 5
- [ ] `runner._resolve_token_budget()` — `MONIX_LLM_INPUT_TOKEN_BUDGET`, 기본 800000
- [ ] `executor`가 `MONIX_LLM_TOOL_RESULT_MAX_BYTES`(기본 16384) 한도 적용 + 잘림 시 `_truncated`/`_original_size_bytes` 메타 추가
- [ ] `os.environ` 직접 접근이 `runner.py`에만 존재
- [ ] `monix.tools` 임포트가 `registry.py`에만 존재
- [ ] `monix/safety/` 임포트가 본 태스크 코드에 존재하지 않음
- [ ] `registry`가 `__all__` 자동 스캔 + 제외 목록(`human_bytes`, `human_duration`, `build_alerts`) 적용
- [ ] `__all__`에 새 심볼 추가 시 `monix/llm/` 코드 변경 없이 자동 인식
- [ ] `executor`가 미등록 도구·인자 오류·실행 실패를 `functionResponse.error`로 모델에 피드백
- [ ] `executor`가 도구 결과에 `measured_at`(ISO8601 UTC) 자동 부여 (도구 자체 timestamp가 있으면 그쪽 우선)
- [ ] `masker`가 4개 정규식 패턴(API 키/JWT/hex/AWS)을 도구 결과에 적용하며 `***`로 치환
- [ ] 마스킹은 도구 결과만 적용 (사용자 입력·SYSTEM_PROMPT·모델 응답 미적용)
- [ ] `trimmer`가 토큰 임계 도달 시 사용자-모델 턴 페어 단위로 history를 in-place 트리밍하며 최근 N턴은 보존
- [ ] `client`가 응답에서 `usageMetadata.totalTokenCount`를 추출하여 `runner`가 누적
- [ ] `runner`가 max 호출 한도 안에서 다중 턴 루프 + 토큰 누적 + 트리밍 트리거를 처리
- [ ] 외부 history에 `functionCall`/`functionResponse` 파트가 누적되어 후속 질의에서 이전 결과 참조 가능
- [ ] `run_query` 시그너처 `(question, *, history=None) -> str | None`, `model` 인자 미노출
- [ ] HTTP/인증/네트워크/응답 파싱 실패가 `LLMError` 계열로 정규화
- [ ] 외부 SDK 의존 0건 (표준 라이브러리만)
- [ ] 공개 API(`run_query`, `GeminiClient`, `MODEL_*`, `SYSTEM_PROMPT`, `LLMError` 계열, `ToolError`)가 `__init__.py`에서 재노출
- [ ] 기존 `GeminiClient`/`SYSTEM_PROMPT` 시그너처 보존
- [ ] `monix/llm/anthropic.py` 삭제
- [ ] `monix/llm/tests/`의 단위 테스트 통과 (registry, executor, masker, trimmer, client, runner)
- [ ] 호출자 트리밍 로직 영향, `monix/safety/` 마스킹 통합, `monix/tools/` docstring 보강이 별도 보고 항목으로 정리됨
