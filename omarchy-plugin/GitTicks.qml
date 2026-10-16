import QtQuick
import qs.Commons
import qs.Ui

// Two ticks for finished work: merged into the base branch, and pushed to the remote. The push tick is a button
// while the work isn't on the remote; a failed push says why underneath. `g` holds the fields of util.gitFields.
Flow {
  id: t
  required property var g
  required property var view
  readonly property var fleet: view.fleet
  property bool justClicked: false
  readonly property bool pushing: g.gitPushState === "running" || justClicked
  readonly property bool failed: !pushing && g.gitPushState === "failed"
  spacing: Style.space(6)
  visible: g.gitPath !== ""

  Timer { id: settle; interval: 2500; onTriggered: t.justClicked = false }

  component Tick: Rectangle {
    id: tick
    property string label: ""
    property color tone: "white"
    property string tip: ""
    property bool clickable: false
    signal clicked()
    implicitWidth: txt.implicitWidth + Style.space(12)
    implicitHeight: txt.implicitHeight + Style.space(4)
    radius: 3
    color: clickable && area.containsMouse ? Qt.rgba(tone.r, tone.g, tone.b, 0.16) : Qt.rgba(tone.r, tone.g, tone.b, 0.06)
    border.color: Qt.rgba(tone.r, tone.g, tone.b, clickable && area.containsMouse ? 0.9 : 0.5)
    border.width: 1
    Text {
      id: txt
      anchors.centerIn: parent
      text: tick.label
      color: tick.tone
      font.family: t.view.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
    MouseArea {
      id: area
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: tick.clickable ? Qt.PointingHandCursor : Qt.ArrowCursor
      onClicked: if (tick.clickable) tick.clicked()
    }
    PanelToolTip { visible: area.containsMouse && tick.tip !== ""; text: tick.tip; fontFamily: t.view.fontFamily }
  }

  Tick {
    label: t.g.gitMerged ? "✓ merged · " + t.g.gitBase : "○ not merged into " + t.g.gitBase
    tone: t.g.gitMerged ? t.fleet.green : t.view.dim
    tip: t.g.gitMerged ? (t.g.gitBranch === t.g.gitBase ? "The work is on " + t.g.gitBase + "."
                                                         : t.g.gitBranch + " is merged into " + t.g.gitBase + ".")
                       : (t.g.gitBranch || "HEAD") + " isn't merged into " + t.g.gitBase + " yet."
  }
  Tick {
    visible: t.g.gitDirty > 0
    label: "● " + t.g.gitDirty + " uncommitted"
    tone: t.fleet.yellow
    tip: t.g.gitDirty + " tracked file(s) have changes that aren't committed, so they're neither merged nor pushed."
  }
  Tick {
    label: t.pushing ? "◌ pushing " + (t.g.gitTarget || "") + "…"
         : t.g.gitPushed ? "✓ pushed · " + t.g.gitRemote
         : t.failed ? "✗ push failed · retry"
         : t.g.gitRemote === "" ? "↑ no remote · push"
         : "↑ push " + t.g.gitTarget + " to " + t.g.gitRemote
    tone: t.pushing ? t.fleet.cyan : t.g.gitPushed ? t.fleet.green : t.failed ? t.fleet.red : t.fleet.yellow
    clickable: !t.pushing && !t.g.gitPushed
    tip: t.g.gitPushed ? "Everything here is on " + t.g.gitRemote + "."
       : t.pushing ? "git push " + t.g.gitRemote + " " + t.g.gitTarget
       : (t.g.gitUnpushed > 0 ? t.g.gitUnpushed + " commit(s) exist only on this machine.\n" : "")
         + (t.g.gitRemote === "" ? "This repository has no remote yet." : "Click to push " + t.g.gitTarget + " to " + t.g.gitRemote + ".")
    onClicked: {
      t.justClicked = true
      settle.restart()
      t.view.push(t.g.gitPath, t.g.gitTarget, t.g.gitRemote)
    }
  }
  Text {
    visible: t.failed && t.g.gitPushMsg !== ""
    width: t.width
    text: t.g.gitPushMsg
    color: t.fleet.red
    font.family: t.view.fontFamily
    font.pixelSize: Style.font.bodySmall
    wrapMode: Text.Wrap
  }
}
