# Synthetic Protocol Specification: Aurora Cache Handshake

> Synthetic sample. Inspired by public document structure, not copied from any source.

## SP-1.1 Scope

Aurora Cache Handshake defines how a client advertises cache freshness before requesting a model artifact. The protocol is intentionally small so Ragstudio can test exact section retrieval and normative language.

## SP-1.2 Normative Language

The words MUST, SHOULD, and MAY are used as test markers. A client MUST send a `Cache-Intent` header before requesting a resumable artifact. A server SHOULD include `Trace-Anchor` when the response is assembled from more than one storage layer.

## SP-2.1 Freshness Request

The request contains three fields: `artifact_id`, `known_revision`, and `max_age_seconds`. If `known_revision` is empty, the server MUST treat the request as a cold fetch.

## SP-2.2 Error Handling

If the artifact is unavailable, the server MUST return `STALE_MISS`. If the client asks for an unknown artifact family, the server SHOULD return `FAMILY_UNKNOWN`.

## SP-3.1 Cross-Reference

The server response in SP-2.1 depends on the trace field defined in SP-1.2. Ragstudio should preserve both section labels so an answer can cite the exact clause.

## SP-9.9 Unsupported Claim Trap

This document does not define encryption algorithms, transport ports, or authentication tokens. Questions about those details should not be answered from this document.
