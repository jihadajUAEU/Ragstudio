---
quick_id: 260515-kc3
status: complete
completed_at: "2026-05-15T10:40:41Z"
task: "Align public-site changelog, roadmap, and GitHub links with Ragstudio"
---

# Summary

Updated the Ragstudio public site so `/changelog/`, `/roadmap/`, the header GitHub link, and feedback issue links point readers toward the Ragstudio product and main `jihadajUAEU/Ragstudio` repository instead of the website wrapper.

## Verification

- `npm test`
- `npm run lint`
- `npm run build:app`
- `npm run launch:check -- --allow-pending-manual`
- Playwright smoke check for `/changelog/` and `/roadmap/` confirmed the expected H1 text, main Ragstudio GitHub URL, and no page-level horizontal overflow.
