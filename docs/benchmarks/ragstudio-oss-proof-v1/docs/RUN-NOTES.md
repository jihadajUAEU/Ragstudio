# Run Notes

## Capture Mode

This Phase 1 packet was created as a static fixture packet. It is not a live
backend export and does not call any provider endpoint.

## Source Commit

The manifest and claims registry record the source commit used when the first
packet artifacts were authored.

## Evidence Included

The packet includes redacted JSON artifacts for:

- parser quality,
- chunk metadata,
- retrieval run traces,
- graph projection state,
- reranker traces.

The artifacts are intentionally small but complete for the synthetic run they
represent.

## Evidence Not Included

The packet does not include:

- live provider responses,
- customer files,
- restricted real corpus text,
- private endpoints,
- local runtime cache files,
- benchmark-scale performance output.

Scale and public-upload claims remain non-proven in the claims registry.
