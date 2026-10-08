"""python3 tests/test_reader.py — checks the parts of bin/search-menu-items
that need no app to talk to."""

import importlib.machinery
import importlib.util
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "search-menu-items"
loader = importlib.machinery.SourceFileLoader("reader", str(SCRIPT))
reader = importlib.util.module_from_spec(importlib.util.spec_from_loader("reader", loader))
sys.modules["reader"] = reader  # dataclasses look their module up by name
loader.exec_module(reader)

Node, Ref = reader.Node, reader.Ref


def state(*bits):
    return sum(1 << bit for bit in bits)


def ref(name):
    return Ref(":1.1", "/" + name)


class Shortcut(unittest.TestCase):
    def test_gtk_gives_mnemonics_then_the_accelerator(self):
        self.assertEqual(reader.shortcut("s;<Alt>f:s;<Primary>s"), "Ctrl+S")

    def test_gtk_without_an_accelerator_has_no_shortcut(self):
        self.assertEqual(reader.shortcut("s;<Alt>f:s;"), "")

    def test_qt_gives_the_accelerator_alone(self):
        self.assertEqual(reader.shortcut("Ctrl+Shift+F"), "Ctrl+Shift+F")

    def test_a_qt_mnemonic_is_not_a_shortcut(self):
        self.assertEqual(reader.shortcut("Alt+C"), "")

    def test_modifiers_come_in_one_order(self):
        self.assertEqual(reader.shortcut("n;<Alt>f:n;<Shift><Primary>n"), "Ctrl+Shift+N")

    def test_the_plus_key(self):
        self.assertEqual(reader.shortcut("Ctrl++"), "Ctrl++")
        self.assertEqual(reader.shortcut("+"), "+")

    def test_named_keys_are_capitalised(self):
        self.assertEqual(reader.shortcut("<Primary>plus"), "Ctrl+Plus")
        self.assertEqual(reader.shortcut("F11"), "F11")

    def test_nothing_reported(self):
        self.assertEqual(reader.shortcut(""), "")
        self.assertEqual(reader.shortcut(None), "")
        self.assertEqual(reader.shortcut(";;"), "")


class Text(unittest.TestCase):
    def test_clean_makes_one_line(self):
        self.assertEqual(reader.clean("  Save\tAs\n now "), "Save As now")

    def test_clean_cuts_a_tooltip_short(self):
        cut = reader.clean("Paintbrush " + "x" * 100)
        self.assertEqual(len(cut), 70)
        self.assertTrue(cut.endswith("…"))

    def test_humanize(self):
        self.assertEqual(reader.humanize("toggle-sidebar"), "Toggle sidebar")
        self.assertEqual(reader.humanize("tab_move.left"), "Tab move left")


class Nodes(unittest.TestCase):
    def test_usable_needs_an_action_and_to_be_enabled(self):
        self.assertTrue(Node(actions=1, state=state(reader.ENABLED)).usable)
        self.assertTrue(Node(actions=1, state=state(reader.SENSITIVE)).usable)
        self.assertFalse(Node(actions=0, state=state(reader.ENABLED)).usable)
        self.assertFalse(Node(actions=1, state=state(reader.SHOWING)).usable)

    def test_states_above_the_first_32_bits(self):
        self.assertTrue(Node(state=1 << 41).has(41))


class ChooseFrames(unittest.TestCase):
    def test_the_active_frame_wins(self):
        frames = {ref("a"): Node(name="Doc"), ref("b"): Node(name="Doc", state=state(reader.ACTIVE))}
        self.assertEqual(reader.choose_frames(frames, "Doc"), ([ref("b")], ""))

    def test_else_the_one_with_the_title(self):
        frames = {ref("a"): Node(name="One"), ref("b"): Node(name="Two")}
        self.assertEqual(reader.choose_frames(frames, "Two"), ([ref("b")], ""))

    def test_two_with_the_title_are_not_run(self):
        frames = {ref("a"): Node(name="Home"), ref("b"): Node(name="Home"), ref("c"): Node(name="tmp")}
        chosen, why = reader.choose_frames(frames, "Home")
        self.assertEqual(chosen, [ref("a")])
        self.assertEqual(why, reader.SAME_TITLE)

    def test_no_title_match_leaves_every_frame_a_candidate(self):
        frames = {ref("a"): Node(name=""), ref("b"): Node(name="Main")}
        self.assertEqual(reader.choose_frames(frames, "Other"), ([ref("a"), ref("b")], ""))

    def test_an_empty_title_matches_nothing(self):
        frames = {ref("a"): Node(name=""), ref("b"): Node(name="")}
        self.assertEqual(reader.choose_frames(frames, "")[1], "")


