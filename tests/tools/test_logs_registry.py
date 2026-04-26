import json
from pathlib import Path
from unittest.mock import patch

import pytest

from monix.tools.logs.registry import LogEntry, add, aliases, get, load, remove


@pytest.fixture
def tmp_registry(tmp_path, monkeypatch):
    reg_file = tmp_path / ".monix" / "log_registry.json"
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_DIR", tmp_path / ".monix")
    monkeypatch.setattr("monix.tools.logs.registry._REGISTRY_FILE", reg_file)
    return reg_file


# --- load ---

def test_load_empty_when_no_file(tmp_registry):
    assert load() == []


def test_load_returns_entries(tmp_registry):
    tmp_registry.parent.mkdir(parents=True)
    tmp_registry.write_text(json.dumps([
        {"alias": "api", "type": "app", "path": "/var/log/api.log", "container": None}
    ]))
    entries = load()
    assert len(entries) == 1
    assert entries[0].alias == "api"
    assert entries[0].type == "app"


def test_load_handles_corrupt_file(tmp_registry):
    tmp_registry.parent.mkdir(parents=True)
    tmp_registry.write_text("not json{{{")
    assert load() == []


# --- add ---

def test_add_new_entry(tmp_registry):
    entry, is_new = add("web", "app", path="/var/log/web.log")
    assert is_new is True
    assert entry.alias == "web"
    assert entry.path == "/var/log/web.log"


def test_add_updates_existing(tmp_registry):
    add("web", "app", path="/old/path.log")
    entry, is_new = add("web", "app", path="/new/path.log")
    assert is_new is False
    assert entry.path == "/new/path.log"


def test_add_docker_entry(tmp_registry):
    entry, is_new = add("mycontainer", "docker", container="web_container")
    assert is_new is True
    assert entry.container == "web_container"
    assert entry.type == "docker"


def test_add_persists_to_file(tmp_registry):
    add("api", "app", path="/var/log/api.log")
    data = json.loads(tmp_registry.read_text())
    assert any(e["alias"] == "api" for e in data)


# --- remove ---

def test_remove_existing_alias(tmp_registry):
    add("api", "app", path="/var/log/api.log")
    assert remove("api") is True
    assert get("api") is None


def test_remove_nonexistent_alias(tmp_registry):
    assert remove("ghost") is False


def test_remove_leaves_others_intact(tmp_registry):
    add("api", "app", path="/var/log/api.log")
    add("web", "app", path="/var/log/web.log")
    remove("api")
    assert get("web") is not None


# --- get ---

def test_get_existing(tmp_registry):
    add("nginx", "nginx", path="/var/log/nginx/access.log")
    entry = get("nginx")
    assert entry is not None
    assert entry.alias == "nginx"
    assert entry.type == "nginx"


def test_get_nonexistent(tmp_registry):
    assert get("nope") is None


# --- aliases ---

def test_aliases_empty(tmp_registry):
    assert aliases() == []


def test_aliases_returns_names(tmp_registry):
    add("a", "app", path="/a.log")
    add("b", "app", path="/b.log")
    result = aliases()
    assert "a" in result
    assert "b" in result
