from monix.llm.masker import mask_text, mask_value


def test_mask_text_replaces_api_key_keyword_value():
    masked = mask_text('api_key="abcd-1234-secret"')
    assert "abcd-1234-secret" not in masked
    assert "***" in masked


def test_mask_text_replaces_jwt():
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.signature_abc"
    masked = mask_text(f"token: {jwt}")
    assert jwt not in masked
    assert "***" in masked


def test_mask_text_replaces_long_hex():
    hex_token = "a" * 40
    masked = mask_text(f"hash={hex_token}")
    assert hex_token not in masked


def test_mask_text_replaces_aws_key():
    masked = mask_text("AKIAABCDEFGHIJKLMNOP")
    assert masked == "***"


def test_mask_text_passthrough_for_non_secret():
    plain = "CPU usage 85%, memory 4.2 GiB"
    assert mask_text(plain) == plain


def test_mask_value_walks_dict_and_list():
    payload = {
        "logs": [
            {"line": 'SECRET="hunter2hunter"'},
            {"line": "ok"},
        ],
        "auth": {"value": 'token="abc-token-123"'},
    }
    masked = mask_value(payload)
    assert "hunter2hunter" not in masked["logs"][0]["line"]
    assert masked["logs"][1]["line"] == "ok"
    assert "abc-token-123" not in masked["auth"]["value"]


def test_mask_value_keeps_non_string_scalars():
    assert mask_value(42) == 42
    assert mask_value(None) is None
    assert mask_value(True) is True
