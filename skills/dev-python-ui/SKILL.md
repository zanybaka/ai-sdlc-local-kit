---
name: dev-python-ui
description: Choose and implement Python UI approaches. Use when building Python user interfaces, choosing between Streamlit, Gradio, NiceGUI, Textual, PySide6, tkinter, Django, FastAPI, HTMX, or frontend-backed Python apps.
---

# Python UI

Use this skill when a task involves a Python user interface or when the UI stack is not yet chosen.

## First Check

1. Read project docs and `AGENTS.md` for an existing UI stack decision.
2. If the project already names a stack, follow it unless the user asks to revisit the choice.
3. If the user explicitly names a UI framework, use that framework and do not ask stack-selection questions unless requirements conflict.
4. If neither the project nor the user names a stack, do not choose one silently. Run a short clarification loop before selecting a UI stack: ask one focused question per turn, stop as soon as the stack choice is clear, and skip questions already answered by the request or project docs. Draw questions from the missing high-impact inputs:
   - Target platform: browser, terminal, desktop, or notebook-like app.
   - Distribution model: local script, internal service, packaged app, or public product.
   - Users: developer, analyst, operator, customer, or mixed.
   - State and persistence needs.
   - Offline requirements.
   - Packaging and deployment constraints.
   - Exploratory/demo UI or production-facing UI.

## Stack Selection

Prefer the smallest stack that fits the product shape:

- Use `Streamlit` for quick internal data tools, prototypes, dashboards, and analyst workflows where speed matters more than fine UI control.
- Use `Gradio` for ML demos, model playgrounds, simple input/output workflows, and shareable experiments.
- Use `NiceGUI` for Python-first web UIs that need more app structure and interactivity while avoiding a separate JavaScript frontend.
- Use `Textual` for terminal UIs, operator tools, rich CLI workflows, and keyboard-centric apps.
- Use `PySide6` or Qt Widgets when the requirement is a real desktop app with native windows, menus, files, or long-lived local UI (not QML-first apps).
- Use `tkinter` only for very small local windows where built-in availability matters more than UI polish.
- Use `Django` or `FastAPI` with HTMX or a frontend framework for production web apps, multi-user systems, auth-heavy apps, or anything with serious deployment and maintenance needs.

## Tkinter Availability Caveat

Do not assume `tkinter` is available just because it is part of the Python standard library.

On macOS and some package-manager Python builds, Python may be installed without the `_tkinter` extension. In that case, importing `tkinter` fails with:

```text
ModuleNotFoundError: No module named '_tkinter'
```

Before choosing `tkinter`, verify `python -c "import tkinter"` in the target environment or confirm that the project controls a Python distribution with Tk support.

## Framework Skills

After selecting or detecting a framework, load framework-specific skills when they are available:

- For Streamlit, use `developing-with-streamlit` before writing Streamlit-specific code.
- For Gradio, use `gradio` before writing Gradio-specific code.
- For **PySide6 Qt Widgets** in Python, use `dev-pyside-ui` when available before writing widget code.
- For **Qt Quick / QML** (not Widgets), use `qt-qml` for implementation, `qt-qml-review` for review, `qt-qml-profiler` for performance, and `qt-ui-design` for design intake.
- For **Qt C++** or mixed C++/Python boundaries, use `qt-cpp-review` or `qt-cpp-docs` when the task touches C++ sources.
- For Qt UI design intake on any Qt stack, use `qt-ui-design` when available.
- For browser E2E checks and Playwright automation, use `playwright-skill` when available (profile-level `ai-sdlc-local-kit` install; see `SETUP.md`).
- For a GitHub repository link or icon button in the app header, use `dev-ui-github-link` after the stack is chosen.
- If a framework-specific skill is not installed, continue with the guidance in this skill and note that the specialized skill was unavailable.

Do not install third-party skills into the active project during normal UI implementation. Skill installation belongs to the shared profile setup in `ai-sdlc-local-kit`.

## Implementation Guardrails

- Do not force a Python-only UI if the project is really a production web app with frontend requirements.
- Keep UI state explicit. Separate business logic from UI callbacks or event handlers.
- Prefer project-local conventions for dependency management, formatting, testing, and packaging.
- Add new dependencies only when they match the chosen stack and the project has no existing equivalent.
- For async or long-running work, avoid blocking the UI event loop; use the framework's background task pattern.
- For file uploads, secrets, credentials, or generated artifacts, validate paths and avoid logging sensitive content.
- Preserve already chosen project architecture. This skill helps choose when the choice is open; it does not override project policy.

## Verification

Choose checks that match the selected UI type:

- Streamlit, Gradio, and NiceGUI: run import or smoke checks, and test pure business logic separately from the UI layer.
- Textual: test app logic and widgets where practical; run the app smoke path if the environment supports it.
- PySide6 and tkinter: smoke test window creation when possible, and keep core logic unit-testable without a display.
- Django, FastAPI, and HTMX/frontend-backed apps: run route/view tests, template checks, API tests, and existing frontend checks when present.

Report the selected stack, the reason for choosing it, verification performed, and any assumptions or trade-offs.
