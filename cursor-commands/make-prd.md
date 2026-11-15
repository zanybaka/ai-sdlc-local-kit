# PRD Command Router

Use skill: "sdlc-prd-interview".

## Task
- Execute the skill end-to-end for the current idea.
- Keep interview-driven discovery strict (one question at a time) and make assumptions explicit.
- Follow agent policy in workspace-root **`AGENTS.md`**.

## Input
- User idea, context, and constraints.
- Workspace-root **`AGENTS.md`**.
- Optional **`PRD.md`** / **`TECHSPEC.md`** when present in the workspace or attached by the user.
- Any existing PRD notes in the workspace (`docs/prd.md`, `PRD.md`, etc.).

## Output
- Create or update "docs/prd.md" (or "PRD.md" if project uses that naming).
- Include explicit assumptions, risks, and ADR-candidate decisions required by "AGENTS.md" ADR policy.