class MenuItems(unittest.TestCase):
    def items(self, nodes, bar):
        return [(path, node.label) for path, _, node in reader.menu_items(nodes, bar)]

    def test_gtk_menus_hold_their_items(self):
        bar, file, new, save, text = ref("bar"), ref("file"), ref("new"), ref("save"), ref("text")
        nodes = {
            bar: Node(children=[file]),
            file: Node(children=[new, save], role=reader.MENU, name="File"),
            new: Node(children=[text], role=reader.MENU, name="New"),
            text: Node(role=35, name="Text Document"),
            save: Node(role=35, name="Save"),
        }
        self.assertEqual(self.items(nodes, bar), [(["File", "New"], "Text Document"), (["File"], "Save")])

    def test_qt_hangs_items_off_a_popup_under_the_item(self):
        bar, file, popup, save, recent, inner, clear = (ref(n) for n in "bar file popup save recent inner clear".split())
        nodes = {
            bar: Node(children=[file]),
            file: Node(children=[popup], role=35, name="File"),
            popup: Node(children=[save, recent], role=reader.POPUP_MENU, name="Kdenlive"),
            save: Node(role=35, name="Save"),
            recent: Node(children=[inner], role=35, name="Open Recent"),
            inner: Node(children=[clear], role=reader.POPUP_MENU),
            clear: Node(role=35, name="Clear List"),
        }
        self.assertEqual(self.items(nodes, bar), [(["File"], "Save"), (["File", "Open Recent"], "Clear List")])

    def test_separators_and_nameless_things_are_left_out(self):
        bar, file, sep, blank = ref("bar"), ref("file"), ref("sep"), ref("blank")
        nodes = {
            bar: Node(children=[file]),
            file: Node(children=[sep, blank], role=reader.MENU, name="File"),
            sep: Node(role=50),
            blank: Node(role=35, name=""),
        }
        self.assertEqual(self.items(nodes, bar), [])

    def test_a_child_that_was_not_read_is_skipped(self):
        bar = ref("bar")
        self.assertEqual(self.items({bar: Node(children=[ref("gone")])}, bar), [])


class GtkActions(unittest.TestCase):
    def test_action_root(self):
        self.assertEqual(reader.action_root("org.gnome.Nautilus"), "/org/gnome/Nautilus")
        self.assertEqual(reader.action_root("com.example.my-app"), "/com/example/my_app")

    def test_one_window_runs_its_actions(self):
        self.assertEqual(reader.action_groups("/a", ["1"]), [("/a", ""), ("/a/window/1", "")])

    def test_several_windows_list_them_without_running(self):
        self.assertEqual(reader.action_groups("/a", ["2", "1"]),
                         [("/a", ""), ("/a/window/1", reader.SEVERAL_WINDOWS)])

    def test_no_window_leaves_the_app_actions(self):
        self.assertEqual(reader.action_groups("/a", []), [("/a", "")])

    def test_a_named_process_is_looked_up_by_its_name(self):
        self.assertEqual(reader.action_sources(["org.gnome.Nautilus"], "org.gnome.Nautilus"),
                         [("org.gnome.Nautilus", "/org/gnome/Nautilus")])

    def test_a_further_process_is_looked_up_by_the_window_app_id(self):
        self.assertEqual(reader.action_sources([":1.140"], "com.mitchellh.ghostty"),
                         [(":1.140", "/com/mitchellh/ghostty")])

    def test_an_app_id_that_is_not_one_gives_no_path(self):
        self.assertEqual(reader.action_sources([":1.9"], "libreoffice-writer"), [])

    def test_window_names(self):
        self.assertEqual(reader.window_names('<node><node name="1"/><node name="2"/></node>'), ["1", "2"])
        self.assertEqual(reader.window_names("not xml"), [])


class EntriesAndRunning(unittest.TestCase):
    def test_a_message_says_only_what_is_set(self):
        entries = reader.Entries(reader.to_nowhere)
        entries.add(["File"], "Save", "menu", reader.Press(ref("save")), key="Ctrl+S")
        self.assertEqual(entries.all[0].message(),
                         {"id": 0, "path": ["File"], "label": "Save", "key": "Ctrl+S", "kind": "menu"})

    def test_greyed_by_the_app_is_off_without_a_reason(self):
        entries = reader.Entries(reader.to_nowhere)
        entries.add([], "Redo", "menu", reader.Press(ref("redo")), enabled=False, checked=True)
        message = entries.all[0].message()
        self.assertTrue(message["off"] and message["on"])
        self.assertNotIn("why", message)

    def test_not_run_for_a_reason_is_off_with_it(self):
        entries = reader.Entries(reader.to_nowhere)
        entries.add([], "New tab", "action", reader.GtkAction("b", "/p", "new-tab"), why=reader.SEVERAL_WINDOWS)
        self.assertEqual(entries.all[0].message()["why"], reader.SEVERAL_WINDOWS)
        self.assertFalse(entries.all[0].runnable)

    def test_flush_sends_new_entries_in_lines_of_a_hundred(self):
        sent = []
        entries = reader.Entries(sent.append)
        for number in range(250):
            entries.add([], str(number), "menu", reader.Press(ref(str(number))))
        self.assertEqual(entries.flush(), 250)
        self.assertEqual([len(message["items"]) for message in sent], [100, 100, 50])
        entries.add([], "late", "menu", reader.Press(ref("late")))
        self.assertEqual(entries.flush(), 1)
        self.assertEqual(sent[-1]["items"][0]["id"], 250)
        self.assertEqual(entries.flush(), 0)

    def test_an_entry_that_is_off_is_never_run(self):
        entries = reader.Entries(reader.to_nowhere)
        entries.add([], "New tab", "action", reader.GtkAction("b", "/p", "new-tab"), why=reader.SAME_TITLE)
        entries.add([], "Redo", "menu", reader.Press(ref("redo")), enabled=False)
        for entry in entries.all:
            # No bus is given: reaching for one would raise.
            self.assertEqual(reader.run(entry, None, None), "that entry is not available")

    def test_commands(self):
        self.assertEqual(reader.parse_command("run 12\n"), ("run", 12))
        self.assertEqual(reader.parse_command("accessibility\n"), ("accessibility", 0))
        for junk in ("", "run", "run x", "run 1 2", "run -1", "quit"):
            self.assertEqual(reader.parse_command(junk), ("", 0))


if __name__ == "__main__":
    unittest.main()
