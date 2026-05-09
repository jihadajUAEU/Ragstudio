<!-- generated-by: gsd-doc-writer -->
# RAG-Anything Studio User Guide

RAG-Anything Studio is a local workbench for uploading source material, indexing chunks, creating retrieval variants, asking grounded questions, importing evaluation sets, scoring experiment runs, comparing answers, and checking runtime diagnostics.

The app is designed for local RAG pipeline development. It stores state under `.ragstudio/` by default, serves the backend at `http://127.0.0.1:8000`, and serves the Vite frontend at `http://127.0.0.1:5173` when started with the project dev script.

## Setup and Running

Prerequisites:

- Python `>=3.12,<3.15`
- npm, for the frontend dependencies in `frontend/package.json`

Install backend and frontend dependencies from the repository root:

```bash
./scripts/setup.sh
```

The setup script runs:

```bash
python -m pip install -e "backend[dev]"
npm --prefix frontend install
```

Start the full local app:

```bash
./scripts/dev.sh
```

The dev script starts:

- FastAPI with `python -m uvicorn ragstudio.app:create_app --factory --reload --app-dir backend/src --host 127.0.0.1 --port 8000`
- Vite with `npm run dev -- --host 127.0.0.1 --port 5173`

Open the Studio UI at:

```text
http://127.0.0.1:5173
```

Run the full project test suite with:

```bash
./scripts/test-all.sh
```

## First Successful Workflow

Use this path to get from an empty local workspace to a completed answer and inspectable result:

1. Open `Settings`, fill `Provider`, `Storage backend`, `LLM generation`, and `Embeddings` fields, then click `Save`. If your HPC endpoints are published in a provider manifest, use `Provider sync` first and review the previewed fields before saving.
2. Open `Variants`, create a variant with `Name`, `Preset`, and a JSON `Parameters` object. The default example is:

   ```json
   {
     "top_k": 5,
     "temperature": 0.2
   }
   ```

3. Open `Documents`, choose a source file in `Upload file`, then click `Upload`.
4. Wait for the document row and the `Jobs` panel to show a succeeded indexing job.
5. Open `Chunks`, select the document, optionally click `Index`, enter `Question or search text`, set `Limit`, then click `Search`.
6. Open `Query`, enter a `Question`, select at least one document and one variant, set `Chunk limit`, then click `Run`.
7. Review the `Answers and traces` result: answer text, `Sources`, `Chunk traces`, and `Timings`.
8. Open `Comparison` to compare recorded runs, or import an evaluation set in `Evaluation` and run a scored experiment from `Experiments`.

## Pages

### Dashboard

`Dashboard` is the operational overview. It shows API health, uploaded document count, recorded run count, graph node and edge counts, diagnostics warnings, recent documents, jobs, variants, and runs. Use `Refresh` when another page has changed state and you want a current snapshot.

### Pipeline

`Pipeline` shows the RAG flow from source files to grounded answers. The canvas stages are `Documents`, `Chunking`, `Variants`, `Retrieval`, `Generation`, `Graph`, and `Answer`. The `Stage checklist` summarizes document count, chunk indexing, variant count, scoped retrieval, recorded runs, answer traces, and graph edges.

### Documents

`Documents` is for source file upload and ingestion status.

Fields and controls:

- `Upload file`: local file chooser.
- `Upload`: sends the file to the backend.
- `Refresh`: reloads documents and jobs.

Tables:

- `Documents`: `Document`, `Status`, and `SHA-256`.
- `Jobs`: `Job`, `Progress`, `Status`, and `Latest log`.

Duplicate uploads are detected by SHA-256. If a duplicate document is missing chunks, Studio re-indexes it.

### Chunks

`Chunks` is the chunk inspector. Use it to inspect RAGed results before running generation.

Controls:

- `Documents`: select one or more uploaded documents.
- `Index`: re-indexes a selected document.
- `Question or search text`: text used to rank chunks.
- `Limit`: maximum returned chunks, from `1` to `100`.
- `Search`: searches selected document chunks.

Results show each chunk's `id`, `document_id`, `score`, chunk text, `Source location`, and `Metadata`.

Chunk search is scoped by selected document IDs. If you submit without a document selected, the UI shows `Select at least one document to avoid searching every chunk.`

