import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "util.js" as U

// One run: header with controls, the ticket graph, banners, and the agent lanes.
ColumnLayout {
  id: sec
  required property string runId
  required property var view
  readonly property var fleet: view.fleet
  readonly property var run: view.runById(runId)
  readonly property var tickets: run ? run.tickets || [] : []
  readonly property int merged: tickets.filter(function(t) { return t.state === "merged" }).length
  readonly property bool queued: run && run.status === "queued"
  readonly property bool confirmingAbort: view.confirmKill === "abort:" + runId
  spacing: Style.space(4)

  ListModel { id: rows }
  function sync() { if (run && !queued) U.syncModel(rows, view.runRows(run)) }
  onRunChanged: sync()
  Connections { target: sec.view; function onLayoutChanged() { sec.sync() } }
  Component.onCompleted: sync()

  // ---- header
  RowLayout {
    Layout.fillWidth: true
    Layout.leftMargin: Style.space(14)
    Layout.rightMargin: Style.space(14)
    Layout.topMargin: Style.space(10)
    spacing: Style.space(10)
    Text { text: "RUN"; color: sec.view.dim; font.family: sec.view.fontFamily; font.pixelSize: Style.font.caption; font.letterSpacing: 2 }
    Text { text: sec.run ? sec.run.name : ""; color: sec.view.fg; font.family: sec.view.fontFamily; font.pixelSize: Style.font.subtitle; font.bold: true }
    Text {
      Layout.fillWidth: true
      elide: Text.ElideMiddle
      text: sec.queued ? "queued · waiting for an orchestrator slot"
          : (sec.merged + "/" + sec.tickets.length + " merged to " + (sec.run ? sec.run.base : "") + " · " + (sec.run ? sec.run.repo.replace(sec.fleet.home, "~") : ""))
      color: sec.view.dim
      font.family: sec.view.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
    Text {
      visible: !!sec.run && !!sec.run.slots && !sec.queued
      text: sec.run && sec.run.slots ? "slots " + sec.run.slots.used + "/" + sec.run.slots.max : ""
      color: sec.view.dim
      font.family: sec.view.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
    Row {
      spacing: Style.space(6)
      visible: !!sec.run && !sec.run.mock && ["active", "paused"].indexOf(sec.run.status) >= 0 && !sec.confirmingAbort
      SmallButton {
        text: sec.run && sec.run.status === "paused" ? "▶ Resume" : "❚❚ Pause"
        tone: sec.view.fg; font: sec.view.fontFamily
        onClicked: sec.run.status === "paused" ? sec.fleet.run(["resume", sec.runId], "Resumed " + sec.run.name)
                                               : sec.fleet.run(["pause", sec.runId], "Paused " + sec.run.name + ". Running agents finish; nothing new starts.")
      }
      SmallButton { text: "■ Abort"; tone: sec.fleet.red; font: sec.view.fontFamily; onClicked: sec.view.confirmKill = "abort:" + sec.runId }
    }
    Row {
      spacing: Style.space(6)
      visible: sec.confirmingAbort
      Text { text: "Abort the run?"; color: sec.fleet.red; font.family: sec.view.fontFamily; font.pixelSize: Style.font.bodySmall; anchors.verticalCenter: parent.verticalCenter }
      SmallButton { text: "Abort"; tone: sec.fleet.red; font: sec.view.fontFamily; onClicked: { sec.fleet.run(["abort", sec.runId], "Aborted " + sec.run.name + ". Worktrees kept."); sec.view.confirmKill = "" } }
      SmallButton { text: "Keep"; tone: sec.view.dim; font: sec.view.fontFamily; onClicked: sec.view.confirmKill = "" }
    }
    SmallButton {
      visible: !!sec.run && ["done", "aborted"].indexOf(sec.run.status) >= 0
      text: "✕ Close"; tone: sec.view.dim; font: sec.view.fontFamily
      onClicked: sec.view.closeRun(sec.run)
    }
  }

  // ---- ticket graph + legend
  RowLayout {
    Layout.fillWidth: true
    Layout.leftMargin: Style.space(14)
    spacing: Style.space(18)
    visible: sec.tickets.length > 0
    Dag {
      id: dag
      Layout.preferredWidth: implicitWidth
      Layout.preferredHeight: implicitHeight
      tickets: sec.tickets
      laneColors: sec.view.laneColorsFor(sec.run)
      fg: sec.view.fg; dim: sec.view.dim; bg: sec.view.surface
      line: Qt.rgba(sec.view.fg.r, sec.view.fg.g, sec.view.fg.b, 0.25)
      green: sec.fleet.green; red: sec.fleet.red; accent: sec.fleet.accent
      fontFamily: sec.view.fontFamily
      onTicketClicked: function(t) {
        sec.fleet.open(t.short)
        sec.view.toast("Opened a terminal on #" + t.id + " (" + t.short + "). Closing it leaves the session as it was.", false)
      }
    }
    ColumnLayout {
      Layout.alignment: Qt.AlignVCenter
      spacing: Style.space(4)
      Repeater {
        model: [["merged", sec.fleet.green, false], ["running (lane color)", sec.fleet.accent, false],
                ["needs you", sec.fleet.red, false], ["waiting", sec.view.dim, true]]
        Row {
          required property var modelData
          spacing: Style.space(6)
          Rectangle {
            width: Style.space(8); height: width; radius: width / 2
            anchors.verticalCenter: parent.verticalCenter
            color: modelData[2] ? "transparent" : modelData[1]
            border.color: modelData[1]; border.width: 1.2
          }
          Text { text: modelData[0]; color: sec.view.dim; font.family: sec.view.fontFamily; font.pixelSize: Style.font.bodySmall }
        }
      }
    }
  }

  // ---- banners
  Banner {
    Layout.fillWidth: true
    visible: !!sec.run && sec.run.status === "paused"
    text: "❚❚  Paused. Running agents finish their work; no new tickets start."
    tone: sec.fleet.yellow; font: sec.view.fontFamily
  }
  Banner {
    Layout.fillWidth: true
    visible: !!sec.run && !!sec.run.held
    text: "⚠  " + (sec.run && sec.run.held ? sec.run.held.reason : "")
    tone: sec.fleet.red; font: sec.view.fontFamily
  }
  Banner {
    Layout.fillWidth: true
    visible: !!sec.run && sec.run.status === "active" && ["running", "cleanup"].indexOf(sec.run.finalCheck) >= 0
    text: !sec.run ? "" : sec.run.finalCheck === "cleanup"
      ? "◌  Every ticket is merged and the full suite is green. Cleaning up worktrees…"
      : "◌  Every ticket is merged. Running the full suite on " + sec.run.base
        + (sec.run.finalCheckAt ? " since " + Qt.formatTime(new Date(sec.run.finalCheckAt * 1000), "HH:mm") : "")
        + (sec.run.finalCmd ? ": " + sec.run.finalCmd : "")
    tone: sec.fleet.cyan; font: sec.view.fontFamily
  }
  Banner {
    Layout.fillWidth: true
    visible: !!sec.run && sec.run.status === "done"
    text: "✓  Every ticket is merged and the full suite is green."
    tone: sec.fleet.green; font: sec.view.fontFamily
  }
  GitTicks {
    Layout.fillWidth: true
    Layout.leftMargin: Style.space(14)
    Layout.rightMargin: Style.space(14)
    g: U.gitFields(sec.run ? sec.run.git : null)
    view: sec.view
    visible: !!sec.run && sec.run.status === "done" && !!sec.run.git
  }
  Banner {
    Layout.fillWidth: true
    visible: !!sec.run && sec.run.status === "aborted"
    text: "■  Aborted. Worktrees are kept; nothing else merges."
    tone: sec.view.dim; font: sec.view.fontFamily
  }

  // ---- lanes
  ColumnHeader {
    Layout.fillWidth: true
    Layout.rightMargin: Style.space(10)
    visible: !sec.queued && rows.count > 0
    view: sec.view
  }
  Repeater {
    model: rows
    AgentRow {
      required property var model
      Layout.fillWidth: true
      row: model
      view: sec.view
    }
  }

  // ---- what's waiting
  Flow {
    Layout.fillWidth: true
    Layout.leftMargin: Style.space(44)
    Layout.rightMargin: Style.space(14)
    Layout.topMargin: Style.space(2)
    spacing: Style.space(14)
    visible: !sec.queued
    Repeater {
      model: sec.tickets.filter(function(t) { return t.state === "wait" })
      Text {
        required property var modelData
        readonly property var stuck: modelData.blockedOn || []
        readonly property var open: (modelData.blockedBy || []).filter(function(b) {
          var bt = sec.tickets.filter(function(x) { return x.id === b })[0]
          return bt && bt.state !== "merged"
        })
        text: "#" + modelData.id + (stuck.length ? " blocked by " + stuck.map(function(b) { return "#" + b }).join(", ")
                                   : open.length ? " waits on " + open.map(function(b) { return "#" + b }).join(", ") : " waits for a free slot")
        color: stuck.length ? sec.fleet.red : sec.view.dim
        font.family: sec.view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }
    }
  }
}
