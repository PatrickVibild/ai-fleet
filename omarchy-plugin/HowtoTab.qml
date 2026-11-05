import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import "util.js" as U

// The How-to tab: your playbooks of which skill to use when, one Markdown file in ~/.config/ai-fleet/howto each.
// A playbook with `/skill` bullets draws as a flowchart; any other Markdown file shows as it is.
ColumnLayout {
  id: tab
  property var view
  property var docs: []
  property var skills: []
  property int current: 0
  property string raw: ""
  readonly property var doc: docs[Math.min(current, docs.length - 1)] || null
  readonly property var book: U.parsePlaybook(raw)
  function step(d) { if (docs.length) current = (Math.min(current, docs.length - 1) + d + docs.length) % docs.length }
  spacing: Style.space(10)

  FileView {
    path: tab.doc ? tab.doc.path : ""
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: tab.raw = text()
    onLoadFailed: tab.raw = ""
  }

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
          readonly property bool picked: !!tab.doc && tab.doc.path === modelData.path
          text: modelData.name; font: view.fontFamily
          tone: picked ? view.fg : view.dim
          primary: picked; ink: view.surface
          onClicked: tab.current = index
        }
      }
    }
    Item { Layout.fillWidth: true }
    SmallButton {
      visible: !!tab.doc
      text: "Edit playbook"; font: view.fontFamily
      tone: view.dim; ink: view.surface
      onClicked: Quickshell.execDetached(["omarchy-launch-editor", tab.doc.path])
    }
  }

  FlowChart {
    Layout.fillWidth: true
    Layout.leftMargin: Style.space(14)
    Layout.rightMargin: Style.space(14)
    Layout.bottomMargin: Style.space(10)
    visible: !!tab.doc && tab.book.skills > 0
    view: tab.view
    book: tab.book
    skills: tab.skills
  }

  MdView {
    Layout.fillWidth: true
    Layout.leftMargin: Style.space(14)
    Layout.rightMargin: Style.space(14)
    visible: !!tab.doc && tab.book.skills === 0
    view: tab.view
    path: visible ? tab.doc.path : ""
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