### Query

`Query` asks questions against chunk contents and records runs.

Fields and controls:

- `Question`: the question to ask.
- `Documents`: one or more uploaded documents to scope retrieval.
- `Variants`: one or more variants to run.
- `Chunk limit`: maximum chunks passed into each run, from `0` to `50`; default is `8`.
- `Run`: executes the query once per selected variant.

Results appear under `Answers and traces`:

- Answer text, or the run error if generation failed.
- `Sources`: source chunk objects used for the answer.
- `Chunk traces`: adapter trace objects, including inclusion status when available.
- `Timings`: measured `search_ms`, `query_ms`, and `total_ms`, plus adapter timings when provided.

When the local fallback adapter is active, a generated answer is the question followed by selected chunk excerpts. This is useful for validating indexing, search, and trace plumbing even without a full `raganything` backend.

### Evaluation

`Evaluation` imports and inspects evaluation sets.

Fields and controls:

- `Set name`: display name for the imported set. If blank at submit time, the file name is used.
- `Upload evaluation file`: accepts `.csv`, `.json`, `.yaml`, `.yml`, and `.jsonl`.
- `Import`: imports the file.
- `Refresh`: reloads imported sets.

The `Sets` table shows `Set`, `Cases`, and `ID`. Click a set name to inspect its `Cases`. Case cards show the query, case ID, document count, expected answer when present, `Include` and `Avoid` chips, and expandable JSON `Details`.

### Experiments

`Experiments` runs evaluation cases across selected variants and documents.

Fields and controls:

- `Name`: experiment name.
- `Evaluation set`: imported evaluation set to run.
- `Documents`: fallback document scope for cases that do not specify their own `documents`.
- `Variants`: variants to compare.
- `Objective JSON`: JSON object stored with the experiment. The default is:

  ```json
  {
    "metric": "total"
  }
  ```

- `Run`: executes every evaluation case across every selected variant.

The `Runs and scores` area shows experiment metadata, returned runs, and score rows. Scores are generated by comparing answer text against evaluation signals. `expected_answer` contributes expected term hits, `must_include` contributes required phrase hits, and `must_avoid` penalizes avoided phrase hits.

### Comparison

`Comparison` compares recorded query and experiment runs.

The `Runs` table shows `Compare`, `Query`, `Variant`, and `Status`. The first two runs are selected by default until you edit the selection. Selected runs appear under `Answers, sources, and traces`, where each card shows the answer or error plus expandable `Sources`, `Traces`, and `Timings`.

### Optimizer

`Optimizer` recommends the strongest variant for an experiment.

Fields and controls:

- `Experiment ID`: experiment to optimize. If recent experiment runs exist, the page shows `Recent experiment` with a `Use` button.
- `Objective JSON`: JSON object for the optimization objective. The default is:

  ```json
  {
    "metric": "total"
  }
  ```

- `Recommend`: creates an optimization recommendation.

The recommendation shows `Selected variant`, an explanation, candidate summaries, and expandable `Recommendation details`. Candidate summaries include variant, run count, average score, and best score. If persisted scores are unavailable for a run, the optimizer falls back to a run-derived score: failed runs score `0`, and successful runs score `min(100, 50 + 10 * source_count)`.

### Variants

`Variants` manages retrieval and generation variants.

Fields and controls:

- `Name`: required variant name.
- `Preset`: one of `Balanced`, `Precise`, `Broad`, or `Fast`.
- `Parameters`: JSON object. The page requires valid object JSON.
- `Create`: saves the variant.
- `Refresh`: reloads variants.

The `Variant matrix` table lists each variant name, ID, preset, and parameter key/value chips.

### Graph

`Graph` reads `/api/graph` and exposes the returned graph payload for debugging graph-backed retrieval.

It shows node and edge counts, then previews up to 50 `Nodes` and 50 `Edges`. In fallback mode, the graph service returns no nodes or edges, so the page shows `Graph is empty`.

### Diagnostics

`Diagnostics` reports backend capabilities and dependency status.

It shows:

- `Capabilities`: flags such as `raganything_available`, `fallback_active`, `indexing`, `query`, and `graph`.
- `Dependencies`: values such as `raganything`, `active_backend`, `indexing`, `query`, and `graph`.
- `Warnings`: active runtime warnings.
- `Raw diagnostics`: expandable full JSON payload.

