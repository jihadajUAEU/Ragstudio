from ragstudio.services.runtime_policy import (
    DEFAULT_EMBEDDING_PROVIDER,
    DEFAULT_PARSER_MODE,
    DEFAULT_RUNTIME_MODE,
    DEFAULT_STORAGE_BACKEND,
    ProductPolicyError,
    enforce_product_index_options,
    enforce_product_runtime_settings,
    normalize_embedding_provider,
    normalize_parser_mode,
    normalize_runtime_mode,
    normalize_storage_backend,
)


def test_runtime_policy_defaults_are_explicit():
    assert DEFAULT_RUNTIME_MODE == "runtime"
    assert DEFAULT_STORAGE_BACKEND == "postgres_pgvector_neo4j"
    assert DEFAULT_PARSER_MODE == "mineru_strict"
    assert DEFAULT_EMBEDDING_PROVIDER == "vllm_openai"


def test_fallback_storage_is_removed_from_product_runtime():
    try:
        normalize_runtime_mode("runtime", "fallback_local")
    except ValueError as exc:
        assert "fallback" in str(exc)
    else:
        raise AssertionError("Expected fallback storage to be rejected")


def test_missing_runtime_values_use_defaults_but_invalid_values_fail_closed():
    assert normalize_runtime_mode(None, "postgres_pgvector_neo4j") == "runtime"
    assert normalize_storage_backend(None) == "postgres_pgvector_neo4j"
    assert normalize_parser_mode(None) == "mineru_strict"
    assert normalize_embedding_provider(None) == "vllm_openai"
    for call in (
        lambda: normalize_runtime_mode("nonsense", "postgres_pgvector_neo4j"),
        lambda: normalize_storage_backend("nonsense"),
        lambda: normalize_parser_mode("nonsense"),
        lambda: normalize_embedding_provider("nonsense"),
    ):
        try:
            call()
        except ValueError:
            pass
        else:
            raise AssertionError("Expected invalid product runtime value to be rejected")


def test_legacy_parser_modes_are_removed_after_migration():
    for value in ("local_fallback", "mineru_with_fallback"):
        try:
            normalize_parser_mode(value)
        except ValueError as exc:
            assert value in str(exc)
        else:
            raise AssertionError(f"Expected {value} to be rejected")


def test_product_index_policy_rejects_fallback_parser_modes():
    for parser_mode in ("local_fallback", "mineru_with_fallback"):
        try:
            enforce_product_index_options(parser_mode=parser_mode)
        except ProductPolicyError as exc:
            assert "mineru_strict" in str(exc)
        else:
            raise AssertionError(f"Expected ProductPolicyError for {parser_mode}")


def test_product_index_policy_accepts_mineru_strict():
    enforce_product_index_options(parser_mode="mineru_strict")


def test_product_runtime_policy_rejects_fallback_storage_and_runtime():
    for storage_backend, runtime_mode in (
        ("fallback_local", "fallback"),
        ("postgres_pgvector_neo4j", "fallback"),
    ):
        try:
            enforce_product_runtime_settings(
                storage_backend=storage_backend,
                runtime_mode=runtime_mode,
            )
        except ProductPolicyError:
            pass
        else:
            raise AssertionError("Expected ProductPolicyError")


def test_product_runtime_policy_accepts_postgres_runtime_and_rejects_degraded():
    enforce_product_runtime_settings(
        storage_backend="postgres_pgvector_neo4j",
        runtime_mode="runtime",
    )
    try:
        enforce_product_runtime_settings(
            storage_backend="postgres_pgvector_neo4j",
            runtime_mode="degraded",
        )
    except ProductPolicyError as exc:
        assert "runtime_mode=runtime" in str(exc)
    else:
        raise AssertionError("Expected degraded runtime mode to be rejected")
