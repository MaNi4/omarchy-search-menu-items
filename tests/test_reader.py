"""python3 tests/test_reader.py — checks the parts of bin/search-menu-items
that need no app to talk to."""

import importlib.machinery
import importlib.util
import sys
import time
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


class PageMenus(unittest.TestCase):
    """A menu as a web page draws one: plain boxes, told apart by what they
    do when clicked."""

    def box(self, press="", **given):
        return Node(role=85, actions=2, press=press, state=state(reader.ENABLED), **given)

    def menu(self):
        menu, split, title, text, rename, words, icon = (ref(n) for n in "menu split title text rename words icon".split())
        nodes = {
            menu: self.box("click", children=[split, rename]),
            split: self.box("click", children=[icon, title]),
            icon: Node(role=27, actions=2, press="clickAncestor"),
            title: self.box("clickAncestor", children=[text]),
            text: Node(role=116, actions=2, press="clickAncestor", name="Split right"),
            rename: self.box("click", children=[words]),
            words: Node(role=116, actions=2, press="clickAncestor", name="Rename..."),
        }
        return nodes, menu, split, rename

    def test_the_innermost_things_that_take_a_click_are_the_choices(self):
        nodes, menu, split, rename = self.menu()
        self.assertEqual([(found, label) for found, label, _ in reader.choices(nodes, menu)],
                         [(split, "Split right"), (rename, "Rename...")])

    def test_a_named_button_is_a_choice_whatever_its_action_is_called(self):
        layer, button = ref("layer"), ref("button")
        nodes = {layer: self.box(children=[button]), button: Node(role=43, actions=1, press="press", name="Close")}
        self.assertEqual([label for _, label, _ in reader.choices(nodes, layer)], ["Close"])

    def test_what_takes_no_click_or_says_nothing_is_no_choice(self):
        layer, tip, blank = ref("layer"), ref("tip"), ref("blank")
        nodes = {
            layer: self.box(children=[tip, blank]),
            tip: Node(role=116, actions=2, press="clickAncestor", name="Opens the menu"),
            blank: self.box("click"),
        }
        self.assertEqual(list(reader.choices(nodes, layer)), [])

    def test_text_is_the_name_or_else_what_is_inside(self):
        nodes, menu, split, _ = self.menu()
        self.assertEqual(reader.text_of(nodes, split), "Split right")
        self.assertEqual(reader.text_of(nodes, menu), "Split right Rename...")
        nodes[split].name = "Split"
        self.assertEqual(reader.text_of(nodes, split), "Split")
        self.assertEqual(reader.text_of(nodes, ref("gone")), "")

    def layers(self, nodes, layer):
        class Read:
            def fetch(self, refs, **asked):
                return {found: nodes[found] for found in refs}
        return reader.read_drawn(Read(), [layer], float("inf"), False)

    def test_a_layer_of_choices_is_a_menu(self):
        nodes, menu, _, _ = self.menu()
        self.assertEqual([label for _, label, _ in self.layers(nodes, menu)], ["Split right", "Rename..."])

    def test_a_layer_with_a_field_to_fill_in_is_a_dialog(self):
        nodes, menu, _, _ = self.menu()
        field = ref("field")
        nodes[field] = Node(role=79)
        nodes[menu].children.append(field)
        self.assertEqual(self.layers(nodes, menu), [])

    def test_one_thing_to_click_is_a_notice(self):
        nodes, menu, split, _ = self.menu()
        nodes[menu].children = [split]
        self.assertEqual(self.layers(nodes, menu), [])

    def test_what_a_page_calls_a_menu_is_one_even_with_a_single_item(self):
        class Read:
            def fetch(self, refs, **asked):
                return {found: nodes[found] for found in refs}
        nodes, menu, split, _ = self.menu()
        nodes[menu].children = [split]
        self.assertEqual([label for _, label, _ in reader.read_drawn(Read(), [menu], float("inf"), True)],
                         ["Split right"])

    def drawn(self, roles):
        """A page with an app in it; `roles` are of what was drawn since: in
        the app, and over the page."""
        page, app, old, deep, sub, layer = (ref(n) for n in "page app old deep sub layer".split())
        nodes = {page: Node(children=[app, layer]), app: Node(children=[old, deep], role=85), old: Node(role=85),
                 deep: Node(children=[sub], role=roles[0]), sub: Node(role=roles[1]), layer: Node(role=roles[2])}
        parents = {app: page, layer: page, old: app, deep: app, sub: deep}
        return reader.drawn_menus(nodes, parents, {page, app, old}, page), deep, layer

    def test_what_the_page_calls_a_menu_is_found_wherever_it_is_drawn(self):
        found, deep, _ = self.drawn([reader.MENU, 85, 85])
        self.assertEqual(found, ([deep], True))

    def test_a_menu_inside_a_new_menu_is_part_of_it(self):
        found, deep, _ = self.drawn([reader.MENU, reader.MENU, 85])
        self.assertEqual(found, ([deep], True))

    def test_without_one_only_a_new_layer_over_the_page_may_be_a_menu(self):
        found, _, layer = self.drawn([85, 85, 85])
        self.assertEqual(found, ([layer], False))

    def test_shortcuts_are_taken_out_of_names(self):
        split = reader.split_shortcut
        self.assertEqual(split("Settings Ctrl+,"), ("Settings", "Ctrl+,"))
        self.assertEqual(split("Toggle Panel (Ctrl+J)"), ("Toggle Panel", "Ctrl+J"))
        self.assertEqual(split("Keyboard Shortcuts Ctrl+K Ctrl+S"), ("Keyboard Shortcuts", "Ctrl+K Ctrl+S"))
        self.assertEqual(split("Dictate (Speech to Text) (Ctrl+I)"), ("Dictate (Speech to Text)", "Ctrl+I"))
        self.assertEqual(split("Rename F2"), ("Rename F2", ""))
        self.assertEqual(split("Help (F1)"), ("Help", "F1"))
        for plain in ("More options", "Split Editor Right (Ctrl+\\) [Alt] Split Editor Down", "Ctrl+S", "C++ Tools"):
            self.assertEqual(split(plain), (plain, ""))


