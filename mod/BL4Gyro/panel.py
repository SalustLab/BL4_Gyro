"""In-game gyro panel: a UMG widget built by reflection (drawn by the game's own UI renderer).

Input, as measured in game: BL4 reads the controller through a path the keybinds hook and
IsInputKeyDown never see, so controller buttons come from bl4gyro.dll (bl4gyro_buttons) and cannot be blocked.
The panel therefore opens only during gameplay and pauses the game, which stops every device from acting on the
character. Keyboard and mouse do go through the keybinds hook: their gameplay keys are blocked while the panel is
open (a mouse click made while paused is otherwise replayed on unpause).
"""

from __future__ import annotations

import sys
import time

import unrealsdk
from keybinds.keybinds import deregister_keybind, register_keybind
from mods_base import EInputEvent, get_pc
from unrealsdk import logging
from unrealsdk.hooks import Block, Type, add_hook, remove_hook

from . import state

FRAME_HOOK = "/Script/Engine.CameraModifier:BlueprintModifyCamera"
HOOK_ID = "bl4_gyro_panel"  # separate from the camera hook: the panel keeps working if injection stops itself
TITLE = "BORDERLANDS 4 GYRO"
# bl4gyro_buttons bit per button (positional names, Xbox layout).
PAD_BITS = {"A": 0, "B": 1, "X": 2, "Y": 3, "View": 4, "Menu": 5, "L3": 6, "R3": 7, "LB": 8, "RB": 9,
            "D-pad Up": 10, "D-pad Down": 11, "D-pad Left": 12, "D-pad Right": 13, "LT": 14, "RT": 15}
COMBOS = {
    "L3 + R3": ("L3", "R3"),
    "LT + D-pad Up": ("LT", "D-pad Up"),
    "View + Menu": ("View", "Menu"),
    "LB + RB": ("LB", "RB"),
    "Off (F8 only)": (),
}
# The keybinds hook does see the stick clicks (measured: the L3 + R3 combo opened the panel and its R3 press was
# blocked), so those come from it too, which keeps the second click (melee) away from the game.
HOOK_KEYS = {"L3": "Gamepad_LeftThumbstick", "R3": "Gamepad_RightThumbstick"}
GYRO_BUTTONS = ("None", "L3", "R3", "LB", "RB", "LT", "RT", "D-pad Down", "View")
# No Menu: it opens the game's own pause menu. B goes back, and closes the panel from the first page.
PAD_NAV = {"D-pad Up": "up", "D-pad Down": "down", "D-pad Left": "left", "D-pad Right": "right", "A": "confirm",
           "B": "back", "LB": "fine_left", "RB": "fine_right"}
KEY_NAV = {
    "Up": "up", "Down": "down", "Left": "left", "Right": "right", "Enter": "confirm", "Escape": "back",
    "BackSpace": "erase", "Period": ".", "Comma": ",", "Decimal": ".", "Hyphen": "-", "Subtract": "-",
    **{name: str(i) for i, name in enumerate(("Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
                                              "Nine"))},
    **{f"NumPad{name}": str(i) for i, name in enumerate(("Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven",
                                                        "Eight", "Nine"))},
}
# Every keyboard/mouse key BL4 maps (from its input mappings) is blocked while the panel is open, so neither
# gameplay nor the game's menus react. Not the console key (F6, handled before this hook) nor the panel's own key.
KEY_SWALLOW = (
    *"ABCDEFGHIJKLMNOPQRSTUVWXYZ", "F1", "F2", "F3", "F4", "F5", "F7", "F8", "F9", "F10", "F11", "F12",
    "Tab", "CapsLock", "LeftShift", "RightShift", "LeftControl", "RightControl", "LeftAlt", "RightAlt", "SpaceBar",
    "Insert", "Delete", "Home", "End", "PageUp", "PageDown", "Pause", "Tilde", "Apostrophe", "Quote", "Semicolon",
    "Slash", "Backslash", "LeftBracket", "RightBracket", "Equals", "Add", "Multiply", "Divide", "NumLock",
    "LeftMouseButton", "RightMouseButton", "MiddleMouseButton", "ThumbMouseButton", "ThumbMouseButton2",
    "MouseScrollUp", "MouseScrollDown")
