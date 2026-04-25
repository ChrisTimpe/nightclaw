# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in NightClaw, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, use GitHub's private vulnerability reporting feature
(Security tab → Report a vulnerability) when available, or contact the
maintainer directly by emailing Chris Timpe at [human@tokenarch.com](mailto:human@tokenarch.com).

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We will acknowledge receipt within 48 hours and aim to provide a fix or mitigation within 7 days
for critical issues.

## Scope

NightClaw is a set of markdown documents that guide AI agent behavior. It does not include
executable code beyond optional shell scripts (scripts/). Security concerns typically involve:

- **Prompt injection vectors** — instructions embedded in content that could bypass Hard Lines
- **Integrity verification bypasses** — ways to modify protected files without detection
- **Information disclosure** — patterns that could leak credentials or private data
- **Placeholder injection** — malicious values in placeholder substitution

## Known Limitations

- SHA-256 integrity checks detect accidental drift, not adversarial tampering.
  For tamper-proof integrity, use signed git commits.
- Safety constraints are natural language instructions to LLM agents. They are
  defense-in-depth, not cryptographic guarantees.
- The append-only audit trail can be circumvented by direct file editing outside
  the agent framework. It is designed to govern agent behavior, not human behavior.

## Guest Deployment Threat Model

The supported production topology is Windows host → VirtualBox →
Ubuntu guest, with OpenClaw + NightClaw running entirely inside the
guest (see [README.md § Platform setup](README.md#platform-setup-windows--virtualbox--ubuntu)). Treat the guest as the
security boundary. The following guest-specific risks do not apply on
a bare-metal install but matter once a VirtualBox host is in the loop.

**G1. Shared folders widen the trust boundary.** If you enable a
VirtualBox Shared Folder from the host into the guest, the host can
read and write every file the guest user can — including
`$HOME/.openclaw/workspace`, `audit/AUDIT-LOG.md`,
`audit/INTEGRITY-MANIFEST.md`, and any OpenClaw credentials under
`$HOME/.openclaw/`. Integrity hashes catch accidental drift but not a
host process that recomputes and rewrites the manifest after tampering.
*Mitigation:* do not shared-folder the workspace or the OpenClaw config
directory. If a shared folder is required for file handoff, mount it
read-only and outside `$HOME/.openclaw/`.

**G2. OpenClaw credentials are guest-local.** Provider tokens (LLM
OAuth tokens and API keys) live under
`$HOME/.openclaw/` on the guest. A guest-image backup that is copied
to the host (or to cloud storage) carries those credentials with it.
*Mitigation:* use VirtualBox's built-in disk encryption for the guest
VDI, rotate provider keys if the guest image leaves the host, and
never copy `$HOME/.openclaw/` into a shared folder.

**G3. Snapshots capture live credentials.** A VirtualBox snapshot
taken after the NightClaw install step in README.md includes the authenticated
OpenClaw state. Restoring a snapshot on a different host reactivates
those credentials. *Mitigation:* treat snapshot files as credential
material; don't share them out of band.

**G4. Cron fires even with the VM window minimized.** Once the guest
is running, OpenClaw's cron fires regardless of whether you are
looking at the VM window. Hard-line violations and emergency-stop
procedures in [`DEPLOY.md § Uninstall & Emergency Stop`](DEPLOY.md#uninstall--emergency-stop)
are the correct stop surface; shutting the VM window down is not.

**G5. Host-side kernel compromise trumps guest defences.** VirtualBox
guest isolation depends on an uncompromised host hypervisor. NightClaw's
integrity hashing, append-only audit log, and hard-line guardrails all
live inside the guest — a host with kernel-level malware can bypass
every one of them. *Mitigation:* keep the Windows host patched, run
reputable endpoint protection on it, and do not install NightClaw on a
host you do not own.

**Out of scope for NightClaw:** VirtualBox CVEs, Windows hypervisor
integrity, Ubuntu kernel hardening, physical host access. Those belong
to the host operator, not this workspace.

## Supported Versions

NightClaw uses `YYYY.M.D` calendar versioning as of 2026.4.16. Security fixes ship against the latest CalVer release only — reinstall from the latest release zip using `INSTALL.md` to stay supported.

| Version                    | Supported                                                  |
|----------------------------|------------------------------------------------------------|
| Latest CalVer release      | Yes                                                        |
| Prior CalVer releases      | No — upgrade to latest                                     |
| Pre-CalVer (`v0.1.0`–`v0.3.0`) | No — superseded by CalVer scheme as of 2026.4.16       |