If `raganything` is not installed in the active Python environment, Diagnostics reports a warning and Studio uses the local fallback adapter. Run `./scripts/setup.sh` or `python -m pip install -e 'backend[dev]'` to install the backend with its declared dependencies, including `raganything[all]`.

### Settings

`Settings` manages the default runtime profile.

Runtime profile fields:

- `Provider`
- `Storage backend`

Provider sync fields:

- `Provider manifest URL`: Cloudflare-hosted JSON manifest, such as `https://updates.jihadaj.com/providers.json`.
- `Sync`: fetches the manifest and previews supported endpoint changes in the form. Sync does not save; click `Save` after reviewing the populated fields.

Supported manifest sections:

- `reasoning`: updates the OpenAI-compatible LLM endpoint, model, timeout, and read-only capability badges.
- `embeddings`: updates embedding provider, model, base URL, dimensions, and timeout.
- `hpcMineru`: updates MinerU enabled state, base URL, and timeout.

LLM generation fields:

- `LLM provider`: OpenAI-compatible generation endpoint.
- `LLM model`: model name sent to `/chat/completions`.
- `LLM base URL`: OpenAI-compatible base URL such as `http://10.10.9.195:8004/v1`.
- `LLM API key`: optional bearer token. Saved keys are not returned by the API.
- `LLM timeout (ms)`: request timeout for the connection test and future generation calls.
- `Capabilities`: read-only `Text`, `Vision`, and `Reasoning` badges from the manifest or model inference.

Embeddings fields:

- `Embedding provider`: `Local fallback` or `vLLM / OpenAI-compatible`.
- `Embedding model`: model name sent to the embeddings endpoint.
- `Base URL`: OpenAI-compatible base URL such as `http://127.0.0.1:8001/v1`.
- `API key`: optional bearer token. Saved keys are not returned by the API.
- `Timeout (ms)`: request timeout for the connection test and future embedding calls.
- `Dimensions`: expected vector dimension.
- `Batch size`: planned maximum embedding batch size.
- `Verify TLS`: TLS verification for HTTPS endpoints.

MinerU parser fields:

- `Enable MinerU`: marks MinerU as available for parser-mode choices.
- `MinerU base URL`: URL for an already running MinerU/RAG-Anything service, normally `http://127.0.0.1:8765` through a local sidecar or SSH tunnel.
- `MinerU timeout (ms)`: total parse polling timeout.
- `MinerU poll interval (ms)`: delay between parse job status checks.

Controls:

- `Reload`: refetches the saved default profile.
- `Sync`: previews provider manifest changes for LLM, embeddings, and MinerU.
- `Test LLM`: sends a tiny chat-completions request to the configured LLM endpoint.
- `Test connection`: sends a one-text embedding request to `/embeddings` and validates vector dimensions.
- `Test MinerU`: checks the configured MinerU `/health` endpoint.
- `Reset`: resets unsaved form edits.
- `Save`: writes the default profile.

If no profile exists, the page shows `No default profile saved`.

For UAEU HPC or another Slurm-hosted vLLM embedding job, use an SSH tunnel or stable internal alias and set `Base URL` to the local OpenAI-compatible endpoint, for example `http://127.0.0.1:8001/v1`. The model name must match the model served by vLLM, such as `Qwen/Qwen3-Embedding-8B`.

### MinerU parser and domain metadata

Settings includes a `MinerU parser` section for connecting to an already running MinerU/RAG-Anything sidecar. Set the base URL, normally `http://127.0.0.1:8765` when using an SSH tunnel or local sidecar, then click `Test MinerU`.

For `MinerU strict`, Ragstudio requires the sidecar health response to report `hpcMineru.enabled=true` and `hpcMineru.mode=coordinator` by default. If the sidecar reports `mode=local`, strict parsing is blocked before a job is queued because large PDFs can appear stuck at `25%` while local MinerU parsing runs inside the sidecar process. Disable `Require HPC MinerU coordinator` only when you intentionally want the sidecar to parse locally and accept the longer single-process runtime.

Upload and Index actions support three parser modes:

