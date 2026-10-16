import QtQuick
import qs.Ui
import "util.js" as U

// The run's ticket graph. Layout is computed once per set of tickets so nodes never jump around;
// state changes only recolor.
Canvas {
  id: dag
  property var tickets: []
  property var laneColors: ({})     // ticket id -> lane color for running tickets
  property color fg: "white"
  property color dim: "gray"
  property color line: "#55888888"
  property color bg: "black"
  property color green: "green"
  property color red: "red"
  property color accent: "blue"
  property string fontFamily: "monospace"
  property real colW: 76
  property real rowH: 34

  readonly property string shapeKey: JSON.stringify((tickets || []).map(function(t) { return [t.id, t.blockedBy] }))
  property var layout: null
  onShapeKeyChanged: { layout = U.dagLayout(tickets || []); requestPaint() }
  onTicketsChanged: requestPaint()
  onLaneColorsChanged: requestPaint()

  implicitWidth: layout ? 44 + (layout.cols - 1) * colW : 0
  implicitHeight: layout ? 44 + (layout.rows - 1) * rowH : 0

  function xy(id) {
    var p = layout.pos[id]
    return [22 + p.col * colW, 28 + p.row * rowH]
  }

  function colorFor(t) {
    if (t.state === "merged") return green
    if (t.state === "attn") return red
    if (t.state === "killed") return dim
    if (["running", "testing", "review", "ready", "merging", "conflict"].indexOf(t.state) >= 0)
      return laneColors[t.id] || accent
    return dim
  }

  onPaint: {
    var ctx = getContext("2d")
    ctx.reset()
    if (!layout) return
    var byId = {}
    tickets.forEach(function(t) { byId[t.id] = t })
    ctx.lineWidth = 1.3
    layout.chains.forEach(function(c) {
      ctx.strokeStyle = byId[c.from] && byId[c.from].state === "merged" ? Qt.rgba(green.r, green.g, green.b, 0.55) : line
      ctx.beginPath()
      var p0 = xy(c.chain[0])
      ctx.moveTo(p0[0], p0[1])
      for (var i = 1; i < c.chain.length; i++) {
        var a = xy(c.chain[i - 1]), b = xy(c.chain[i]), mx = (a[0] + b[0]) / 2
        ctx.bezierCurveTo(mx, a[1], mx, b[1], b[0], b[1])
      }
      ctx.stroke()
    })
    tickets.forEach(function(t) {
      var p = xy(t.id), c = colorFor(t)
      var live = c !== dim && t.state !== "merged"
      if (live) {
        ctx.fillStyle = Qt.rgba(c.r, c.g, c.b, 0.2)
        ctx.beginPath(); ctx.arc(p[0], p[1], 10, 0, Math.PI * 2); ctx.fill()
      }
      var hollow = t.state === "wait" || t.state === "killed"
      ctx.fillStyle = hollow ? bg : c
      ctx.strokeStyle = c
      ctx.lineWidth = 1.8
      ctx.beginPath(); ctx.arc(p[0], p[1], 6, 0, Math.PI * 2); ctx.fill(); ctx.stroke()
      ctx.fillStyle = live ? fg : dim
      ctx.font = "500 11.5px '" + fontFamily + "'"
      ctx.textAlign = "center"
      ctx.fillText(t.id, p[0], p[1] - 11)
    })
  }

  // Hover: a tooltip naming the ticket under the pointer (floating, so nothing reflows).
  // Click: open that ticket's session in a terminal, while it still has one.
  signal ticketClicked(var ticket)
  property var hovered: null
  property point hoverAt: Qt.point(0, 0)
  function hit(x, y) {
    var found = null
    if (layout) tickets.forEach(function(t) {
      var p = xy(t.id)
      if (Math.abs(p[0] - x) < 10 && Math.abs(p[1] - y) < 10) found = t
    })
    return found
  }
  MouseArea {
    id: area
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: dag.hovered && dag.hovered.short ? Qt.PointingHandCursor : Qt.ArrowCursor
    onPositionChanged: function(m) {
      var t = dag.hit(m.x, m.y)
      if (t) dag.hoverAt = Qt.point(dag.xy(t.id)[0], dag.xy(t.id)[1])
      dag.hovered = t
    }
    onExited: dag.hovered = null
    onClicked: function(m) { var t = dag.hit(m.x, m.y); if (t && t.short) dag.ticketClicked(t) }
  }
  PanelToolTip {
    visible: !!dag.hovered
    delay: 0
    x: dag.hoverAt.x + 14
    y: dag.hoverAt.y + 10
    text: dag.hovered ? "#" + dag.hovered.id + " " + dag.hovered.title + " · " + dag.hovered.state
                        + (dag.hovered.short ? "\nclick to open its terminal" : "") : ""
    fontFamily: dag.fontFamily
  }
}
