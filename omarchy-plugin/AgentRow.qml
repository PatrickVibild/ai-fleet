import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "util.js" as U

// One agent in the tree. `row` is a ListModel entry (see util.flattenRun), so the delegate survives updates.
Item {
  id: r
  required property var row
  required property var view
  readonly property var fleet: view.fleet
  readonly property real indent: Style.space(22)
  readonly property bool inLane: row.depth >= 1
  readonly property real laneGap: inLane && row.laneFirst ? Style.space(6) : 0
  readonly property real laneInset: inLane ? Style.space(28) : 0
  readonly property color laneColor: row.lane !== "" ? row.lane : view.fleet.accent
  readonly property bool focused: view.focusedKey === row.key
  readonly property bool confirming: view.confirmKill === row.key
  readonly property bool hot: hover.containsMouse || focused || confirming || row.state === "attn"
  readonly property bool live: row.state === "run"

  Component.onCompleted: view.rowItems[row.key] = r
  Component.onDestruction: if (view && view.rowItems[row.key] === r) delete view.rowItems[row.key]

  width: parent ? parent.width : 0
  implicitHeight: laneGap + Math.max(Style.space(36), content.implicitHeight + Style.space(14))

  function stateColor() {
    if (row.state === "attn" || (row.kind === "check" && row.note === "red")) return fleet.red
    if (row.state === "done") return fleet.green
    if (row.state === "wait") return fleet.yellow
    if (row.state === "killed" || row.state === "blocked") return view.dim
    if (row.kind === "shell" || row.kind === "check") return fleet.cyan
    if (row.kind === "skill") return laneColor
    return inLane ? laneColor : fleet.accent
  }

  // lane band: tinted, with a colored rail on the left
  Rectangle {
    visible: r.inLane
    x: r.laneInset; y: r.laneGap
    width: parent.width - x; height: parent.height - y
    gradient: Gradient {
      orientation: Gradient.Horizontal
      GradientStop { position: 0; color: Qt.rgba(r.laneColor.r, r.laneColor.g, r.laneColor.b, r.row.state === "killed" ? 0.04 : 0.11) }
      GradientStop { position: 0.55; color: Qt.rgba(r.laneColor.r, r.laneColor.g, r.laneColor.b, 0.03) }
      GradientStop { position: 1; color: "transparent" }
    }
    Rectangle { width: Style.space(3); height: parent.height; color: r.row.state === "killed" ? r.view.dim : r.laneColor }
  }

  // nested-level guides: one line per ancestor level, in the lane color
  Repeater {
    model: Math.max(0, r.row.depth - 1)
    Rectangle {
      required property int index
      x: r.laneInset + Style.space(3) + Style.space(14) + index * r.indent
      y: r.laneGap
      width: 1
      height: r.height - r.laneGap
      color: Qt.rgba(r.laneColor.r, r.laneColor.g, r.laneColor.b, index === 0 ? 0.5 : 0.3)
    }
  }

  // hover / focus wash and the focus bar
  Rectangle {
    x: r.inLane ? r.laneInset + Style.space(3) : 0; y: r.laneGap
    width: parent.width - x; height: parent.height - y
    color: r.focused ? Qt.rgba(r.fleet.accent.r, r.fleet.accent.g, r.fleet.accent.b, 0.13)
         : hover.containsMouse ? Qt.rgba(r.view.fg.r, r.view.fg.g, r.view.fg.b, 0.05) : "transparent"
    Rectangle { visible: r.focused; width: 2; height: parent.height; color: r.fleet.accent }
  }

  MouseArea {
    id: hover
    anchors.fill: parent
    hoverEnabled: true
    acceptedButtons: Qt.LeftButton
    onClicked: r.view.focusRow(r.row.key)
    onDoubleClicked: if (r.row.hasKids) r.view.toggleExpand(r.row.key, r.row.expanded)
  }

  RowLayout {
    id: content
    x: (r.inLane ? r.laneInset + Style.space(8) : Style.space(4)) + Math.max(0, r.row.depth - 1) * r.indent
    y: r.laneGap + Style.space(7)
    width: parent.width - x - Style.space(10)
    spacing: Style.space(8)

    Text {
      Layout.preferredWidth: Style.space(12)
      Layout.alignment: Qt.AlignTop
      text: r.row.hasKids ? (r.row.expanded ? "▾" : "▸") : ""
      color: chevronArea.containsMouse ? r.fleet.accent : r.view.dim
      font.family: r.view.fontFamily
      font.pixelSize: Style.font.body
      MouseArea {
        id: chevronArea
        anchors.fill: parent
        anchors.margins: -4
        hoverEnabled: true
        enabled: r.row.hasKids
        onClicked: r.view.toggleExpand(r.row.key, r.row.expanded)
      }
    }

    Item {
      Layout.preferredWidth: Style.space(10)
      Layout.preferredHeight: Style.font.body + 2
      Layout.alignment: Qt.AlignTop
      Rectangle {
        id: halo
        anchors.centerIn: dot
        width: dot.width; height: width; radius: width / 2
        color: "transparent"
        border.color: dot.color
        border.width: 1
        visible: r.live || r.row.state === "attn"
        SequentialAnimation on scale {
          running: halo.visible
          loops: Animation.Infinite
          NumberAnimation { from: 1; to: 2.6; duration: r.row.state === "attn" ? 1100 : 1700; easing.type: Easing.OutCubic }
        }
        SequentialAnimation on opacity {
          running: halo.visible
          loops: Animation.Infinite
          NumberAnimation { from: 0.8; to: 0; duration: r.row.state === "attn" ? 1100 : 1700; easing.type: Easing.OutCubic }
        }
      }
      Rectangle {
        id: dot
        anchors.centerIn: parent
        readonly property bool dash: r.row.kind === "shell" || r.row.kind === "check"
        width: dash ? Style.space(8) : Style.space(7)
        height: dash ? 2 : width
        radius: r.row.kind === "skill" || dash ? 1 : width / 2
        rotation: r.row.kind === "skill" ? 45 : 0
        color: r.row.state === "killed" || r.row.state === "blocked" ? "transparent" : r.stateColor()
        border.color: r.stateColor()
        border.width: r.row.state === "killed" || r.row.state === "blocked" ? 1.5 : 0
      }
    }

    ColumnLayout {
      Layout.fillWidth: true
      Layout.minimumWidth: 0
      spacing: Style.space(2)
      RowLayout {
        Layout.fillWidth: true
        spacing: Style.space(8)
        Text {
          text: r.row.name
          color: r.row.depth === 1 && r.row.state !== "killed" ? r.laneColor
               : r.row.kind === "shell" ? r.fleet.cyan : r.view.fg
          font.family: r.view.fontFamily
          font.pixelSize: Style.font.body
          font.bold: r.row.kind !== "shell" && r.row.kind !== "skill"
          font.letterSpacing: r.row.kind === "orchestrator" ? 0.6 : 0
        }
        Text {
          Layout.fillWidth: true
          Layout.minimumWidth: 0
          text: r.row.tag
          elide: Text.ElideRight
          color: r.row.depth === 1 ? r.view.fg : r.view.dim
          font.family: r.view.fontFamily
          font.pixelSize: Style.font.body
        }
        Pill { visible: r.row.state === "attn"; text: "needs you"; tone: r.fleet.red; font: r.view.fontFamily }
        Pill { visible: r.row.state === "done" && r.row.depth <= 1 && r.row.kind !== "check"; text: "done"; tone: r.fleet.green; font: r.view.fontFamily }
        Pill { visible: r.row.state === "killed"; text: "killed"; tone: r.view.dim; font: r.view.fontFamily }
        Pill { visible: r.row.note !== ""; text: r.row.note; tone: r.row.kind !== "check" ? r.fleet.magenta : r.row.note === "red" ? r.fleet.red : r.row.note === "green" ? r.fleet.green : r.fleet.cyan; font: r.view.fontFamily }
      }
      Text {
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        readonly property bool ai: r.fleet.summaries === "ai" && r.row.summary !== ""
        text: ai ? r.row.summary : r.row.status
        visible: text !== ""
        color: ai ? Qt.tint(r.view.fg, Qt.rgba(r.fleet.magenta.r, r.fleet.magenta.g, r.fleet.magenta.b, 0.25)) : r.view.dim
        font.family: r.view.fontFamily
        font.pixelSize: Style.font.bodySmall
        font.italic: ai
        wrapMode: Text.Wrap
        maximumLineCount: 2
        elide: Text.ElideRight
      }
      // the latest test run's counts: the daemon's own check, or the last test command the agent ran
      RowLayout {
        Layout.fillWidth: true
        visible: r.row.testTotal > 0
        spacing: Style.space(8)
        Text {
          text: "✓ " + r.row.testPassed + " passed"
          color: r.fleet.green
          font.family: r.view.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
        Text {
          visible: r.row.testFailed > 0
          text: "✗ " + r.row.testFailed + " failed"
          color: r.fleet.red
          font.family: r.view.fontFamily
          font.pixelSize: Style.font.bodySmall
          font.bold: true
        }
        Text {
          visible: r.row.testSkipped > 0
          text: r.row.testSkipped + " skipped"
          color: r.view.dim
          font.family: r.view.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
        Text {
          Layout.fillWidth: true
          Layout.minimumWidth: 0
          text: "of " + r.row.testTotal + (r.row.kind !== "check" && r.row.testCmd !== "" ? " · " + r.row.testCmd : "")
          elide: Text.ElideRight
          color: r.view.dim
          font.family: r.view.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
      }
      // your own session in a git repo, once it stops working: is the work merged, and is it pushed?
      GitTicks {
        Layout.fillWidth: true
        Layout.topMargin: Style.space(2)
        g: r.row
        view: r.view
        visible: r.row.gitPath !== "" && r.row.activity !== "working"
      }
    }

    // column widths are mirrored in ColumnHeader.qml
    Text {
      Layout.preferredWidth: Style.space(52)
      Layout.alignment: Qt.AlignTop
      horizontalAlignment: Text.AlignRight
      text: U.canOpen(r.row) && r.row.mdTokens > 0 ? U.fmtTokens(r.row.mdTokens) : ""
      color: r.view.dim
      font.family: r.view.fontFamily
      font.pixelSize: Style.font.body
      HoverHandler { id: mdHover }
      PanelToolTip {
        visible: mdHover.hovered && r.row.mdFiles !== ""
        text: r.row.mdFiles
        fontFamily: r.view.fontFamily
      }
    }

    Row {
      Layout.preferredWidth: Style.space(70)
      Layout.alignment: Qt.AlignTop | Qt.AlignRight
      layoutDirection: Qt.RightToLeft
      spacing: Style.space(5)
      id: ctxCol
      visible: U.hasCtx(r.row) && r.row.ctxSize > 0
      readonly property real frac: r.row.ctxSize > 0 ? r.row.ctxUsed / r.row.ctxSize : 0
      readonly property string band: U.ctxBand(r.row.ctxUsed)
      readonly property color tone: band === "hot" ? r.fleet.red : band === "warn" ? r.fleet.orange : r.fleet.green
      Text {
        width: Style.space(44)
        horizontalAlignment: Text.AlignRight
        text: U.fmtCtx(r.row.ctxUsed)
        color: ctxCol.tone
        font.family: r.view.fontFamily
        font.pixelSize: Style.font.body
        HoverHandler { id: ctxHover }
        PanelToolTip {
          visible: ctxHover.hovered
          text: U.fmtTokens(r.row.ctxUsed) + " of " + U.fmtCtx(r.row.ctxSize) + " (" + Math.round(ctxCol.frac * 100) + "%)"
              + "\nunder 200k green · 200k–350k orange · over 350k red"
          fontFamily: r.view.fontFamily
        }
      }
      Ring {
        width: Style.space(16); height: width
        value: ctxCol.frac
        track: Qt.rgba(r.view.fg.r, r.view.fg.g, r.view.fg.b, 0.14)
        tone: ctxCol.tone
      }
    }
    Item { Layout.preferredWidth: Style.space(70); visible: !(U.hasCtx(r.row) && r.row.ctxSize > 0) }

    Text {
      Layout.preferredWidth: Style.space(60)
      Layout.alignment: Qt.AlignTop
      horizontalAlignment: Text.AlignRight
      text: U.hasCtx(r.row) ? U.fmtTokens(r.row.tokens) : ""
      color: r.view.fg
      font.family: r.view.fontFamily
      font.pixelSize: Style.font.body
    }
    Text {
      Layout.preferredWidth: Style.space(56)
      Layout.alignment: Qt.AlignTop
      horizontalAlignment: Text.AlignRight
      text: r.row.startedAt ? U.fmtDuration((r.row.endedAt || r.fleet.nowSec) - r.row.startedAt) : ""
      color: r.live ? r.view.fg : r.view.dim
      font.family: r.view.fontFamily
      font.pixelSize: Style.font.body
    }

    Item {
      Layout.preferredWidth: Style.space(96)
      Layout.preferredHeight: Style.space(22)
      Layout.alignment: Qt.AlignTop
      Row {
        anchors.right: parent.right
        spacing: Style.space(2)
        visible: r.hot && !r.confirming
        PanelActionButton {
          visible: r.row.kind === "implementor" && (r.row.state === "killed" || r.row.state === "attn")
          iconText: "󰑓"; tooltipText: "Retry (r)"; foreground: r.view.dim; hoverColor: r.view.fg
          onClicked: r.view.retry(r.row)
        }
        PanelActionButton {
          visible: U.canOpen(r.row) && r.row.state !== "killed"
          iconText: ""; tooltipText: "Open in a terminal (o)"; foreground: r.view.dim; hoverColor: r.view.fg
          onClicked: r.view.openRow(r.row)
        }
        PanelActionButton {
          visible: U.canOpen(r.row) && (r.row.alive || ["run", "attn", "wait"].indexOf(r.row.state) >= 0)
          iconText: "󰅖"; tooltipText: "Kill (x)"; foreground: r.view.dim; hoverColor: r.fleet.red
          onClicked: r.view.confirmKill = r.row.key
        }
      }
      Row {
        anchors.right: parent.right
        spacing: Style.space(4)
        visible: r.confirming
        Text { text: "Kill?"; color: r.fleet.red; font.family: r.view.fontFamily; font.pixelSize: Style.font.bodySmall; anchors.verticalCenter: parent.verticalCenter }
        SmallButton { text: "Kill"; tone: r.fleet.red; font: r.view.fontFamily; onClicked: r.view.kill(r.row) }
        SmallButton { text: "Keep"; tone: r.view.dim; font: r.view.fontFamily; onClicked: r.view.confirmKill = "" }
      }
    }
  }
}
