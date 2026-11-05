import QtQuick
import QtQuick.Layouts
import qs.Commons

// The How-to tab: your playbooks of which skill to use when, one Markdown file in ~/.config/ai-fleet/howto each.
ColumnLayout {
  id: tab
  property var view
  property var docs: []
  property var skills: []
  property int current: 0
  readonly property var doc: docs[Math.min(current, docs.length - 1)] || null
  function step(d) { if (docs.length) current = (Math.min(current, docs.length - 1) + d + docs.length) % docs.length }
  spacing: Style.space(8)

  RowLayout {
    Layout.fillWidth: true
    Layout.leftMargin: Style.space(14)
    Layout.rightMargin: Style.space(14)
    Layout.topMargin: Style.space(6)
    spacing: Style.space(12)
    Text { text: "H O W - T O"; color: view.fg; font.family: view.fontFamily; font.pixelSize: Style.font.subtitle; font.bold: true }
    Row {
      spacing: 0
      Repeater {
        model: tab.docs
        SmallButton {
          required property var modelData
          required property int index
          text: modelData.name; font: view.fontFamily
          readonly property bool picked: !!tab.doc && tab.doc.path === modelData.path
          tone: picked ? view.fg : view.dim
          primary: picked; ink: view.surface
          onClicked: tab.current = index
        }
      }
    }
    Item { Layout.fillWidth: true }
    Text {
      text: tab.doc ? tab.doc.path.replace(view.fleet.home, "~") : ""
      color: view.dim
      font.family: view.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  MdView {
    Layout.fillWidth: true
    Layout.leftMargin: Style.space(14)
    Layout.rightMargin: Style.space(14)
    visible: !!tab.doc
    view: tab.view
    path: tab.doc ? tab.doc.path : ""
    skills: tab.skills
  }

  Text {
    Layout.fillWidth: true
    Layout.margins: Style.space(14)
    visible: !tab.docs.length
    text: "No playbooks yet. Put Markdown files in ~/.config/ai-fleet/howto and each one becomes a tab here."
    wrapMode: Text.Wrap
    color: view.dim
    font.family: view.fontFamily
    font.pixelSize: Style.font.body
  }
}
