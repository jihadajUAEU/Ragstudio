# Evaluation, Experiments, Comparison, Optimizer, Variants, and Graphs

This guide explains how to test Ragstudio answers in simple terms.

Use it when you want to answer one question:

> Which settings give the best grounded answers for my uploaded documents?

## The Short Version

1. Upload and index a document in `Documents`.
2. Create a few `Variants`. Each variant is one way to retrieve chunks and write answers.
3. Import an `Evaluation` set. This is a list of test questions and expected checks.
4. Run an `Experiment`. This tests every selected variant against every evaluation question.
5. Open `Comparison`. This lets you inspect answer quality, sources, traces, and timings side by side.
6. Open `Optimizer`. This recommends the strongest variant from the experiment scores.
7. Open `Graph`. This shows how documents, chunks, references, and relationships connect.

## Simple Meaning of Each Page

| Page | Simple meaning | Use it for |
| --- | --- | --- |
| `Variants` | Different recipes for retrieval and answers | Try precise, broad, balanced, or fast settings |
| `Evaluation` | A test sheet with questions and expected checks | Define what a good answer should include or avoid |
| `Experiments` | A batch test runner | Run the same questions across many variants |
| `Comparison` | Side-by-side answer review | See which answer has better sources and fewer mistakes |
| `Optimizer` | A score-based recommender | Pick the best variant from experiment results |
| `Graph` | A relationship map | Inspect connected references, chunks, entities, and edges |

## Example Scenario

The repository includes a Quran experiment sample pack:

```text
samples/quran_experiment/
```

It contains ready-to-use files:

| File | Where to use it |
| --- | --- |
| `quran-domain-metadata.json` | Use during document upload or reindexing |
| `quran-evaluation-set.json` | Import on the `Evaluation` page |
| `quran-variants.json` | Create on the `Variants` page |
| `experiment-objective.json` | Paste into `Experiments` objective JSON |
| `optimizer-objective.json` | Paste into `Optimizer` objective JSON |
| `comparison-checklist.md` | Use while reviewing runs on `Comparison` |

The sample tests questions like:

```text
What does Quran 2:255 say about Allah's life, sleep, knowledge, and Kursi?
```

A good answer should use the uploaded Quran PDF, include the right verse, and avoid unsupported outside material.

If you are testing a contract, policy, paper, or book instead, use the same workflow. Replace the Quran examples with questions and expected checks for your own document.

## Step 1: Create Variants

A variant is a saved set of retrieval and answer settings.

Think of variants as different strategies:

| Preset | Simple meaning | Good for |
| --- | --- | --- |
| `Precise` | Use fewer chunks and stay focused | Exact references and citation-heavy answers |
| `Balanced` | Mix precision and coverage | General default testing |
| `Broad` | Use more context | Questions needing nearby or related passages |
| `Fast` | Use fewer expensive steps | Quick checks and low-latency runs |

Open `Variants`, then:

1. Enter a `Name`.
2. Choose a `Preset`.
3. Edit `Parameters` as JSON.
4. Click `Create`.

Example precise variant:

```json
{
  "top_k": 3,
  "temperature": 0.0,
  "enable_rerank": true,
  "retrieval_mode": "metadata",
  "reference_query_mode": "exact",
  "answer_style": "cite-first"
}
```

What the main fields mean:

| Field | Simple meaning |
| --- | --- |
| `top_k` | How many chunks to retrieve before answering |
| `temperature` | Lower means more stable answers, higher means more varied answers |
| `enable_rerank` | Reorder retrieved chunks to put stronger evidence first |
| `retrieval_mode` | Which retrieval strategy the variant asks for |
| `reference_query_mode` | How strongly to favor exact references |
| `answer_style` | A hint about how the answer should be shaped |

Start with two or three variants. For example:

1. `Precise reference`: small `top_k`, low temperature.
2. `Balanced grounded`: medium `top_k`, reranking enabled.
3. `Broad context`: larger `top_k`, useful for adjacent passages.

## Step 2: Import an Evaluation Set

An evaluation set is a list of test questions.

Each case says:

1. Ask this question.
2. A good answer should include these words or phrases.
3. A bad answer should avoid these words or phrases.
4. Optional: the answer should come from these sources.

Open `Evaluation`, then:

1. Enter a `Set name`.
2. Choose a `.json`, `.jsonl`, `.csv`, `.yaml`, or `.yml` file.
3. Click `Import`.
4. Select the set to review its cases.

