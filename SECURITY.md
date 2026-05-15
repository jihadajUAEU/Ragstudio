# Security Policy

## Supported Versions

Ragstudio is pre-1.0. Security fixes target the current `main` branch unless a maintained release branch is announced.

## Reporting A Vulnerability

Please do not create a public issue for suspected vulnerabilities.

Report privately by opening a GitHub security advisory for the repository, or contact the maintainers through a private channel listed on the GitHub organization/profile.

Include:

- Affected component: frontend, backend, worker, Docker Compose, proof packet, docs site, or deployment.
- Reproduction steps.
- Expected impact.
- Whether private data, credentials, provider egress, upload handling, or public site behavior is involved.

## Public Site Boundary

The public v1 site must remain static:

- No public upload endpoint.
- No auth flow.
- No live Ragstudio backend calls.
- No provider calls.
- No private document content.
- No secrets, local database dumps, or environment files.

## Local Development Credentials

Docker Compose uses local development credentials for Postgres and Neo4j. They are for local use only and must not be reused in shared or public deployments.

## Disclosure

We aim to acknowledge reports promptly and coordinate fixes before public disclosure.