REPEATS = ("up", "down", "left", "right", "fine_left", "fine_right")
MOUSE_AXES = ("MouseX", "MouseY")  # only to notice the mouse (button hints switch to keyboard); never blocked
def _pad_labels() -> tuple[str, ...]:
    """(confirm, back, left shoulder, right shoulder) names, per the Button names option (state.pad_labels)."""
    g = _g()
    return state.pad_labels(g.button_labels.value, g.button_names(), g.status().split(" | ")[0])


def _hints(device: str) -> tuple[str, str, dict]:
    """(confirm, back, footer per row kind) for the last device used."""
    if device == "keyboard":
        return "Enter", "Esc", {"slider": "Left/Right adjust   type a number + Enter",
                                "toggle": "Enter or Left/Right change", "choice": "Left/Right change",
                                "action": "Enter run", "section": "Enter open"}
    ok, back, left, right = _pad_labels()
    return ok, back, {"slider": f"Left/Right adjust   {left}/{right} fine", "toggle": f"{ok} or Left/Right change",
                      "choice": "Left/Right change", "action": f"{ok} run", "section": f"{ok} open"}
ROWS_SHOWN = 11  # the longest pages (Main with individual sensitivities, Advanced)
TOAST_S = 5.0
# Slate units; the game scales them with the resolution (0.5 at 1080p), so the panel keeps its share of the screen.
FONT_TITLE, FONT_ROW, FONT_HELP, FONT_FOOTER = 46, 38, 30, 28
PANEL_W = 1840  # fixed width; the height fits the page (the help area always keeps 3 lines)
HELP_H = 3 * FONT_HELP * 1.45
# Fixed columns (the game font is not monospaced); VALUE_W fits "SwitchProController via Steam Input".
MARK_W, LABEL_W, VALUE_W = 50, 800, 900
ROW_PAD = 8  # above and below each row
WHITE, DIM, ACCENT, BG = (0.95, 0.95, 0.95, 1), (0.62, 0.65, 0.7, 1), (1.0, 0.78, 0.2, 1), (0.03, 0.035, 0.05, 0.92)

_p: dict = {"started": False, "open": False, "widget": None, "title": None, "rows": [], "help": None, "footer": None,
            "combo": state.Combo(()), "combo_handles": [], "key_handles": [], "repeat": state.Repeater(), "menu": None, "toast": None,
            "toast_until": 0.0, "last_draw": 0.0, "last_frame": 0.0, "notified": set(), "actions": [], "buttons": 0,
            "device": "pad",
            "paused_by_us": False, "quickstart_closed": False}


def _g():
    """The mod package (imported lazily: it imports this module first)."""
    return sys.modules[__package__]


def held(name: str) -> bool:
    """True while the named pad button is down (as of the last camera update)."""
    bit = PAD_BITS.get(name)
    return bit is not None and bool(_p["buttons"] >> bit & 1)


# --- input ----------------------------------------------------------------------------------------------------------

def _combo_callback(name: str):
    def cb(event):
        if event == EInputEvent.IE_Pressed:
            if _p["combo"].press(name, time.perf_counter()):
                _p.setdefault("combo_blocked", set()).add(name)
                return Block
        elif event == EInputEvent.IE_Repeat and name in _p.get("combo_blocked", set()):
            return Block
        elif event == EInputEvent.IE_Released:
            _p["combo"].release(name)
            _p.get("combo_blocked", set()).discard(name)
        return None
    return cb


def set_combo(name: str) -> None:
    for handle in _p["combo_handles"]:
        deregister_keybind(handle)
    _p["combo"] = state.Combo(COMBOS.get(name, COMBOS["L3 + R3"]))
    _p["combo_handles"] = ([register_keybind(HOOK_KEYS[k], None, _combo_callback(k))
                            for k in _p["combo"].keys if k in HOOK_KEYS] if _p["started"] else [])