class Page:
    """Stands in for an app: a page with a More options button, and what a
    press of anything on it does."""

    def __init__(self, on_press=None, accepts=True):
        self.page, self.app, self.more = ref("page"), ref("app"), ref("more")
        self.nodes = {self.page: Node(children=[self.app]), self.app: Node(children=[], role=85)}
        self.on_press = on_press or (lambda: None)
        self.accepts = accepts
        self.pressed = []
        self.batch = self
        self.connection = self

    def fetch(self, refs, **asked):
        return {found: self.nodes.get(found, Node()) for found in refs}

    def call(self, bus, path, interface, method, arguments, reply_type, flags, timeout, cancellable, done):
        self.pressed.append(Ref(bus, path))
        self.on_press()
        done(self, None)

    def call_finish(self, result):
        return self

    def unpack(self):
        return (self.accepts,)

    def draw_menu(self, *labels, inside=None, role=85):
        """Draws a menu, as a press would have it do: over the page, or
        `inside` something on it."""
        holder = inside or self.page
        menu = ref("menu" + "".join(labels))
        items = [ref("item" + label) for label in labels]
        self.nodes[menu] = Node(children=items, role=role)
        for item, label in zip(items, labels):
            self.nodes[item] = Node(role=85, actions=2, press="click", name=label, state=state(reader.ENABLED))
        self.nodes[holder].children.append(menu)
        return holder, menu

    def button(self, entries):
        entries.add([], "More options", "button", reader.Press(self.more, self.page))
        return entries.all[-1]


