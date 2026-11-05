import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import "util.js" as U

// One Markdown file, rendered and kept current. `/skill` mentions copy themselves when clicked; other links open.
Text {
  id: md
  property var view
  property string path: ""
  property var skills: []      // installed skill names; empty leaves `/skill` mentions as they are
  property string raw: ""

  FileView {
    path: md.path
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: md.raw = text()
    onLoadFailed: md.raw = "*Can't read " + md.path + "*"
  }

  text: md.skills.length ? U.skillLinks(raw, md.skills) : raw
  textFormat: Text.MarkdownText
  wrapMode: Text.Wrap
  color: view.fg
  linkColor: view.fleet.accent
  font.family: view.fontFamily
  font.pixelSize: Style.font.body
  onLinkActivated: function(link) {
    if (link.indexOf("skill:") === 0) {
      Quickshell.execDetached(["wl-copy", link.slice(6)])
      view.toast("Copied " + link.slice(6), false)
    } else {
      Qt.openUrlExternally(link)
    }
  }
  MouseArea {
    anchors.fill: parent
    acceptedButtons: Qt.NoButton
    cursorShape: md.hoveredLink ? Qt.PointingHandCursor : Qt.ArrowCursor
  }
}
