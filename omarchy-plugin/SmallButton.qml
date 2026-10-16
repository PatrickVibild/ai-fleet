import QtQuick
import qs.Commons

// Compact text button used in cards and confirmations. `primary` fills it with the tone.
Rectangle {
  id: b
  property string text: ""
  property color tone: "white"
  property color ink: "black"
  property string font: "monospace"
  property bool primary: false
  property bool enabledState: true
  signal clicked()
  implicitWidth: label.implicitWidth + Style.space(18)
  implicitHeight: label.implicitHeight + Style.space(9)
  radius: 3
  opacity: enabledState ? 1 : 0.4
  color: primary ? tone : (area.containsMouse ? Qt.rgba(tone.r, tone.g, tone.b, 0.12) : "transparent")
  border.color: primary ? tone : Qt.rgba(tone.r, tone.g, tone.b, area.containsMouse ? 0.9 : 0.45)
  border.width: 1
  Text {
    id: label
    anchors.centerIn: parent
    text: b.text
    color: b.primary ? b.ink : b.tone
    font.family: b.font
    font.pixelSize: Style.font.bodySmall
    font.bold: b.primary
  }
  MouseArea {
    id: area
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    enabled: b.enabledState
    onClicked: b.clicked()
  }
}
