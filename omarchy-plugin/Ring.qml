import QtQuick

// Context-window gauge: an arc that fills with use, drawn in `tone`.
Canvas {
  id: ring
  property real value: 0
  property color track: "#33ffffff"
  property color tone: "#7aa2f7"

  implicitWidth: 18
  implicitHeight: 18
  onValueChanged: requestPaint()
  onToneChanged: requestPaint()
  onTrackChanged: requestPaint()

  onPaint: {
    var ctx = getContext("2d")
    ctx.reset()
    var r = Math.min(width, height) / 2 - 2
    ctx.lineWidth = 2.5
    ctx.strokeStyle = track
    ctx.beginPath()
    ctx.arc(width / 2, height / 2, r, 0, Math.PI * 2)
    ctx.stroke()
    if (value > 0) {
      ctx.strokeStyle = tone
      ctx.lineCap = "round"
      ctx.beginPath()
      ctx.arc(width / 2, height / 2, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * Math.min(1, value))
      ctx.stroke()
    }
  }
}
