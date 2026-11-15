---
name: dev-pyside-ui
description: PySide6 and Qt Widgets desktop UI in Python. Use for QWidget apps, signals and slots, model/view, QThread workers, .ui files, and packaging. Not for QML/Qt Quick (use qt-qml) or C++ (use qt-cpp skills).
---

# PySide6 UI (Qt Widgets)

Use this skill when the stack is **PySide6 / Qt Widgets** in Python. For **Qt Quick / QML**, use `qt-qml` and related skills. For **UI design intake**, use `qt-ui-design` when available.

## First Check

1. Confirm **PySide6** is the target (not PyQt6 unless the project already standardizes on PyQt6).
2. Ask only missing constraints: **platform** (Windows, macOS, Linux), **packaging** (pip install, PyInstaller, Briefcase, system packages), **display** (headless CI vs local GUI), **offline** needs.
3. Read project dependency files (`pyproject.toml`, `requirements.txt`) before adding PySide6.

## Availability

```bash
python -c "from PySide6 import QtWidgets; print(QtWidgets.__version__)"
```

If import fails, add `PySide6` with the project package manager. On Linux CI without a display, prefer unit tests on non-GUI logic or use `QT_QPA_PLATFORM=offscreen` when the environment supports it.

## Architecture

- **Entry**: `QApplication` / `QGuiApplication` once per process; `app.exec()` at the end of `main`.
- **Structure**: thin `main.py`, windows/dialogs in dedicated modules, business logic **outside** widget classes when possible.
- **UI files**: prefer `QUiLoader` or `uic.loadUi` for `.ui` from Qt Designer; keep widget logic in Python subclasses.
- **Resources**: use `.qrc` / `:/` paths for icons; regenerate `*_rc.py` when assets change.
- **Settings**: `QSettings` for user prefs; do not scatter path literals.

## Signals, Slots, and State

- Connect signals to slots or small handlers; avoid heavy work in slots.
- Use **typed** signals where they improve clarity (`Signal(str)`).
- Block signals (`blockSignals(True)`) only for short, documented updates.

## Model / View

- For tables and lists with non-trivial data, prefer **`QAbstractTableModel` / `QAbstractListModel`** instead of filling widgets item-by-item in loops.
- Keep models free of GUI imports when you can test them standalone.

## Threading

- **Never** touch QWidget APIs from a background thread. Use **`QThread` + worker `QObject`** with signals back to the GUI thread, or `QThreadPool` + `QRunnable` with signal bridges.
- Long I/O, network, and CPU work stay off the main thread.
- Shut down threads before destroying related widgets (`wait()` on quit).

## Lifetime and Ownership

- Parent/child: child `QObject`s are destroyed with the parent unless you reparent.
- Avoid circular references between Python callables and Qt objects; prefer weakrefs or explicit `deleteLater()` when detaching.
- Do not keep dangling references to deleted C++ wrappers (`RuntimeError: wrapped C/C++ object ... has been deleted`).

## Testability

- Extract decisions, parsing, and state transitions into pure functions or small classes without Qt imports.
- GUI smoke: create the main window, show optionally, `QApplication.processEvents()` once, then close (skip on headless CI if needed).
- Use `pytest-qt` or project conventions when already present; do not add it only for trivial apps.

## Packaging Notes

- macOS: app bundle, icon, and code signing are project-specific; see `dev-macos-app-icon` when icons are needed.
- Windows: watch DLL deployment with PyInstaller/cx_Freeze.
- Pin **PySide6** version in lockfiles; Qt minor upgrades can change behavior.

## Verification

- Import check for PySide6 and main window module.
- Unit tests on logic without a display when possible.
- One local smoke run of the app entry point when a display is available.
- Report platform, packaging choice, and threading boundaries in the handoff.
