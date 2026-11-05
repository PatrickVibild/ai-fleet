import QtQuick
import QtQuick.Layouts
import Quickshell
import qs.Commons
import qs.Ui
import "util.js" as U

// The Todo tab: your todos and reminders (a todo with a due time), each optionally linked to a Markdown file.
// Every change goes through `fleet todo`, which writes todos.json; the panel only watches it.
ColumnLayout {
  id: tab
  property var view
  property var todos: []
  property int editingId: 0      // the todo the fields are editing; 0 means they add a new one
  property string openMd: ""     // the linked file showing in place of the list
  readonly property var shown: U.orderTodos(todos)
  readonly property int doneCount: todos.filter(function(t) { return t.done }).length
  readonly property int openCount: todos.length - doneCount
  spacing: Style.space(6)

  function startEdit(t) {
    editingId = t.id
    textField.text = t.text
    dueField.text = t.due ? Qt.formatDateTime(new Date(t.due * 1000), "yyyy-MM-dd HH:mm") : ""
    mdField.text = t.md || ""
    textField.forceActiveFocus()
  }
  function reset() {
    editingId = 0
    textField.text = ""; dueField.text = ""; mdField.text = ""
  }
  // options as --opt=value, so text that starts with "-" can't be read as a flag
  function submit() {
    var text = textField.text.trim(), due = dueField.text.trim(), md = mdField.text.trim()
    if (!text) return
    if (editingId) {
      view.fleet.run(["todo", "edit", String(editingId), "--text=" + text, due ? "--due=" + due : "--no-due", md ? "--md=" + md : "--no-md"],
                     "Saved", undefined, "Not saved")
    } else {
      var args = ["todo", "add"]
      if (due) args.push("--due=" + due)
      if (md) args.push("--md=" + md)
      view.fleet.run(args.concat(["--", text]), due ? "Reminder set" : "Added", undefined, "Not added")
    }
    reset()
  }
  function toggle(t) { view.fleet.run(["todo", t.done ? "undone" : "done", String(t.id)]) }
  function editInEditor(path) { Quickshell.execDetached(["omarchy-launch-editor", path]) }

  RowLayout {
    Layout.fillWidth: true
    Layout.leftMargin: Style.space(14)
    Layout.rightMargin: Style.space(14)
    Layout.topMargin: Style.space(6)
    spacing: Style.space(8)
    Text { text: "T O D O"; color: view.fg; font.family: view.fontFamily; font.pixelSize: Style.font.subtitle; font.bold: true }
    Text {
      Layout.fillWidth: true
      text: tab.openCount + " open" + (view.fleet.overdue ? " · " + view.fleet.overdue + " overdue" : "")
      color: view.fleet.overdue ? view.fleet.red : view.dim
      font.family: view.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
    SmallButton {
      visible: tab.doneCount > 0 && !tab.openMd
      text: "Clear " + tab.doneCount + " done"; font: view.fontFamily
      tone: view.dim; ink: view.surface
      onClicked: view.fleet.run(["todo", "clear-done"], "Cleared done todos")
    }
  }

  // ---- add, or edit the todo picked from its menu
  RowLayout {
    Layout.fillWidth: true
    Layout.leftMargin: Style.space(14)
    Layout.rightMargin: Style.space(14)
    visible: !tab.openMd
    spacing: Style.space(6)
    TextField {
      id: textField
      Layout.fillWidth: true
      Layout.preferredWidth: 3
      placeholderText: tab.editingId ? "Todo text" : "Add a todo"
      font.family: view.fontFamily
      font.pixelSize: Style.font.bodySmall
      foreground: view.fg
      accent: view.fleet.accent
      onActiveFocusChanged: view.typing = activeFocus
      onAccepted: tab.submit()
      Keys.onEscapePressed: { tab.reset(); view.typing = false; focus = false }
    }
    TextField {
      id: dueField
      Layout.fillWidth: true
      Layout.preferredWidth: 1
      placeholderText: "due: tomorrow 9:00, +2h"
      font.family: view.fontFamily
      font.pixelSize: Style.font.bodySmall
      foreground: view.fg
      accent: view.fleet.accent
      onActiveFocusChanged: view.typing = activeFocus
      onAccepted: tab.submit()
      Keys.onEscapePressed: { tab.reset(); view.typing = false; focus = false }
    }
    TextField {
      id: mdField
      Layout.fillWidth: true
      Layout.preferredWidth: 1.4
      placeholderText: "link: ~/notes/plan.md"
      font.family: view.fontFamily
      font.pixelSize: Style.font.bodySmall
      foreground: view.fg
      accent: view.fleet.accent
      onActiveFocusChanged: view.typing = activeFocus
      onAccepted: tab.submit()
      Keys.onEscapePressed: { tab.reset(); view.typing = false; focus = false }
    }
    SmallButton {
      text: tab.editingId ? "Save" : "Add"; font: view.fontFamily
      primary: true; tone: view.fleet.accent; ink: view.surface
      enabledState: textField.text.trim() !== ""
      onClicked: tab.submit()
    }
    SmallButton {
      visible: tab.editingId !== 0
      text: "Cancel"; font: view.fontFamily
      tone: view.dim; ink: view.surface
      onClicked: tab.reset()
    }
  }

  // ---- the list
  Item { Layout.preferredHeight: Style.space(2); visible: !tab.openMd }
  Repeater {
    model: tab.openMd ? [] : tab.shown
    Rectangle {
      id: entry
      required property var modelData
      readonly property var todo: modelData
      readonly property bool overdue: !todo.done && !!todo.due && todo.due <= view.fleet.nowSec
      Layout.fillWidth: true
      implicitHeight: line.implicitHeight + Style.space(10)
      color: rowArea.containsMouse || tab.editingId === todo.id ? Qt.rgba(view.fg.r, view.fg.g, view.fg.b, 0.05) : "transparent"
      MouseArea {
        id: rowArea
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: function(mouse) {
          if (mouse.button === Qt.RightButton)
            view.openMenu(Object.assign({ key: "todo-" + entry.todo.id, isTodo: true }, entry.todo), rowArea, mouse.x, mouse.y, false)
          else tab.toggle(entry.todo)
        }
      }
      RowLayout {
        id: line
        x: Style.space(14)
        y: Style.space(5)
        width: parent.width - 2 * x
        spacing: Style.space(10)
        Text {
          text: entry.todo.done ? "☑" : "☐"
          color: entry.todo.done ? view.fleet.green : entry.overdue ? view.fleet.red : view.fg
          font.family: view.fontFamily
          font.pixelSize: Style.font.body
        }
        Text {
          Layout.fillWidth: true
          text: entry.todo.text
          wrapMode: Text.Wrap
          font.strikeout: entry.todo.done
          color: entry.todo.done ? view.dim : view.fg
          font.family: view.fontFamily
          font.pixelSize: Style.font.body
        }
        SmallButton {
          visible: !!entry.todo.md
          text: "▤ " + U.baseName(entry.todo.md); font: view.fontFamily
          tone: view.fleet.cyan; ink: view.surface
          onClicked: tab.openMd = entry.todo.md
        }
        Text {
          visible: !!entry.todo.due
          text: entry.todo.due ? (entry.overdue ? "overdue · " : "⏰ ") + U.fmtDue(entry.todo.due, view.fleet.nowSec) : ""
          color: entry.overdue ? view.fleet.red : view.dim
          font.family: view.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
      }
    }
  }

  Text {
    Layout.fillWidth: true
    Layout.margins: Style.space(14)
    visible: !tab.openMd && tab.todos.length === 0
    text: "Nothing to do. Add a todo above, or from anywhere: fleet todo add \"check the eval run\" --due tomorrow --md ~/notes/eval.md. Ask a Claude session to remind you of something and it lands here too."
    wrapMode: Text.Wrap
    color: view.dim
    font.family: view.fontFamily
    font.pixelSize: Style.font.body
  }

  // ---- a linked file, in place of the list
  RowLayout {
    Layout.fillWidth: true
    Layout.leftMargin: Style.space(14)
    Layout.rightMargin: Style.space(14)
    visible: !!tab.openMd
    spacing: Style.space(8)
    SmallButton { text: "← Todos"; font: view.fontFamily; tone: view.fg; ink: view.surface; onClicked: tab.openMd = "" }
    Text {
      Layout.fillWidth: true
      text: tab.openMd.replace(view.fleet.home, "~")
      elide: Text.ElideMiddle
      color: view.dim
      font.family: view.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
    SmallButton { text: "Open in editor"; font: view.fontFamily; tone: view.dim; ink: view.surface; onClicked: tab.editInEditor(tab.openMd) }
  }
  MdView {
    Layout.fillWidth: true
    Layout.leftMargin: Style.space(14)
    Layout.rightMargin: Style.space(14)
    Layout.bottomMargin: Style.space(10)
    visible: !!tab.openMd
    view: tab.view
    path: tab.openMd
    skills: tab.view.fleet.howto.skills || []
  }
}
