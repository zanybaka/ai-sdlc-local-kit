# UI GitHub link — platform templates

Copy the section that matches the project stack. Adapt names and layout hooks to existing code style.

## GitHub mark SVG

Official Invertocat path (viewBox `0 0 98 96`). Set `fill` to the theme text color or `currentColor` in CSS.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 98 96">
  <path fill="currentColor" d="M49 0C21.9 0 0 22 0 49.1c0 21.7 14 40.1 33.5 46.6 2.4.4 3.3-1.1 3.3-2.4 0-1.2 0-5.2-.1-9.4-13.6 3-16.5-5.8-16.5-5.8-2.2-5.7-5.4-7.2-5.4-7.2-4.4-3 .3-3 .3-3 4.9.3 7.5 5 7.5 5 4.4 7.5 11.5 5.3 14.3 4.1.4-3.2 1.7-5.3 3.1-6.6-10.9-1.2-22.3-5.4-22.3-24.2 0-5.4 1.9-9.7 5-13.2-.5-1.2-2.2-6.2.5-13 0 0 4.1-1.3 13.5 5 3.9-1.1 8.1-1.6 12.3-1.6 4.2 0 8.4.6 12.3 1.6 9.4-6.4 13.5-5 13.5-5 2.7 6.8 1 11.8.5 13 3.1 3.4 5 7.8 5 13.2 0 18.8-11.5 23-22.4 24.2 1.8 1.5 3.3 4.5 3.3 9.1 0 6.6-.1 11.9-.1 13.5 0 1.3.9 2.8 3.4 2.4C84 89.1 98 70.7 98 49.1 98 22 76.1 0 49 0Z"/>
</svg>
```

## Qt Widgets (PySide6 / PyQt)

Header row with a round `QToolButton`, palette-tinted SVG icon, and external open:

```python
REPOSITORY_URL = "https://github.com/owner/repo"

# In window __init__ / _build:
self.github_button = QToolButton()
self.github_button.setToolTip("Open GitHub repository")
self.github_button.setAccessibleName("Open GitHub repository")
self.github_button.setFixedSize(30, 30)
self.github_button.setIcon(self._github_icon())
self.github_button.setIconSize(self.github_button.size() * 0.55)
self.github_button.clicked.connect(self._open_repository)
self.github_button.setStyleSheet(self._round_tool_button_style())

header_row = QHBoxLayout()
header_row.setContentsMargins(0, 0, 0, 0)
header_row.addWidget(title_label)
header_row.addStretch()
header_row.addWidget(self.github_button)

def _open_repository(self) -> None:
    QDesktopServices.openUrl(QUrl(REPOSITORY_URL))

def _github_icon(self) -> QIcon:
    text_color = self.palette().color(QPalette.ColorRole.WindowText).name()
    svg = """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 98 96">
      <path fill="{text_color}" d="M49 0C21.9 0 0 22 0 49.1c0 21.7 14 40.1 33.5 46.6 2.4.4 3.3-1.1 3.3-2.4 0-1.2 0-5.2-.1-9.4-13.6 3-16.5-5.8-16.5-5.8-2.2-5.7-5.4-7.2-5.4-7.2-4.4-3 .3-3 .3-3 4.9.3 7.5 5 7.5 5 4.4 7.5 11.5 5.3 14.3 4.1.4-3.2 1.7-5.3 3.1-6.6-10.9-1.2-22.3-5.4-22.3-24.2 0-5.4 1.9-9.7 5-13.2-.5-1.2-2.2-6.2.5-13 0 0 4.1-1.3 13.5 5 3.9-1.1 8.1-1.6 12.3-1.6 4.2 0 8.4.6 12.3 1.6 9.4-6.4 13.5-5 13.5-5 2.7 6.8 1 11.8.5 13 3.1 3.4 5 7.8 5 13.2 0 18.8-11.5 23-22.4 24.2 1.8 1.5 3.3 4.5 3.3 9.1 0 6.6-.1 11.9-.1 13.5 0 1.3.9 2.8 3.4 2.4C84 89.1 98 70.7 98 49.1 98 22 76.1 0 49 0Z"/>
    </svg>
    """.format(text_color=text_color)
    pixmap = QPixmap()
    pixmap.loadFromData(QByteArray(svg.encode("utf-8")), "SVG")
    return QIcon(pixmap)

