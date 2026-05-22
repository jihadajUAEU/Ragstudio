# Limitations

## What This Packet Proves

This packet proves that a public reviewer can inspect:

- proof packet structure,
- manifest provenance,
- artifact hash coverage,
- public claim statuses,
- synthetic parser-quality warnings,
- chunk and trace evidence,
- graph and reranker evidence state,
- redaction and screenshot-signoff policy.

## What This Packet Does Not Prove

This packet does not prove:

- 2000+ page scale,
- GPU performance,
- customer validation,
- public upload safety,
- live hosted backend uptime,
- parser recall over a real corpus,
- retrieval quality over a production corpus.

Those claims remain roadmap, disabled, or out of scope unless future public
artifacts prove them.

## Screenshot Limitation

Screenshots require manual signoff. A screenshot cannot support a proven claim
unless `screenshots/signoff.json` marks it safe to publish.

## Synthetic Corpus Limitation

The Arabic and English content is artificial. It demonstrates trace and warning
shape, not rights-cleared coverage of a real corpus.

## Retrieval Architecture Limitations

- Domain-specific lexical expansion is registry-based, but only adapters present
  in the public fixture are proven by this packet.
- Native RAG-Anything is a secondary runtime lane. Public proof claims are made
  from canonical Ragstudio evidence and hydrated bridge metadata, not from opaque
  runtime snippets alone.
- Layout-aware retrieval uses canonical page, reference, content type, and
  provenance metadata. Query-time visual reinspection is not part of the V1
  static proof path.
- Context assembly includes safe breadcrumbs and dropped-evidence reasons, but
  does not claim full document summarization or unbounded sliding-window recall.
