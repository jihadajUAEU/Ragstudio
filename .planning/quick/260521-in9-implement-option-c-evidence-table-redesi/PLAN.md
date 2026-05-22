---
status: in-progress
quick_id: 260521-in9
slug: implement-option-c-evidence-table-redesi
---

# Implement Option C Evidence Table Redesign

Task: implement the selected Option C design for the chunks page.

Plan:
- Refactor the chunks inspector into a search-first workbench.
- Hide parser/index/domain controls behind a collapsed disclosure.
- Render search results as a compact evidence table with expandable row previews.
- Keep raw JSON details collapsed and avoid stringifying large metadata until opened.
- Verify with frontend checks and the in-app browser.