def _round_tool_button_style(self) -> str:
    colors = self._semantic_colors()
    return f"""
        QToolButton {{
            background: {colors["group_surface"]};
            border: 1px solid {colors["outline"]};
            border-radius: 15px;
        }}
        QToolButton:hover {{
            background: {colors["hover_surface"]};
        }}
        """

def _semantic_colors(self) -> dict[str, str]:
    palette = self.palette()
    window = palette.color(QPalette.ColorRole.Window)
    return {
        "group_surface": window.lighter(106).name(),
        "hover_surface": window.darker(104).name(),
        "outline": palette.color(QPalette.ColorRole.Mid).name(),
    }
```

Imports: `QToolButton`, `QHBoxLayout`, `QIcon`, `QPixmap`, `QByteArray`, `QPalette`, `QDesktopServices`, `QUrl`. PyQt6 uses the same API.

## Qt Quick / QML

Place a `ToolButton` in the header `RowLayout`:

```qml
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

RowLayout {
    width: parent.width
    spacing: 0

    Label {
        text: qsTr("App title")
        font.pixelSize: 18
        font.bold: true
        Layout.fillWidth: true
    }

    ToolButton {
        id: githubButton
        implicitWidth: 30
        implicitHeight: 30
        display: AbstractButton.IconOnly
        icon.width: 16
        icon.height: 16
        icon.color: palette.windowText
        icon.source: "qrc:/icons/github-mark.svg"
        ToolTip.visible: hovered
        ToolTip.text: qsTr("Open GitHub repository")
        Accessible.name: qsTr("Open GitHub repository")
        background: Rectangle {
            radius: width / 2
            color: githubButton.down || githubButton.hovered ? palette.mid : palette.button
            border.color: palette.mid
            border.width: 1
        }
        onClicked: Qt.openUrlExternally("https://github.com/owner/repo")
    }
}
```

Ship `github-mark.svg` in Qt resources. Set `icon.color` to `palette.windowText` for theme-aware tinting.

## SwiftUI

```swift
import SwiftUI

private enum AppLinks {
    static let repository = URL(string: "https://github.com/owner/repo")!
}

struct ContentView: View {
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.openURL) private var openURL

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("App title")
                    .font(.title2.bold())
                Spacer()
                Button {
                    openURL(AppLinks.repository)
                } label: {
                    GitHubMarkView()
                        .frame(width: 16, height: 16)
                        .padding(7)
                        .background(.quaternary.opacity(colorScheme == .dark ? 0.35 : 0.6))
                        .clipShape(Circle())
                        .overlay(Circle().stroke(.separator, lineWidth: 1))
                }
                .buttonStyle(.plain)
                .help("Open GitHub repository")
                .accessibilityLabel("Open GitHub repository")
            }
            // ...
        }
    }
}

private struct GitHubMarkView: View {
    var body: some View {
        Image("GitHubMark")
            .renderingMode(.template)
            .resizable()
            .scaledToFit()
            .foregroundStyle(.primary)
    }
}
```

Add a vector GitHub mark asset to the asset catalog with template rendering so light and dark modes inherit `.primary`.

## AppKit (macOS)

```swift
final class GitHubLinkButton: NSButton {
    var repositoryURL = URL(string: "https://github.com/owner/repo")!

    override func awakeFromNib() {
        super.awakeFromNib()
        configure()
    }

    convenience init() {
        self.init(frame: NSRect(x: 0, y: 0, width: 30, height: 30))
        configure()
    }

    private func configure() {
        bezelStyle = .regularSquare
        isBordered = false
        image = NSImage(named: "GitHubMark")
        contentTintColor = .labelColor
        toolTip = "Open GitHub repository"
        setAccessibilityLabel("Open GitHub repository")
        target = self
        action = #selector(openRepository)
        wantsLayer = true
        layer?.cornerRadius = 15
        layer?.borderWidth = 1
        layer?.borderColor = NSColor.separatorColor.cgColor
    }

