import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import qs.Commons
import qs.Ui
import "util.js" as U

// Fleet: every Claude agent on the machine as a live tree, in a calendar-style dropdown from the bar.
Panel {
  id: root
  moduleName: "patrick.ai-fleet"
  ipcTarget: "patrick.ai-fleet"

  readonly property color fg: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(fg, 1.55)
  readonly property color surface: Color.popups.background
  readonly property color surfaceDeep: Qt.darker(surface, 1.25)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  property alias fleet: fleetModel
  Fleet { id: fleetModel }

  // ---- view state that must survive state.json updates
  property var expandOverrides: ({})
  property string focusedKey: ""
  property string confirmKill: ""
  property bool typing: false
  property var rowIndex: ({})     // key -> row object, for keyboard actions
  property var order: []          // visible row keys, top to bottom
  property var rowItems: ({})     // key -> AgentRow item, for scrolling the focused row into view
  signal layoutChanged()

  readonly property int attentionCount: fleet.attention.length
  // bar icon: red when something needs you or an agent is over 350k context, then orange, green while
  // anything runs, gray when nothing does
  readonly property string worstBand: U.worstBand(fleet.runs.map(function(r) { return r.tree }).filter(Boolean).concat(fleet.sessions))
  readonly property color iconColor: attentionCount > 0 || worstBand === "hot" ? fleet.red
                                   : worstBand === "warn" || limited ? fleet.orange
                                   : worstBand === "ok" ? fleet.green : dim
  readonly property var activeRuns: fleet.runs.filter(function(r) { return ["active", "paused"].indexOf(r.status) >= 0 })
  readonly property int implementorsRunning: {
    var n = 0
    fleet.runs.forEach(function(r) { (r.tickets || []).forEach(function(t) {
      if (["running", "testing", "review"].indexOf(t.state) >= 0) n++ }) })
    return n
  }
  readonly property int ticketsDone: activeRuns.reduce(function(a, r) { return a + (r.tickets || []).filter(function(t) { return t.state === "merged" }).length }, 0)
  readonly property int ticketsTotal: activeRuns.reduce(function(a, r) { return a + (r.tickets || []).length }, 0)

  // ---- account usage limit: the daemon reads it from the statusline input of any session
  readonly property var usage: fleet.usage
  readonly property bool limited: !!usage.limited
  readonly property int limitStopped: usage.stopped || 0
  function clock(ts) { return ts ? Qt.formatTime(new Date(ts * 1000), "HH:mm") : "?" }

  function runById(id) {
    for (var i = 0; i < fleet.runs.length; i++) if (fleet.runs[i].id === id) return fleet.runs[i]
    return null
  }

  // Lanes keep one color per ticket for the life of a run: implementors cycle the theme's accents,
  // the merger is neutral, the fixer is yellow, the daemon's base-branch checks are cyan.
  readonly property var lanePalette: [fleet.accent, fleet.magenta, fleet.green, fleet.cyan]
  function laneColorForTicket(run, ticketId) {
    var ts = run ? run.tickets || [] : []
    for (var i = 0; i < ts.length; i++) if (ts[i].id === ticketId) return String(lanePalette[i % lanePalette.length])
    return String(fleet.accent)
  }
  function laneFor(run, node) {
    if (node.kind === "fixer") return String(fleet.yellow)
    if (node.kind === "merger") return String(fg)
    if (node.kind === "check" && !node.ticket) return String(fleet.cyan)
    if (node.ticket) return laneColorForTicket(run, node.ticket)
    return String(fleet.accent)
  }
  function laneColorsFor(run) {
    var out = {}
    if (run) (run.tickets || []).forEach(function(t) { out[t.id] = laneColorForTicket(run, t.id) })
    return out
  }
  function runRows(run) {
    var rows = U.flattenRun(run, expandOverrides, function(n) { return laneFor(run, n) })
    rows.forEach(function(r) { rowIndex[r.key] = r })
    return rows
  }

  ListModel { id: runsModel }
  ListModel { id: sessionRows }
  ListModel { id: attentionModel }

  function rebuild() {
    U.syncModel(runsModel, fleet.runs.map(function(r) { return { key: r.id } }))
    var idx = 0
    var sess = U.flattenSessions(fleet.sessions, expandOverrides, function(s) {
      return String(lanePalette[(idx++) % lanePalette.length])
    })
    U.syncModel(sessionRows, sess)
    U.syncModel(attentionModel, fleet.attention.map(function(a) {
      return {
        key: a.id, type: a.type || "", who: a.who || "", where: a.where || "", msg: a.msg || "",
        why: a.why || "", output: a.output || "", qid: a.qid || "", run: a.run || "",
        ticket: String(a.ticket || ""), session: a.session || "",
        questionsJson: JSON.stringify(a.questions || []), quotesJson: JSON.stringify(a.quotes || [])
      }
    }))
    var keys = []
    fleet.runs.forEach(function(r) { if (r.status !== "queued") runRows(r).forEach(function(x) { keys.push(x.key) }) })
    sess.forEach(function(x) { keys.push(x.key); rowIndex[x.key] = x })
    order = keys
    layoutChanged()
  }
  Connections { target: root.fleet; function onStateChanged() { root.rebuild() } }

  function toggleExpand(key, current) {
    var o = Object.assign({}, expandOverrides)
    o[key] = !current
    expandOverrides = o
    rebuild()
  }
  function focusRow(key) { focusedKey = key; confirmKill = ""; keyCatcher.forceActiveFocus() }
  function moveFocus(d) {
    if (!order.length) return
    var i = order.indexOf(focusedKey)
    i = i < 0 ? (d > 0 ? 0 : order.length - 1) : Math.max(0, Math.min(order.length - 1, i + d))
    focusedKey = order[i]
    confirmKill = ""
    closeMenu()
  }
  function focused() { return rowIndex[focusedKey] || null }

  function openRow(row) { if (U.canOpen(row)) { fleet.open(row.short); toast("Opened a terminal on " + row.short + ". Closing it leaves the agent running.", false) } }
  function kill(row) {
    confirmKill = ""
    var run = row.kind === "orchestrator" && row.runId ? runById(row.runId) : null
    if (run && ["done", "aborted"].indexOf(run.status) >= 0) return closeRun(run)
    if (row.kind === "implementor" && row.runId && row.ticket) fleet.run(["kill", row.runId, row.ticket], "Killed #" + row.ticket + ". Worktree kept.")
    else if (row.short) fleet.run(["stop", row.short], "Stopped " + row.short)
  }
  function retry(row) { if (row.runId && row.ticket) fleet.run(["retry", row.runId, row.ticket], "Retrying #" + row.ticket) }

  // ---- right-click menu on a row: open, retry, kill (kill asks first, inside the menu)
  property var menuRow: null
  property string menuKey: ""
  property bool menuConfirm: false
  property real menuX: 0
  property real menuY: 0
  function killable(row) {
    return U.canOpen(row) && row.state !== "killed" && (row.alive || ["run", "attn", "wait"].indexOf(row.state) >= 0)
  }
  function killLabel(row) {
    var run = row.kind === "orchestrator" && row.runId ? runById(row.runId) : null
    return run && ["done", "aborted"].indexOf(run.status) >= 0 ? "Close run" : "Kill"
  }
  function menuItems(row) {
    var out = []
    if (U.canOpen(row) && row.state !== "killed") out.push({ label: "Open in terminal", hint: "o", act: "open" })
    if (row.kind === "implementor" && (row.state === "killed" || row.state === "attn")) out.push({ label: "Retry", hint: "r", act: "retry" })
    if (killable(row)) out.push({ label: killLabel(row) + "…", hint: "x", act: "confirm", danger: true })
    return out
  }
  function confirmItems(row) {
    return [{ label: killLabel(row) + " " + row.name + (row.tag ? " " + row.tag : ""), hint: "y", act: "kill", danger: true },
            { label: "Keep", hint: "esc", act: "keep" }]
  }
  // x, y in `item`'s coordinates; `confirm` opens straight at the kill question (the x key)
  function openMenu(row, item, x, y, confirm) {
    if (!row || !(confirm ? killable(row) : menuItems(row).length)) return
    var p = item.mapToItem(keyCatcher, x, y)
    menuX = p.x; menuY = p.y
    menuRow = row; menuKey = row.key; menuConfirm = !!confirm
    keyCatcher.forceActiveFocus()
  }
  function openMenuAtRow(row, confirm) {
    var item = rowItems[row.key]
    if (item) openMenu(row, item, Style.space(40), item.height / 2, confirm)
  }
  function closeMenu() { menuRow = null; menuKey = ""; menuConfirm = false }
  function menuAct(act) {
    var row = menuRow
    if (!row) return
    if (act === "confirm") { menuConfirm = true; return }
    closeMenu()
    if (act === "open") openRow(row)
    else if (act === "retry") retry(row)
    else if (act === "kill") kill(row)
  }
  // A finished run leaves the panel; its orchestrator is stopped if it's still around.
  function closeRun(run) { fleet.run(["close", run.id], "Closed " + run.name) }
  // A failed push toasts the daemon's reason, and GitTicks keeps showing it under the row.
  function push(path, target, remote) {
    if (!path) return
    toast("Pushing " + target + (remote ? " to " + remote : "") + "…", false)
    fleet.run(["push", path], "Pushed " + target + (remote ? " to " + remote : ""), undefined, "Push failed")
  }

  // ---- toast
  property string toastText: ""
  property bool toastError: false
  function toast(text, error) { toastText = text; toastError = !!error; toastTimer.restart() }
  Connections { target: root.fleet; function onToast(text, error) { root.toast(text, error) } }
  Timer { id: toastTimer; interval: 4200; onTriggered: root.toastText = "" }

  // AI summaries are pulled: the daemon only asks Haiku while this says someone is looking.
  Timer {
    interval: 5000
    repeat: true
    triggeredOnStart: true
    running: root.opened && root.fleet.summaries === "ai"
    onTriggered: Quickshell.execDetached([root.fleet.fleetBin, "viewing"])
  }

  implicitWidth: barButton.implicitWidth
  implicitHeight: barButton.implicitHeight

  onOpenedChanged: if (opened) {
    confirmKill = ""
    closeMenu()
    rebuild()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  // ---- bar button: robot glyph, running implementors, tickets merged, red badge when something needs you
  Item {
    id: barButton
    anchors.fill: parent
    implicitWidth: barRow.implicitWidth + Style.space(8)
    implicitHeight: icon.implicitHeight
    Row {
      id: barRow
      anchors.centerIn: parent
      spacing: Style.space(4)
      BarIconButton {
        id: icon
        bar: root.bar
        active: root.attentionCount > 0
        iconComponent: Component {
          Item {
            FleetIcon {
              anchors.centerIn: parent
              size: Style.space(14)
              color: root.iconColor
            }
          }
        }
        onPressed: function(code) { root.toggle() }
      }
      Text {
        anchors.verticalCenter: parent.verticalCenter
        visible: root.implementorsRunning > 0 || root.ticketsTotal > 0
        text: root.implementorsRunning + (root.ticketsTotal ? " · " + root.ticketsDone + "/" + root.ticketsTotal : "")
        color: root.fg
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        MouseArea { anchors.fill: parent; onClicked: root.toggle() }
      }
    }
    Rectangle {
      visible: root.attentionCount > 0
      anchors.right: barRow.left
      anchors.rightMargin: -width - Style.space(2) + icon.width
      y: Style.space(1)
      width: Math.max(height, badgeText.implicitWidth + Style.space(6))
      height: badgeText.implicitHeight + 1
      radius: height / 2
      color: root.fleet.red
      Text {
        id: badgeText
        anchors.centerIn: parent
        text: root.attentionCount
        color: root.surface
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption - 1
        font.bold: true
      }
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: barButton
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(1140))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(1400))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: root.typing

      onMoveRequested: function(dx, dy) {
        if (dy !== 0) {
          root.moveFocus(dy)
          var item = root.rowItems[root.focusedKey]
          if (item) flick.ensureVisible(item)
        }
        var row = root.focused()
        if (dx !== 0 && row && row.hasKids && (dx > 0) !== row.expanded) root.toggleExpand(row.key, row.expanded)
      }
      onActivateRequested: {
        if (root.menuConfirm) return root.menuAct("kill")
        var row = root.focused(); if (row && row.hasKids) root.toggleExpand(row.key, row.expanded)
      }
      onDeleteRequested: {
        var row = root.focused()
        if (row && root.menuConfirm && root.menuKey === row.key) root.closeMenu()
        else if (row) root.openMenuAtRow(row, true)
      }
      onCloseRequested: root.menuRow ? root.closeMenu() : root.confirmKill !== "" ? root.confirmKill = "" : root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) {
        var row = root.focused()
        if (!row) return
        if (t === "o") root.openRow(row)
        else if (t === "r" && row.kind === "implementor") root.retry(row)
        else if (t === "y" && root.menuConfirm && root.menuKey === row.key) root.menuAct("kill")
      }

      Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        function ensureVisible(item) {
          var p = item.mapToItem(column, 0, 0)
          if (p.y < contentY) contentY = Math.max(0, p.y - Style.space(8))
          else if (p.y + item.height > contentY + height) contentY = Math.min(contentHeight - height, p.y + item.height - height + Style.space(8))
        }

        ColumnLayout {
          id: column
          width: flick.width
          spacing: Style.space(6)

          // ---- header
          RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Style.space(14)
            Layout.rightMargin: Style.space(14)
            Layout.topMargin: Style.space(6)
            spacing: Style.space(14)
            ColumnLayout {
              Layout.fillWidth: true
              Layout.minimumWidth: Style.space(160)
              spacing: Style.space(4)
              RowLayout {
                spacing: Style.space(8)
                FleetIcon { size: Style.space(16); stroke: 1.5; color: root.fleet.accent; Layout.alignment: Qt.AlignVCenter }
                Text { text: "F L E E T"; color: root.fg; font.family: root.fontFamily; font.pixelSize: Style.font.subtitle; font.bold: true }
              }
              Text {
                text: {
                  var agents = 0
                  function walk(n) { if (U.hasCtx(n) && ["run", "attn", "wait"].indexOf(n.state) >= 0) agents++; (n.children || []).forEach(walk) }
                  root.fleet.runs.forEach(function(r) { if (r.tree) walk(r.tree) })
                  root.fleet.sessions.forEach(walk)
                  return agents + " agents live · " + root.implementorsRunning + "/" + (root.activeRuns.length * (root.fleet.limits.implementors_per_orchestrator || 0))
                    + " implementors · " + root.ticketsDone + "/" + root.ticketsTotal + " merged"
                }
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
              }
              // account usage, as in Claude Code's /usage: the 5-hour session window, then the week
              RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: Style.space(2)
                spacing: Style.space(14)
                UsageBar { Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Session"; window: root.usage.five_hour || {}; view: root }
                UsageBar { Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Week"; window: root.usage.seven_day || {}; view: root }
              }
            }
            Stepper {
              Layout.alignment: Qt.AlignTop
              label: "Orchestrators"; value: root.fleet.limits.orchestrators || 0; view: root
              onChange: function(v) { root.fleet.run(["limits", "--orchestrators", String(v)], "Max orchestrators: " + v) }
            }
            Stepper {
              Layout.alignment: Qt.AlignTop
              label: "/implement each"; value: root.fleet.limits.implementors_per_orchestrator || 0; view: root
              onChange: function(v) { root.fleet.run(["limits", "--per", String(v)], "Max implementors per orchestrator: " + v) }
            }
            Row {
              Layout.alignment: Qt.AlignTop
              spacing: 0
              SmallButton {
                text: "Tool calls"; font: root.fontFamily
                tone: root.fleet.summaries === "tool" ? root.fg : root.dim
                primary: root.fleet.summaries === "tool"; ink: root.surface
                onClicked: root.fleet.run(["limits", "--summaries", "tool"], "Status lines from tool calls")
              }
              SmallButton {
                text: "✦ AI summary"; font: root.fontFamily
                tone: root.fleet.summaries === "ai" ? root.fleet.magenta : root.dim
                primary: root.fleet.summaries === "ai"; ink: root.surface
                onClicked: root.fleet.run(["limits", "--summaries", "ai"], "AI summaries on: Haiku rewrites status lines every 20s")
              }
            }
          }

          Banner {
            Layout.fillWidth: true
            visible: root.fleet.stale
            text: "The ai-fleet daemon isn't answering. Start it with: systemctl --user start ai-fleet"
            tone: root.fleet.red; font: root.fontFamily
          }

          // ---- usage limit: agents stopped by it, and the button that resumes them
          Rectangle {
            id: limitBox
            Layout.fillWidth: true
            Layout.leftMargin: Style.space(14)
            Layout.rightMargin: Style.space(14)
            visible: root.limited || root.limitStopped > 0
            readonly property color tone: root.limited ? root.fleet.orange : root.fleet.green
            implicitHeight: limitRow.implicitHeight + Style.space(10)
            radius: 3
            color: Qt.rgba(tone.r, tone.g, tone.b, 0.09)
            border.color: Qt.rgba(tone.r, tone.g, tone.b, 0.3)
            border.width: 1
            RowLayout {
              id: limitRow
              anchors.verticalCenter: parent.verticalCenter
              x: Style.space(10)
              width: parent.width - 2 * x
              spacing: Style.space(10)
              Text {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                color: limitBox.tone
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                text: root.limited
                  ? "Usage limit reached · resets " + root.clock(root.usage.until) + ". "
                    + root.limitStopped + " agent" + (root.limitStopped === 1 ? "" : "s") + " stopped; no new tickets start until then."
                  : "Usage limit has reset. " + root.limitStopped + " agent" + (root.limitStopped === 1 ? " is" : "s are") + " waiting to continue."
              }
              SmallButton {
                visible: root.limitStopped > 0
                text: "▶ Continue " + root.limitStopped + (root.limitStopped === 1 ? " agent" : " agents")
                font: root.fontFamily
                tone: root.limited ? root.dim : root.fleet.green
                primary: !root.limited
                ink: root.surface
                onClicked: root.fleet.run(["continue"], "Resumed agents stopped by the usage limit")
              }
            }
          }

          // ---- needs you
          RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Style.space(14)
            Layout.rightMargin: Style.space(14)
            Layout.topMargin: Style.space(4)
            visible: attentionModel.count > 0
            spacing: Style.space(8)
            Text { text: "NEEDS YOU · " + attentionModel.count; color: root.fleet.red; font.family: root.fontFamily; font.pixelSize: Style.font.caption; font.letterSpacing: 2 }
            Rectangle { Layout.fillWidth: true; height: 1; color: Qt.rgba(root.fleet.red.r, root.fleet.red.g, root.fleet.red.b, 0.35) }
          }
          Repeater {
            model: attentionModel
            AttentionCard {
              required property var model
              Layout.fillWidth: true
              Layout.leftMargin: Style.space(14)
              Layout.rightMargin: Style.space(14)
              item: model
              view: root
            }
          }

          // ---- runs
          Repeater {
            model: runsModel
            ColumnLayout {
              required property var model
              Layout.fillWidth: true
              spacing: 0
              Rectangle { Layout.fillWidth: true; Layout.topMargin: Style.space(6); height: 1; color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.1) }
              Run { Layout.fillWidth: true; runId: model.key; view: root }
            }
          }

          // ---- your sessions
          RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Style.space(14)
            Layout.rightMargin: Style.space(14)
            Layout.topMargin: Style.space(10)
            visible: sessionRows.count > 0
            spacing: Style.space(8)
            Text { text: "YOUR SESSIONS"; color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption; font.letterSpacing: 2 }
            Rectangle { Layout.fillWidth: true; height: 1; color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.1) }
          }
          ColumnHeader {
            Layout.fillWidth: true
            Layout.rightMargin: Style.space(10)
            visible: sessionRows.count > 0
            view: root
          }
          Repeater {
            model: sessionRows
            AgentRow {
              required property var model
              Layout.fillWidth: true
              row: model
              view: root
            }
          }

          Text {
            Layout.fillWidth: true
            Layout.margins: Style.space(14)
            visible: !root.fleet.stale && runsModel.count === 0 && sessionRows.count === 0
            text: "Nothing running. Start a run with /implement-orchestrator in a repo, or `fleet cc` for a session that keeps running after you close its terminal."
            wrapMode: Text.Wrap
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
          }

          // ---- footer
          Rectangle { Layout.fillWidth: true; Layout.topMargin: Style.space(8); height: 1; color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.1) }
          RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Style.space(14)
            Layout.rightMargin: Style.space(14)
            Layout.bottomMargin: Style.space(4)
            Text {
              Layout.fillWidth: true
              text: root.toastText !== "" ? root.toastText : "j/k move   l/h expand   o open in terminal   x kill   r retry   esc close"
              color: root.toastText !== "" ? (root.toastError ? root.fleet.red : root.fleet.accent) : root.dim
              elide: Text.ElideRight
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
            }
            Text {
              text: root.fleet.stale ? "daemon down" : "nothing is ever pushed"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
        }
      }

      // ---- the row menu, above everything; a click anywhere outside it closes it
      MouseArea {
        anchors.fill: parent
        visible: root.menuRow !== null
        acceptedButtons: Qt.AllButtons
        onPressed: root.closeMenu()
        onWheel: function(wheel) { root.closeMenu() }
      }
      Rectangle {
        id: rowMenu
        visible: root.menuRow !== null
        readonly property var entries: !root.menuRow ? []
            : root.menuConfirm ? root.confirmItems(root.menuRow) : root.menuItems(root.menuRow)
        width: Style.space(260)
        height: menuList.implicitHeight + Style.space(10)
        x: Math.max(Style.space(4), Math.min(root.menuX, parent.width - width - Style.space(4)))
        y: Math.max(Style.space(4), Math.min(root.menuY, parent.height - height - Style.space(4)))
        radius: Style.space(6)
        color: root.surface
        border.color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.18)
        border.width: 1
        Column {
          id: menuList
          x: Style.space(5); y: Style.space(5)
          width: parent.width - Style.space(10)
          Repeater {
            model: rowMenu.entries
            Rectangle {
              required property var modelData
              width: menuList.width
              height: Style.space(30)
              radius: Style.space(4)
              color: entryArea.containsMouse
                  ? (modelData.danger ? Qt.rgba(root.fleet.red.r, root.fleet.red.g, root.fleet.red.b, 0.16)
                                      : Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.09))
                  : "transparent"
              RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Style.space(10)
                anchors.rightMargin: Style.space(10)
                spacing: Style.space(10)
                Text {
                  Layout.fillWidth: true
                  text: modelData.label
                  elide: Text.ElideRight
                  color: modelData.danger ? root.fleet.red : root.fg
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                }
                Text {
                  text: modelData.hint || ""
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }
              MouseArea {
                id: entryArea
                anchors.fill: parent
                hoverEnabled: true
                onClicked: root.menuAct(modelData.act)
              }
            }
          }
        }
      }
    }
  }
}
