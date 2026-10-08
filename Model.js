.pragma library

// What the menu lists for a place in the app's menu and a search query.
// Pure: entries in, rows out, so it runs under node in tests/run.js.
//
// An entry is what bin/search-menu-items sends:
//   { id, path: ["File", "Export As"], label, key, kind, off, on, why }
// A row is what SearchMenuItems.qml draws:
//   { type: "section" | "item", label, where, key, off, on, id, target, count }

var SEPARATOR = " › "
var LIMIT = 300

function startsWith(path, prefix) {
  if (path.length < prefix.length) return false
  for (var i = 0; i < prefix.length; i++) if (path[i] !== prefix[i]) return false
  return true
}

function fold(text) {
  return String(text || "").toLowerCase().replace(/\.\.\.|…/g, "").trim()
}

// "help > about" and "help about" search alike.
function terms(query) {
  return fold(query).split(/[\s>›]+/).filter(function(term) { return term })
}

function sectionRow(prefix, name, where, count) {
  return { type: "section", label: name, where: where, key: "", count: count, target: prefix.concat([name]) }
}

function itemRow(entry, where) {
  return { type: "item", label: entry.label, where: where, key: entry.key || "", kind: entry.kind,
           off: !!entry.off, on: !!entry.on, why: entry.why || "", id: entry.id }
}

// One level of the menu, in the app's own order: sub-menus and items mixed
// as the app lists them. Before the entries arrive, `sections` (the top-level
// names) stands in for the top level.
function browse(entries, sections, prefix) {
  var depth = prefix.length
  var rows = []
  var bySection = {}
  for (var i = 0; i < entries.length; i++) {
    var entry = entries[i]
    if (!startsWith(entry.path, prefix)) continue
    if (entry.path.length === depth) { rows.push(itemRow(entry, "")); continue }
    var name = entry.path[depth]
    if (!bySection[name]) {
      bySection[name] = sectionRow(prefix, name, "", 0)
      rows.push(bySection[name])
    }
    bySection[name].count++
  }
  if (depth === 0 && rows.length === 0) {
    for (var j = 0; j < sections.length; j++) rows.push(sectionRow([], sections[j], "", -1))
  }
  return rows
}

// How well `label` answers the query; lower is better, -1 is no match.
// `context` is where the label lives ("file export as"): terms may match
// there, but a match in the label itself ranks first.
function score(label, context, query, words) {
  var inLabel = true
  for (var i = 0; i < words.length; i++) {
    if (label.indexOf(words[i]) >= 0) continue
    if (context.indexOf(words[i]) < 0) return -1
    inLabel = false
  }
  if (label === query) return 0
  if (label.indexOf(query) === 0) return 1
  if ((" " + label).indexOf(" " + query) >= 0) return 2
  if (label.indexOf(query) >= 0) return 3
  return inLabel ? 4 : 5
}

// Everything below `prefix` that matches, best first; ties keep menu order.
function search(entries, prefix, query) {
  var words = terms(query)
  var needle = words.join(" ")
  var depth = prefix.length
  var found = []
  var sections = {}

  for (var i = 0; i < entries.length; i++) {
    var entry = entries[i]
    if (!startsWith(entry.path, prefix)) continue
    var inner = entry.path.slice(depth)

    for (var d = 0; d < inner.length; d++) {
      var key = inner.slice(0, d + 1).join("\n")
      if (sections[key]) { sections[key].row.count++; continue }
      var above = inner.slice(0, d)
      var row = sectionRow(prefix.concat(above), inner[d], above.join(SEPARATOR), 1)
      // A section is found by its own name only, and comes before an item
      // that matches equally well.
      var s = score(fold(inner[d]), "", needle, words)
      sections[key] = { row: row }
      if (s >= 0) found.push({ score: s - 0.5, order: found.length, row: row })
    }

    var points = score(fold(entry.label), fold(inner.join(" ")), needle, words)
    if (points < 0) continue
    found.push({ score: points + (entry.off ? 0.25 : 0), order: found.length, row: itemRow(entry, inner.join(SEPARATOR)) })
  }

  found.sort(function(a, b) { return a.score - b.score || a.order - b.order })
  return found.slice(0, LIMIT).map(function(hit) { return hit.row })
}

function rows(entries, sections, prefix, query) {
  return terms(query).length > 0 ? search(entries, prefix, query) : browse(entries, sections, prefix)
}

// Where the row for `name` sits, so going back up lands on the section left.
function indexOfSection(rowList, name) {
  for (var i = 0; i < rowList.length; i++) {
    if (rowList[i].type === "section" && rowList[i].label === name) return i
  }
  return 0
}

// "Ctrl+Shift+S" -> ["Ctrl", "Shift", "S"], keeping a "+" key.
function keys(shortcut) {
  var text = String(shortcut || "")
  if (!text) return []
  if (text === "+") return ["+"]
  if (text.slice(-2) === "++") return text.slice(0, -2).split("+").concat(["+"])
  return text.split("+")
}