def _pad(now: float) -> None:
    """Edges of the pad buttons: combo, and navigation while the panel is open."""
    before, now_bits = _p["buttons"], _g().buttons()
    _p["buttons"] = now_bits
    for name, bit in PAD_BITS.items():
        was, down = before >> bit & 1, now_bits >> bit & 1
        if was == down:
            continue
        if name in _p["combo"].keys and name not in HOOK_KEYS:  # hook keys are tracked by their callbacks
            _p["combo"].press(name, now) if down else _p["combo"].release(name)
        if down:
            _use_device("pad")
        action = PAD_NAV.get(name)
        if _p["open"] and action is not None:
            if down:
                _p["actions"].append(action)
                if action in REPEATS:
                    _p["repeat"].press(name, now)
            else:
                _p["repeat"].release(name)


def _use_device(device: str) -> None:
    """Button hints follow the last device used; redrawn on the next update."""
    if _p["device"] != device:
        _p["device"] = device
        _p["last_draw"] = 0.0


def _mouse_callback(_event) -> None:
    _use_device("keyboard")


def _key_callback(key: str, action: str | None):
    def cb(event):
        if event == EInputEvent.IE_Pressed:
            _use_device("keyboard")
        if event == EInputEvent.IE_Released:
            _p["repeat"].release(key)
            return None  # releases always reach the game: no stuck keys
        if event == EInputEvent.IE_Pressed and action is not None:
            # Run on the next camera update, not here: an action can change keybinds, which must not happen inside
            # the input hook's own dispatch.
            _p["actions"].append(action)
            if action in REPEATS:
                _p["repeat"].press(key, time.perf_counter())
        return Block
    return cb


def _act(action: str) -> None:
    menu: state.Menu = _p["menu"]
    if action == "up":
        menu.move(-1)
    elif action == "down":
        menu.move(1)
    elif action in ("left", "right", "fine_left", "fine_right"):
        menu.adjust(-1 if "left" in action else 1, fine=action.startswith("fine"))
    elif action == "confirm":
        menu.confirm()
    elif action == "back":
        if menu.back():
            close()
            return
    elif action == "close":
        close()
        return
    elif action == "erase":
        menu.erase()
    else:
        menu.type_char(action)
    _draw()


# --- widgets --------------------------------------------------------------------------------------------------------

def _color(rgba) -> object:
    return unrealsdk.make_struct("SlateColor", SpecifiedColor=unrealsdk.make_struct("LinearColor", R=rgba[0], G=rgba[1],
                                                                                    B=rgba[2], A=rgba[3]))


def _cosmetic(fn) -> None:
    """Layout niceties (spacing, wrapping, alignment): a failure must never stop the panel from opening."""
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        if not _p.get("cosmetic_error"):
            _p["cosmetic_error"] = True
            logging.warning(f"[BL4Gyro] panel layout: {type(e).__name__}: {e}")


def _margin(top: float = 0, bottom: float = 0) -> object:
    return unrealsdk.make_struct("Margin", Left=0, Top=top, Right=0, Bottom=bottom)


def _new_text(tree, size: int, rgba) -> object:
    t = unrealsdk.construct_object("TextBlock", tree)
    font = t.Font
    font.Size = size
    t.SetFont(font)
    t.SetColorAndOpacity(_color(rgba))
    return t


def _text(tree, box, size: int, rgba, gap: float = 0, below: float = 0) -> object:
    t = _new_text(tree, size, rgba)
    slot = box.AddChildToVerticalBox(t)
    if gap or below:
        _cosmetic(lambda: slot.SetPadding(_margin(top=gap, bottom=below)))
    return t


def _column(tree, line, width: float, size: int, centered: bool = False) -> object:
    box = unrealsdk.construct_object("SizeBox", tree)
    _cosmetic(lambda: box.SetWidthOverride(width))
    text = _new_text(tree, size, WHITE)
    if centered:
        _cosmetic(lambda: text.SetJustification(1))  # ETextJustify::Center
    box.SetContent(text)
    line.AddChildToHorizontalBox(box)
    return text


