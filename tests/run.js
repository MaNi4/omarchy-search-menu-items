// node tests/run.js — checks Model.js and Hotkey.js, which have no QML in them.
const fs = require("fs")
const path = require("path")
const assert = require("assert")

const library = (file, names) => {
  const source = fs.readFileSync(path.join(__dirname, "..", file), "utf8").replace(/^\.pragma library\s*$/m, "")
  return new Function(source + "\nreturn { " + names + " }")()
}
const Model = library("Model.js", "rows, browse, search, keys, indexOfSection, terms")
const Hotkey = library("Hotkey.js", "parse, format, tidy, holder, plan, choices, IDEAS, DESCRIPTION")

// What `hyprctl binds -j` reports: SUPER is 64, ALT 8, SHIFT 1.
const bind = (modmask, key, description) => ({ modmask, key, description, dispatcher: "exec" })
const binds = extra => JSON.stringify([
  bind(64, "K", "Keybindings"), bind(65, "M", "Music"), bind(64, "", "By keycode"),
].concat(extra || []))
const ours = (modmask, key) => bind(modmask, key, Hotkey.DESCRIPTION)

let id = 0
const entry = (menuPath, label, extra) => Object.assign({ id: id++, path: menuPath, label, key: "", kind: "menu" }, extra)
const entries = [
  entry(["File", "New"], "Text Document", { key: "Ctrl+N" }),
  entry(["File", "New"], "Spreadsheet"),
  entry(["File"], "Open...", { key: "Ctrl+O" }),
  entry(["File"], "Save", { key: "Ctrl+S", off: true }),
  entry(["File", "Export As"], "Export as PDF..."),
  entry(["Edit"], "Find...", { key: "Ctrl+F" }),
  entry(["View"], "Status Bar", { on: true }),
  entry(["Tools"], "Help Options"),
  entry(["Help"], "LibreOffice Help", { key: "F1" }),
  entry(["Help"], "About LibreOffice"),
  entry([], "New tab", { kind: "action" }),
]
const labels = rows => rows.map(row => (row.type === "section" ? "[" + row.label + "]" : row.label))

const tests = {
  "the top level lists the menus in order, then loose entries"() {
    assert.deepStrictEqual(labels(Model.rows(entries, [], [], "")), ["[File]", "[Edit]", "[View]", "[Tools]", "[Help]", "New tab"])
  },
  "a section keeps the app's order, sub-menus and items mixed"() {
    assert.deepStrictEqual(labels(Model.rows(entries, [], ["File"], "")), ["[New]", "Open...", "Save", "[Export As]"])
  },
  "a section counts every item below it"() {
    const file = Model.rows(entries, [], [], "")[0]
    assert.strictEqual(file.count, 5)
    assert.deepStrictEqual(file.target, ["File"])
  },
  "the top-level names stand in until the entries arrive"() {
    const rows = Model.rows([], ["File", "Edit"], [], "")
    assert.deepStrictEqual(labels(rows), ["[File]", "[Edit]"])
    assert.strictEqual(rows[0].count, -1)
  },
  "searching a menu's name puts that menu first"() {
    // Then labels with the word, then what merely lives in Help.
    assert.deepStrictEqual(labels(Model.rows(entries, [], [], "help")),
      ["[Help]", "Help Options", "LibreOffice Help", "About LibreOffice"])
  },
  "\"help >\" finds what is in Help"() {
    assert.deepStrictEqual(labels(Model.rows(entries, [], [], "help > about")), ["About LibreOffice"])
  },
  "a search result says where it lives"() {
    const row = Model.rows(entries, [], [], "pdf")[0]
    assert.strictEqual(row.where, "File › Export As")
  },
  "search inside a section stays inside it"() {
    assert.deepStrictEqual(labels(Model.rows(entries, [], ["File"], "s")),
      ["Spreadsheet", "Save", "[Export As]", "Export as PDF..."])
  },
  "a label that starts with the query beats one that contains it"() {
    assert.deepStrictEqual(labels(Model.rows(entries, [], [], "sp")), ["Spreadsheet"])
    const found = labels(Model.rows(entries, [], [], "o"))
    assert.ok(found.indexOf("Open...") < found.indexOf("About LibreOffice"))
  },
  "an item that cannot be run sorts after one that can"() {
    const found = labels(Model.rows(entries, [], [], "s"))
    assert.ok(found.indexOf("Spreadsheet") < found.indexOf("Save"))
  },
  "the ellipsis does not have to be typed"() {
    assert.deepStrictEqual(labels(Model.rows(entries, [], [], "open")), ["Open..."])
    assert.deepStrictEqual(labels(Model.rows(entries, [], [], "find...")), ["Find..."])
  },
  "nothing matches nonsense"() {
    assert.deepStrictEqual(Model.rows(entries, [], [], "zzz"), [])
  },
  "going back up lands on the section left"() {
    assert.strictEqual(Model.indexOfSection(Model.rows(entries, [], [], ""), "Help"), 4)
  },
  "a shortcut splits into keys, keeping a plus key"() {
    assert.deepStrictEqual(Model.keys("Ctrl+Shift+S"), ["Ctrl", "Shift", "S"])
    assert.deepStrictEqual(Model.keys("Ctrl++"), ["Ctrl", "+"])
    assert.deepStrictEqual(Model.keys("F1"), ["F1"])
    assert.deepStrictEqual(Model.keys(""), [])
  },
}

