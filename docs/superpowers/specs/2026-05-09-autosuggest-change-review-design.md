# Autosuggest Change Review Design

## Goal

Make the Documents page metadata autosuggest flow trustworthy by showing exactly which metadata fields changed after Auto-suggest runs.

## Context

`DomainMetadataPanel` already supports:

- Selecting a parser mode.
- Selecting a domain profile.
- Editing structured metadata fields.
- Editing `custom_json` directly in a textarea.
- Calling `apiClient.suggestDomainMetadata` when a file is selected.

Today, autosuggest updates the form values and replaces the Custom JSON textarea, but it does not summarize what changed. Users must inspect the whole form manually to understand what the suggestion did.

## Selected Approach

Use the hybrid UI approach:

- A compact autosuggest review panel appears above the metadata fields after a successful suggestion.
- Changed fields receive subtle visual highlighting in the form.
- The review panel lists all changed metadata fields, including Custom JSON changes.

This balances scanability and trust. The panel answers "what changed"; the field highlighting answers "where did it land?"

## Behavior

When the user clicks **Auto-suggest**:

1. Capture the current `domain_metadata` as the baseline.
2. Send the current filename, content type, selected profile id, and sample text to `apiClient.suggestDomainMetadata`.
3. Compare the returned metadata against the baseline.
4. Apply the returned metadata to the form.
5. Show a review panel if at least one field changed.
6. Highlight every changed field in the form.

If the suggestion fails:

- Keep existing metadata unchanged.
- Keep existing custom JSON draft unchanged.
- Show the existing error message.
- Do not replace the previous successful change summary.

If the user runs Auto-suggest again:

- Replace the previous baseline, summary, and highlights with the new comparison result.

If the user manually edits a highlighted field:

- Clear the highlight for that field.
- Remove that field from the review panel.
- Hide the review panel once no changed fields remain.

## Fields Compared

The diff includes these top-level `DomainMetadata` fields:

- `domain`
- `document_type`
- `language`
- `collection`
- `tags`
- `reference_pattern`
- `metadata_sources`
- `custom_json`

For scalar fields, show the old and new values.

For array fields, show added and removed values.

For `custom_json`, compare top-level keys:

- Added keys.
- Removed keys.
- Changed keys.

Nested custom JSON objects are treated as changed when their serialized values differ. The UI does not need a deep visual diff in this iteration.

## UI Details

The review panel appears below the Auto-suggest button and above the form grid.

Panel title:

`Auto-suggest updated metadata`

Panel content:

- A concise count, such as `5 fields changed`.
- One row per changed field.
- Rows use field labels users already see in the form.
- Each row shows a compact before/after summary.

Changed fields use a subtle accent border and light background. The visual treatment must not make the form look invalid or alarming.

Custom JSON remains editable in the textarea. Its summary row should list changed top-level keys, for example:

`Custom JSON: added citation_style, audience; changed review`

## Components and Data Flow

Keep the implementation inside `frontend/src/features/domain-metadata/domain-metadata-panel.tsx` unless the diff helpers become too large.

Recommended internal helpers:

- `buildMetadataChangeSet(before, after)` returns a list of changed fields.
- `formatMetadataValue(value)` returns display text for scalar and array values.
- `formatCustomJsonChange(before, after)` summarizes added, removed, and changed top-level keys.
- `clearChangedField(field)` removes a field from the current change set after manual edit.

The parent Documents page should not need to know about the review panel. It already passes `value`, `onChange`, and `suggestContext`; those are enough.

## Error Handling

Suggestion errors keep the current metadata and draft unchanged. The status text continues to show `Metadata suggestion failed.`

Invalid Custom JSON continues to disable upload through `onValidityChange(false)`.

Manual edits to Custom JSON clear the Custom JSON highlight only after the JSON parses as an object. Invalid JSON keeps the existing validation behavior.

## Testing

Update `frontend/tests/domain-metadata-panel.test.tsx`.

Required coverage:

- Auto-suggest displays a review panel with all changed scalar fields.
- Auto-suggest displays added and removed tag changes.
- Auto-suggest displays Custom JSON key changes.
- Changed fields are visibly marked in the DOM in a testable way, such as `data-autosuggest-changed="true"`.
- Manually editing a changed scalar field removes that field from the review panel.
- Failed autosuggest does not overwrite the previous metadata or custom JSON draft.

Targeted test command:

```bash
docker compose run --rm --no-deps -v "$PWD/frontend/src:/app/frontend/src" -v "$PWD/frontend/tests:/app/frontend/tests:ro" frontend npm run test -- --run frontend/tests/domain-metadata-panel.test.tsx
```

## Out of Scope

- Backend suggestion heuristic changes.
- Deep visual diffs for nested Custom JSON.
- Accept/reject individual autosuggest changes.
- Persisting autosuggest review state after leaving the page.

