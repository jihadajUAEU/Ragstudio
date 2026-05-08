# HPC Provider Sync Design

## Goal

Add a Cloudflare-published provider sync workflow to Ragstudio Settings so users can paste a hosted manifest URL, preview endpoint updates, and save a coordinated HPC runtime profile for LLM generation, embeddings, and MinerU parsing.

## Context

Meeting Copilot publishes provider metadata at URLs such as `https://updates.jihadaj.com/providers.json`. The current sample manifest includes:

```json
{
  "version": 2,
  "updatedAt": "2026-05-07T08:23:27.928Z",
  "reasoning": {
    "apiUrl": "http://10.10.9.195:8004/v1",
    "model": "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
    "timeoutMs": 5000
  },
  "embeddings": {
    "apiUrl": "http://10.10.9.192:8001/v1",
    "model": "Qwen/Qwen3-Embedding-8B",
    "dimensions": 1536,
    "timeoutMs": 10000
  },
  "hpcMineru": {
    "enabled": true,
    "apiUrl": "http://10.10.9.19:8765",
    "timeoutMs": 1800000
  }
}
```

Ragstudio already supports embeddings and MinerU settings, but the runtime profile only stores generic `provider` and `llm_model` values. This feature adds first-class LLM endpoint settings and a manifest sync flow that mirrors Meeting Copilot without making Ragstudio manage Cloudflare deployments.

## Scope

The Settings page gets a new **Provider sync** block above runtime service sections. It contains a `Provider manifest URL` text field, a `Sync` button, and a status/change preview line. Sync does not write to the database. It fetches and validates the manifest, applies supported values to the visible form fields, and leaves the final persistence step to the existing `Save` button.

The first supported manifest sections are:

- `reasoning`: updates LLM generation base URL, model, timeout, and read-only capabilities.
- `embeddings`: updates embedding base URL, model, dimensions, and timeout.
- `hpcMineru`: updates MinerU enabled flag, base URL, and timeout.

The `ragAnything` and `stt` manifest sections are ignored for now because Ragstudio does not expose matching runtime services in Settings.

## LLM Runtime Settings

Ragstudio should treat the LLM as an OpenAI-compatible generation endpoint. Settings should include:

- `llm_provider`: initially `openai_compatible`.
- `llm_base_url`: HTTP or HTTPS base URL, usually ending in `/v1`.
- `llm_api_key`: optional secret, preserved when omitted from save requests.
- `llm_timeout_ms`: request timeout for LLM test and future generation calls.
- `llm_model`: the existing model field.
- `llm_capabilities`: read-only capability labels for `text`, `vision`, and `reasoning`.

Capabilities are display metadata, not user-editable switches. If the manifest includes `reasoning.capabilities`, Ragstudio uses those values after filtering to supported labels. If the manifest omits capabilities, Ragstudio infers:

- `text`: enabled whenever a reasoning endpoint is configured.
- `reasoning`: enabled for the `reasoning` manifest section.
- `vision`: enabled only when the model name strongly signals multimodal support, such as `VL`, `Vision`, or `multimodal`.

## Data Flow

1. User enters a manifest URL in Settings.
2. User clicks **Sync**.
3. Frontend sends the URL to a backend sync-preview endpoint.
4. Backend validates the URL, fetches JSON with a short timeout, validates supported sections, and returns a proposed patch plus manifest metadata.
5. Frontend applies the proposed patch to the form fields only and shows changed field names.
6. User reviews the fields and clicks **Save**.
7. Existing settings save persists the default runtime profile.

## Backend API

Add `POST /api/settings/default/sync-provider-preview` with a small request body:

```json
{
  "manifest_url": "https://updates.jihadaj.com/providers.json"
}
```

The response includes:

```json
{
  "ok": true,
  "manifest_url": "https://updates.jihadaj.com/providers.json",
  "manifest_version": 2,
  "updated_at": "2026-05-07T08:23:27.928Z",
  "patch": {
    "llm_provider": "openai_compatible",
    "llm_base_url": "http://10.10.9.195:8004/v1",
    "llm_model": "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
    "llm_timeout_ms": 5000,
    "llm_capabilities": ["text", "vision", "reasoning"],
    "embedding_provider": "vllm_openai",
    "embedding_base_url": "http://10.10.9.192:8001/v1",
    "embedding_model": "Qwen/Qwen3-Embedding-8B",
    "embedding_dimensions": 1536,
    "embedding_timeout_ms": 10000,
    "mineru_enabled": true,
    "mineru_base_url": "http://10.10.9.19:8765",
    "mineru_timeout_ms": 1800000
  },
  "changed_fields": ["llm_base_url", "llm_model", "embedding_base_url", "mineru_base_url"],
  "ignored_sections": ["stt", "ragAnything"]
}
```

The backend compares the patch to the current saved settings to produce `changed_fields`, but it does not persist the patch.

Add `POST /api/settings/default/test-llm` to validate the configured LLM endpoint. It should call the OpenAI-compatible chat completions endpoint with a tiny prompt and return connected/failed status, latency, provider, model, and detail. If no API key is provided in the request but one is saved, the backend should reuse the saved key, matching embedding secret behavior.

## Error Handling

Sync fails without mutating form state when:

- the manifest URL is empty or not HTTP/HTTPS;
- the URL includes credentials;
- the URL returns non-JSON or malformed JSON;
- a supported section is present but not an object;
- supported fields have invalid types;
- the fetch times out or returns an HTTP error.

Partial manifests are allowed. Missing supported sections leave those form fields unchanged. Unknown sections are ignored and reported in `ignored_sections` when useful.

## Frontend UX

Settings should show a **Provider sync** section with:

- manifest URL input;
- Sync button with loading state;
- concise status message such as `Synced preview: LLM base URL, Embedding model, MinerU base URL`;
- failure message in the existing Settings message style.

Runtime controls should show an **LLM generation** area similar to Embeddings:

- provider select or fixed select with `OpenAI-compatible`;
- model;
- base URL;
- optional API key;
- timeout;
- read-only capability badges;
- Test LLM button.

Embeddings and MinerU remain separate sections, but sync can update their fields.

## Testing

Backend tests should cover manifest parsing, patch generation, partial manifests, malformed manifests, URL validation, ignored sections, saved LLM API key reuse, and LLM test success/failure.

Frontend tests should cover entering a manifest URL, clicking Sync, applying patch values to the form without saving, showing changed fields, preserving current values after sync failure, and sending the final patched settings through Save.

The full verification command remains:

```bash
PATH=$PWD/.venv/bin:$PATH ./scripts/test-all.sh
```
