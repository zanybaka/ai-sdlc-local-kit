# ai-task review skill registry

Machine-readable source: `skills/ai-task-reviewer/registry.json`.

## Purpose

Map **stack ids** to Agent Skills the teamlead/reviewer loads after `ai-task review`. The CLI resolves stacks from:

- **Plan / DoR (predictive):** repo markers (`pyproject.toml`, `package.json`, …) plus Task Context keywords. A marker with a wildcard matches at any depth. ai-task walks the tree once per process and skips `node_modules`, `.git` and `.ai-task/worktrees`, so a marker inside those directories does not count.
- **Review (authoritative):** changed file paths under the run cwd or worktree.

## Base stacks (shipped)

| Stack id | Typical skills | Notes |
|----------|----------------|-------|
| `python` | `modern-python`, `py-security` | Optional security pass |
| `qt-cpp` | `qt-cpp-review` | From `third_party/qt-agent-skills` after sync |
| `qt-qml` | `qt-qml-review` | Same pack |
| `swift` | `engineering:code-review` | Plugin-provided; fallback built-in `/code-review`. Markers `Package.swift`, `*.xcodeproj`, `*.xcworkspace`; suffix `.swift`. No dedicated Swift review skill yet — security via the conditional `security-review` row |
| `dotnet` | `engineering:code-review` | Plugin-provided (engineering plugin); fallback built-in `/code-review` |
| `javascript` | `engineering:code-review` | Plugin-provided; fallback built-in `/code-review` |
| `typescript` | `engineering:code-review` | Often with `javascript` when `tsconfig` exists |
| `go` | `engineering:code-review` | Plugin-provided; fallback built-in `/code-review` |
| `docker` | `engineering:code-review`, `sdlc-contract-guard` | Suffixes `dockerfile`, `.dockerignore`, `docker-compose.yml`, `compose.yaml`; markers `Dockerfile`/compose at root. Pending a thin local container checklist |
| `terraform` | `engineering:code-review`, `sdlc-contract-guard` | `.tf`, `.tfvars`; marker `*.tf` (root or nested) |
| `helm` | `engineering:code-review`, `sdlc-contract-guard` | Suffixes `chart.yaml`, `values.yaml`; marker `Chart.yaml`. Suffix match is plain `endswith`, so any `values.yaml` (e.g. Ansible) also maps here — acceptable over-trigger |
| `sql` | `sdlc-contract-guard` | `.sql` files were keyword-only before; DDL/migrations are contract surface |

Conditional (not stack rows): **sdlc-contract-guard** when `review_gates` or contract keywords; **playwright-skill** when Task Context matches web/UI heuristics (verify path unchanged); **security-review** (built-in) when Task Context matches web/auth/infra security keywords (authentication/login, XSS/CSRF/user input, secrets, exposed ports/network exposure, container images/manifests) or changed paths touch Dockerfile/compose/`.tf` — the reviewer runs built-in `/security-review` in the fresh-context pass and folds findings into pass 2; py-security stays the Python remediation pass.

UI/UX design conditionals: **qt-ui-design** and **dev-web-ui-design**. This kit does not ship the second; without it the row reports `partial`, as for any skill that is not installed. Each fires on either of two independent triggers, so a UI-shaped diff gets design review instead of generic review:

| Row | Changed-path trigger | Own context keywords | Shared UI vocabulary |
|-----|----------------------|----------------------|----------------------|
| `qt-ui-design` | `.qml`, `.ui` | qml, qt quick, qtquick, qt widgets, qwidget, pyside, pyqt | fires only when a `qt-qml` or `qt-cpp` stack is detected |
| `dev-web-ui-design` | `.html`, `.htm`, `.css`, `.scss`, `.sass`, `.less`, `.jsx`, `.tsx`, `.vue`, `.svelte` | landing page, tailwind, css, html markup, вёрстк / верстк (stems, so case endings match) | fires only when a `javascript` or `typescript` stack is detected |

The shared vocabulary (`ui design`, `ux design`, `ui/ux`, `ui-фикс`, `design system`, `screen layout`, `ui layout`, `дизайн интерфейса`, `макет экрана`, `mockup`, `мокап`, `wireframe`, `responsive layout`, `accessibility`) never fires on its own — bare "design" and "layout" also describe schema and architecture work, so the generic words appear only in UI-bound forms AND require a matching UI stack. A plain backend task keeps generic review: "design system for the state schema" on a `python` stack pulls neither row.

Levers live next to the security ones in the CLI: `QT_UI_DESIGN_PATH_SUFFIXES`, `QT_UI_DESIGN_KEYWORDS`, `WEB_UI_DESIGN_PATH_SUFFIXES`, `WEB_UI_DESIGN_KEYWORDS`, `UI_DESIGN_REVIEW_KEYWORDS`, `QT_UI_DESIGN_STACKS`, `WEB_UI_DESIGN_STACKS`. `playwright-skill` is unchanged and orthogonal: it covers browser E2E checks, these two cover design review of the diff.

Evaluation note: trailofbits `differential-review` (https://github.com/trailofbits/skills) is a candidate diff-security skill for this conditional row; recorded here because `third-party-skills.json` is comment-free JSON — evaluate before syncing, not synced.

Infra rows never pick the verify `default_profile` and never count as "mixed stacks" at init (`INFRA_STACKS` in the CLI); the matching profiles (`docker-build`, `compose-config`, `terraform-validate`, `helm-lint`) are opt-in via `Verify:` or `--profile`.

## Add a new stack

1. Edit `registry.json`: add a `stacks.<id>` entry with `skills`, `path_suffixes`, `repo_markers`, `context_keywords`.
2. Document the row in this file.
3. Run `ai-task plan --json` or `dor --json` on a fixture task and confirm `review_skills_status: ok`.
4. If the skill lives in a new third_party pack, add to `third-party-skills.json` and `SETUP.md` (same as other skills).

## Status values (`review_skills_status`)

| Value | Meaning |
|-------|---------|
| `ok` | Every detected stack has a registry row and every resolved skill is installed |
| `partial` | Some stacks unknown, **or** a registry row points at a skill that exists nowhere (`missing_skills` names it) |
| `missing` | No overlap with registry (extend before relying on review) |
| `none-detected` | Changed paths present but no stack matched (assets, `.ini`, `.proto`, …; Dockerfile/`.tf`/`.sql` map to infra rows) — run built-in `/code-review` |

`review_skills_missing: true` blocks confident automation; product may add a DoR gap row «review registry».

Skill existence: a resolved skill counts as installed when its dir exists under `skills/` (target repo or ai-sdlc-local-kit profile), or it is plugin-provided — any plugin-namespaced id (contains `:`) or a name in `KNOWN_PLUGIN_SKILLS` (`engineering:code-review`, `security-review`).