class OpeningMenus(unittest.TestCase):
    def test_a_press_that_draws_a_menu_adds_its_items_below_the_button(self):
        page = Page()
        page.on_press = lambda: page.draw_menu("Split right", "Rename...")
        entries = reader.Entries(reader.to_nowhere)
        menu, error = reader.open_menu(page, page.button(entries), entries, [])
        self.assertEqual((error, page.pressed), ("", [page.more]))
        self.assertEqual(menu.drawn, [(page.page, ref("menuSplit rightRename..."))])
        self.assertEqual([(entry.path, entry.label, entry.opens) for entry in entries.all[1:]],
                         [(["More options"], "Split right", True), (["More options"], "Rename...", True)])

    def test_a_menu_the_page_names_is_found_inside_the_app_with_its_shortcuts(self):
        page = Page()
        page.on_press = lambda: page.draw_menu("Settings Ctrl+,", inside=page.app, role=reader.MENU)
        entries = reader.Entries(reader.to_nowhere)
        menu, _ = reader.open_menu(page, page.button(entries), entries, [])
        self.assertEqual(menu.drawn, [(page.app, ref("menuSettings Ctrl+,"))])
        self.assertEqual([(entry.label, entry.key) for entry in entries.all[1:]], [("Settings", "Ctrl+,")])

    def test_a_panel_that_opens_inside_the_app_is_no_menu(self):
        page = Page()
        page.on_press = lambda: page.draw_menu("Terminal", "Problems", inside=page.app)
        entries = reader.Entries(reader.to_nowhere)
        self.assertEqual(reader.open_menu(page, page.button(entries), entries, []), (None, ""))

    def test_a_press_that_draws_nothing_is_not_waited_on_for_long(self):
        page = Page()
        entries = reader.Entries(reader.to_nowhere)
        started = time.monotonic()
        self.assertEqual(reader.open_menu(page, page.button(entries), entries, []), (None, ""))
        self.assertLess(time.monotonic() - started, reader.MENU_WAIT)
        self.assertEqual(len(entries.all), 1)

    def test_a_layer_that_is_no_menu_adds_nothing(self):
        page = Page()
        page.on_press = lambda: page.draw_menu("Copied to the clipboard")
        entries = reader.Entries(reader.to_nowhere)
        self.assertEqual(reader.open_menu(page, page.button(entries), entries, []), (None, ""))
        self.assertEqual(len(entries.all), 1)

    def test_a_press_the_app_refuses_says_so(self):
        page = Page(accepts=False)
        entries = reader.Entries(reader.to_nowhere)
        self.assertEqual(reader.open_menu(page, page.button(entries), entries, []),
                         (None, "the app refused that action"))

    def test_a_choice_that_closes_the_open_menu_is_not_waited_on(self):
        page = Page()
        up = reader.Opened([page.draw_menu("Split right", "Rename...")])
        page.on_press = lambda: page.nodes[page.page].children.pop()
        entries = reader.Entries(reader.to_nowhere)
        started = time.monotonic()
        self.assertEqual(reader.open_menu(page, page.button(entries), entries, [up]), (None, ""))
        self.assertLess(time.monotonic() - started, reader.LAYER_WAIT)


class ClosingMenus(unittest.TestCase):
    def setUp(self):
        self.page = Page()
        self.sent = []
        self.kept = reader.send_escape
        self.addCleanup(setattr, reader, "send_escape", self.kept)

    def escapes(self, closes=True):
        def send(address):
            self.sent.append(address)
            if closes and len(self.page.nodes[self.page.page].children) > 1:
                self.page.nodes[self.page.page].children.pop()
        reader.send_escape = send

    def test_a_menu_still_up_gets_one_escape(self):
        self.escapes()
        opened = [reader.Opened([self.page.draw_menu("Split right", "Rename...")])]
        reader.close_menus(self.page, "0x55aa", opened)
        self.assertEqual((self.sent, opened), (["0x55aa"], []))

    def test_a_menu_that_is_gone_gets_none(self):
        self.escapes()
        opened = [reader.Opened([(self.page.page, ref("gone"))])]
        reader.close_menus(self.page, "0x55aa", opened)
        self.assertEqual((self.sent, opened), ([], []))

    def test_no_more_escapes_than_menus(self):
        self.escapes(closes=False)
        first = self.page.draw_menu("Split right", "Rename...")
        second = self.page.draw_menu("Left", "Right")
        reader.close_menus(self.page, "0x55aa", [reader.Opened([first]), reader.Opened([second])])
        self.assertEqual(len(self.sent), 2)

    def test_a_window_that_is_not_known_gets_none(self):
        self.escapes()
        reader.close_menus(self.page, "", [reader.Opened([self.page.draw_menu("A", "B")])])
        self.assertEqual(self.sent, [])


