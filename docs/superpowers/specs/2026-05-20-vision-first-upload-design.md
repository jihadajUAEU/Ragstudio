# Vision-First Upload Design

Date: 2026-05-20
Status: Approved for implementation planning

## Problem

The current document upload flow asks the user to choose a default profile, domain profile, domain, document type, language, collection, tags, custom JSON, and per-document MinerU options before indexing. For mixed layout/domain documents such as Quran Arabic-English, that manual/profile-first path can preserve the wrong baseline and hide what the vision model actually inferred from the sampled pages.

## Decision

Use a vision-first upload flow. The normal upload screen contains only a file chooser, a vision analysis action, a compact read-only generated metadata summary, and the upload/index action. No profile selector or manual metadata editor appears in this path.

The upload must not index a new file until vision metadata is generated successfully for that exact file. The frontend calls `/api/domain-profiles/suggest` without `profile_id`, stores the returned `domain_metadata`, and submits that metadata as the document's `IndexDocumentIn.domain_metadata`.

## User Flow

1. User chooses a file.
2. User clicks `Analyze with vision`.
3. The app requests AI metadata suggestion with no baseline profile.
4. If analysis succeeds, the app shows the generated domain, document type, confidence, evidence pages, and source marker.
5. User clicks `Upload and index`.
6. The app uploads the file with the generated metadata.
7. If the selected file changes, the generated metadata is cleared and upload is blocked until the new file is analyzed.

## Requirements

- Remove the normal upload controls for default profile, domain profile, domain, document type, language, collection, tags, custom JSON, and per-document MinerU options.
- Do not call `apiClient.domainProfiles()` from the upload path.
- Do not pass `profile_id` to `apiClient.suggestDomainMetadata()` from the upload path.
- Disable upload when no file is selected, vision analysis is pending, upload is pending, or generated metadata is missing.
- Show a clear blocking message when vision analysis fails.
- Preserve existing stored-option reindex behavior for previously indexed documents.
- Do not use the current upload form state as a fallback for reindexing.
- Keep `DomainMetadataPanel` available for other/advanced surfaces unless a separate cleanup proves it is unused.

## Non-Goals

- Do not redesign the backend metadata schema in this change.
- Do not remove saved domain profiles from the backend.
- Do not add raw vision response persistence in this UI simplification. That should be a follow-up auditability improvement.
- Do not change the worker, parser, canonical assembly, or chunk persistence pipeline in this change.

## Acceptance Criteria

- A user can upload only after successful vision analysis.
- The upload request includes the generated `domain_metadata`.
- The upload UI no longer exposes profile/manual metadata controls.
- Vision failure blocks upload and surfaces the failure.
- Reindexing an existing document uses `latest_index_options` and is independent of the upload file's vision state.
- Focused frontend tests pass for `frontend/tests/documents-page.test.tsx`.
