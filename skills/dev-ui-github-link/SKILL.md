---
name: dev-ui-github-link
description: Add a GitHub repository link control to app UI headers (round icon button, theme-aware GitHub mark, opens repo in browser). Use when the user wants a GitHub button, repo link, or source link in a desktop or web UI for PySide6/PyQt, Qt Quick/QML, SwiftUI, AppKit, or browser-based apps.
---

# UI GitHub link

Add a small GitHub repository control to the app header: title on the left, a round 30×30 icon button on the right, theme-aware GitHub mark, opens the repo in the default browser.

## Before coding

1. Detect the UI stack from imports, project docs, or the user's request. Do not switch stacks.
2. Resolve `REPOSITORY_URL`:
   - Prefer `git remote get-url origin` and normalize to `https://github.com/<owner>/<repo>` (strip `.git`, convert `git@github.com:` SSH URLs).
   - Else check `pyproject.toml` (`[project.urls]`), `package.json` (`repository`), README badge/link, or Xcode bundle metadata.
   - Ask one short question only if the URL is still unknown.
3. Place the control in the main window header row, aligned trailing/top-right. Do not bury it in settings or About unless the user asks.
4. Keep accessibility: tooltip/label like "Open GitHub repository", and a visible focus/hover state.

## Visual contract (all stacks)

- Button footprint about **30×30** logical pixels.
- **Circular or fully rounded** hit target with a 1 px outline and subtle surface fill.
- GitHub **mark** (not the word "GitHub") at roughly **55%** of the button size.
- Icon fill follows **primary text color** so light and dark themes stay readable.
- Hover/active uses a slightly darker or lighter surface, not a loud accent color.
- Click opens `REPOSITORY_URL` externally; do not embed a web view for this.

Use the official GitHub Invertocat mark. Download the SVG from [GitHub brand toolkit](https://brand.github.com/) when you need a checked-in asset; for runtime tinting, inline the path from [reference.md](reference.md#github-mark-svg).

## Stack routing

Read [reference.md](reference.md) and copy the section that matches the project stack.

| Stack | When | Section |
|-------|------|---------|
| PySide6 / PyQt6 / PySide2 / PyQt5 | Qt Widgets desktop app | [Qt Widgets](reference.md#qt-widgets-pyside6--pyqt) |
| Qt Quick / QML | `.qml` UI | [Qt Quick / QML](reference.md#qt-quick--qml) |
| SwiftUI | `.swift` SwiftUI app | [SwiftUI](reference.md#swiftui) |
| AppKit | macOS `NSViewController` / `NSWindow` | [AppKit](reference.md#appkit-macos) |
| Browser UI | React, Vue, HTML, HTMX | [Browser UI](reference.md#browser-ui) |
| Streamlit / Gradio / NiceGUI | Python web-style UI | [Streamlit, Gradio, NiceGUI](reference.md#streamlit-gradio-nicegui) |

For Qt Widgets work, prefer matching existing palette helpers (`_semantic_colors`, grouped surfaces) in the project before inventing hard-coded hex colors.

## External references (optional)

Use when you need authoritative details beyond the templates:

- [GitHub brand toolkit](https://brand.github.com/) — official mark, spacing, and usage rules.
- [Qt `QDesktopServices::openUrl`](https://doc.qt.io/qt-6/qdesktopservices.html#openUrl) — open repo URLs from Qt Widgets.
- [Qt `Qt.openUrlExternally`](https://doc.qt.io/qt-6/qml-qtquick-qdesktopservices.html) — open repo URLs from QML.
- [Apple Human Interface Guidelines: Buttons](https://developer.apple.com/design/human-interface-guidelines/buttons) — hit target and accessibility for SwiftUI/AppKit.

## Wiring checklist

- [ ] `REPOSITORY_URL` constant or config in one obvious place
- [ ] Header layout: title + stretch/spacer + GitHub control
- [ ] External open handler (browser), not in-app navigation
- [ ] Tooltip and accessible name set
- [ ] Icon tint follows theme text color
- [ ] Tab order includes the button when the window has keyboard focus
- [ ] No secrets or tokens in the URL

## Verification

- Smoke-run the UI when the environment allows it.
- Confirm the button opens the correct GitHub repo in the default browser.
- Check light and dark theme if the app supports both.
- For Qt: confirm SVG loads (`QIcon` not null) and the button stays circular at the target size.

## Report back

Tell the user:

- Resolved repository URL and how it was found
- Files changed and stack used
- Any stack limitation (for example Streamlit has no true window chrome, so placement is header/sidebar instead)