- `Local fallback`: uses Studio's local line splitter.
- `MinerU strict`: sends the document to MinerU and fails indexing if MinerU fails.
- `MinerU with fallback`: tries MinerU first, then indexes locally if MinerU fails.

Before parsing, choose or review domain metadata. This metadata is copied onto every resulting chunk, including local fallback chunks. MinerU adds parser metadata such as page numbers, artifact references, content type, and parse job id.

Auto-suggest uses the configured vision model before upload indexing starts. Ragstudio samples up to four representative pages from the selected file, asks the model for strict domain metadata JSON, validates the response, and shows changed fields before applying them. Filename-only heuristics are not used for autosuggest.

For large parsed documents, Ragstudio applies metadata-driven chunk profiles. Tafseer/book uploads are split into semantic retrieval chunks, Quran-style text favors verse-aware chunks, papers favor section chunks, and every parser path has a hard cap to prevent oversized single chunks.

## Evaluation File Formats

Studio accepts JSONL, NDJSON, JSON, YAML, YML, and CSV evaluation imports. JSONL is the canonical repeatable format.

Every imported case must have a `query` and at least one expected-output signal. If `id` is missing, Studio assigns `case-1`, `case-2`, and so on.

Accepted case fields:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Optional in import files; generated when omitted. |
| `query` | string | Required question text. Aliases: `question`, `prompt`. |
| `documents` | string list | Optional document IDs. If present, experiments use these instead of the experiment-level document selection for that case. |
| `expected_answer` | string | Expected answer text. Aliases: `expected_output`, `expected`, `answer`. |
| `expected_sources` | string list | Expected source identifiers. Alias: `sources`. |
| `must_include` | string list | Phrases that should appear in the answer. |
| `must_avoid` | string list | Phrases that should not appear in the answer. |
| `expected_media` | list of objects | Structured media expectations. |
| `expected_structure` | object | Structured answer-shape expectations. |
| `rubric` | object with string values | Rubric metadata. |
| `objective` | object | Case-level objective metadata. |
| `variant_hints` | object of string lists | Variant-specific hints. |

Expected-output signals are `expected_answer`, `expected_sources`, `must_include`, `must_avoid`, `expected_media`, `expected_structure`, `rubric`, or `objective`. A case with none of these signals is rejected.

### JSONL and NDJSON

Use one evaluation case object per line:

```jsonl
{"id":"case-1","query":"What changed in the contract?","expected_answer":"The renewal term changed.","must_include":["renewal term"]}
{"id":"case-2","query":"Which source mentions pricing?","expected_sources":["pricing.pdf"]}
```

### JSON

Use an array of cases, an object with a `cases` array, an object with an `items` array, or a single case object:

```json
{
  "cases": [
    {
      "id": "case-1",
      "query": "What changed in the contract?",
      "expected_answer": "The renewal term changed."
    }
  ]
}
```

### YAML and YML

YAML follows the same shapes as JSON:

```yaml
cases:
  - id: case-1
    query: What changed in the contract?
    expected_answer: The renewal term changed.
    must_include:
      - renewal term
```

### CSV

CSV imports map columns into evaluation case fields. Use simple scalar columns for `id`, `query`, and `expected_answer`.

List-like fields use pipe-delimited values inside a cell:

- `documents`
- `expected_sources`
- `must_include`
- `must_avoid`

Structured fields must contain valid JSON inside the cell:

- `expected_media`
- `expected_structure`
- `rubric`
- `objective`
- `variant_hints`

Example:

```csv
id,query,expected_answer,must_include,expected_sources
case-1,What changed in the contract?,The renewal term changed.,renewal term|effective date,contract.pdf
```

Example with a structured rubric:

```csv
id,query,rubric,expected_structure
case-2,Summarize the timeline,"{""accuracy"":""Dates must match the source.""}","{""format"":""bullet-list""}"
```

## Inspecting RAGed Results

Use `Chunks` before `Query` when you need to understand what will be available to generation:

1. Select the uploaded document.
2. Click `Index` if you want to rebuild chunks.
3. Enter a focused phrase or question in `Question or search text`.
4. Set `Limit`.
5. Click `Search`.

The returned chunk cards show:

