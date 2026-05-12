from ragstudio.services.reranker_service import RerankerService


def test_reranker_allowlist_accepts_ipv4_wildcard():
    service = RerankerService(allowed_hosts=["10.10.9.*"])

    assert service._is_allowed_endpoint("http://10.10.9.193:8005/v1/rerank")


def test_reranker_allowlist_rejects_other_private_subnets():
    service = RerankerService(allowed_hosts=["10.10.9.*"])

    assert not service._is_allowed_endpoint("http://10.10.8.193:8005/v1/rerank")


def test_reranker_allowlist_wildcard_requires_valid_ipv4_host():
    service = RerankerService(allowed_hosts=["10.10.9.*"])

    assert not service._is_allowed_endpoint("http://10.10.9.evil.test/v1/rerank")
