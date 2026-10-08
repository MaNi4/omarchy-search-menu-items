import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import "Hotkey.js" as Hotkey

// Binds the key that opens the menu (SearchMenuItems.qml). A service is mounted
// with the shell, so the key works before the menu has ever been opened.
Item {
  id: service
  visible: false

  readonly property string command: "omarchy-shell shell toggle mani4.search-menu-items '{}'"
  readonly property string configPath: Quickshell.env("HOME") + "/.config/omarchy/extensions/search-menu-items.json"
  readonly property string defaultHotkey: "SUPER + M"

  // Set "hotkey" to "" in the config to bind nothing.
  property string hotkey: defaultHotkey
  property string boundHotkey: ""     // what we bound, so unloading can unbind it
  property string warnedConflict: ""  // notify once per key, not on every reload
  property bool queued: false

  function applyConfig(text) {
    var next = service.defaultHotkey
    try {
      var config = JSON.parse(text)
      if (config && typeof config.hotkey === "string") next = config.hotkey.trim()
    } catch (e) {
      if (text) console.warn("search-menu-items: bad " + service.configPath + ": " + e)
    }
    service.hotkey = next
    startTimer.restart()
  }

  FileView {
    path: service.configPath
    watchChanges: true
    printErrors: false
    onLoaded: service.applyConfig(text())
    onLoadFailed: service.applyConfig("")
    onFileChanged: reload()
  }

  // The short delay lets a previous instance's unbind land first when the
  // plugin is reloaded.
  Timer {
    id: startTimer
    interval: 600
    onTriggered: service.ensureHotkey()
  }

  function ensureHotkey() {
    if (bindsProc.running) { service.queued = true; return }
    bindsProc.running = true
  }

  // The menu appears at once, like Omarchy's own, not with the layer animation.
  function ruleOutAnimation() {
    Quickshell.execDetached(["hyprctl", "eval",
      'hl.layer_rule({ match = { namespace = "^omarchy-search-menu-items$" }, no_anim = true, animation = "none" })'])
  }

  Component.onCompleted: service.ruleOutAnimation()

  function reconcile(bindsJson) {
    var plan = Hotkey.plan(bindsJson, service.hotkey, service.command)
    if (plan.lua.length > 0) Quickshell.execDetached(["hyprctl", "eval", plan.lua.join("\n")])
    service.boundHotkey = plan.bound ? service.hotkey : ""
    if (plan.conflict && service.warnedConflict !== service.hotkey) {
      service.warnedConflict = service.hotkey
      conflictNote.taken = service.hotkey + " already runs \"" + plan.conflict + "\"."
      conflictNote.running = true
    }
    if (service.queued) { service.queued = false; service.ensureHotkey() }
  }

  // Clicking the notification opens the menu on a list of free keys.
  Process {
    id: conflictNote
    property string taken: ""
    command: ["notify-send", "-a", "Search Menu Items", "-A", "default=Choose a key",
      "Search Menu Items has no key", taken + " Click to choose another one."]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        if (String(text || "").trim() === "default")
          Quickshell.execDetached(["omarchy-shell", "shell", "summon", "mani4.search-menu-items", '{"setup": "hotkey"}'])
      }
    }
  }

  Process {
    id: bindsProc
    command: ["hyprctl", "binds", "-j"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: service.reconcile(String(text || ""))
    }
  }

  // Hyprland drops runtime binds and rules when its config reloads.
  Connections {
    target: Hyprland
    function onRawEvent(event) {
      if (!event || String(event.name) !== "configreloaded") return
      service.ruleOutAnimation()
      service.ensureHotkey()
    }
  }

  // Disabling, removing or reloading the plugin takes the binding with it.
  Component.onDestruction: {
    var combo = Hotkey.parse(service.boundHotkey)
    if (combo) Quickshell.execDetached(["hyprctl", "eval", Hotkey.unbind(combo.mask, combo.key)])
  }
}
