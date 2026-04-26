---
name: generate-tests
description: This skill should be used when the user asks to "generate tests", "create tests", "테스트 생성", "테스트 만들어", or provides a directory path and wants pytest test files written for the Python modules in that directory. Activates when user says things like "이 디렉토리 테스트 생성해줘", "generate tests for monix/tools", "/generate-tests <path>".
argument-hint: "<directory_path>"
version: 1.0.0
---

# Generate Tests Skill

pytest 테스트 파일을 지정한 디렉토리의 Python 소스 코드로부터 자동 생성합니다.

## When to Activate

- 사용자가 특정 디렉토리의 테스트를 만들어달라고 요청할 때
- `/generate-tests <path>` 형식으로 호출될 때
- "테스트 생성", "generate tests for" 같은 표현이 포함될 때

## Workflow

### Step 1: 대상 디렉토리 확인

1. 인자로 받은 경로(또는 사용자 메시지에서 추출한 경로)를 절대 경로로 정규화
2. 디렉토리 내 `.py` 파일 목록을 Glob으로 수집 (`**/*.py`, `__init__.py` 제외)
3. 파일이 없으면 사용자에게 알리고 종료

### Step 2: 소스 코드 분석

각 `.py` 파일에 대해:
1. Read 툴로 파일 전체를 읽는다
2. 다음을 파악한다:
   - **최상위 함수**: `def function_name(...)` — 파라미터 타입, 반환값, 예외
   - **클래스 및 메서드**: `class ClassName` + `def method_name(...)`
   - **의존성**: import 목록 (mock 대상 파악)
   - **엣지 케이스**: `None`, 빈 입력, 경계값이 의미 있는 곳

### Step 3: 테스트 파일 이름 결정

```
소스 파일: monix/tools/system.py
테스트 파일: tests/tools/test_system.py

소스 파일: monix/core/assistant.py
테스트 파일: tests/core/test_assistant.py
```

- `tests/` 디렉토리를 루트로 사용
- 소스의 서브디렉토리 구조를 그대로 유지
- 파일명 앞에 `test_` 접두사 추가

### Step 4: 테스트 코드 생성 규칙

**반드시 지킬 것:**
- `pytest` 스타일 (클래스 없이 `def test_*` 함수, 필요시 클래스 사용)
- 외부 API·시스템 호출은 `unittest.mock.patch` / `MagicMock` 으로 격리
- 각 테스트는 **하나의 동작만** 검증
- 테스트 함수명: `test_<함수명>_<시나리오>` 형식
  - 예: `test_human_bytes_none_input`, `test_human_bytes_kilobytes`

**테스트 케이스 생성 우선순위:**
1. **정상 경로(happy path)** — 일반적인 입력으로 예상 결과 반환
2. **엣지 케이스** — `None`, 빈 문자열, 빈 리스트, 0, 음수
3. **예외 케이스** — 잘못된 입력, 외부 호출 실패
4. **경계값** — 최솟값/최댓값, 임계값 근처

**이 프로젝트의 관례:**
- `from monix.<module> import <symbol>` 임포트 방식
- `Thresholds` 데이터클래스는 `from monix.config import Thresholds`
- 시스템 정보(`psutil` 등) 의존 함수는 반드시 mock 처리
- 한국어 입력 테스트 포함 (NLP 계열 함수)

**코드 템플릿:**

```python
import pytest
from unittest.mock import MagicMock, patch

from monix.<module_path> import <FunctionOrClass>


def test_<func>_<scenario>():
    # arrange
    ...
    # act
    result = <func>(...)
    # assert
    assert result == expected
```

### Step 5: 기존 테스트 파일 처리

- 테스트 파일이 **이미 존재**하면:
  1. 기존 파일을 Read로 읽어 커버된 함수 목록 파악
  2. 아직 테스트가 없는 함수만 추가
  3. 기존 테스트는 그대로 유지
- 파일이 **없으면** 새로 생성

### Step 6: 파일 저장 및 실행 확인

1. 필요한 경우 디렉토리 생성 (`mkdir -p`)
2. Write 툴로 테스트 파일 저장
3. `uv run pytest <test_file> -v` 로 실행하여 구문 오류 없음을 확인
4. 실패한 테스트가 있으면 원인 분석 후 수정

## Output Format

작업 완료 후 다음을 보고:

```
생성된 테스트 파일:
- tests/tools/test_system.py  (+12 테스트)
- tests/tools/test_processes.py  (+5 테스트)

테스트 실행 결과:
  17 passed in 0.42s

커버리지 요약:
  human_bytes         ✓ (2 케이스)
  human_duration      ✓ (2 케이스)
  build_alerts        ✓ (3 케이스)
  collect_snapshot    ✓ (mock 사용, 2 케이스)
```

## Error Handling

| 상황 | 처리 |
|------|------|
| 디렉토리 없음 | 경로 확인 요청 메시지 출력 |
| `__init__.py`만 있음 | "테스트할 함수/클래스가 없습니다" 안내 |
| 테스트 실행 실패 | 오류 메시지 분석 후 자동 수정 시도 |
| mock 대상 불분명 | 보수적으로 mock 처리 후 주석으로 설명 |

## Examples

```
사용자: monix/tools 디렉토리 테스트 생성해줘
→ monix/tools/*.py 분석 후 tests/tools/test_*.py 생성

사용자: /generate-tests monix/llm
→ monix/llm/gemini.py, monix/llm/anthropic.py 분석 후 tests/llm/test_*.py 생성

사용자: monix/core/assistant.py 테스트 만들어줘
→ 단일 파일 분석 후 tests/core/test_assistant.py 생성
```
