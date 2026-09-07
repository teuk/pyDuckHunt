# Security policy

## Supported versions

pyDuckHunt is beta software and has no published release yet. Only the latest
revision of `main` is supported during the public beta.

## Sensitive data

Never open an issue containing credentials, private IRC logs, hostmasks,
account identifiers or production configuration.

Report a suspected vulnerability through a private
[GitHub security advisory](https://github.com/teuk/pyDuckHunt/security/advisories/new).
Do not open a public issue for a suspected vulnerability. Rotate any credential
that may have been exposed before sharing diagnostic material.

The optional partyline is plain TCP. Keep its permanent listener on loopback or
a separately protected administrative network, use a narrow DCC range, and
never send its password through IRC. First-owner bootstrap must retain an exact
account or hostmask allowlist. See `docs/PARTYLINE.md`.
