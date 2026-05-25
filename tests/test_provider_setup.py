from __future__ import annotations

import json

import pytest

from monix import cli
from monix.config import Settings
from monix.config import keystore


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / ".monix" / "config.json"
    monkeypatch.setattr(keystore, "_CONFIG_DIR", path.parent)
    monkeypatch.setattr(keystore, "_CONFIG_FILE", path)
    for name in ("GEMINI_API_KEY", "MONIX_LLM_PROVIDER", "MONIX_LLM_MODEL", "MONIX_MODEL"):
        monkeypatch.delenv(name, raising=False)
    return path


def test_legacy_gemini_config_implies_provider_and_saved_model(config_file):
    keystore._save({"gemini_api_key": "saved-gemini-key", "model": "saved-model"})

    settings = Settings.from_env()

    assert settings.gemini_api_key == "saved-gemini-key"
    assert settings.llm_provider == "gemini"
    assert settings.model == "saved-model"
    assert settings.gemini_enabled


def test_explicit_codex_provider_does_not_use_gemini_fallback(config_file, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-gemini-key")
    monkeypatch.setenv("MONIX_LLM_PROVIDER", "openai-codex")

    settings = Settings.from_env()

    assert settings.llm_provider == "openai-codex"
    assert settings.gemini_api_key == "env-gemini-key"
    assert not settings.gemini_enabled


def test_unsupported_provider_does_not_fall_back_to_gemini(config_file, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-gemini-key")
    monkeypatch.setenv("MONIX_LLM_PROVIDER", "not-supported")

    settings = Settings.from_env()

    assert settings.llm_provider == "not-supported"
    assert not settings.llm_enabled


def test_llm_model_env_wins_over_legacy_model_env_and_saved_model(config_file, monkeypatch):
    keystore._save({"llm_provider": "openai-codex", "model": "saved-model"})
    monkeypatch.setenv("MONIX_MODEL", "legacy-model")
    monkeypatch.setenv("MONIX_LLM_MODEL", "provider-model")

    assert Settings.from_env().model == "provider-model"


def test_codex_saved_legacy_default_moves_to_oauth_default(config_file):
    keystore._save({"llm_provider": "openai-codex", "model": "codex-mini-latest"})

    assert Settings.from_env().model == "gpt-5.5"


def test_provider_picker_offers_initial_providers(config_file, monkeypatch):
    seen = {}

    def pick_option(title, options, default=0):
        seen["title"] = title
        seen["options"] = options
        return 0

    monkeypatch.setattr("monix.picker.pick_option", pick_option)
    monkeypatch.setattr(cli, "_setup_gemini_provider", lambda settings: settings)

    settings = cli._prompt_llm_provider_setup(Settings.from_env())

    assert seen == {
        "title": "Select LLM provider",
        "options": [
            ("Gemini", "Gemini API key"),
            ("OpenAI Codex", "Codex CLI login from this user"),
        ],
    }
    assert settings.llm_provider == "gemini"


def test_codex_setup_reports_missing_cli(config_file, monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", lambda _command: None)

    result = cli._setup_codex_provider(Settings.from_env())

    output = capsys.readouterr().out
    assert result.llm_provider == "openai-codex"
    assert "Codex CLI is required" in output
    assert "codex login" in output
    assert not config_file.exists()


def test_codex_setup_reports_missing_current_user_auth(config_file, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", lambda _command: "codex")
    monkeypatch.setattr(cli, "_codex_auth_path", lambda: tmp_path / "missing-auth.json")

    cli._setup_codex_provider(Settings.from_env())

    output = capsys.readouterr().out
    assert "OpenAI Codex auth was not found" in output
    assert "codex login" in output
    assert not config_file.exists()


def test_codex_setup_stores_provider_without_copying_auth(config_file, tmp_path, monkeypatch, capsys):
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(
        json.dumps({"tokens": {"access_token": "codex-access-secret"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli.shutil, "which", lambda _command: "codex")
    monkeypatch.setattr(cli, "_codex_auth_path", lambda: auth_file)

    settings = cli._setup_codex_provider(Settings.from_env())

    saved = config_file.read_text(encoding="utf-8")
    output = capsys.readouterr().out
    assert settings.llm_provider == "openai-codex"
    assert settings.model == "gpt-5.5"
    assert json.loads(saved) == {
        "llm_provider": "openai-codex",
        "model": "gpt-5.5",
    }
    assert "codex-access-secret" not in saved
    assert "codex-access-secret" not in output


def test_codex_setup_rejects_auth_shape_runtime_will_not_load(
    config_file,
    tmp_path,
    monkeypatch,
    capsys,
):
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({"access_token": "top-level-token"}), encoding="utf-8")
    monkeypatch.setattr(cli.shutil, "which", lambda _command: "codex")
    monkeypatch.setattr(cli, "_codex_auth_path", lambda: auth_file)

    cli._setup_codex_provider(Settings.from_env())

    output = capsys.readouterr().out
    assert "OpenAI Codex auth was not found" in output
    assert not config_file.exists()


def test_codex_natural_language_uses_llm_route(config_file, monkeypatch):
    monkeypatch.setenv("MONIX_LLM_PROVIDER", "openai-codex")
    monkeypatch.setattr(cli, "answer", lambda raw, settings, history: f"codex:{raw}")

    settings = Settings.from_env()

    assert cli.dispatch_natural("check cpu pressure", settings) == "codex:check cpu pressure"
    assert cli._llm_spinner_message(settings) == "Asking OpenAI Codex..."
