import QtQuick
import QtQuick.Layouts
import qs.Commons
import "util.js" as U

// The AI-train tab: every run Claude registered, one row each; a click opens its curves.
ColumnLayout {
  id: tab
  property var view
  property var runs: []
  property string openId: ""        // the run whose detail is showing
  property string openClass: ""     // the class whose curve is showing
  property string openTag: ""       // the raw tag whose curve is showing
  spacing: Style.space(4)

  readonly property var byId: {
    var out = {}
    runs.forEach(function(r) { out[r.id] = r })
    return out
  }
  ListModel { id: rowsModel }
  onRunsChanged: U.syncModel(rowsModel, runs.map(function(r) { return { key: r.id } }))

  function statusTone(r) {
    if (r.unreachable) return view.fleet.red
    return { running: view.fleet.accent, finished: view.fleet.green, stalled: view.fleet.orange }[r.status] || view.dim
  }
  function statusText(r) { return r.unreachable ? "host unreachable" : r.status }

  RowLayout {
    Layout.fillWidth: true
    Layout.leftMargin: Style.space(14)
    Layout.rightMargin: Style.space(14)
    Layout.topMargin: Style.space(6)
    spacing: Style.space(8)
    Text { text: "A I - T R A I N"; color: view.fg; font.family: view.fontFamily; font.pixelSize: Style.font.subtitle; font.bold: true }
    Text {
      Layout.fillWidth: true
      horizontalAlignment: Text.AlignRight
      text: {
        var going = tab.runs.filter(function(r) { return r.status === "running" }).length
        return going + " running · " + tab.runs.length + " tracked"
      }
      color: view.dim
      font.family: view.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
  }

  // column heads
  RowLayout {
    Layout.fillWidth: true
    Layout.leftMargin: Style.space(14)
    Layout.rightMargin: Style.space(14)
    Layout.topMargin: Style.space(6)
    visible: rowsModel.count > 0
    spacing: Style.space(12)
    Repeater {
      model: [["RUN", -1], ["MACHINE", 110], ["STATUS", 130], ["EPOCH", 74], ["ETA", 66], ["MAP", 54], ["LOSS", 120]]
      Text {
        required property var modelData
        Layout.fillWidth: modelData[1] < 0
        Layout.preferredWidth: modelData[1] < 0 ? -1 : Style.space(modelData[1])
        text: modelData[0]
        color: view.dim
        font.family: view.fontFamily
        font.pixelSize: Style.font.caption
        font.letterSpacing: 1.5
      }
    }
  }

  Repeater {
    model: rowsModel
    ColumnLayout {
      id: entry
      required property var model
      readonly property var run: tab.byId[model.key] || ({})
      readonly property bool isOpen: tab.openId === model.key
      Layout.fillWidth: true
      spacing: 0

      Rectangle {
        Layout.fillWidth: true
        implicitHeight: rowLine.implicitHeight + Style.space(10) + (errorLine.visible ? errorLine.implicitHeight : 0)
        color: rowHover.containsMouse || entry.isOpen ? Qt.rgba(view.fg.r, view.fg.g, view.fg.b, 0.05) : "transparent"
        MouseArea {
          id: rowHover
          anchors.fill: parent
          hoverEnabled: true
          acceptedButtons: Qt.LeftButton | Qt.RightButton
          onClicked: function(mouse) {
            if (mouse.button === Qt.RightButton) {
              view.openMenu(Object.assign({ key: entry.run.id, isTrain: true }, entry.run), rowHover, mouse.x, mouse.y, false)
            } else if (!entry.run.placeholder) {
              tab.openClass = ""; tab.openTag = ""
              tab.openId = entry.isOpen ? "" : entry.run.id
            }
          }
        }
        RowLayout {
          id: rowLine
          x: Style.space(14)
          y: Style.space(5)
          width: parent.width - 2 * x
          spacing: Style.space(12)
          Text {
            Layout.fillWidth: true
            text: (entry.isOpen ? "▾ " : entry.run.placeholder ? "  " : "▸ ") + (entry.run.name || "")
            elide: Text.ElideMiddle
            color: view.fg
            font.family: view.fontFamily
            font.pixelSize: Style.font.body
          }
          Text {
            Layout.preferredWidth: Style.space(110)
            text: entry.run.machine || ""
            elide: Text.ElideRight
            color: view.fg
            font.family: view.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
          Item {
            Layout.preferredWidth: Style.space(130)
            implicitHeight: statusPill.implicitHeight
            Pill { id: statusPill; text: tab.statusText(entry.run); tone: tab.statusTone(entry.run); font: view.fontFamily }
          }
          Text {
            Layout.preferredWidth: Style.space(74)
            text: (entry.run.epoch || 0) + "/" + (entry.run.epochs || "?")
            color: view.fg
            font.family: view.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
          Text {
            Layout.preferredWidth: Style.space(66)
            text: entry.run.status === "running" && !entry.run.unreachable ? U.fmtEta(entry.run.etaSec) : "–"
            color: view.dim
            font.family: view.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
          Text {
            Layout.preferredWidth: Style.space(54)
            text: entry.run.map === undefined || entry.run.map === null ? "–" : entry.run.map.toFixed(3)
            color: view.fg
            font.family: view.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
          Chart {
            Layout.preferredWidth: Style.space(120)
            Layout.preferredHeight: Style.space(22)
            compact: true
            view: tab.view
            series: [{ name: "train", color: String(view.fleet.accent), points: (entry.run.curves || {}).trainLoss || [] }]
          }
        }
        Text {
          id: errorLine
          visible: !!entry.run.error
          anchors.top: rowLine.bottom
          x: Style.space(14)
          width: parent.width - 2 * x
          text: entry.run.error || ""
          elide: Text.ElideRight
          color: view.fleet.red
          font.family: view.fontFamily
          font.pixelSize: Style.font.caption
        }
      }

      // ---- detail
      Loader {
        Layout.fillWidth: true
        active: entry.isOpen
        visible: active
        sourceComponent: ColumnLayout {
          id: detail
          spacing: Style.space(10)
          readonly property var curves: entry.run.curves || {}
          readonly property var classes: entry.run.classes || []
          readonly property var rawTags: Object.keys(entry.run.raw || {})
          readonly property real xMax: Math.max(entry.run.epoch || 0, 1)
          Item { Layout.preferredHeight: Style.space(2) }
          RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Style.space(14)
            Layout.rightMargin: Style.space(14)
            spacing: Style.space(16)
            Chart {
              Layout.fillWidth: true
              Layout.preferredWidth: 1
              view: tab.view
              title: "Loss"
              xMax: detail.xMax
              series: [{ name: "train", color: String(view.fleet.accent), points: detail.curves.trainLoss || [] },
                       { name: "val", color: String(view.fleet.magenta), points: detail.curves.valLoss || [] }]
            }
            Chart {
              Layout.fillWidth: true
              Layout.preferredWidth: 1
              view: tab.view
              title: "Val mAP"
              xMax: detail.xMax
              series: [{ name: "mAP50-95", color: String(view.fleet.accent), points: detail.curves.map || [] },
                       { name: "mAP50", color: String(view.fleet.magenta), points: detail.curves.map50 || [] }]
            }
          }

          // per-class mAP, only if the run logs it; a click shows that class over time
          Text {
            Layout.leftMargin: Style.space(14)
            visible: detail.classes.length > 0
            text: "PER-CLASS VAL MAP, LOWEST FIRST"
            color: view.dim
            font.family: view.fontFamily
            font.pixelSize: Style.font.caption
            font.letterSpacing: 1.5
          }
          Repeater {
            model: detail.classes
            Rectangle {
              required property var modelData
              readonly property bool shown: tab.openClass === modelData.name
              Layout.fillWidth: true
              Layout.leftMargin: Style.space(14)
              Layout.rightMargin: Style.space(14)
              implicitHeight: classRow.implicitHeight + Style.space(4)
              color: classHover.containsMouse || shown ? Qt.rgba(view.fg.r, view.fg.g, view.fg.b, 0.05) : "transparent"
              MouseArea {
                id: classHover
                anchors.fill: parent
                hoverEnabled: true
                onClicked: tab.openClass = parent.shown ? "" : modelData.name
              }
              RowLayout {
                id: classRow
                width: parent.width
                y: Style.space(2)
                spacing: Style.space(10)
                Text {
                  Layout.preferredWidth: Style.space(200)
                  text: modelData.name
                  elide: Text.ElideRight
                  color: view.fg
                  font.family: view.fontFamily
                  font.pixelSize: Style.font.bodySmall
                }
                Rectangle {
                  Layout.fillWidth: true
                  implicitHeight: Style.space(5)
                  radius: 2
                  color: Qt.rgba(view.fg.r, view.fg.g, view.fg.b, 0.08)
                  Rectangle {
                    width: parent.width * Math.max(0, Math.min(1, modelData.map))
                    height: parent.height
                    radius: 2
                    color: view.fleet.accent
                  }
                }
                Text {
                  Layout.preferredWidth: Style.space(44)
                  horizontalAlignment: Text.AlignRight
                  text: modelData.map.toFixed(3)
                  color: view.fg
                  font.family: view.fontFamily
                  font.pixelSize: Style.font.bodySmall
                }
              }
            }
          }
          Chart {
            id: classChart
            readonly property var picked: (detail.classes.filter(function(k) { return k.name === tab.openClass }))[0]
            visible: !!picked
            Layout.fillWidth: true
            Layout.leftMargin: Style.space(14)
            Layout.rightMargin: Style.space(14)
            view: tab.view
            title: picked ? picked.name + " mAP" : ""
            xMax: detail.xMax
            series: picked ? [{ name: picked.name, color: String(view.fleet.accent), points: picked.curve }] : []
          }

          // every tag the run logs; drawn one at a time so a run with hundreds stays light
          Text {
            Layout.leftMargin: Style.space(14)
            visible: detail.rawTags.length > 0
            text: "ALL CURVES"
            color: view.dim
            font.family: view.fontFamily
            font.pixelSize: Style.font.caption
            font.letterSpacing: 1.5
          }
          Flow {
            Layout.fillWidth: true
            Layout.leftMargin: Style.space(14)
            Layout.rightMargin: Style.space(14)
            spacing: Style.space(4)
            Repeater {
              model: detail.rawTags
              SmallButton {
                required property var modelData
                text: modelData
                font: view.fontFamily
                tone: tab.openTag === modelData ? view.fg : view.dim
                primary: tab.openTag === modelData
                ink: view.surface
                onClicked: tab.openTag = tab.openTag === modelData ? "" : modelData
              }
            }
          }
          Chart {
            visible: tab.openTag !== ""
            Layout.fillWidth: true
            Layout.leftMargin: Style.space(14)
            Layout.rightMargin: Style.space(14)
            view: tab.view
            title: tab.openTag
            xMax: detail.xMax
            series: tab.openTag !== "" ? [{ name: tab.openTag, color: String(view.fleet.accent), points: (entry.run.raw || {})[tab.openTag] || [] }] : []
          }
          Item { Layout.preferredHeight: Style.space(6) }
        }
      }
    }
  }

  Text {
    Layout.fillWidth: true
    Layout.margins: Style.space(14)
    visible: rowsModel.count === 0
    text: "No training tracked. Runs appear here when a Claude session launches training and registers it with `fleet train watch`."
    wrapMode: Text.Wrap
    color: view.dim
    font.family: view.fontFamily
    font.pixelSize: Style.font.body
  }
}