Simple JSON example:

```json
{
  "cases": [
    {
      "id": "quran-ref-2-255",
      "query": "What does Quran 2:255 say about Allah's life, sleep, knowledge, and Kursi?",
      "expected_answer": "Ever-Living Sustainer neither drowsiness nor sleep knowledge Kursi heavens earth",
      "expected_sources": ["2:255"],
      "must_include": ["Ever-Living", "Sustainer", "Kursi", "heavens", "earth"],
      "must_avoid": ["hadith", "Bible", "commentary without citation"]
    }
  ]
}
```

Important fields:

| Field | Simple meaning |
| --- | --- |
| `id` | A readable name for the test case |
| `query` | The question Ragstudio will ask |
| `expected_answer` | Important answer terms the scorer should look for |
| `must_include` | Phrases that should appear in the answer |
| `must_avoid` | Phrases that should not appear in the answer |
| `expected_sources` | Source hints for human review |
| `documents` | Optional document IDs for this case only |

Scoring currently focuses on `expected_answer`, `must_include`, and `must_avoid`. `expected_sources`, rubrics, objectives, and structure fields are still useful because they appear in case details and help you review runs manually.

## Step 3: Run an Experiment

An experiment runs an evaluation set across selected variants.

For example:

```text
8 evaluation questions x 4 variants = 32 recorded runs
```

Open `Experiments`, then:

1. Enter a `Name`.
2. Choose an `Evaluation set`.
3. Select the uploaded document or documents.
4. Select the variants you want to test.
5. Paste an `Objective JSON`.
6. Click `Run`.

Simple objective JSON:

```json
{
  "metric": "total",
  "primary_goal": "choose the most grounded answer variant",
  "tie_breakers": [
    "fewer failed runs",
    "better source coverage",
    "lower latency"
  ]
}
```

The objective JSON is saved with the experiment so you and other reviewers know what the test was trying to optimize. The current automatic score still comes from the evaluation case checks.

## How Scores Work

Scores are from `0` to `100`.

Ragstudio looks at the answer text and checks:

| Signal | What it checks |
| --- | --- |
| `expected_answer` | Did the answer contain expected important terms? |
| `must_include` | Did the answer include required phrases? |
| `must_avoid` | Did the answer avoid forbidden phrases? |

Simple interpretation:

| Score | Meaning |
| --- | --- |
| `90-100` | Strong candidate, still review sources |
| `75-89` | Usable, inspect misses and source quality |
| `50-74` | Needs tuning |
| `0-49` | Likely wrong, missing, or failed |

Score details show what was hit or missed. Use those details to decide what to change in the next variant.

## Step 4: Compare Runs

Comparison is where you inspect the real answers.

Open `Comparison`, then:

1. Select two or more runs in the `Runs` table.
2. Read each answer side by side.
3. Expand `Sources`.
4. Expand `Traces`.
5. Expand `Timings`.

Look for these things:

| Area | What to ask |
| --- | --- |
| `Answer` | Does it answer the question directly? |
| `Sources` | Did it use the expected source chunks? |
| `Traces` | Did the right chunks make it into the context? |
| `Timings` | Did a better answer cost much more time? |
| `Status` | Did any run fail? |

Example comparison:

| Variant | Expected result |
| --- | --- |
| `Quran precise reference` | Should put `2:255` at or near the top source |
| `Quran broad neighbor context` | May include nearby verses, but should not replace `2:255` |
| `Quran fast lexical` | Should be quick, but may miss harder semantic questions |

Do not rely only on the score. A high score can still have weak sources. A lower score can still reveal a useful retrieval setting.

## Step 5: Use the Optimizer

The optimizer reads experiment runs and recommends the strongest variant.

Open `Optimizer`, then:

1. Use the recent experiment ID shown by the page, or paste an `Experiment ID`.
2. Paste an `Objective JSON`.
3. Click `Recommend`.

Example optimizer objective:

```json
{
  "metric": "total",
  "selection_policy": "highest average score with fewer failed runs",
  "required_behavior": [
    "answers must be grounded in uploaded document chunks",
    "answers should cite or show the needed source",
    "answers should avoid unsupported external claims"
  ]
}
```

Read the optimizer output like this:

