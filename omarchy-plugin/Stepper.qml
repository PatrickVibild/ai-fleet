import QtQuick
import qs.Commons

// "Label  −  4  +" limit control. Emits change(newValue); the daemon owns the real value.
Rectangle {
  id: s
  property string label: ""
  property int value: 0
  property int min: 1
  property int max: 16
  property var view
  signal change(int v)
  implicitWidth: row.implicitWidth + 2
  implicitHeight: Style.space(28)
  radius: 4
  color: "transparent"
  border.color: Qt.rgba(view.fg.r, view.fg.g, view.fg.b, 0.18)
  Row {
    id: row
    anchors.verticalCenter: parent.verticalCenter
    x: 1
    Text { text: s.label; leftPadding: Style.space(10); rightPadding: Style.space(6); anchors.verticalCenter: parent.verticalCenter; color: s.view.dim; font.family: s.view.fontFamily; font.pixelSize: Style.font.bodySmall }
    Repeater {
      model: ["−", "v", "+"]
      Item {
        required property string modelData
        width: modelData === "v" ? Style.space(22) : Style.space(24)
        height: s.height - 2
        Text {
          anchors.centerIn: parent
          text: parent.modelData === "v" ? s.value : parent.modelData
          color: parent.modelData === "v" ? s.view.fg : (btn.containsMouse ? s.view.fleet.accent : s.view.dim)
          font.family: s.view.fontFamily
          font.pixelSize: Style.font.body
          font.bold: parent.modelData === "v"
        }
        MouseArea {
          id: btn
          anchors.fill: parent
          enabled: parent.modelData !== "v"
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: {
            var v = Math.max(s.min, Math.min(s.max, s.value + (parent.modelData === "+" ? 1 : -1)))
            if (v !== s.value) s.change(v)
          }
        }
      }
    }
  }
}
