from monix.llm import registry


def test_exclusion_list_dropped():
    names = registry.tool_names()
    for excluded in ("human_bytes", "human_duration", "build_alerts"):
        assert excluded not in names


def test_expected_tools_registered():
    names = set(registry.tool_names())
    expected = {
        "collect_snapshot",
        "memory_info",
        "disk_info",
        "top_processes",
        "service_status",
        "tail_log",
        "follow_log",
        "filter_errors",
        "classify_line",
    }
    assert expected.issubset(names)


def test_list_tools_returns_schemas_with_expected_shape():
    schemas = registry.list_tools()
    assert schemas, "registry should expose at least one tool"
    for schema in schemas:
        assert set(schema.keys()) >= {"name", "description", "parameters"}
        params = schema["parameters"]
        assert params["type"] == "object"
        assert "properties" in params
        assert isinstance(params["properties"], dict)


def test_service_status_required_field():
    schemas = {s["name"]: s for s in registry.list_tools()}
    schema = schemas["service_status"]
    assert "name" in schema["parameters"]["properties"]
    assert schema["parameters"]["properties"]["name"]["type"] == "string"
    assert "name" in schema["parameters"].get("required", [])


def test_top_processes_optional_int_arg():
    schemas = {s["name"]: s for s in registry.list_tools()}
    schema = schemas["top_processes"]
    assert schema["parameters"]["properties"]["limit"]["type"] == "integer"
    assert "limit" not in schema["parameters"].get("required", [])


def test_get_tool_lookup():
    func = registry.get_tool("classify_line")
    assert callable(func)
    assert registry.get_tool("does_not_exist") is None


def test_discover_filters_excluded(monkeypatch):
    """Whitebox: re-running _discover should respect EXCLUDED_TOOL_NAMES even
    if a new tool is added to ``monix.tools.__all__``."""

    def fake_tool() -> dict:
        """fake docstring"""
        return {"ok": True}

    import monix.tools as tools_module

    original_all = list(tools_module.__all__)
    monkeypatch.setattr(tools_module, "fake_tool", fake_tool, raising=False)
    monkeypatch.setattr(tools_module, "__all__", original_all + ["fake_tool"])

    funcs, schemas = registry._discover()
    assert "fake_tool" in funcs
    schema_names = {s["name"] for s in schemas}
    assert "fake_tool" in schema_names
    assert "human_bytes" not in funcs
