import QtQuick
import qs.Commons

// Small uppercase state chip.
Rectangle {
  id: pill
  property string text: ""
  property color tone: "white"
  property string font: "monospace"
  implicitWidth: label.implicitWidth + Style.space(10)
  implicitHeight: label.implicitHeight + Style.space(2)
  radius: 2
  color: "transparent"
  border.color: tone
  border.width: 1
  Text {
    id: label
    anchors.centerIn: parent
    text: pill.text.toUpperCase()
    color: pill.tone
    font.family: pill.font
    font.pixelSize: Style.font.caption - 1
    font.letterSpacing: 1.1
  }
}
