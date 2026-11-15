---
name: dev-security-audit
description: Deep security check of a repository by event - a new public host or service, or once a quarter. Runs gitleaks, Semgrep and OWASP ZAP baseline in Docker, writes SECURITY-REVIEW.md and files one backlog task per finding. Use when the owner says "security audit", "аудит безопасности", "проверь безопасность", "квартальная проверка". Not for a diff review (built-in /security-review) or Python-only remediation (py-security).
status: stable
---

# dev-security-audit

A deep, evidence-based check that goes beyond the routine scans. Those come from CI where a repository has them: a scheduled scan of main (Semgrep and gitleaks) and gitleaks on every PR of a public repository. This skill adds what they do not do: it reads the live surface, judges the findings, and leaves a report and tasks.

## When to run

- A new public host or a new service appears.
- Once a quarter, per repository that serves anything public.
- After a real secret was found in history (to see what else was exposed).

Not for reviewing a diff (the built-in `/security-review` does that), not for Python-only remediation (`py-security`), not for a company's inner-source requirements.

## Before you start

1. Read the repository's `AGENTS.md` and `AGENTS.override.md`. Boundaries there say what may be written into tracked files (host names, other repositories).
2. Decide the repository's visibility (`gh repo view --json visibility`). It decides where findings go, see "Where findings go".
3. Check that Docker works (`docker info`). Without it, say so at the top of the report and mark every result that depends on a scanner as "indirect".

## Scanners

Pin the images by digest and record the version in the report. Run them read-only against a checkout, never against a production host with load.

| Scanner | Command shape | What it answers |
|---|---|---|
| gitleaks | `docker run --rm -v "$PWD:/repo" -w /repo <image> git --redact --no-banner --verbose /repo` | secrets in the whole git history |
| Semgrep | `docker run --rm -v "$PWD:/src" -w /src <image> semgrep scan --config p/default --config p/javascript --config p/dockerfile --metrics=off .` | code and workflow weaknesses; adjust the rule sets to the stack |
| OWASP ZAP baseline | `docker run --rm -t <image> zap-baseline.py -t <url>` | passive findings of a running public site |

Rules for every run:

- `--redact` on gitleaks always. A found value does not go into the report, the chat or a task.
- Semgrep with `--metrics=off`, no login, no code upload.
- ZAP baseline is passive. Do not run an active scan, and run it only against hosts the owner named.
- Do not install anything on the host machine; Docker only.

## Judge the findings

A scanner output is a list of suspects. For each one decide:

- **Real**: reproduce it with a command and keep the command (the report lists reproduction, not the value).
- **False positive**: name why (a vendored file, a documentation example, a test fixture). A false positive that will return gets an entry in `.gitleaksignore`, `.semgrepignore` or a `nosemgrep` comment with the reason, so it does not surface every week.
- **Cannot tell**: say so and say what is missing.

A real secret is rotated first by a human. Only after that may its fingerprint go into `.gitleaksignore`, and only the fingerprint, never the value.

## The report

Write `SECURITY-REVIEW.md` with these sections in this order:

0. State: date, commit the measurements were taken on, what could not be run and why.
1. What is published: every route, file and endpoint a visitor can reach, and which of them the runtime needs.
2. Leaks: secrets, internal names, debug files, source maps, backups.
3. Headers and config: response headers, server config, path behaviour. Mark an answer derived from config rather than from a live server as "indirect".
4. Client code: DOM sinks, URL parameters, parsing of saved data, third-party domains.
5. Dependencies: audit output and what is actually reachable.
6. Verdict: a short findings table (finding, severity, evidence, task) and the task texts.

Writing rules: a person reads this, so follow the Writing style section of `AGENTS.md`. Name hosts and other repositories only where the repository's boundaries allow it; in a tracked file of a public repository, do not name private repositories, hosts or internal task numbers at all.

## Where findings go

- **Private repository**: the report may be committed. Each real finding becomes one backlog task (use `sdlc-backlog-add`), and the report links the task ids.
- **Public repository**: the report is NOT committed to it, and no finding becomes a public issue or a public task before the fix: an open description of a hole publishes it. Put the report and the findings in a private place you control (a private repository or tracker) and tell the owner. Only the fix, without the description of the finding, reaches the public repository.
- A real secret in history always goes to the owner at once in the chat, with the one line "rotate this key", and never with its value.

## Finish

End the report with who does what: what you filed, and what only the owner can do (rotate a key, set a header at the proxy, grant access). If nothing was found, say that in the first paragraph and list what you ran and on which commit, so the next quarter can compare.
