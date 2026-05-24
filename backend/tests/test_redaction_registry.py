from ragstudio.services.redaction_registry import find_redaction_matches, redact_text


def test_shared_redaction_registry_detects_secret_and_private_location() -> None:
    text = (
        "token sk-exampleSecretValue123456 "
        "host http://127.0.0.1:8000 "
        "path C:\\Users\\jihad\\private.txt"
    )

    matches = find_redaction_matches(text)
    rule_ids = {match.rule_id for match in matches}

    assert "openai_key" in rule_ids
    assert "localhost" in rule_ids
    assert "local_absolute_path" in rule_ids


def test_shared_redaction_registry_redacts_values() -> None:
    text = "Authorization: Bearer abcdefghijklmnop and file://private"

    redacted = redact_text(text)

    assert "abcdefghijklmnop" not in redacted
    assert "file://" not in redacted
    assert "[REDACTED:bearer_token]" in redacted
    assert "[REDACTED:file_uri]" in redacted