class TheFlag(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = self.folder.name + "/apps/code-flags.conf"

    def lines(self):
        return Path(self.path).read_text().splitlines()

    def test_it_is_added_to_a_file_that_is_not_there(self):
        self.assertFalse(reader.has_flag(self.path))
        self.assertTrue(reader.add_flag(self.path))
        self.assertEqual(self.lines(), [reader.ACCESSIBILITY_FLAG])
        self.assertTrue(reader.has_flag(self.path))

    def test_what_the_file_holds_is_kept(self):
        Path(self.path).parent.mkdir()
        Path(self.path).write_text("# mine\n--ozone-platform=wayland")
        reader.add_flag(self.path)
        self.assertEqual(self.lines(), ["# mine", "--ozone-platform=wayland", reader.ACCESSIBILITY_FLAG])

    def test_it_is_not_added_twice(self):
        reader.add_flag(self.path)
        reader.add_flag(self.path)
        self.assertEqual(self.lines(), [reader.ACCESSIBILITY_FLAG])

    def test_a_file_that_cannot_be_written_says_so(self):
        self.assertFalse(reader.add_flag("/proc/nowhere/flags.conf"))

    def test_a_program_no_launcher_is_known_for_is_not_set_up(self):
        import os
        self.assertIsNone(reader.launcher_of(os.getpid()))
        self.assertFalse(reader.flag_set(os.getpid()))

    def setting(self, before):
        path = self.folder.name + "/settings.json"
        if before is not None:
            Path(path).write_text(before)
        done = reader.set_setting(path, "editor.accessibilitySupport", "off")
        return done, Path(path).read_text()

    def test_a_setting_goes_into_a_file_that_is_not_there(self):
        self.assertEqual(self.setting(None), (True, '{\n  "editor.accessibilitySupport": "off"\n}\n'))

    def test_a_setting_goes_in_front_of_the_others_which_stay_as_they_are(self):
        before = '{ "workbench.colorTheme": "Gruvbox",\n  "update.mode": "none"\n}\n'
        self.assertEqual(self.setting(before),
                         (True, '{\n  "editor.accessibilitySupport": "off", "workbench.colorTheme": "Gruvbox",\n'
                                '  "update.mode": "none"\n}\n'))

    def test_comments_before_the_brace_and_an_empty_file_of_settings(self):
        self.assertEqual(self.setting("// mine\n{\n  // none yet\n}\n"),
                         (True, '// mine\n{\n  "editor.accessibilitySupport": "off"\n  // none yet\n}\n'))
        self.assertEqual(self.setting("{}"), (True, '{\n  "editor.accessibilitySupport": "off"}'))

    def test_a_setting_someone_chose_is_left_alone(self):
        before = '{ "editor.accessibilitySupport": "on" }'
        self.assertEqual(self.setting(before), (True, before))

    def test_a_file_that_is_no_settings_is_left_alone(self):
        self.assertEqual(self.setting("[1, 2]"), (False, "[1, 2]"))

    def test_what_is_written_is_still_settings(self):
        import json
        for before in (None, "{}", '{ "a": 1 }', '{\n  "a": 1,\n  "b": [2]\n}'):
            self.assertEqual(json.loads(self.setting(before)[1])["editor.accessibilitySupport"], "off")


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

    def test_a_button_of_a_page_may_open_a_menu(self):
        entries = reader.Entries(reader.to_nowhere)
        entries.add([], "More options", "button", reader.Press(ref("more"), ref("page")))
        entries.add([], "New tab", "action", reader.GtkAction("b", "/p", "new-tab"))
        self.assertIs(entries.all[0].message()["opens"], True)
        self.assertNotIn("opens", entries.all[1].message())

    def panes(self, titles):
        """A window of panes, each a header with a title, a button of its own
        and a More options; and a Close that is in none of them."""
        window = ref("window")
        nodes, parents = {window: Node(children=[])}, {}
        entries = reader.Entries(reader.to_nowhere)
        for number, title in enumerate(titles):
            pane, view, holder, text, more = (ref(f"{name}{number}") for name in "pane view holder text more".split())
            nodes.update({
                pane: Node(children=[view, holder, more], role=85),
                view: Node(role=43, name=f"View {number}"),
                holder: Node(children=[text], role=85),
                text: Node(role=116, name=title),
                more: Node(role=43, name="More options"),
            })
            nodes[window].children.append(pane)
            parents.update({pane: window, view: pane, holder: pane, more: pane, text: holder})
            entries.add([], f"View {number}", "button", reader.Press(view))
            entries.add([], "More options", "button", reader.Press(more))
        close = ref("close")
        nodes[close] = Node(role=43, name="Close")
        nodes[window].children.append(close)
        parents[close] = window
        entries.add([], "Close", "button", reader.Press(close))
        reader.place_buttons(entries.all, nodes, parents)
        return {(entry.label, entry.place) for entry in entries.all}, entries.all

    def test_buttons_with_one_label_say_which_pane_they_are_in(self):
        placed, entries = self.panes(["Welcome", "Graph view"])
        self.assertLessEqual({("More options", "Welcome"), ("More options", "Graph view")}, placed)
        self.assertEqual(entries[1].message()["place"], "Welcome")

    def test_the_other_buttons_of_a_pane_are_placed_with_them(self):
        placed, _ = self.panes(["Welcome", "Graph view"])
        self.assertLessEqual({("View 0", "Welcome"), ("View 1", "Graph view")}, placed)

    def test_a_button_in_no_pane_has_no_place(self):
        placed, entries = self.panes(["Welcome", "Graph view"])
        self.assertIn(("Close", ""), placed)
        self.assertNotIn("place", entries[-1].message())

    def test_panes_with_one_title_are_numbered_in_order(self):
        placed, _ = self.panes(["Welcome", "Graph view", "Welcome"])
        self.assertLessEqual({("More options", "Welcome"), ("More options", "Welcome 2"), ("View 2", "Welcome 2"),
                              ("More options", "Graph view")}, placed)

    def test_the_order_is_the_windows_not_the_one_buttons_were_read_in(self):
        window, left, right = ref("window"), ref("left"), ref("right")
        nodes = {window: Node(children=[left, right])}
        parents = {left: window, right: window}
        entries = reader.Entries(reader.to_nowhere)
        for pane in (right, left):  # the right pane's button was read first
            text, more = ref(f"text{pane.path}"), ref(f"more{pane.path}")
            nodes.update({pane: Node(children=[text, more], role=85), text: Node(role=116, name="Welcome"),
                          more: Node(role=43, name="More options")})
            parents.update({text: pane, more: pane})
            entries.add([], "More options", "button", reader.Press(more))
        reader.place_buttons(entries.all, nodes, parents)
        self.assertEqual([entry.place for entry in entries.all], ["Welcome 2", "Welcome"])

    def test_a_window_with_no_two_buttons_alike_places_none(self):
        placed, _ = self.panes(["Welcome"])
        self.assertEqual({place for _, place in placed}, {""})

    def test_fresh_gives_each_entry_once(self):
        entries = reader.Entries(reader.to_nowhere)
        entries.add([], "Save", "menu", reader.Press(ref("save")))
        self.assertEqual([entry.label for entry in entries.fresh()], ["Save"])
        self.assertEqual(entries.fresh(), [])
        self.assertEqual(entries.flush(), 0)

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
        self.assertEqual(reader.parse_command("open 3\n"), ("open", 3))
        self.assertEqual(reader.parse_command("back\n"), ("back", 0))
        self.assertEqual(reader.parse_command("flag\n"), ("flag", 0))
        for junk in ("", "run", "run x", "run 1 2", "run -1", "quit", "open", "open x", "back 1"):
            self.assertEqual(reader.parse_command(junk), ("", 0))


if __name__ == "__main__":
    unittest.main()
