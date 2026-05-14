# Design System - Ragstudio

## Product Context

- **What this is:** Ragstudio is an open-source RAG data-quality workbench that makes document quality inspectable before bad chunks become bad answers.
- **Who it's for:** RAG engineers, AI application teams, and technical founders who need to inspect parser warnings, references, chunks, retrieval traces, reranker behavior, and proof artifacts.
- **Space/industry:** AI developer tools, RAG observability, document parsing quality, benchmark-backed open-source infrastructure.
- **Project type:** Hybrid public launch site, static proof viewer, benchmark/docs site, and app-like evidence workbench.
- **Memorable thing:** Ragstudio makes RAG quality inspectable before bad answers happen.

## Aesthetic Direction

- **Direction:** Technical Field Guide with an embedded proof instrument.
- **Decoration level:** Intentional and sparse.
- **Mood:** Serious, readable, public, and evidence-first. The public site should feel like a technical publication that contains a working proof viewer, not like a generic SaaS landing page or terminal-themed demo.
- **Reference sites:** Research considered current AI observability and eval tools such as Langfuse, W&B Weave, Braintrust, Arize/Phoenix, Evidently AI, LlamaIndex, and document-processing products. Ragstudio should borrow their clarity around traces/docs/source links, but avoid converging on their generic observability-platform posture.

## Design Thesis

Ragstudio's public surface should lead with a written benchmark story and then let reviewers inspect the evidence. The strongest visual object is the proof packet: claims, warnings, chunks, traces, source commits, schemas, hashes, and raw artifacts.

Design the site as a field guide:

- Start with a readable product thesis.
- Show the proof packet as a field note, not a decorative dashboard screenshot.
- Make every claim traceable to an artifact, source path, commit, or roadmap entry.
- Treat disabled and roadmap claims as trust-building objects, not as footnotes.
- Keep the proof viewer compact, stable, and work-focused.

## Typography

- **Display/Hero:** Literata, 650-700 weight. Use for the launch H1 and major editorial headings. It gives the site a technical-publication character without making the proof viewer feel ornamental.
- **Body:** Source Sans 3, 400-600 weight. Use for public pages, docs, explanations, navigation, and UI labels.
- **UI/Labels:** Source Sans 3, 600-700 weight. Labels should be short and scannable.
- **Data/Tables:** IBM Plex Mono, 400-600 weight. Use for hashes, commit IDs, artifact paths, schema names, commands, JSON previews, and compact metadata.
- **Code:** IBM Plex Mono.
- **Loading:** Prefer Google Fonts for V1 preview and implementation speed. If the public site later self-hosts fonts, keep the same families and weights.

### Type Scale

| Token | Size | Use |
| --- | ---: | --- |
| `display-xl` | 88-96px desktop, 48px mobile | Homepage H1 only |
| `display-lg` | 56-60px desktop, 34px mobile | Major page headers |
| `title-lg` | 28-32px | Section headers |
| `title-md` | 20-22px | Panel groups |
| `body-lg` | 18-20px | Lead paragraphs |
| `body-md` | 16px | Public body text |
| `body-sm` | 14px | Dense UI and table cells |
| `caption` | 12px | Metadata, badges, table labels |

Rules:

- Body text on public pages must be at least 16px.
- Dense proof panels may use 14px body text and 12px captions.
- No negative letter spacing.
- Do not scale font size directly with viewport width outside responsive clamp ranges.

## Color

- **Approach:** Restrained field-guide palette with status color reserved for evidence state.
- **Primary:** `#0f766e` field-guide teal. Use for primary actions, current navigation, selected claim rail, links, and verified proof emphasis.
- **Secondary:** `#7b5f28` earth. Use sparingly for benchmark notes, corpus notes, or release-evidence markers. Do not use it as a broad theme.
- **Neutrals:** Warm paper and cool-green gray surfaces.
- **Semantic:** Use semantic colors only for status: proven, warning, error, disabled, roadmap.
- **Dark mode:** Not required for V1. If added later, redesign surfaces instead of inverting colors directly.

### Tokens

```css
:root {
  --rs-page: #fbfaf4;
  --rs-paper: #ffffff;
  --rs-field: #f0f4ef;
  --rs-ink: #18211f;
  --rs-text: #33413e;
  --rs-muted: #6c7975;
  --rs-line: #d9ded7;
  --rs-line-strong: #b8c1ba;
  --rs-accent: #0f766e;
  --rs-accent-deep: #0c524d;
  --rs-accent-soft: #e3f3f1;
  --rs-earth: #7b5f28;
  --rs-earth-soft: #f3ecd9;
  --rs-success: #256a3b;
  --rs-success-soft: #e9f6eb;
  --rs-warning: #8a5a00;
  --rs-warning-soft: #fff4d7;
  --rs-danger: #8c2525;
  --rs-danger-soft: #fff0f0;
  --rs-visited: #5e4b8b;
}
```

Rules:

- Links must have a visited state using `--rs-visited`.
- Teal marks action, selection, and proof navigation.
- Status colors must not be used as decoration.
- Avoid purple/indigo gradients, neon terminal themes, beige-only pages, and one-note teal pages.

## Spacing

- **Base unit:** 4px.
- **Density:** Public reading surfaces are comfortable; proof viewer surfaces are compact.
- **Scale:** `2xs=2px`, `xs=4px`, `sm=8px`, `md=16px`, `lg=24px`, `xl=32px`, `2xl=48px`, `3xl=64px`, `4xl=80px`.

Rules:

