import QtQuick
import QtQuick.Layouts
import qs.Commons

// A one-line run status strip (paused, held, done, aborted).
Rectangle {
  id: b
  property string text: ""
  property color tone: "yellow"
  property string font: "monospace"
  implicitHeight: label.implicitHeight + Style.space(10)
  Layout.leftMargin: Style.space(14)
  Layout.rightMargin: Style.space(14)
  radius: 3
  color: Qt.rgba(tone.r, tone.g, tone.b, 0.09)
  border.color: Qt.rgba(tone.r, tone.g, tone.b, 0.3)
  border.width: 1
  Text {
    id: label
    anchors.verticalCenter: parent.verticalCenter
    x: Style.space(10)
    width: parent.width - 2 * x
    text: b.text
    color: b.tone
    wrapMode: Text.Wrap
    font.family: b.font
    font.pixelSize: Style.font.bodySmall
  }
}
