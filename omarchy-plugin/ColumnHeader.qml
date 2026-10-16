import QtQuick
import QtQuick.Layouts
import qs.Commons

// Labels for AgentRow's right-hand columns; the widths and spacing match AgentRow's.
RowLayout {
  id: h
  required property var view
  spacing: Style.space(8)

  component Label: Text {
    horizontalAlignment: Text.AlignRight
    color: h.view.dim
    font.family: h.view.fontFamily
    font.pixelSize: Style.font.caption
    font.letterSpacing: 1
  }

  Item { Layout.fillWidth: true }
  Label { Layout.preferredWidth: Style.space(52); text: "CLAUDE.MD" }
  Label { Layout.preferredWidth: Style.space(70); text: "CONTEXT" }
  Label { Layout.preferredWidth: Style.space(60); text: "TOKENS" }
  Label { Layout.preferredWidth: Style.space(56); text: "TIME" }
  Label { Layout.preferredWidth: Style.space(110); text: "TESTS" }
}