- Public page sections use 56-72px vertical spacing on desktop, 40-48px on mobile.
- Proof panels use 12-18px internal padding.
- Table cells use 10-12px vertical padding.
- Keep related metadata tight enough for scanning, but never rely on tiny text to fit more data.

## Layout

- **Approach:** Editorial public shell plus app-like proof workbench.
- **Grid:** Public pages use a max width of 1160px and a two-column hero when space allows.
- **Max content width:** 1160px for site content; 760px for long-form prose; full width only for proof/workbench layouts inside the content max.
- **Border radius:** `sm=4px`, `md=8px`, `lg=10px`, `full=9999px`. Most UI should use 8px or less.

### Site Structure

Primary navigation order:

1. Proof
2. Benchmark
3. Docs
4. Roadmap
5. GitHub

The homepage first viewport has three jobs:

1. Name Ragstudio as a RAG quality workbench.
2. State the proof-backed launch claim.
3. Send the visitor to inspect the proof.

### Proof Viewer Layout

Desktop and wide tablet:

- Persistent claim rail on the left.
- Evidence detail on the right.
- Selected claim remains visible while panels change.
- Raw artifact links are always available from capped or failed panels.

Mobile:

- Claim rail becomes a top claim list or segmented selector.
- Evidence detail follows selection.
- Touch targets must be at least 44px high.
- Horizontal overflow is allowed only inside bounded code/table scrollers.

## Components

### Buttons

- Primary: teal background, white text, 8px radius.
- Secondary: paper background, strong border, ink text.
- Ghost: use sparingly for low-priority links.
- Buttons use direct action copy: `Inspect proof`, `Replay benchmark`, `Open raw artifact`, `View source commit`, `File feedback`.

### Badges

- Proven: green.
- Warning/partial: amber.
- Error: red.
- Disabled/roadmap: neutral or amber, depending on whether action is needed.
- Badges describe evidence state, not marketing emphasis.

### Field Notes

Use field-note panels for benchmark or launch narrative objects:

- Claim summary.
- Source commit.
- Proof packet ID.
- Corpus note.
- Replay command.

These panels should read like evidence annotations, not marketing cards.

### Proof Cards

Use cards only when the card is the interactive or repeated evidence unit:

- Claim row.
- Artifact row.
- Warning unit.
- Retrieval trace preview.
- Chunk comparison.

Do not create decorative feature-card grids.

### Tables And Code

- Tables must be horizontally scrollable inside bounded containers.
- Code and JSON previews use IBM Plex Mono.
- Long paths and hashes must wrap or scroll without widening the page.
- Capped previews must show hidden counts and raw links.

## Motion

- **Approach:** Minimal-functional.
- **Easing:** `ease-out` for entrance, `ease-in` for exits, `ease-in-out` for movement.
- **Duration:** micro 50-100ms, short 150-250ms, medium 250-400ms.

Allowed motion:

- Claim selection transition.
- Panel expand/collapse.
- Loading skeleton fade.
- Copy-link confirmation.
- Anchor-scroll offset behavior.

Avoid:

- Decorative parallax.
- Scroll choreography.
- Animated gradients.
- Motion that competes with reading evidence.

## Accessibility

- Body text contrast must be at least 4.5:1.
- Focus states must be visible on links, buttons, tabs, and collapsible panels.
- Every form control needs a visible label. Do not use placeholder-only labels.
- Proof viewer landmarks: header, nav, main, complementary claim rail, region-labeled evidence panels, footer.
- Keyboard users must be able to move through claim list, evidence panels, raw artifact links, and feedback links.
- Use `aria-current` for active navigation and selected claim.
- Preserve visited vs unvisited link distinction.

## Copy

Use direct product language:

- `Inspect proof`
- `Replay benchmark`
- `Open raw artifact`
- `View source commit`
- `File feedback`
- `No proof packet imported yet`
- `This claim has no evidence attached`
- `Reranker not configured`

Avoid:

- `unlock`
- `all-in-one`
- `powerful`
- `seamless`
- `next-generation`
- `modern AI`
- `transform your workflow`
- `built for the future`

Every section has one job and one headline. Delete copy that does not help a reviewer verify, replay, or contribute.

## Anti-Slop Rules

- No 3-column feature grid with circular icons.
- No centered-everything page rhythm.
- No decorative blobs, orbital gradients, wavy dividers, or emoji decoration.
- No generic hero copy that could fit any other RAG tool.
- No dashboard-card mosaic as the first impression.
- No dark neon terminal direction for the main public site.
- No low-contrast body text or body text below 16px on public pages.
- No cards inside cards.

## Implementation Notes

- The chosen preview direction was `Option 3 - Technical Field Guide`.
- Preview file used during consultation: `/tmp/design-consultation-preview-1778694347-option3.html`.
- The rejected direction was the dark verification console. Do not revive dark/neon/terminal styling unless explicitly requested.
- Refined Option 1 was stronger as a product launch, but Option 3 was selected for a more technical-publication feel.

## Decisions Log

| Date | Decision | Rationale |
| --- | --- | --- |
| 2026-05-13 | Initial design system created | Created by `/design-consultation` for the Ragstudio open-source proof launch. |
| 2026-05-13 | Selected Technical Field Guide direction | User chose Option 3 after rejecting the dark verification-console direction and reviewing the refined evidence-workbench option. |
| 2026-05-13 | Use Literata, Source Sans 3, and IBM Plex Mono | This supports public benchmark reading, practical UI, and artifact inspection. |
| 2026-05-13 | Keep proof viewer compact and workbench-like | The site can read editorially while the proof surface remains task-focused. |
