import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Wayland
import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model
import "Hotkey.js" as Hotkey

// The focused app's menu bar as an Omarchy menu. bin/search-menu-items reads the app
// and runs the chosen entry; Model.js decides which rows a place and a query
// show; this file draws them and moves through them.
Item {
  id: root

  property var shell: null
  property var manifest: null

  property bool opened: false
  property var entries: []          // everything the app offers, as the reader sent it
  property var sections: []         // the top-level menu names, which arrive first
  property var prefix: []           // the menu we are in: ["File", "Export As"]
  property var rows: []
  property int selectedIndex: 0
  property string status: "reading" // reading | ok | empty | accessibility-off | accessibility-on | no-window
  property string windowClass: ""
  property int pendingRun: -1       // entry the reader is running, so closing does not stop it
  property bool restart: false      // a reader is still stopping; start the next when it has
  property string mode: "menu"      // "menu", or "hotkey" to choose the key that opens it
  property string bindsJson: ""     // `hyprctl binds -j`, to tell free keys from taken ones
  readonly property string configDir: Quickshell.env("HOME") + "/.config/omarchy/extensions"
  // Nothing is drawn until there is something to list, so the menu appears
  // once, whole, and not as "Reading the menu…" that jumps to full height a
  // moment later. The window is up from the start: keys typed in that moment
  // already land in the search field.
  property bool ready: false
  property var incoming: []         // entries read so far; listed when the reader is done
  // The counts come with the entries, after the menu names are already up:
  // they ease in instead of popping.
  property real counts: 0
  Behavior on counts { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

  readonly property string pluginId: (manifest && manifest.id) || "mani4.search-menu-items"
  readonly property string pluginDir: {
    var s = String(Qt.resolvedUrl("."))
    return s.indexOf("file://") === 0 ? s.substring(7) : s
  }
  readonly property var desktopEntry: windowClass ? DesktopEntries.heuristicLookup(windowClass) : null
  readonly property string appName: (desktopEntry && desktopEntry.name) || windowClass || "App"
  readonly property string appIcon: desktopEntry && desktopEntry.icon ? Quickshell.iconPath(desktopEntry.icon, true) : ""
  readonly property var selectedRow: rows[selectedIndex] || null

  // Menu surface tokens, so a theme that styles the Omarchy menu styles this.
  readonly property color background: Color.menu.background
  readonly property color foreground: Color.menu.text
  readonly property color scrim: Color.menu.scrim
  readonly property color selectedBackground: Color.menu.selectedBackground
  readonly property color selectedText: Color.menu.selectedText
  readonly property var borderSpec: Border.surfaceSpec("menu", "border", Color.menu.border, Math.max(1, Style.space(2)))
  readonly property int cornerRadius: Style.cornerRadius
  readonly property string fontFamily: Style.font.menuFamily
  readonly property int inputFont: Style.font.heading
  readonly property int inputHeight: Math.max(Style.space(38), inputFont + Style.spacing.controlPaddingY * 2)
  readonly property int rowHeight: Math.max(Style.space(34), Style.font.subtitle + Style.spacing.lg * 2)
  readonly property int footerHeight: Math.max(Style.space(30), Style.font.caption + Style.spacing.md * 2)
  readonly property int maxRows: 10
  readonly property int cardWidth: Math.min(Style.space(680), panel.width - Style.gapsOut * 2)
  // Rows only take the selection on hover when the pointer really moved, so
  // a list that changes under a resting pointer does not move it.
  property point lastPointer: Qt.point(-1, -1)

  readonly property string message: {
    if (rows.length > 0) return ""
    if (mode === "hotkey") return "Type a key combination, like SUPER + ALT + M."
    if (status === "reading") return "Reading the menu…"
    if (status === "no-window") return "No window is focused."
    if (status === "accessibility-on") return "Accessibility support is on. Restart " + appName + " so it publishes its menu."
    if (input.text.trim() !== "") return "Nothing matches “" + input.text.trim() + "”."
    return appName + " publishes no menu or buttons."
  }

  // ---------------------------------------------------------------- lifecycle

  // payloadJson may carry a starting query: '{"query": "export"}'.
  function open(payloadJson) {
    var payload = {}
    try { payload = JSON.parse(payloadJson || "{}") || {} } catch (e) {}
    root.mode = payload.setup === "hotkey" ? "hotkey" : "menu"
    var active = Hyprland.activeToplevel
    reader.address = active && active.address ? String(active.address) : ""
    root.ready = false
    root.counts = 0
    root.incoming = []
    readyGuard.restart()
    root.entries = []
    root.sections = []
    root.prefix = []
    root.status = "reading"
    root.windowClass = ""
    root.pendingRun = -1
    root.selectedIndex = 0
    root.lastPointer = Qt.point(-1, -1)
    input.text = typeof payload.query === "string" ? payload.query : ""
    root.recompute()
    if (root.mode === "hotkey") {
      root.restart = false
      reader.running = false
      root.status = "ok"
      bindsReader.running = true
    } else if (reader.running) {
      // A reader from the last time may still be stopping.
      root.restart = true
      reader.running = false
    } else {
      reader.running = true
    }
    root.opened = true
    Qt.callLater(function() { input.forceActiveFocus() })
  }

  function close() {
    root.opened = false
    if (root.pendingRun < 0) { root.restart = false; reader.running = false }
  }

  function dismiss() {
    root.close()
    if (root.shell && typeof root.shell.hide === "function") root.shell.hide(root.pluginId)
  }

  function toggle() {
    if (root.opened) root.dismiss()
    else root.open("{}")
  }

  // ---------------------------------------------------------------- reader

  Process {
    id: reader
    property string address: ""
    command: [root.pluginDir + "bin/search-menu-items", "--serve"].concat(address ? ["--window", address] : [])
    stdinEnabled: true
    stdout: SplitParser {
      onRead: function(line) { root.receive(String(line)) }
    }
    onRunningChanged: {
      if (running) return
      if (root.restart) { root.restart = false; running = true }
      else if (root.opened && root.status === "reading") { root.status = "empty"; root.ready = true }
    }
  }

  function receive(line) {
    var message = null
    try { message = JSON.parse(line) } catch (e) { return }
    if (!message || root.restart) return
    if (message.t === "window") {
      root.windowClass = message["class"] || ""
    } else if (message.t === "sections") {
      root.sections = message.names || []
      root.recompute()
      root.ready = true
    } else if (message.t === "items") {
      // A long menu comes as several lines. Listing each as it lands would
      // show the first two menus, then four, then all: keep them for "done".
      root.incoming = root.incoming.concat(message.items || [])
    } else if (message.t === "done") {
      root.entries = root.incoming
      root.incoming = []
      root.status = message.status
      root.recompute()
      root.ready = true
      root.counts = 1
    } else if (message.t === "accessibility") {
      root.status = message.on ? "accessibility-on" : "empty"
      root.recompute()
    } else if (message.t === "ran") {
      if (message.error) Quickshell.execDetached(["notify-send", "-a", "Search Menu Items", "Search Menu Items", "Could not run that: " + message.error])
      root.pendingRun = -1
      runGuard.stop()
      reader.running = false
    }
  }

  // An app that is slow to answer still gets its "Reading the menu…".
  Timer {
    id: readyGuard
    interval: 400
    onTriggered: root.ready = true
  }

  // The reader runs the entry a moment after it is told to, so the menu is
  // gone and the app has the focus back when a dialog opens. This only makes
  // sure a reader that never answers does not stay around.
  Timer {
    id: runGuard
    interval: 5000
    onTriggered: { root.pendingRun = -1; reader.running = false }
  }

  // ---------------------------------------------------------------- rows

  // The key picker's rows; Hotkey.js decides which keys and in what order.
  function hotkeyRows() {
    return Hotkey.choices(root.bindsJson, input.text).map(function(choice) {
      return { type: "hotkey", label: choice.hotkey, key: "", off: choice.holder !== "",
               where: choice.holder ? "runs “" + choice.holder + "”" : "free" }
    })
  }

  function saveHotkey(hotkey) {
    Quickshell.execDetached(["sh", "-c",
      'mkdir -p "$1" && printf \'{ "hotkey": "%s" }\\n\' "$2" > "$1/search-menu-items.json" && '
      + 'notify-send -a "Search Menu Items" "Search Menu Items" "$2 opens the menu of the focused app."',
      "sh", root.configDir, hotkey])
    root.dismiss()
  }

  Process {
    id: bindsReader
    command: ["hyprctl", "binds", "-j"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        root.bindsJson = String(text || "")
        root.recompute()
        root.ready = true
      }
    }
  }

  function recompute() {
    if (root.mode === "hotkey") {
      root.rows = root.hotkeyRows()
      if (root.selectedIndex >= root.rows.length) root.selectedIndex = Math.max(0, root.rows.length - 1)
      return
    }
    var next = Model.rows(root.entries, root.sections, root.prefix, input.text)
    if (next.length === 0 && root.status === "accessibility-off" && input.text.trim() === "") {
      next = [{ type: "enable", label: "Turn on accessibility support", where: "Apps publish their menus once it is on", key: "" }]
    }
    root.rows = next
    if (root.selectedIndex >= next.length) root.selectedIndex = Math.max(0, next.length - 1)
  }

  function move(step) {
    if (root.rows.length === 0) return
    root.selectedIndex = Math.max(0, Math.min(root.rows.length - 1, root.selectedIndex + step))
    list.positionViewAtIndex(root.selectedIndex, ListView.Contain)
  }

  function enter(target) {
    root.prefix = target
    input.text = ""
    root.selectedIndex = 0
    root.recompute()
    list.positionViewAtBeginning()
  }

  function leave() {
    if (root.prefix.length === 0) return false
    var left = root.prefix[root.prefix.length - 1]
    root.prefix = root.prefix.slice(0, -1)
    input.text = ""
    root.recompute()
    root.selectedIndex = Model.indexOfSection(root.rows, left)
    list.positionViewAtIndex(root.selectedIndex, ListView.Contain)
    return true
  }

  function activate(index) {
    var row = root.rows[index]
    if (!row) return
    if (row.type === "section") {
      root.enter(row.target)
    } else if (row.type === "hotkey") {
      if (!row.off) root.saveHotkey(row.label)
    } else if (row.type === "enable") {
      if (reader.running) reader.write("accessibility\n")
    } else if (!row.off) {
      if (!reader.running) return
      root.pendingRun = row.id
      reader.write("run " + row.id + "\n")
      runGuard.restart()
      root.dismiss()
    }
  }

  // ---------------------------------------------------------------- pieces

  component Keycap: Rectangle {
    id: cap
    property string label: ""
    property color tint: root.foreground
    implicitWidth: Math.max(implicitHeight, capText.implicitWidth + Style.space(10))
    implicitHeight: capText.implicitHeight + Style.space(4)
    radius: root.cornerRadius > 0 ? Style.space(4) : 0
    color: Util.alpha(cap.tint, 0.08)
    border.width: 1
    border.color: Util.alpha(cap.tint, 0.18)

    Text {
      id: capText
      anchors.centerIn: parent
      text: cap.label
      color: cap.tint
      opacity: 0.8
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  component Hint: Row {
    property string keyLabel: ""
    property string text: ""
    spacing: Style.space(5)
    Keycap { label: parent.keyLabel; anchors.verticalCenter: parent.verticalCenter }
    Text {
      anchors.verticalCenter: parent.verticalCenter
      text: parent.text
      color: root.foreground
      opacity: 0.5
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  // ---------------------------------------------------------------- window

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "omarchy-search-menu-items"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    Rectangle {
      anchors.fill: parent
      color: root.scrim
      opacity: root.ready ? 1 : 0
    }

    MouseArea {
      anchors.fill: parent
      onClicked: root.dismiss()
    }

    BorderSurface {
      id: card
      width: root.cardWidth
      height: contentTopInset + contentBottomInset + layout.implicitHeight
      radius: root.cornerRadius
      anchors.horizontalCenter: parent.horizontalCenter
      y: Math.round(panel.height * 0.2)
      color: root.background
      borderSpec: root.borderSpec
      padding: Style.spacing.panelPadding
      opacity: root.ready ? 1 : 0

      MouseArea { anchors.fill: parent; onClicked: input.forceActiveFocus() }

      Column {
        id: layout
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.topMargin: card.contentTopInset
        anchors.leftMargin: card.contentLeftInset
        anchors.rightMargin: card.contentRightInset
        spacing: Style.spacing.md

        // ---------- where we are, and the search field ----------
        Item {
          width: parent.width
          height: root.inputHeight

          Row {
            id: trail
            anchors.left: parent.left
            anchors.leftMargin: Style.space(4)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(6)

            Image {
              visible: root.appIcon !== "" && root.mode === "menu"
              anchors.verticalCenter: parent.verticalCenter
              width: Math.round(root.inputFont * 1.25)
              height: width
              sourceSize.width: width * 2
              sourceSize.height: height * 2
              fillMode: Image.PreserveAspectFit
              asynchronous: true
              source: root.appIcon
            }

            // The app, then the menus we went into; the last one is where we are.
            Repeater {
              model: root.mode === "hotkey" ? ["Open the menu with"] : [root.appName].concat(root.prefix)
              Row {
                id: crumb
                required property string modelData
                required property int index
                readonly property bool here: root.mode === "hotkey" || index === root.prefix.length
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(6)

                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  text: crumb.modelData
                  color: root.foreground
                  opacity: crumb.here ? 0.9 : 0.5
                  font.family: root.fontFamily
                  font.pixelSize: root.inputFont
                  elide: Text.ElideRight
                  width: Math.min(implicitWidth, root.cardWidth * (crumb.here ? 0.34 : 0.16))
                }
                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  text: "›"
                  color: root.foreground
                  opacity: 0.4
                  font.family: root.fontFamily
                  font.pixelSize: root.inputFont
                }
              }
            }
          }

          TextInput {
            id: input
            anchors.left: trail.right
            anchors.leftMargin: Style.space(6)
            anchors.right: tally.left
            anchors.rightMargin: Style.spacing.md
            anchors.verticalCenter: parent.verticalCenter
            color: root.foreground
            selectionColor: root.selectedBackground
            selectedTextColor: root.selectedText
            font.family: root.fontFamily
            font.pixelSize: root.inputFont
            clip: true
            focus: true
            onTextChanged: {
              root.selectedIndex = 0
              root.recompute()
              list.positionViewAtBeginning()
            }

            Text {
              anchors.fill: parent
              verticalAlignment: Text.AlignVCenter
              visible: !input.text
              text: root.mode === "hotkey" ? "Pick one, or type your own" : "Search"
              color: root.foreground
              opacity: 0.4
              font: input.font
            }

            Keys.priority: Keys.BeforeItem
            Keys.onPressed: function(event) {
              var ctrl = event.modifiers & Qt.ControlModifier
              var atEnd = input.cursorPosition === input.text.length
              var section = root.selectedRow && root.selectedRow.type === "section"
              if (event.key === Qt.Key_Escape) {
                if (input.text) input.text = ""
                else if (!root.leave()) root.dismiss()
              } else if (event.key === Qt.Key_Down || (ctrl && (event.key === Qt.Key_N || event.key === Qt.Key_J))) {
                root.move(1)
              } else if (event.key === Qt.Key_Up || (ctrl && (event.key === Qt.Key_P || event.key === Qt.Key_K))) {
                root.move(-1)
              } else if (event.key === Qt.Key_PageDown) {
                root.move(root.maxRows - 1)
              } else if (event.key === Qt.Key_PageUp) {
                root.move(1 - root.maxRows)
              } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                root.activate(root.selectedIndex)
              } else if (event.key === Qt.Key_Tab || (event.key === Qt.Key_Right && atEnd)) {
                // Into a section; on an item the key does nothing, as in a menu.
                if (section) root.activate(root.selectedIndex)
                else if (event.key === Qt.Key_Right) return
              } else if (event.key === Qt.Key_Backtab || ((event.key === Qt.Key_Left || event.key === Qt.Key_Backspace) && !input.text)) {
                if (!root.leave() && event.key !== Qt.Key_Backtab) return
              } else {
                return
              }
              event.accepted = true
            }
          }

          Text {
            id: tally
            anchors.right: parent.right
            anchors.rightMargin: Style.space(4)
            anchors.verticalCenter: parent.verticalCenter
            visible: root.entries.length > 0
            text: input.text.trim() ? root.rows.length + " of " + root.entries.length : String(root.entries.length)
            color: root.foreground
            opacity: 0.4 * root.counts
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        Rectangle {
          width: parent.width
          height: 1
          color: Util.alpha(root.foreground, 0.1)
        }

        // ---------- what there is ----------
        ListView {
          id: list
          width: parent.width
          height: Math.min(root.rows.length, root.maxRows) * root.rowHeight
          visible: root.rows.length > 0
          model: root.rows
          clip: true
          boundsBehavior: Flickable.StopAtBounds
          currentIndex: root.selectedIndex

          delegate: Item {
            id: rowItem
            required property int index
            required property var modelData
            readonly property bool selected: index === root.selectedIndex
            readonly property bool section: modelData.type === "section"
            readonly property bool off: !!modelData.off
            readonly property color ink: selected && !off ? root.selectedText : root.foreground

            width: list.width
            height: root.rowHeight

            Rectangle {
              anchors.fill: parent
              radius: root.cornerRadius > 0 ? Style.space(6) : 0
              color: rowItem.selected ? root.selectedBackground : "transparent"
            }

            // A folder for a menu to step into, a tick for what is switched on.
            Text {
              id: tick
              anchors.left: parent.left
              anchors.leftMargin: Style.spacing.md
              anchors.verticalCenter: parent.verticalCenter
              width: Style.space(18)
              horizontalAlignment: Text.AlignHCenter
              text: rowItem.section ? "󰉋" : rowItem.modelData.on ? "✓" : ""
              color: rowItem.ink
              opacity: rowItem.off ? 0.4 : rowItem.section ? 0.65 : 0.9
              font.family: root.fontFamily
              font.pixelSize: Style.font.subtitle
            }

            Text {
              id: label
              anchors.left: tick.right
              anchors.leftMargin: Style.spacing.sm
              anchors.verticalCenter: parent.verticalCenter
              width: Math.min(implicitWidth, parent.width - tick.width - trailing.width - Style.spacing.md * 4)
              text: rowItem.modelData.label
              color: rowItem.ink
              opacity: rowItem.off ? 0.4 : 1
              font.family: root.fontFamily
              font.pixelSize: Style.font.subtitle
              elide: Text.ElideRight
            }

            // Where a search result lives: "File › Export As".
            Text {
              anchors.left: label.right
              anchors.leftMargin: Style.spacing.lg
              anchors.right: trailing.left
              anchors.rightMargin: Style.spacing.lg
              anchors.verticalCenter: parent.verticalCenter
              visible: text !== ""
              text: rowItem.modelData.where || ""
              color: rowItem.ink
              opacity: rowItem.off ? 0.25 : 0.45
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              elide: Text.ElideRight
            }

            Row {
              id: trailing
              anchors.right: parent.right
              anchors.rightMargin: Style.spacing.lg
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(4)
              opacity: rowItem.off ? 0.4 : 1

              Repeater {
                model: Model.keys(rowItem.modelData.key)
                Keycap {
                  required property string modelData
                  anchors.verticalCenter: parent.verticalCenter
                  label: modelData
                  tint: rowItem.ink
                }
              }

              Text {
                visible: rowItem.section && rowItem.modelData.count > 0
                anchors.verticalCenter: parent.verticalCenter
                text: rowItem.section ? String(rowItem.modelData.count) : ""
                color: rowItem.ink
                opacity: 0.45 * root.counts
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }

              Text {
                visible: rowItem.section
                anchors.verticalCenter: parent.verticalCenter
                text: "›"
                color: rowItem.ink
                opacity: 0.7
                font.family: root.fontFamily
                font.pixelSize: Style.font.title
              }
            }

            MouseArea {
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: rowItem.off ? Qt.ArrowCursor : Qt.PointingHandCursor
              onPositionChanged: function(mouse) {
                var p = mapToItem(null, mouse.x, mouse.y)
                if (p.x === root.lastPointer.x && p.y === root.lastPointer.y) return
                var first = root.lastPointer.x < 0
                root.lastPointer = Qt.point(p.x, p.y)
                if (!first) root.selectedIndex = rowItem.index
              }
              onClicked: {
                input.forceActiveFocus()
                root.selectedIndex = rowItem.index
                // Last: it may replace the rows, and this one with them.
                root.activate(rowItem.index)
              }
            }
          }
        }

        // ---------- nothing to list ----------
        Text {
          width: parent.width
          height: root.rowHeight * 2
          visible: root.rows.length === 0
          horizontalAlignment: Text.AlignHCenter
          verticalAlignment: Text.AlignVCenter
          wrapMode: Text.WordWrap
          text: root.message
          color: root.foreground
          opacity: 0.55
          font.family: root.fontFamily
          font.pixelSize: Style.font.subtitle
        }

        // ---------- what the keys do ----------
        Item {
          width: parent.width
          height: root.footerHeight
          visible: root.rows.length > 0

          Rectangle {
            anchors.top: parent.top
            width: parent.width
            height: 1
            color: Util.alpha(root.foreground, 0.1)
          }

          Row {
            anchors.left: parent.left
            anchors.leftMargin: Style.space(4)
            anchors.bottom: parent.bottom
            spacing: Style.spacing.xxl

            Hint {
              keyLabel: "↵"
              text: !root.selectedRow ? "" : root.selectedRow.type === "section" ? "Open"
                : root.selectedRow.type === "hotkey" ? (root.selectedRow.off ? "Taken" : "Use this key")
                : root.selectedRow.off ? (root.selectedRow.why || "Not available now") : "Run"
            }
            Hint { keyLabel: "←"; text: "Back"; visible: root.prefix.length > 0 }
          }

          Hint {
            anchors.right: parent.right
            anchors.rightMargin: Style.space(4)
            anchors.bottom: parent.bottom
            keyLabel: "esc"
            text: input.text ? "Clear" : root.prefix.length > 0 ? "Back" : "Close"
          }
        }
      }
    }
  }
}
