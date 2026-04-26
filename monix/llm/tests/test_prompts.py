from monix.llm.prompts import SYSTEM_PROMPT


def test_system_prompt_is_non_empty_string():
    assert isinstance(SYSTEM_PROMPT, str)
    assert SYSTEM_PROMPT.strip()


def test_system_prompt_is_english_only_body():
    """Prompt body must be English; the only Korean allowed is the
    parenthetical hint that confirms the reply language target."""
    allowed_korean = {"한국어"}
    for ch in SYSTEM_PROMPT:
        if "가" <= ch <= "힣":
            assert any(token in SYSTEM_PROMPT for token in allowed_korean), ch


def test_system_prompt_directs_korean_replies():
    assert "Always reply in Korean" in SYSTEM_PROMPT
    assert "한국어" in SYSTEM_PROMPT


def test_system_prompt_contains_core_sections():
    assert "Monix" in SYSTEM_PROMPT
    # Read-only / safety guidance
    assert "Read-only" in SYSTEM_PROMPT
    # Tool-calling guidance
    assert "collect_snapshot" in SYSTEM_PROMPT
    assert "tail_log" in SYSTEM_PROMPT
    # Freshness guidance
    assert "measured_at" in SYSTEM_PROMPT


def test_system_prompt_forbids_bold_markdown():
    """The output-format rule must explicitly ban Markdown bold."""
    assert "Output Format" in SYSTEM_PROMPT
    assert "Do not use Markdown bold" in SYSTEM_PROMPT
    assert "**text**" in SYSTEM_PROMPT
