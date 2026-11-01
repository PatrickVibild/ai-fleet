import QtQuick
import QtQuick.Layouts
import qs.Commons
import "util.js" as U

// Line chart on one y axis, x in epochs. series: [{ name, color, points: [[x, y], ...] }].
// `compact` is the row's sparkline: no axes, legend or hover.
Item {
  id: c
  property var view
  property string title: ""
  property var series: []
  property real xMax: 0
  property bool compact: false

  readonly property var live: (series || []).filter(function(s) { return s.points && s.points.length })
  readonly property int padL: compact ? 1 : Style.space(44)
  readonly property int padR: compact ? 3 : Style.space(10)
  readonly property int padT: compact ? 2 : Style.space(6)
  readonly property int padB: compact ? 2 : Style.space(18)
  readonly property var bounds: {
    var lo = Infinity, hi = -Infinity, xs = xMax
    live.forEach(function(s) { s.points.forEach(function(p) {
      lo = Math.min(lo, p[1]); hi = Math.max(hi, p[1]); xs = Math.max(xs, p[0])
    }) })
    if (lo === Infinity) return { lo: 0, hi: 1, x: 1 }
    if (lo === hi) { lo -= 0.5; hi += 0.5 }
    var pad = (hi - lo) * 0.06
    return { lo: lo - pad, hi: hi + pad, x: xs || 1 }
  }
  property real hoverX: -1

  implicitHeight: compact ? Style.space(22) : body.implicitHeight

  function px(x) { return padL + x / bounds.x * (plot.width - padL - padR) }
  function py(y) { return padT + (1 - (y - bounds.lo) / (bounds.hi - bounds.lo)) * (plot.height - padT - padB) }
  function latest(s) { return U.fmtMetric(s.points[s.points.length - 1][1]) }
  // the point of each series closest to the pointer
  function hoverRows() {
    if (hoverX < 0) return []
    var x = (hoverX - padL) / (plot.width - padL - padR) * bounds.x
    return live.map(function(s) {
      var best = s.points[0]
      s.points.forEach(function(p) { if (Math.abs(p[0] - x) < Math.abs(best[0] - x)) best = p })
      return { name: s.name, x: best[0], y: best[1], color: s.color }
    })
  }

  onSeriesChanged: plot.requestPaint()
  onXMaxChanged: plot.requestPaint()
  onHoverXChanged: plot.requestPaint()

  ColumnLayout {
    id: body
    anchors.fill: parent
    spacing: Style.space(3)

    RowLayout {
      visible: !c.compact && (c.title !== "" || c.live.length >= 2)
      Layout.fillWidth: true
      spacing: Style.space(10)
      Text {
        Layout.fillWidth: true
        text: c.title + (c.live.length === 1 ? "  " + c.latest(c.live[0]) : "")
        color: c.view.fg
        elide: Text.ElideRight
        font.family: c.view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }
      Repeater {
        model: c.live.length >= 2 ? c.live : []
        Row {
          required property var modelData
          spacing: Style.space(4)
          Rectangle { width: Style.space(10); height: 2; anchors.verticalCenter: parent.verticalCenter; color: modelData.color }
          Text { text: modelData.name + " " + c.latest(modelData); color: c.view.dim; font.family: c.view.fontFamily; font.pixelSize: Style.font.caption }
        }
      }
    }

    Canvas {
      id: plot
      Layout.fillWidth: true
      Layout.fillHeight: c.compact
      Layout.preferredHeight: c.compact ? -1 : Style.space(130)
      implicitHeight: c.compact ? Style.space(22) : Style.space(130)
      onWidthChanged: requestPaint()
      onHeightChanged: requestPaint()

      onPaint: {
        var g = getContext("2d")
        g.reset()
        g.lineJoin = "round"
        if (!c.compact) {
          g.font = Style.font.caption + "px '" + c.view.fontFamily + "'"
          g.lineWidth = 1
          g.fillStyle = String(c.view.dim)
          g.strokeStyle = Qt.rgba(c.view.fg.r, c.view.fg.g, c.view.fg.b, 0.09)
          g.textBaseline = "middle"
          g.textAlign = "right"
          for (var i = 0; i < 3; i++) {   // recessive grid at the bottom, middle and top of the range
            var v = c.bounds.lo + (c.bounds.hi - c.bounds.lo) * (0.06 + i * 0.44)
            var gy = Math.round(c.py(v)) + 0.5
            g.beginPath(); g.moveTo(c.padL, gy); g.lineTo(width - c.padR, gy); g.stroke()
            g.fillText(U.fmtMetric(v), c.padL - Style.space(5), gy)
          }
          g.textBaseline = "alphabetic"
          g.textAlign = "left"
          g.fillText("0", c.padL, height - 2)
          g.textAlign = "right"
          g.fillText(Math.round(c.bounds.x) + " epochs", width - c.padR, height - 2)
        }
        g.lineWidth = c.compact ? 1.5 : 2
        c.live.forEach(function(s) {
          g.strokeStyle = String(s.color)
          g.beginPath()
          s.points.forEach(function(p, j) {
            if (j === 0) g.moveTo(c.px(p[0]), c.py(p[1]))
            else g.lineTo(c.px(p[0]), c.py(p[1]))
          })
          g.stroke()
          var end = s.points[s.points.length - 1]
          if (s.points.length === 1 || c.compact) {   // a single point draws no line
            g.fillStyle = String(s.color)
            g.beginPath(); g.arc(c.px(end[0]), c.py(end[1]), c.compact ? 1.5 : 4, 0, 2 * Math.PI); g.fill()
          }
        })
        if (c.hoverX >= 0) {
          g.lineWidth = 1
          g.strokeStyle = Qt.rgba(c.view.fg.r, c.view.fg.g, c.view.fg.b, 0.3)
          var rows = c.hoverRows()
          if (rows.length) {
            var cx = Math.round(c.px(rows[0].x)) + 0.5
            g.beginPath(); g.moveTo(cx, c.padT); g.lineTo(cx, height - c.padB); g.stroke()
          }
          rows.forEach(function(r) {
            g.fillStyle = String(r.color)
            g.strokeStyle = String(c.view.surface)
            g.lineWidth = 2
            g.beginPath(); g.arc(c.px(r.x), c.py(r.y), 4, 0, 2 * Math.PI); g.fill(); g.stroke()
          })
        }
      }

      MouseArea {
        anchors.fill: parent
        enabled: !c.compact
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
        onPositionChanged: function(mouse) { c.hoverX = mouse.x >= c.padL ? mouse.x : -1 }
        onExited: c.hoverX = -1
      }

      Rectangle {
        id: tip
        readonly property var rows: c.hoverRows()
        visible: !c.compact && rows.length > 0
        x: c.hoverX + width + Style.space(16) > plot.width ? c.hoverX - width - Style.space(8) : c.hoverX + Style.space(8)
        y: Style.space(4)
        width: tipCol.implicitWidth + Style.space(12)
        height: tipCol.implicitHeight + Style.space(8)
        radius: Style.space(3)
        color: c.view.surface
        border.color: Qt.rgba(c.view.fg.r, c.view.fg.g, c.view.fg.b, 0.2)
        border.width: 1
        Column {
          id: tipCol
          x: Style.space(6); y: Style.space(4)
          Text {
            text: tip.rows.length ? "epoch " + U.fmtMetric(tip.rows[0].x) : ""
            color: c.view.dim
            font.family: c.view.fontFamily
            font.pixelSize: Style.font.caption
          }
          Repeater {
            model: tip.rows
            Text {
              required property var modelData
              text: modelData.name + "  " + U.fmtMetric(modelData.y)
              color: c.view.fg
              font.family: c.view.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
        }
      }
    }
  }
}