    @objc private func openRepository() {
        NSWorkspace.shared.open(repositoryURL)
    }
}
```

Pin the button in the title bar area or top-trailing corner of the content view.

## Browser UI

```html
<header class="app-header">
  <h1>App title</h1>
  <a
    class="github-link"
    href="https://github.com/owner/repo"
    target="_blank"
    rel="noopener noreferrer"
    aria-label="Open GitHub repository"
    title="Open GitHub repository"
  >
    <svg viewBox="0 0 98 96" aria-hidden="true">
      <path fill="currentColor" d="M49 0C21.9 0 0 22 0 49.1c0 21.7 14 40.1 33.5 46.6 2.4.4 3.3-1.1 3.3-2.4 0-1.2 0-5.2-.1-9.4-13.6 3-16.5-5.8-16.5-5.8-2.2-5.7-5.4-7.2-5.4-7.2-4.4-3 .3-3 .3-3 4.9.3 7.5 5 7.5 5 4.4 7.5 11.5 5.3 14.3 4.1.4-3.2 1.7-5.3 3.1-6.6-10.9-1.2-22.3-5.4-22.3-24.2 0-5.4 1.9-9.7 5-13.2-.5-1.2-2.2-6.2.5-13 0 0 4.1-1.3 13.5 5 3.9-1.1 8.1-1.6 12.3-1.6 4.2 0 8.4.6 12.3 1.6 9.4-6.4 13.5-5 13.5-5 2.7 6.8 1 11.8.5 13 3.1 3.4 5 7.8 5 13.2 0 18.8-11.5 23-22.4 24.2 1.8 1.5 3.3 4.5 3.3 9.1 0 6.6-.1 11.9-.1 13.5 0 1.3.9 2.8 3.4 2.4C84 89.1 98 70.7 98 49.1 98 22 76.1 0 49 0Z"/>
    </svg>
  </a>
</header>
```

```css
.app-header {
  display: flex;
  align-items: center;
  gap: 12px;
}
.app-header h1 {
  flex: 1;
  margin: 0;
}
.github-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, CanvasText 20%, Canvas);
  background: color-mix(in srgb, Canvas 92%, CanvasText 8%);
  color: CanvasText;
}
.github-link:hover {
  background: color-mix(in srgb, Canvas 88%, CanvasText 12%);
}
.github-link svg {
  width: 16px;
  height: 16px;
}
```

React/Vue: same markup in the root layout header component.

## Streamlit, Gradio, NiceGUI

These stacks do not have native window chrome. Place a compact repo link in the top area.

**Streamlit**

```python
import streamlit as st

col_title, col_link = st.columns([6, 1], vertical_alignment="center")
with col_title:
    st.title("App title")
with col_link:
    st.link_button(
        ":github:",
        "https://github.com/owner/repo",
        help="Open GitHub repository",
    )
```

Prefer a small custom markdown link with inline SVG if `link_button` styling is too large.

**Gradio**

```python
gr.Markdown(
    '<div style="display:flex;justify-content:space-between;align-items:center">'
    '<h2>App title</h2>'
    '<a href="https://github.com/owner/repo" target="_blank" rel="noopener" '
    'title="Open GitHub repository" aria-label="Open GitHub repository" '
    'style="width:30px;height:30px;display:inline-flex;align-items:center;'
    'justify-content:center;border-radius:999px;border:1px solid #ccc">...</a>'
    '</div>'
)
```

**NiceGUI**

```python
with ui.row().classes("w-full items-center"):
    ui.label("App title").classes("text-h5 flex-grow")
    ui.link(target="https://github.com/owner/repo", new_tab=True).tooltip(
        "Open GitHub repository"
    ).classes("rounded-full border p-1")
```

Keep the same 30 px circular target and external tab behavior even when the host framework limits styling.
