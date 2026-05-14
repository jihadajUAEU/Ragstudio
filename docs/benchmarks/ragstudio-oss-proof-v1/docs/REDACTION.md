# Redaction And Public Safety

## Policy

Public proof artifacts fail closed. If evidence is unsafe, private, local-only,
or unapproved, it must be excluded and any affected claim must not be marked
proven.

## Blocked Patterns

Artifacts and docs must not expose:

- API keys,
- access tokens,
- private hostnames,
- private endpoints,
- local absolute paths,
- LAN IPs,
- unpublished model endpoints,
- private content snippets,
- unapproved screenshots.

## Reserved Examples Only

When examples need a host or IP shape, use reserved documentation values only.

Allowed examples:

- `example.com`
- `example.net`
- `example.org`
- `192.0.2.10`
- `198.51.100.10`
- `203.0.113.10`

Do not use real LAN hosts, private service names, or machine-local paths.

## Screenshot Rule

Screenshots require a `screenshots/signoff.json` entry with reviewer, review
time, source path, safe-to-publish status, affected claim ids, and notes.

If a screenshot is not approved, it stays excluded and cannot support a proven
claim.