- `score`: search score added by Studio.
- `text`: chunk content.
- `Source location`: adapter-provided location data, such as a line number in fallback mode.
- `Metadata`: safe metadata with absolute file paths removed.

Fallback search scores use term overlap, term density, and a phrase bonus. An empty search query returns chunks in source order with score `1.0`.

## Asking Questions Against Chunk Contents

Use `Query` when you want Studio to retrieve chunks and create recorded run results.

Required inputs:

- Non-empty `Question`.
- At least one selected document.
- At least one selected variant.

For each selected variant, Studio:

1. Validates the selected document and variant IDs.
2. Searches chunks scoped to selected documents.
3. Sends selected chunks to the active adapter.
4. Records a run with status, answer, sources, chunk traces, timings, and any error.

The returned runs are also available in `Comparison`, `Optimizer`, and the `Dashboard`.

## Diagnostics and Fallback Behavior

Studio has a safe adapter boundary around the optional `raganything` integration.

When `raganything` is available, Diagnostics reports `raganything_available: true` and clears the missing-dependency warning. The current adapter can still report fallback execution for paths not yet wired to upstream RAG-Anything APIs. When `raganything` is unavailable, the backend still runs with fallback behavior:

- `active_backend`: `fallback`
- `indexing`: `line_split_fallback`
- `query`: `simple_fallback`
- `graph`: `placeholder`

Fallback indexing reads uploaded bytes as UTF-8 with replacement for invalid characters, splits content into non-empty lines, and creates one chunk per non-empty line. If the file has no line breaks but has text, it creates one chunk from the stripped content.

Fallback query uses the selected chunks directly. If chunks are present, the answer is the stripped query followed by the selected chunk text. If no chunks are selected, the answer is empty.

Fallback graph returns an empty graph payload. This is why `Graph` may show `Graph is empty` even when document upload, chunk search, and query runs work.

## Troubleshooting

### The frontend cannot reach the backend

Start the app with:

```bash
./scripts/dev.sh
```

The backend must be available on `127.0.0.1:8000` for the default frontend API calls. If you run the frontend separately against another backend URL, set `VITE_API_BASE_URL` for Vite before starting it.

### Diagnostics says `raganything` is missing

Install the backend dependencies:

```bash
./scripts/setup.sh
```

or:

```bash
python -m pip install -e "backend[dev]"
```

That backend install includes the declared `raganything[all]` dependency.

The app still works in fallback mode, but graph output is a placeholder and query answers are simple chunk excerpts.

### Settings shows `No default profile saved`

Open `Settings`, enter the runtime profile fields, and click `Save`. For vLLM embeddings, also set `Embedding provider`, `Embedding model`, `Base URL`, `Timeout`, `Dimensions`, and `Batch size`.

### Query cannot run

Check that:

- `Question` is not empty.
- At least one document is selected.
- At least one variant is selected.
- The selected document has been uploaded and indexed.

If a selected document or variant no longer exists, the backend returns a `404` with a message like `Document not found: ...` or `Variant not found: ...`.

### Chunk search returns no matches

Try one of these:

- Click `Index` for the selected document.
- Search for a term that appears directly in the source file.
- Increase `Limit`.
- Use an empty `Question or search text` to inspect chunks in source order.

### Evaluation import fails

Check that:

- The file is valid UTF-8.
- The extension is `.csv`, `.json`, `.yaml`, `.yml`, `.jsonl`, or `.ndjson`.
- JSON and YAML cases are objects, arrays of objects, or wrapped in `cases` or `items`.
- Every case has a `query`.
- Every case has at least one expected-output signal.
- CSV list fields use `|` as the separator.
- CSV structured fields contain valid JSON.

### Experiment fails before running cases

Check that the selected evaluation set exists, at least one document and one variant are selected, and `Objective JSON` is valid object JSON. If a case includes `documents`, those document IDs must exist because they override the experiment-level document selection for that case.

### Optimizer says `Experiment not found`

Run an experiment first from `Experiments`, then copy the returned experiment ID into `Optimizer`. If recent experiment runs exist, use the `Use` button next to `Recent experiment`.

### Graph is empty

An empty graph is expected in fallback mode. Confirm `Diagnostics` first. If `graph` reports `placeholder`, graph-backed retrieval data is not available from the current adapter.
