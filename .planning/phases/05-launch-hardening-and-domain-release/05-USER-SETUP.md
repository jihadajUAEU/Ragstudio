# Phase 05: User Setup Required

**Generated:** 2026-05-14
**Phase:** 05-launch-hardening-and-domain-release
**Status:** Incomplete

Complete these items for the Cloudflare Pages public launch. The code, local
checks, launch docs, and release-proof checker are in place; these items require
Cloudflare dashboard access.

## Environment Variables

None. The static proof viewer must not require runtime environment variables.

## Dashboard Configuration

- [ ] **Connect the Pages project to Git**
  - Location: Cloudflare Dashboard -> Workers & Pages -> `ragstudio-site`
  - Set to: Git integration for the canonical `ragstudio-site` repository
  - Required branch: `main`

- [ ] **Set production build settings**
  - Location: Cloudflare Dashboard -> Workers & Pages -> `ragstudio-site` -> Settings
  - Build command: `npm run build`
  - Build output directory: `dist`
  - Runtime environment variables: none

- [ ] **Enable production deployments from `main`**
  - Location: Cloudflare Dashboard -> Workers & Pages -> `ragstudio-site` -> Builds & deployments
  - Set to: automatic production branch deployments enabled

- [ ] **Attach `ragstudio.dev` as the custom domain**
  - Location: Cloudflare Dashboard -> Workers & Pages -> `ragstudio-site` -> Custom domains
  - Domain: `ragstudio.dev`
  - Notes: Pages preview URLs remain prelaunch-only.

## Verification

After completing setup, verify with:

```bash
cd /Users/meet/Documents/ragstudio-site
npm run check:release-proof
curl -I https://ragstudio.dev
curl -L https://ragstudio.dev/ | rg "Inspect RAG evidence|Inspect the proof trail"
curl -L "https://ragstudio.dev/#claim-RAGSTUDIO-TRACE-VISIBILITY" | rg "Claim trail|RAGSTUDIO-TRACE-VISIBILITY"
```

Expected results:

- `npm run check:release-proof` passes after the proof file reflects the verified state.
- `https://ragstudio.dev` returns a successful HTML response.
- The homepage and deep-linked claim route render the proof viewer.

---

**Once all items complete:** Mark status as "Complete" at top of file.