| Output | Meaning |
| --- | --- |
| `Selected variant` | The recommended variant for this experiment |
| `Explanation` | Why it was selected |
| `Average` | Average score across scoreable runs |
| `Best` | Best run score for that variant |
| `Status` | Whether runs were scoreable, partial, unscored, or failed |
| `Recommendation details` | Full JSON details for audit and debugging |

The optimizer prefers candidates with more scoreable runs, fewer failures, and stronger average scores. After it picks a variant, go back to `Comparison` and inspect the selected run before making it your default.

## Step 6: Inspect Graphs

The graph shows relationships as nodes and edges.

Simple terms:

| Graph item | Simple meaning |
| --- | --- |
| Node | A thing, such as a document, chunk, reference, topic, or entity |
| Edge | A relationship between two things |
| Node type | The kind of thing |
| Edge type | The kind of relationship |

Open `Graph` when you want to understand why retrieval worked or failed.

Useful checks:

1. Filter by `Document id` to focus on one upload.
2. Filter by `Node type` to inspect only references, chunks, or entities.
3. Filter by `Edge type` to inspect relationships like contains, references, next, or same-surah style links.
4. Search `Page or reference` for a reference such as `2:255`.
5. Compare the graph with the `Sources` and `Traces` from `Comparison`.

Example graph investigation:

```text
Question: What does Quran 2:255 say?
Expected graph clue: a reference or chunk related to 2:255 should exist.
If it is missing: check document metadata, reindex the document, then refresh Graph.
```

If the graph is empty:

1. Confirm the document finished indexing.
2. Check `Diagnostics` for graph capability warnings.
3. Check whether the document produced relationship metadata.
4. Reindex after fixing metadata or runtime graph settings.

## A Good Testing Loop

Use this loop when improving answer quality:

```mermaid
flowchart TD
  upload["Upload and index document"] --> variants["Create variants"]
  variants --> eval["Import evaluation set"]
  eval --> experiment["Run experiment"]
  experiment --> compare["Compare answers and sources"]
  experiment --> optimizer["Run optimizer"]
  compare --> improve["Adjust variant settings or evaluation cases"]
  optimizer --> improve
  improve --> experiment
  compare --> graph["Inspect graph when source coverage is unclear"]
  graph --> improve
```

## Practical Example Workflow

For the included Quran sample pack:

1. Start the app with `./scripts/dev.sh`.
2. Open `Documents` and upload your Quran PDF.
3. Use `samples/quran_experiment/quran-domain-metadata.json` as the domain metadata.
4. Open `Variants` and create the variants from `samples/quran_experiment/quran-variants.json`.
5. Open `Evaluation` and import `samples/quran_experiment/quran-evaluation-set.json`.
6. Open `Experiments`, select the Quran document, select all Quran variants, and paste `samples/quran_experiment/experiment-objective.json`.
7. Run the experiment.
8. Open `Comparison` and use `samples/quran_experiment/comparison-checklist.md`.
9. Open `Optimizer`, paste `samples/quran_experiment/optimizer-objective.json`, and click `Recommend`.
10. Open `Graph` and search for references from low-scoring cases, such as `2:255`, `24:35`, or `55:19`.

## Common Problems

| Problem | What to check |
| --- | --- |
| No evaluation sets appear | Import a supported file and click `Refresh` |
| Experiment cannot run | Select one evaluation set, at least one document, and at least one variant |
| Scores look too low | Check `must_include` spelling and whether expected phrases appear exactly in answers |
| Scores look too high | Add stronger `must_avoid` phrases or more specific expected terms |
| Optimizer says no runs are available | Run an experiment first |
| Optimizer result is unscored | Add `expected_answer`, `must_include`, or `must_avoid` to evaluation cases |
| Comparison has no runs | Run `Query` or `Experiments` first |
| Graph is empty | Confirm indexing finished, then check `Diagnostics` and document metadata |

## Recommended Starting Point

For a new document, start small:

1. Create three variants: `Precise`, `Balanced`, and `Broad`.
2. Write five evaluation cases.
3. Use short `must_include` phrases that should appear exactly.
4. Add one or two `must_avoid` phrases for common hallucinations.
5. Run one experiment.
6. Compare the best and worst runs.
7. Let the optimizer recommend a variant.
8. Add more evaluation cases only after the first loop makes sense.

Small evaluations are easier to debug than large ones. Once the first five cases behave well, expand to 20, 50, or more.
