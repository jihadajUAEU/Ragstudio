---
status: complete
quick_id: 260521-in9
slug: implement-option-c-evidence-table-redesi
---

# Summary

Implemented option C for the chunks page:
- Reworked the primary flow into a search-first evidence table.
- Moved parser/domain/index controls behind a collapsed Index settings disclosure.
- Added expandable row previews for chunk text, retrieval explain, source summary, and snapshot summary.
- Kept raw JSON hidden until a disclosure is opened.

Validation:
- `npx eslint src/features/chunks/chunk-inspector.tsx`
- `npx tsc --noEmit --jsx react-jsx --moduleResolution bundler --module esnext --target es2022 --lib es2022,dom --skipLibCheck --types vite/client src/features/chunks/chunk-inspector.tsx`
- Browser preview at `/chunks` with mocked API responses because Docker/backend were unavailable locally.
