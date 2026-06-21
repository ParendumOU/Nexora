# Security Policy

## Reporting a vulnerability

If you discover a security vulnerability in Nexora, **please do not open a public issue.**

Instead, email **info@parendum.com** with:

- A description of the vulnerability and its impact.
- Steps to reproduce (proof-of-concept if possible).
- The affected version / commit.

We aim to acknowledge reports within **72 hours** and to provide a remediation timeline after
triage. We will credit reporters who wish to be named once a fix is released.

## Supported versions

Security fixes target the latest tagged release on the default branch. Please upgrade to the
latest version before reporting.

## Scope

Nexora is **self-hosted** — you run it on your own infrastructure. Misconfiguration of your own
deployment (weak `SECRET_KEY`/`ENCRYPTION_KEY`, exposing the Docker socket, disabling the SSRF
allowlist, etc.) is your responsibility, but we're happy to advise on hardening. See
[`SETUP.md`](SETUP.md) for secure-deployment guidance.
