import QtQuick
import QtQuick.Layouts
import qs.Commons

// One account usage window (session or week), like Claude Code's /usage: a label, a thin bar, the percent
// used and when it resets.
ColumnLayout {
  id: bar
  property string label: ""
  property var window: ({})          // {used, resetsAt} from the daemon's usage
  property var view
  readonly property bool known: window && window.used !== undefined && window.used !== null
  readonly property real used: known ? window.used : 0
  readonly property color tone: used >= 80 ? view.fleet.red : used >= 50 ? view.fleet.yellow : view.fleet.green
  spacing: Style.space(3)

  function untilReset(ts) {
    var s = Math.max(0, Math.floor(ts - Date.now() / 1000))
    var d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60)
    return d ? d + "d " + h + "h" : h ? h + "h " + m + "m" : m + "m"
  }

  RowLayout {
    Layout.fillWidth: true
    Text { text: bar.label; color: bar.view.dim; font.family: bar.view.fontFamily; font.pixelSize: Style.font.bodySmall }
    Item { Layout.fillWidth: true }
    Text {
      text: !bar.known ? "–" : Math.round(bar.used) + "%" + (bar.window.resetsAt ? " · ↻ " + bar.untilReset(bar.window.resetsAt) : "")
      color: bar.known ? bar.tone : bar.view.dim
      font.family: bar.view.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
  }
  Rectangle {
    Layout.fillWidth: true
    implicitHeight: Style.space(4)
    radius: height / 2
    color: Qt.rgba(bar.tone.r, bar.tone.g, bar.tone.b, 0.18)
    Rectangle {
      width: parent.width * Math.min(1, bar.used / 100)
      height: parent.height
      radius: parent.radius
      color: bar.tone
    }
  }
}
