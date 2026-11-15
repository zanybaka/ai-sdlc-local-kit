---
name: dev-macos-app-icon
description: Generate macOS app icons from a PNG on macOS (Apple HIG safe zone, squircle, AppIcon.appiconset, .icns). Use when the user wants macOS icon assets for Xcode, PySide6, Qt, or a .app bundle, with or without an existing PNG. If no PNG exists, offer to generate a 1024×1024 source image first, then run macos-icon-gen, iconutil, and common PySide/py2app/Briefcase wiring.
---

# macOS app icon

Turn one source PNG into a full macOS icon set. The user may supply a PNG, or ask for an icon from scratch. When no PNG exists yet, offer to generate a 1024×1024 source image, save it in the project, then continue automatically. Do the rest without asking them to create folders in Xcode or run extra commands by hand.

## Requirements

- macOS only (uses `sips`, `swift`, and `iconutil`).
- Source PNG at 1024×1024 or larger is ideal; smaller PNGs may work but warn if quality looks low.

## Workflow

Run these steps in order. Do not stop after `macos-icon-gen` unless a step fails.

### 1. Inputs

- **Source PNG** — from the user's message, attachment path, or project `resources/` / `assets/`.
- **Project root** — current workspace root unless the user names another directory.

If no PNG is available yet, do not stop. Offer to generate a 1024×1024 source PNG and proceed once the user agrees or their request already implies generation (for example "make an app icon for this project").

**When generating the source PNG:**

1. Infer subject from the app or project name, README, UI domain, or ask one short question only if the theme is still unclear.
2. Generate a **1024×1024** square app-icon concept with:
   - one clear focal symbol, readable at small sizes
   - important content centered inside an **824×824 safe zone** (100 px inset on each side), because `macos-icon-gen` crops to Apple HIG
   - no tiny text, no busy borders, no fine detail near the edges
   - simple background or soft gradient; macOS will apply the squircle mask later
3. Save to a stable project path, prefer `resources/icon-source-1024.png` (create `resources/` if needed).
4. Use that saved PNG as the source for the rest of this workflow.

If the user declines image generation, ask them for a PNG path or attachment and stop until one is available.

### 2. Install CLI if needed

```bash
which macos-icon-gen
```

If missing:

```bash
uv tool install git+https://github.com/zanybaka/MacOS-icon-generator
```

Do not re-install when `which macos-icon-gen` succeeds.

### 3. Pick output location (do not ask the user)

Resolve `APPICONSET` automatically:

1. Existing `AppIcon.appiconset` anywhere under the project (prefer `Assets.xcassets/AppIcon.appiconset`).
2. Else if an `.xcodeproj` exists — `Assets.xcassets/AppIcon.appiconset` under project root.
3. Else if PySide6, PyQt6, PySide2, PyQt5, or Qt packaging is detected (`pyproject.toml`, `setup.py`, imports) — `resources/AppIcon.appiconset`.
4. Else — `resources/AppIcon.appiconset`.

Create the directory tree when missing:

```bash
mkdir -p "<APPICONSET>"
```

For a new Xcode-style layout, also ensure the parent exists:

```bash
mkdir -p "<project>/Assets.xcassets"
```

Do not ask the user to create `AppIcon.appiconset` in Xcode.

### 4. Generate PNG sizes

```bash
macos-icon-gen "<source.png>" -p "<project-root>" -o "<APPICONSET>"
```

Confirm files exist: `AppIcon-16.png` through `AppIcon-1024.png`, plus `Contents.json`.

### 5. Build `.icns` for Dock / `.app` bundle

Always run this on macOS after step 4 (needed for PySide6, py2app, Briefcase, and many Qt macOS bundles):

```bash
iconutil -c icns "<APPICONSET>" -o "<ICNS_PATH>"
```

Set `ICNS_PATH` to a stable project path:

- PySide / Qt / generic — `resources/AppIcon.icns` (same folder as the appiconset parent when possible).
- Xcode — `<APPICONSET>/../AppIcon.icns` or keep inside `Assets.xcassets` only if the project already references it there; prefer `resources/AppIcon.icns` when no Xcode asset wiring exists.

### 6. Wire the project (automatic, no prompts unless ambiguous)

Apply only what matches the repo:

**PySide6 / Qt window icon** — if the app creates `QApplication` in an obvious entry file (`main.py`, `app.py`, `__main__.py`), set the window icon when it is not already set:

```python
from PySide6.QtGui import QIcon  # or PyQt6 / PySide2 / PyQt5 matching the project

icon_path = "<path/to/AppIcon-512.png>"  # or AppIcon-1024.png
app.setWindowIcon(QIcon(icon_path))
```

Use a path relative to the project or `Path(__file__).resolve().parent` so packaged builds still find the file. Prefer reusing an existing `resources/` or `assets/` convention.

**py2app** — if `setup.py` uses py2app, set `iconfile` to the generated `.icns` when missing or still pointing at a placeholder.

**Briefcase** — if `pyproject.toml` has `[tool.briefcase.app.*]`, set `icon = "resources/AppIcon.icns"` (or the path you used) for the macOS app target.

**Xcode** — if `Assets.xcassets` is already in the project, the generated `AppIcon.appiconset` is enough; remind the user to select it in the target's App Icon slot only if the project file does not already reference that catalog.

Skip wiring steps that would duplicate an existing correct configuration.

### 7. Report back

Tell the user:

- Path to the source PNG (generated or supplied)
- Paths to `AppIcon.appiconset` and `AppIcon.icns`
- Which auto-wiring ran (QIcon, py2app, Briefcase)
- That SAP Icons is optional for higher quality (see below)

## Optional: SAP Icons

If [SAP Icons](https://github.com/SAP/macOS-icon-generator) (`Icons.app` in `/Applications` or `~/Applications`) is installed, `macos-icon-gen` uses it automatically. Never block the workflow when it is missing.

## Constraints

- macOS only — on Linux or Windows, explain that icon generation must run on macOS.
- Do not overwrite unrelated asset catalogs; write only to the resolved `APPICONSET` and chosen `.icns` path.
- Do not ask the user to run `iconutil`, create `appiconset` folders, or resize PNGs manually.
- If `macos-icon-gen` or `iconutil` fails, show the command output and fix paths or permissions before retrying once.
