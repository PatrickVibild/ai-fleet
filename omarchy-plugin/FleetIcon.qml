import QtQuick

// The Fleet mark: one node branching to two (orchestrator → agents). Drawn on a 16-unit grid.
Canvas {
  id: icon
  property color color: "white"
  property real size: 14
  property real stroke: 1.4
  implicitWidth: size
  implicitHeight: size
  onColorChanged: requestPaint()
  onSizeChanged: requestPaint()

  onPaint: {
    var ctx = getContext("2d")
    ctx.reset()
    var k = width / 16
    ctx.scale(k, k)
    ctx.strokeStyle = color
    ctx.lineWidth = stroke
    ctx.lineCap = "round"
    ctx.lineJoin = "round"
    var nodes = [[8, 3], [3, 12.5], [13, 12.5]]
    nodes.forEach(function(n) { ctx.beginPath(); ctx.arc(n[0], n[1], 1.8, 0, Math.PI * 2); ctx.stroke() })
    ctx.beginPath()
    ctx.moveTo(8, 4.8); ctx.lineTo(8, 8.2)
    ctx.moveTo(8, 8.2); ctx.lineTo(4, 11)
    ctx.moveTo(8, 8.2); ctx.lineTo(12, 11)
    ctx.stroke()
  }
}