def _row(tree, box) -> tuple[object, object, object, object]:
    """One menu row in three fixed columns: focus marker, label, centred value."""
    line = unrealsdk.construct_object("HorizontalBox", tree)
    _cosmetic(lambda: box.AddChildToVerticalBox(line).SetPadding(_margin(top=ROW_PAD, bottom=ROW_PAD)))
    mark = _column(tree, line, MARK_W, FONT_ROW)
    label = _column(tree, line, LABEL_W, FONT_ROW)
    value = _column(tree, line, VALUE_W, FONT_ROW, centered=True)
    return line, mark, label, value


def _widget(pc, width: float | None = None) -> tuple[object, object, object]:
    """UserWidget > [SizeBox of a fixed width] > Border > VerticalBox; the caller adds the texts, then _show()."""
    lib = unrealsdk.find_class("WidgetBlueprintLibrary").ClassDefaultObject
    widget = lib.Create(pc, unrealsdk.find_class("UserWidget"), pc)
    tree = widget.WidgetTree
    border = unrealsdk.construct_object("Border", tree)
    box = unrealsdk.construct_object("VerticalBox", tree)
    if width is None:
        tree.RootWidget = border
    else:
        frame = unrealsdk.construct_object("SizeBox", tree)
        frame.SetWidthOverride(width)
        frame.SetContent(border)
        tree.RootWidget = frame
    border.SetContent(box)
    border.SetBrushColor(unrealsdk.make_struct("LinearColor", R=BG[0], G=BG[1], B=BG[2], A=BG[3]))
    border.SetPadding(unrealsdk.make_struct("Margin", Left=40, Top=28, Right=40, Bottom=28))
    return widget, tree, box


def _show(widget, pc, anchor: tuple[float, float]) -> None:
    """Adds to the viewport centred on a relative anchor (the game's DPI scaling applies)."""
    widget.AddToViewport(100)
    layout = unrealsdk.find_class("WidgetLayoutLibrary").ClassDefaultObject
    viewport = layout.GetViewportSize(pc)
    widget.SetAlignmentInViewport(unrealsdk.make_struct("Vector2D", X=anchor[0], Y=anchor[1]))
    widget.SetPositionInViewport(unrealsdk.make_struct("Vector2D", X=viewport.X * anchor[0],
                                                       Y=viewport.Y * anchor[1]), True)


def _remove(widget) -> None:
    if widget is not None:
        try:
            widget.RemoveFromParent()
        except Exception:  # noqa: BLE001 - already gone with a level change
            pass


def _set(text_block, value: str, rgba=None) -> None:
    text_block.SetText(value)
    if rgba is not None:
        text_block.SetColorAndOpacity(_color(rgba))


