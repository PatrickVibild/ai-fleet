import QtQuick
import Quickshell
import qs.Commons

// One skill in a playbook's flowchart. "main" is on the main path, "extra" is optional, "side" is for any time.
// Hovering shows when to use it in the flowchart's detail strip; a click copies it.
Rectangle {
  id: node
  property var view
  property var flow
  property var skill: ({})
  property string kind: "main"
  readonly property bool installed: flow.isInstalled(skill.name)
  readonly property color tone: kind === "main" ? view.fleet.accent : kind === "side" ? view.fleet.cyan : view.fg
  readonly property bool hot: area.containsMouse || flow.hovered === skill

  implicitWidth: label.implicitWidth + Style.space(20)
  implicitHeight: label.implicitHeight + Style.space(kind === "main" ? 14 : 10)
  radius: Style.space(5)
  opacity: installed ? 1 : 0.45
  color: kind === "main" ? Qt.rgba(tone.r, tone.g, tone.b, hot ? 0.28 : 0.16)
       : Qt.rgba(tone.r, tone.g, tone.b, hot ? 0.12 : kind === "side" ? 0.06 : 0)
  border.width: 1
  border.color: Qt.rgba(tone.r, tone.g, tone.b, hot ? 0.95 : kind === "main" ? 0.7 : 0.3)

  Text {
    id: label
    anchors.centerIn: parent
    width: Math.min(implicitWidth, node.width - Style.space(16))
    text: "/" + node.skill.name + (node.installed ? "" : "  ✕")
    elide: Text.ElideRight
    color: node.kind === "extra" ? (node.hot ? node.view.fg : node.view.dim) : node.kind === "main" ? node.view.fg : node.tone
    font.family: node.view.fontFamily
    font.pixelSize: node.kind === "main" ? Style.font.body : Style.font.bodySmall
    font.bold: node.kind === "main"
  }
  MouseArea {
    id: area
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: node.installed ? Qt.PointingHandCursor : Qt.ArrowCursor
    onContainsMouseChanged: if (containsMouse) node.flow.hovered = node.skill
    onClicked: {
      if (!node.installed) return node.view.toast("/" + node.skill.name + " isn't installed", true)
      Quickshell.execDetached(["wl-copy", "/" + node.skill.name])
      node.view.toast("Copied /" + node.skill.name, false)
    }
  }
}
