import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// One "needs you" item. `item` is a ListModel entry, so what you type survives state updates.
Rectangle {
  id: card
  required property var item
  required property var view
  readonly property var fleet: view.fleet
  readonly property string type: item.type
  readonly property bool isQuestion: type === "question"
  readonly property bool isSudo: type === "sudo"
  readonly property bool isTicket: ["business_logic", "gave_up", "stopped", "session_ended", "spawn_failed"].indexOf(type) >= 0
  readonly property color tone: isQuestion ? fleet.yellow : isSudo ? fleet.magenta : fleet.red
  readonly property var questions: { try { return JSON.parse(item.questionsJson || "[]") } catch (e) { return [] } }
  readonly property var quotes: { try { return JSON.parse(item.quotesJson || "[]") } catch (e) { return [] } }
  property var picked: ({})

  implicitHeight: col.implicitHeight + Style.space(20)
  radius: 4
  color: Qt.rgba(tone.r, tone.g, tone.b, 0.06)
  border.color: Qt.rgba(tone.r, tone.g, tone.b, 0.35)
  border.width: 1
  Rectangle { width: Style.space(3); height: parent.height; radius: 2; color: card.tone }

  readonly property string kindLabel: ({
    question: "Question", business_logic: "Business logic", gave_up: "Gave up", stopped: "Stopped",
    session_ended: "Session ended", spawn_failed: "Couldn't start", merge_failed: "Merge failed",
    repo: "Merge paused", fixer_gave_up: "Base branch red", fixer_failed: "Fixer failed",
    permission: "Permission", sudo: "Sudo"
  })[type] || type

  function send() {
    if (isQuestion) {
      var answers = {}
      for (var i = 0; i < questions.length; i++) {
        var q = questions[i].question
        var typed = i === 0 ? answerField.text.trim() : ""
        var a = typed !== "" ? typed : (picked[i] || "")
        if (a === "") { answerField.placeholderText = "Pick an option or type an answer first"; answerField.forceActiveFocus(); return }
        answers[q] = a
      }
      fleet.run(["answer", item.qid, "--json", JSON.stringify(answers), "--by", "user"], "Answer sent to #" + item.ticket)
    } else if (isTicket) {
      var note = answerField.text.trim()
      if (note === "") { answerField.placeholderText = "Write a note first, e.g. which side is right"; answerField.forceActiveFocus(); return }
      fleet.run(["sendback", item.run, item.ticket, note], "Sent #" + item.ticket + " back with your note")
    } else if (isSudo) {
      fleet.run(["sudo-answer", item.key], "Password sent", answerField.text)
      answerField.text = ""
    }
  }

  ColumnLayout {
    id: col
    x: Style.space(14); y: Style.space(10)
    width: parent.width - Style.space(26)
    spacing: Style.space(7)

    RowLayout {
      spacing: Style.space(8)
      Text { text: card.kindLabel.toUpperCase(); color: card.tone; font.family: card.view.fontFamily; font.pixelSize: Style.font.caption; font.letterSpacing: 1.4 }
      Text { text: card.item.who; color: card.view.fg; font.family: card.view.fontFamily; font.pixelSize: Style.font.bodySmall; font.bold: true }
      Text { Layout.fillWidth: true; text: card.item.where; elide: Text.ElideRight; color: card.view.dim; font.family: card.view.fontFamily; font.pixelSize: Style.font.bodySmall }
    }

    Text {
      Layout.fillWidth: true
      text: card.item.msg
      wrapMode: Text.Wrap
      color: card.view.fg
      font.family: card.view.fontFamily
      font.pixelSize: Style.font.subtitle
    }
    Text {
      Layout.fillWidth: true
      visible: text !== ""
      text: card.item.why
      wrapMode: Text.Wrap
      color: card.view.dim
      font.family: card.view.fontFamily
      font.pixelSize: Style.font.bodySmall
    }

    // the two sides that disagree
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(8)
      visible: card.quotes.length > 0
      Repeater {
        model: card.quotes
        Rectangle {
          required property var modelData
          width: Math.max(Style.space(240), (col.width - Style.space(8)) / 2 - 1)
          height: qcol.implicitHeight + Style.space(14)
          radius: 3
          color: card.view.surfaceDeep
          border.color: Qt.rgba(card.view.fg.r, card.view.fg.g, card.view.fg.b, 0.15)
          Column {
            id: qcol
            x: Style.space(9); y: Style.space(7)
            width: parent.width - Style.space(18)
            spacing: Style.space(3)
            Text { text: String(modelData[0] || "").toUpperCase(); color: card.view.dim; font.family: card.view.fontFamily; font.pixelSize: Style.font.caption; font.letterSpacing: 1 }
            Text { width: parent.width; text: modelData[1] || ""; wrapMode: Text.Wrap; color: card.view.fg; font.family: card.view.fontFamily; font.pixelSize: Style.font.bodySmall }
          }
        }
      }
    }

    // failing output, when there is some and no quotes already explain it
    Text {
      Layout.fillWidth: true
      visible: card.item.output !== "" && card.quotes.length === 0
      text: card.item.output.split("\n").slice(-6).join("\n")
      color: card.view.dim
      wrapMode: Text.Wrap
      maximumLineCount: 6
      elide: Text.ElideRight
      font.family: card.view.fontFamily
      font.pixelSize: Style.font.caption
    }

    // question options
    Repeater {
      model: card.isQuestion ? card.questions : []
      ColumnLayout {
        id: qblock
        required property var modelData
        required property int index
        spacing: Style.space(4)
        Text { visible: card.questions.length > 1; text: modelData.question; color: card.view.fg; font.family: card.view.fontFamily; font.pixelSize: Style.font.bodySmall }
        Flow {
          Layout.fillWidth: true
          spacing: Style.space(6)
          Repeater {
            model: modelData.options || []
            SmallButton {
              required property var modelData
              text: modelData.label
              tone: card.picked[qblock.index] === modelData.label ? card.fleet.accent : card.view.fg
              font: card.view.fontFamily
              onClicked: {
                var p = Object.assign({}, card.picked)
                p[qblock.index] = modelData.label
                card.picked = p
              }
            }
          }
        }
      }
    }

    RowLayout {
      Layout.fillWidth: true
      spacing: Style.space(6)
      TextField {
        id: answerField
        Layout.fillWidth: true
        visible: card.isQuestion || card.isTicket || card.isSudo
        password: card.isSudo
        placeholderText: card.isQuestion ? "Or type your own answer" : card.isSudo ? "Password for sudo" : "Note for the implementor, e.g. the ticket is right, fix the test"
        font.family: card.view.fontFamily
        font.pixelSize: Style.font.bodySmall
        foreground: card.view.fg
        accent: card.fleet.accent
        onActiveFocusChanged: card.view.typing = activeFocus
        onAccepted: card.send()
      }
      SmallButton {
        visible: card.isQuestion
        text: "Send"; primary: true; tone: card.fleet.accent; ink: card.view.surface; font: card.view.fontFamily
        onClicked: card.send()
      }
      SmallButton {
        visible: card.isTicket
        text: "Send back"; primary: true; tone: card.fleet.accent; ink: card.view.surface; font: card.view.fontFamily
        onClicked: card.send()
      }
      SmallButton {
        visible: card.isSudo
        text: "Approve"; primary: true; tone: card.fleet.magenta; ink: card.view.surface; font: card.view.fontFamily
        onClicked: card.send()
      }
      SmallButton {
        visible: card.isSudo
        text: "Deny"; tone: card.fleet.red; font: card.view.fontFamily
        onClicked: card.fleet.run(["sudo-answer", card.item.key, "--deny"], "Denied")
      }
      SmallButton {
        visible: card.isTicket || card.type === "merge_failed"
        text: card.type === "merge_failed" ? "Retry merge" : "Retry fresh"
        tone: card.view.fg; font: card.view.fontFamily
        onClicked: card.fleet.run(["retry", card.item.run, card.item.ticket], "Retrying #" + card.item.ticket)
      }
      SmallButton {
        visible: card.type === "repo"
        text: "Resume run"; primary: true; tone: card.fleet.accent; ink: card.view.surface; font: card.view.fontFamily
        onClicked: card.fleet.run(["resume", card.item.run], "Resumed")
      }
      SmallButton {
        visible: card.item.session !== ""
        text: "Open session"; tone: card.view.fg; font: card.view.fontFamily
        onClicked: card.fleet.open(card.item.session)
      }
      SmallButton {
        visible: card.isTicket
        text: "Kill ticket"; tone: card.fleet.red; font: card.view.fontFamily
        onClicked: card.fleet.run(["kill", card.item.run, card.item.ticket], "Killed #" + card.item.ticket + ". Worktree kept.")
      }
    }
  }
}