def _draw() -> None:
    if not _p["open"]:
        return
    menu: state.Menu = _p["menu"]
    rows = menu.rows()
    focus = menu.focused()
    first = max(0, min(menu.index - ROWS_SHOWN // 2, len(rows) - ROWS_SHOWN))
    visible = rows[first:first + ROWS_SHOWN]
    _set(_p["title"], f"{TITLE} - {menu.section.upper()}")
    for i, (line, mark_block, label_block, value_block) in enumerate(_p["rows"]):
        shown = i < len(visible)
        if shown != _p["rows_shown"][i]:  # unused rows collapse (1), so the help text follows the list; visible (0)
            _cosmetic(lambda line=line, shown=shown: line.SetVisibility(0 if shown else 1))
            _p["rows_shown"][i] = shown
        if not shown:
            continue
        row = visible[i]
        focused = row is focus
        value = menu.value_text(row)
        if row.kind in ("slider", "toggle", "choice") and focused and menu.entry is None:
            value = f"<   {value}   >"
        elif row.kind == "section":
            value = ">>"
        rgba = ACCENT if focused else (DIM if row.kind == "info" else WHITE)
        _set(mark_block, ">" if focused else "", rgba)
        _set(label_block, row.label, rgba)
        _set(value_block, value, rgba)
    confirm, back, footers = _hints(_p["device"])
    if menu.asking is not None:
        help_text = f"{menu.asking.confirm}   {confirm}: yes   {back}: no"
    elif menu.message:
        help_text = menu.message
    else:
        help_text = focus.help() if callable(focus.help) else focus.help
    _set(_p["help"], help_text)
    _set(_p["footer"], f"{footers.get(focus.kind, '')}      {back} {'back' if menu.trail else 'close'}")
    _p["last_draw"] = time.perf_counter()


# --- open / close ---------------------------------------------------------------------------------------------------

def is_open() -> bool:
    return _p["open"]


# Public open/close/toggle only queue a request: they are also called from keybind callbacks, and registering or
# removing keybinds inside the input hook's own dispatch is not safe. The frame hook applies it.
def open(section: str | None = None) -> None:  # noqa: A001 - module API: panel.open()
    _p["request"] = ("open", section)


def close() -> None:
    _p["request"] = ("close", None)


def toggle() -> None:
    _p["request"] = ("close" if _p["open"] else "open", None)


def _apply_request() -> None:
    request = _p.pop("request", None)
    if request is not None:
        (_open_now(request[1]) if request[0] == "open" else _close_now())


def _open_now(section: str | None = None) -> None:
    if _p["open"] or not _p["started"]:
        return
    pc = get_pc(possibly_loading=True)
    if pc is None:
        return
    statics = _g()._state["statics"]
    # Controller presses can't be blocked, so a game menu behind the panel would react to them.
    if pc.bShowMouseCursor or statics.IsGamePaused(pc):
        toast("open the gyro panel during gameplay (close the game menu first).")
        return
    if _p["menu"] is None:
        _p["menu"] = _build_menu()
    if section is not None:
        _p["menu"].section, _p["menu"].index, _p["menu"].trail = section, 0, []
        _p["menu"].move(0)  # first selectable row
    try:
        widget, tree, box = _widget(pc, PANEL_W)
        title = _text(tree, box, FONT_TITLE, ACCENT, below=24)
        rows = [_row(tree, box) for _ in range(ROWS_SHOWN)]
        help_area = unrealsdk.construct_object("SizeBox", tree)  # 3 lines kept, so the height never jumps
        _cosmetic(lambda: help_area.SetHeightOverride(HELP_H))
        _cosmetic(lambda: box.AddChildToVerticalBox(help_area).SetPadding(_margin(top=20)))
        help_block = _new_text(tree, FONT_HELP, DIM)
        help_area.SetContent(help_block)
        _cosmetic(lambda: help_block.SetAutoWrapText(True))
        footer = _text(tree, box, FONT_FOOTER, DIM, gap=10)
        _show(widget, pc, (0.5, 0.5))
    except Exception as e:  # noqa: BLE001
        logging.error(f"[BL4Gyro] could not open the panel: {type(e).__name__}: {e}")
        return
    _p.update(open=True, widget=widget, title=title, rows=rows, rows_shown=[True] * len(rows), help=help_block,
              footer=footer, actions=[], pc=pc)
    keys = dict(KEY_NAV)
    panel_key = _g().open_panel_key.key
    keys.update({k: None for k in KEY_SWALLOW if k not in keys and k != panel_key})
    _p["key_handles"] = [register_keybind(k, None, _key_callback(k, a)) for k, a in keys.items()]
    _p["key_handles"] += [register_keybind(k, None, _mouse_callback) for k in MOUSE_AXES]
    _p["paused_by_us"] = bool(statics.SetGamePaused(pc, True))
    # Pausing alone does not stop every controller action in BL4 (measured: the trigger still fired, View/Menu
    # opened game menus). Disabling the pawn's and the player controller's input stops it for every device; the
    # panel itself reads the pad through the DLL and the keyboard through the keybinds hook, both before this.
    pawn = pc.Pawn
    if pawn is not None:
        _cosmetic(lambda: pawn.DisableInput(pc))
    _cosmetic(lambda: pc.DisableInput(pc))
    _p["input_pawn"] = pawn
    if not _p["paused_by_us"]:  # e.g. online co-op: at least keep the character still
        pc.SetIgnoreMoveInput(True)
        pc.SetIgnoreLookInput(True)
    logging.info(f"[BL4Gyro] panel open (game paused by the panel: {_p['paused_by_us']})")
    _g().panel_changed()
    _draw()


def _close_now() -> None:
    if not _p["open"]:
        return
    _p["open"] = False
    _p["actions"] = []
    for handle in _p["key_handles"]:
        deregister_keybind(handle)
    _p["key_handles"] = []
    _p["repeat"] = state.Repeater()
    pc = _p.pop("pc", None)
    pawn = _p.pop("input_pawn", None)
    if pc is not None:
        _cosmetic(lambda: pc.EnableInput(pc))
        if pawn is not None:
            _cosmetic(lambda: pawn.EnableInput(pc))
    try:
        if _p["paused_by_us"]:
            _g()._state["statics"].SetGamePaused(pc, False)
        elif pc is not None:
            pc.SetIgnoreMoveInput(False)  # counted by the engine: one False per True
            pc.SetIgnoreLookInput(False)
    except Exception:  # noqa: BLE001 - the controller can be gone after a level change
        pass
    _p["paused_by_us"] = False
    _remove(_p["widget"])
    _p["widget"] = None
    menu = _p["menu"]
    if menu is not None:
        menu.entry, menu.asking, menu.message = None, None, ""
        if menu.section == "Quickstart":  # closed without Got it: the combo reopens it, auto-opens next launch
            _p["quickstart_closed"] = True
    _g().panel_changed()
    _g().save_now()


def _intro_seen() -> None:
    g = _g()
    g.ui.value = {**g.ui.value, "intro_seen": True}


def toast(message: str) -> None:
    """One short line at the top of the screen for a few seconds (state changes only, never repeated)."""
    pc = get_pc(possibly_loading=True)
    if pc is None:
        return
    _remove(_p["toast"])
    try:
        widget, tree, box = _widget(pc)
        _text(tree, box, FONT_HELP, WHITE).SetText(f"Borderlands 4 Gyro: {message}")
        _show(widget, pc, (0.5, 0.08))
        _p.update(toast=widget, toast_until=time.perf_counter() + TOAST_S)
    except Exception as e:  # noqa: BLE001
        logging.error(f"[BL4Gyro] toast failed: {type(e).__name__}: {e}")
    logging.info(f"[BL4Gyro] {message}")


def _notify_once(key: str, active: bool, message: str) -> None:
    if active and key not in _p["notified"]:
        _p["notified"].add(key)
        toast(message)
    elif not active:
        _p["notified"].discard(key)


def _watch(now: float) -> None:
    """Clear messages for missing controller / data and a stopped hook, each once per occurrence."""
    g = _g()
    info = g.info()
    running_s = now - g._state["started_at"]
    _notify_once("no_controller", running_s > 8 and info["source"] in (0, 4),
                 "no controller with gyro found. Connect it (in Steam Input or HID mode).")
    _notify_once("no_data", g._state["gate_open"] and g.gyro_enabled.value and info["source"] in (1, 2)
                 and info["since_packet"] > 3, "the controller sends no motion data. Is the game window focused?")
    _notify_once("stopped", g._state["stopped"], "gyro stopped after repeated errors. Open the panel > Diagnostics.")
    if (not g.ui.value.get("intro_seen") and not _p["quickstart_closed"] and g._state["gate_open"] and not _p["open"]
            and "request" not in _p):
        open("Quickstart")


def _on_frame(_obj, _args, _ret, _func) -> None:
    now = time.perf_counter()
    if now - _p["last_frame"] < 0.001:
        return
    _p["last_frame"] = now
    try:
        _pad(now)
        if _p["combo"].poll(now):
            toggle()
        _apply_request()
        if _p["open"]:
            actions, _p["actions"] = _p["actions"], []
            action_key = _p["repeat"].poll(now)
            if action_key is not None:
                actions.append(PAD_NAV.get(action_key) or KEY_NAV[action_key])
            for action in actions:
                try:
                    _act(action)  # draws after each action
                except Exception as e:  # noqa: BLE001 - one bad action must not freeze the panel
                    logging.error(f"[BL4Gyro] panel: {type(e).__name__}: {e}")
            _apply_request()  # B / Menu close in the same update
            if _p["open"] and now - _p["last_draw"] > 0.25:  # live values: status, calibration progress
                _draw()
        if _p["toast"] is not None and now > _p["toast_until"]:
            _remove(_p["toast"])
            _p["toast"] = None
        _watch(now)
    except Exception as e:  # noqa: BLE001
        if not _p.get("frame_error"):
            _p["frame_error"] = True
            logging.error(f"[BL4Gyro] panel update failed: {type(e).__name__}: {e}")


def start(combo_name: str) -> None:
    _p.update(started=True, notified=set(), buttons=0, combo_blocked=set())
    set_combo(combo_name)
    add_hook(FRAME_HOOK, Type.PRE, HOOK_ID, _on_frame)


def stop() -> None:
    _p.pop("request", None)
    _close_now()
    remove_hook(FRAME_HOOK, Type.PRE, HOOK_ID)
    for handle in _p["combo_handles"]:
        deregister_keybind(handle)
    _p["combo_handles"] = []
    _remove(_p["toast"])
    _p["toast"] = None
    _p["started"] = False


# --- menu content ---------------------------------------------------------------------------------------------------

def _option_row(option, kind: str, label: str | None = None, **extra) -> state.Row:
    def setter(value) -> None:
        option.value = value

    if kind == "slider":
        extra.setdefault("lo", option.min_value)
        extra.setdefault("hi", option.max_value)
        extra.setdefault("step", option.step)
        extra.setdefault("fine", option.step / 10 if option.step >= 0.1 else option.step)
    if kind == "choice":
        extra.setdefault("choices", tuple(option.choices))
    extra.setdefault("help", option.description)
    return state.Row(label or option.display_name, kind, lambda: option.value, setter, **extra)


def _copy_diagnostics(_value) -> None:
    import ctypes

    text = _g().diagnostics()
    data = text.encode("utf-16-le") + b"\0\0"
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    ok = False
    if user32.OpenClipboard(None):
        try:
            user32.EmptyClipboard()
            handle = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
            if handle:
                ctypes.memmove(kernel32.GlobalLock(handle), data, len(data))
                kernel32.GlobalUnlock(handle)
                ok = bool(user32.SetClipboardData(13, handle))  # CF_UNICODETEXT; the clipboard owns it now
        finally:
            user32.CloseClipboard()
    _p["menu"].message = "Copied to the clipboard." if ok else "Could not open the clipboard."
    logging.info(f"[BL4Gyro] diagnostics:\n{text}")


def _build_text() -> str:
    g = _g()
    build = g._installed_build()
    return f"{build} (tested)" if build == g.TESTED_BUILD else f"{build} (tested {g.TESTED_BUILD})"


def _controller_text() -> str:
    g = _g()
    info = g.info()
    source = g.SOURCES[info["source"]] if 0 <= info["source"] < len(g.SOURCES) else "?"
    name = g.status().split(" | ")[0]
    if info["source"] in (1, 2):
        return f"{name} via {source}" if info["since_packet"] >= 0 else f"{name} (no motion yet)"  # fits VALUE_W
    return source


CALIBRATE_HELP = ("Hold the controller still or rest it on a table (most accurate). You get 5 seconds, then it "
                  "measures for 4 seconds. If it moves, the old calibration stays.")


def _build_menu() -> state.Menu:
    g = _g()
    status_row = state.Row("Controller", "info", _controller_text)

    def grouped() -> bool:
        return bool(g.link_vertical.value)

    def individual() -> bool:
        return not g.link_vertical.value

    def intro_done(_value) -> None:
        _intro_seen()
        menu.section, menu.index, menu.trail = "Main", 0, []

    def calibrate(_value) -> None:
        g.start_calibration()

    def switch_hint() -> str:
        return ("TT Max / Switch-style pads: use Switch mode for gyro."
                if "Switch" in g.status() or g.info()["source"] == 0 else "")

    calibrate_row = state.Row("Calibrate now", "action", set=calibrate, help=CALIBRATE_HELP)
    names_row = _option_row(g.button_labels, "choice")
    menu = state.Menu({
        "Quickstart": [
            state.Row("Gyro", "info", lambda: "on" if g.gyro_enabled.value else "off"),
            status_row,
            names_row,
            state.Row("Open this panel", "info", lambda: f"hold {g.combo.value} or press F8"),
            state.Row("Tip", "info", switch_hint, visible=lambda: bool(switch_hint())),
            calibrate_row,
            state.Row("Calibration", "info", g.calibration_text),
            state.Row("Got it", "action", set=intro_done, help="This screen is shown only once."),
        ],
        "Main": [
            _option_row(g.gyro_enabled, "toggle", "Gyro"),
            _option_row(g.mode, "choice"),
            state.Row("Sensitivity", "choice", lambda: "Grouped" if g.link_vertical.value else "Individual",
                      lambda v: setattr(g.link_vertical, "value", v == "Grouped"), choices=("Grouped", "Individual"),
                      help="Grouped: one sensitivity for both directions. Individual: horizontal and vertical "
                           "separately."),
            _option_row(g.sens_x, "slider", "Sensitivity (both directions)", fmt="{:.2f}", visible=grouped,
                        help="Camera degrees per degree you turn or tilt the controller."),
            _option_row(g.sens_x, "slider", fmt="{:.2f}", visible=individual),
            _option_row(g.sens_y, "slider", fmt="{:.2f}", visible=individual),
            _option_row(g.ads_multiplier, "slider", fmt="x{:.2f}", fine=0.01),
            calibrate_row,
            state.Row("Calibration", "info", g.calibration_text),
            status_row,
            state.Row("Advanced", "section", target="Advanced", help="Invert, gyro space, smoothing, buttons."),
            state.Row("Diagnostics", "section", target="Diagnostics", help="Controller source, rates, debug tools."),
        ],
        "Advanced": [
            _option_row(g.invert_x, "toggle"),
            _option_row(g.invert_y, "toggle"),
            _option_row(g.space, "choice"),
            _option_row(g.auto_calibrate, "toggle"),
            _option_row(g.smoothing, "slider", fine=0.1, fmt="{:.1f}"),
            _option_row(g.tighten, "slider", fine=0.1, fmt="{:.1f}"),
            _option_row(g.gyro_button, "choice"),
            _option_row(g.combo, "choice"),
            names_row,
            state.Row("Panel key (keyboard)", "info", lambda: g.open_panel_key.key or "none"),
            state.Row("Restore defaults", "action", set=lambda _v: g.restore_defaults(),
                      confirm="Restore every gyro setting to its default?",
                      help="Sensitivity, ADS, mode, buttons and advanced settings go back to defaults."),
        ],
        "Diagnostics": [
            status_row,
            state.Row("Motion packets/s", "info", lambda: f"{g.info()['packets']:.0f}"),
            state.Row("Gyro offset (deg/s)", "info", lambda: "{:+.2f} {:+.2f} {:+.2f}".format(*g.info()["offset"])),
            state.Row("Camera hook", "info", lambda: "stopped after errors" if g._state["stopped"] else "running"),
            state.Row("Restart gyro", "action", set=lambda _v: g.restart_injection(),
                      visible=lambda: g._state["stopped"], help="Re-attaches the gyro to the camera after it stopped."),
            state.Row("Game build", "info", _build_text),
            _option_row(g.debug_trace, "toggle"),
            state.Row("Copy diagnostics", "action", set=_copy_diagnostics,
                      help="Copies version, controller source, rates and settings (no personal data)."),
        ],
    })
    return menu
