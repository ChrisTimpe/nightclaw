# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in NightClaw, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, use GitHub's private vulnerability reporting feature
(Security tab → Report a vulnerability) or contact the maintainer directly at
https://github.com/ChrisTimpe.

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

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.0   | Yes       |
