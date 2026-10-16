import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons

// The panel's only window onto ai-fleet: it watches the daemon's state.json and runs `fleet` commands.
// The daemon does all the work; nothing here changes state except through the CLI.
QtObject {
  id: root

  readonly property string home: Quickshell.env("HOME")
  readonly property string stateDir: (Quickshell.env("AI_FLEET_STATE") || ((Quickshell.env("XDG_STATE_HOME") || home + "/.local/state") + "/ai-fleet"))
  readonly property string fleetBin: home + "/.local/bin/fleet"

  property var state: null
  property double nowSec: Date.now() / 1000
  readonly property bool stale: !state || (nowSec - (state.updated || 0)) > 15
  readonly property var runs: state ? state.runs || [] : []
  readonly property var sessions: state ? state.sessions || [] : []
  readonly property var attention: state ? state.attention || [] : []
  readonly property var limits: state ? state.limits || {} : {}
  readonly property var usage: state ? state.usage || {} : {}
  readonly property string summaries: state ? state.summaries || "tool" : "tool"

  // Theme palette beyond the shell's five roles; reread whenever the theme's accent changes.
  property var palette: ({})
  function themeColor(name, fallback) { return palette[name] ? palette[name] : fallback }
  readonly property color green: themeColor("green", "#9ece6a")
  readonly property color yellow: themeColor("yellow", "#e0af68")
  readonly property color orange: themeColor("orange", "#ff9e64")
  readonly property color magenta: themeColor("bright_magenta", themeColor("magenta", "#bb9af7"))
  readonly property color cyan: themeColor("bright_cyan", themeColor("cyan", "#0db9d7"))
  readonly property color red: Color.urgent
  readonly property color accent: Color.accent

  signal toast(string text, bool error)

  property FileView stateFile: FileView {
    path: root.stateDir + "/state.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      try { root.state = JSON.parse(text()) } catch (e) { }
    }
    onLoadFailed: root.state = null
  }

  property FileView colorsFile: FileView {
    path: Color.currentThemePath + "/colors.toml"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.parsePalette(text())
  }
  property Connections themeWatch: Connections {
    target: Color
    function onAccentChanged() { root.colorsFile.reload() }
  }

  function parsePalette(raw) {
    var out = {}
    var lines = String(raw || "").split("\n")
    for (var i = 0; i < lines.length; i++) {
      var m = lines[i].match(/^\s*([A-Za-z0-9_-]+)\s*=\s*["']?(#[0-9A-Fa-f]{6})/)
      if (m) out[m[1]] = m[2]
    }
    palette = out
  }

  property Timer clock: Timer {
    interval: 1000
    repeat: true
    running: true
    onTriggered: root.nowSec = Date.now() / 1000
  }

  // ---- commands --------------------------------------------------------------
  property Component cmdComponent: Component {
    Process {
      id: proc
      property string label: ""
      property string failLabel: label
      property string secret: ""
      property bool hasSecret: false
      stdinEnabled: hasSecret
      stdout: StdioCollector { id: out; waitForEnd: true }
      stderr: StdioCollector { id: err; waitForEnd: true }
      onStarted: if (hasSecret) { write(secret + "\n"); secret = "" }
      onExited: function(code) {
        if (code !== 0) root.toast((failLabel ? failLabel + ": " : "") + (String(err.text || out.text || "failed").trim().split("\n").pop()), true)
        else if (label) root.toast(label, false)
        Qt.callLater(function() { proc.destroy() })
      }
    }
  }

  // run(["kill", run, ticket], "Killed #14"); failLabel prefixes the error toast instead of doneLabel
  function run(args, doneLabel, secret, failLabel) {
    var props = {
      command: [fleetBin].concat(args), label: doneLabel || "",
      hasSecret: secret !== undefined, secret: secret || ""
    }
    if (failLabel !== undefined) props.failLabel = failLabel
    var p = cmdComponent.createObject(root, props)
    p.running = true
  }

  function open(short) { if (short) Quickshell.execDetached([fleetBin, "open", short]) }
}
