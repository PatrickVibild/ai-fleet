import QtQuick
import QtQuick.Layouts
import qs.Commons

// A playbook drawn as a flowchart: the main flow's stages left to right, each with its main path stacked in order
// and its optional skills under it, then the groups for any time. See U.parsePlaybook for the Markdown it reads.
ColumnLayout {
  id: chart
  property var view
  property var book: ({ stages: [], side: [] })
  property var skills: []
  property var hovered: null
  readonly property var have: {
    var o = {}
    skills.forEach(function(s) { o[s] = true })
    return o
  }
  function isInstalled(name) { return !skills.length || !!have[name] }
  onBookChanged: hovered = null
  spacing: Style.space(12)

  Text {
    Layout.fillWidth: true
    visible: chart.book.intro !== ""
    text: chart.book.intro || ""
    wrapMode: Text.Wrap
    color: view.dim
    font.family: view.fontFamily
    font.pixelSize: Style.font.body
  }

  // ---- the main flow
  RowLayout {
    Layout.fillWidth: true
    spacing: 0
    Repeater {
      model: chart.book.stages
      RowLayout {
        id: stage
        required property var modelData
        required property int index
        Layout.fillWidth: true
        Layout.preferredWidth: 1
        Layout.alignment: Qt.AlignTop
        spacing: 0

        // the arrow from the stage before, level with the stage heads
        Item {
          visible: stage.index > 0
          Layout.alignment: Qt.AlignTop
          Layout.topMargin: Style.space(4)
          implicitWidth: Style.space(34)
          implicitHeight: Style.space(20)
          Rectangle { anchors.verticalCenter: parent.verticalCenter; x: Style.space(4); width: parent.width - Style.space(12); height: 1.5; color: Qt.rgba(view.fg.r, view.fg.g, view.fg.b, 0.35) }
          Text { anchors.verticalCenter: parent.verticalCenter; anchors.right: parent.right; anchors.rightMargin: Style.space(3); text: "▶"; color: Qt.rgba(view.fg.r, view.fg.g, view.fg.b, 0.5); font.pixelSize: Style.font.caption }
        }

        ColumnLayout {
          Layout.fillWidth: true
          Layout.alignment: Qt.AlignTop
          spacing: Style.space(6)

          RowLayout {
            spacing: Style.space(8)
            Rectangle {
              implicitWidth: Style.space(20); implicitHeight: Style.space(20); radius: width / 2
              color: view.fleet.accent
              Text { anchors.centerIn: parent; text: stage.modelData.n; color: view.surface; font.family: view.fontFamily; font.pixelSize: Style.font.caption; font.bold: true }
            }
            Text {
              Layout.fillWidth: true
              text: stage.modelData.title.toUpperCase()
              elide: Text.ElideRight
              color: view.fg
              font.family: view.fontFamily
              font.pixelSize: Style.font.caption
              font.letterSpacing: 1.5
              font.bold: true
            }
          }
          Item { implicitHeight: Style.space(2) }

          Repeater {
            model: stage.modelData.main
            ColumnLayout {
              id: step
              required property var modelData
              required property int index
              Layout.fillWidth: true
              spacing: Style.space(2)
              Text {   // the main path within a stage runs top to bottom
                visible: step.index > 0
                Layout.alignment: Qt.AlignHCenter
                text: "↓"
                color: Qt.rgba(view.fleet.accent.r, view.fleet.accent.g, view.fleet.accent.b, 0.7)
                font.pixelSize: Style.font.body
              }
              SkillNode { Layout.fillWidth: true; view: chart.view; flow: chart; skill: step.modelData; kind: "main" }
            }
          }

          Text {
            visible: stage.modelData.extra.length > 0
            Layout.topMargin: Style.space(8)
            text: "OPTIONAL"
            color: view.dim
            font.family: view.fontFamily
            font.pixelSize: Style.font.caption - 1
            font.letterSpacing: 1.5
          }
          Repeater {
            model: stage.modelData.extra
            SkillNode {
              required property var modelData
              Layout.fillWidth: true
              Layout.leftMargin: Style.space(10)
              view: chart.view; flow: chart; skill: modelData; kind: "extra"
            }
          }
        }
      }
    }
  }

  // ---- when to use the skill under the pointer
  Rectangle {
    Layout.fillWidth: true
    implicitHeight: detail.implicitHeight + Style.space(16)
    radius: Style.space(5)
    color: Qt.rgba(view.fg.r, view.fg.g, view.fg.b, 0.04)
    border.width: 1
    border.color: Qt.rgba(view.fg.r, view.fg.g, view.fg.b, 0.08)
    Text {
      id: detail
      anchors.verticalCenter: parent.verticalCenter
      x: Style.space(12)
      width: parent.width - 2 * x
      wrapMode: Text.Wrap
      textFormat: Text.StyledText
      text: chart.hovered
        ? "<b>/" + chart.hovered.name + "</b>" + (chart.isInstalled(chart.hovered.name) ? "" : "  <i>(not installed)</i>")
          + "&nbsp;&nbsp;" + chart.hovered.when.replace(/&/g, "&amp;").replace(/</g, "&lt;")
        : "Point at a skill to see when to use it. Click one to copy it."
      color: chart.hovered ? view.fg : view.dim
      font.family: view.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
  }

  // ---- for any time
  RowLayout {
    Layout.fillWidth: true
    visible: chart.book.side.length > 0
    spacing: Style.space(24)
    Repeater {
      model: chart.book.side
      ColumnLayout {
        id: group
        required property var modelData
        Layout.fillWidth: true
        Layout.preferredWidth: Math.max(1, modelData.main.length + modelData.extra.length)
        Layout.alignment: Qt.AlignTop
        spacing: Style.space(6)
        Text {
          text: group.modelData.title.toUpperCase()
          color: view.fleet.cyan
          font.family: view.fontFamily
          font.pixelSize: Style.font.caption
          font.letterSpacing: 1.5
        }
        Flow {
          Layout.fillWidth: true
          spacing: Style.space(6)
          Repeater {
            model: group.modelData.main.concat(group.modelData.extra)
            SkillNode { required property var modelData; view: chart.view; flow: chart; skill: modelData; kind: "side" }
          }
        }
      }
    }
  }

  // ---- legend
  RowLayout {
    spacing: Style.space(16)
    Repeater {
      model: [["main", "main path"], ["extra", "optional"], ["side", "any time"]]
      RowLayout {
        required property var modelData
        spacing: Style.space(6)
        Rectangle {
          readonly property color tone: modelData[0] === "main" ? view.fleet.accent : modelData[0] === "side" ? view.fleet.cyan : view.fg
          implicitWidth: Style.space(14); implicitHeight: Style.space(10); radius: 2
          color: modelData[0] === "main" ? Qt.rgba(tone.r, tone.g, tone.b, 0.16) : modelData[0] === "side" ? Qt.rgba(tone.r, tone.g, tone.b, 0.06) : "transparent"
          border.width: 1
          border.color: Qt.rgba(tone.r, tone.g, tone.b, modelData[0] === "main" ? 0.7 : 0.3)
        }
        Text { text: modelData[1]; color: view.dim; font.family: view.fontFamily; font.pixelSize: Style.font.caption }
      }
    }
    Text { text: "✕ not installed"; color: view.dim; font.family: view.fontFamily; font.pixelSize: Style.font.caption }
  }
}