const hotkeyTests = {
  "a key combination is read whatever its spacing and case"() {
    assert.deepStrictEqual(Hotkey.parse("super+alt + m"), { mask: 72, key: "M" })
    assert.strictEqual(Hotkey.tidy("super+alt + m"), "SUPER + ALT + M")
    assert.strictEqual(Hotkey.tidy("ctrl + super + slash"), "SUPER + CTRL + SLASH")
  },
  "what is not a key combination is turned down"() {
    for (const text of ["", "SUPER + ", "hello world", "super + ctrl", "foo + m", "super + m!"])
      assert.strictEqual(Hotkey.tidy(text), "", JSON.stringify(text))
  },
  "holder names what runs on a key"() {
    assert.strictEqual(Hotkey.holder(binds(), "SUPER + K"), "Keybindings")
    assert.strictEqual(Hotkey.holder(binds(), "super + shift + m"), "Music")
    assert.strictEqual(Hotkey.holder(binds(), "SUPER + M"), "")
  },
  "our own binding does not hold a key against us"() {
    assert.strictEqual(Hotkey.holder(binds([ours(64, "M")]), "SUPER + M"), "")
  },
  "holder copes with output that is not JSON"() {
    assert.strictEqual(Hotkey.holder("", "SUPER + K"), "")
    assert.strictEqual(Hotkey.holder("oops", "SUPER + K"), "")
  },
  "a free key gets bound"() {
    const plan = Hotkey.plan(binds(), "SUPER + M", "open-it")
    assert.strictEqual(plan.bound, true)
    assert.strictEqual(plan.conflict, "")
    assert.deepStrictEqual(plan.lua,
      ['hl.bind("SUPER + M", hl.dsp.exec_cmd("open-it"), { description = "Search menu items" })'])
  },
  "a taken key is left alone and named"() {
    const plan = Hotkey.plan(binds(), "SUPER + K", "open-it")
    assert.deepStrictEqual(plan, { lua: [], bound: false, conflict: "Keybindings" })
  },
  "a key we already hold is not bound twice"() {
    assert.deepStrictEqual(Hotkey.plan(binds([ours(64, "M")]), "SUPER + M", "open-it"),
      { lua: [], bound: true, conflict: "" })
  },
  "changing the key lets go of the old one"() {
    const plan = Hotkey.plan(binds([ours(64, "M")]), "SUPER + ALT + M", "open-it")
    assert.strictEqual(plan.lua[0], 'hl.unbind("SUPER + M")')
    assert.ok(plan.lua[1].startsWith('hl.bind("SUPER + ALT + M"'))
    assert.strictEqual(plan.bound, true)
  },
  "an empty hotkey binds nothing and lets go of ours"() {
    assert.deepStrictEqual(Hotkey.plan(binds([ours(64, "M")]), "", "open-it"),
      { lua: ['hl.unbind("SUPER + M")'], bound: false, conflict: "" })
  },
  "the command is quoted for Lua"() {
    const plan = Hotkey.plan(binds(), "SUPER + M", 'say "hi"\\now')
    assert.ok(plan.lua[0].includes('hl.dsp.exec_cmd("say \\"hi\\"\\\\now")'), plan.lua[0])
  },
  "with nothing typed every idea is offered, free ones first"() {
    const choices = Hotkey.choices(binds(), "")
    assert.strictEqual(choices.length, Hotkey.IDEAS.length)
    assert.deepStrictEqual(choices[0], { hotkey: "SUPER + M", holder: "" })
    assert.deepStrictEqual(choices[choices.length - 1], { hotkey: "SUPER + SHIFT + M", holder: "Music" })
  },
  "typing narrows the ideas"() {
    assert.deepStrictEqual(Hotkey.choices(binds(), "slash").map(choice => choice.hotkey),
      ["SUPER + SLASH", "SUPER + ALT + SLASH", "SUPER + BACKSLASH"])
    assert.deepStrictEqual(Hotkey.choices(binds(), "semi").map(choice => choice.hotkey), ["SUPER + SEMICOLON"])
  },
  "a typed combination is offered itself, and says when it is taken"() {
    assert.deepStrictEqual(Hotkey.choices(binds(), "super + k"), [{ hotkey: "SUPER + K", holder: "Keybindings" }])
    assert.deepStrictEqual(Hotkey.choices(binds(), "super+f9"), [{ hotkey: "SUPER + F9", holder: "" }])
  },
  "a typed idea is not listed twice"() {
    assert.deepStrictEqual(Hotkey.choices(binds(), "super + m").map(choice => choice.hotkey), ["SUPER + M"])
  },
  "a bare letter is not offered as a key"() {
    assert.ok(Hotkey.choices(binds(), "m").every(choice => choice.hotkey !== "M"))
  },
}

let failed = 0
for (const [name, test] of Object.entries(Object.assign({}, tests, hotkeyTests))) {
  try { test(); console.log("ok   " + name) }
  catch (error) { failed++; console.log("FAIL " + name + "\n     " + String(error.message).split("\n").join("\n     ")) }
}
process.exit(failed ? 1 : 0)
