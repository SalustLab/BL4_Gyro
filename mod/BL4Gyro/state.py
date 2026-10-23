"""Game-independent logic of the mod: injection precedence, the panel combo, held-key repeat, settings
sanitizing/migration and the panel's menu model. Nothing here imports unrealsdk, so tests/mod_logic_check.py runs it
outside the game.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

MODES = ("Always", "ADS only", "Hold button")
BUTTON_NAMES = ("Auto", "Xbox", "PlayStation", "Nintendo")
# Names of the buttons the panel uses, by controller family: (bottom face, right face, left shoulder, right shoulder).
# Positions are what the DLL reads (Xbox layout), so a Switch pad's bottom button is its B.
PAD_LABELS = {"Xbox": ("A", "B", "LB", "RB"), "PlayStation": ("X", "O", "L1", "R1"), "Nintendo": ("B", "A", "L", "R")}
COMBO_HOLD_S = 0.5
REPEAT_DELAY_S, REPEAT_EVERY_S = 0.4, 0.08


def should_inject(*, gyro_enabled: bool, panel_open: bool, calibrating: bool, mode: str, button_held: bool,
                  ads: bool, gate_open: bool) -> bool:
    """Precedence: gyro off > panel open > calibrating > game gate > mode. The gyro button enables gyro in Hold
    mode and suspends it in the other modes."""
    if not gyro_enabled or panel_open or calibrating or not gate_open:
        return False
    if mode == "Hold button":
        return button_held
    if button_held:
        return False
    return ads if mode == "ADS only" else True


def pad_family(controller: str) -> str:
    """From the source's controller type (Steam Input: PS5, SwitchProController...; SDL: ps5, switchpro...)."""
    name = controller.lower()
    if name.startswith("ps"):
        return "PlayStation"
    if "switch" in name or "joycon" in name:
        return "Nintendo"
    return "Xbox"


def pad_labels(choice: str, detected: list[str] | None, controller: str) -> tuple[str, ...]:
    """Hint names for the 'Button names' option: a fixed family wins (a Switch 2 pad through Switch2Connect is seen
    as a DualSense); Auto uses the DLL's names (Steam's mapping or SDL's labels), else the controller family."""
    if choice in PAD_LABELS:
        return PAD_LABELS[choice]
    return tuple(detected) if detected else PAD_LABELS[pad_family(controller)]


class Combo:
    """Opens the panel when all keys are held together for COMBO_HOLD_S; fires once per hold. Presses that arrive
    while another combo key is already down are blocked, so the second button never reaches the game."""

    def __init__(self, keys: tuple[str, ...]) -> None:
        self.keys = keys
        self.down: set[str] = set()
        self.since: float | None = None
        self.fired = False

    def press(self, key: str, now: float) -> bool:
        """Returns True when this press should be blocked."""
        block = bool(self.down - {key})
        self.down.add(key)
        if self.down >= set(self.keys) and self.since is None:
            self.since = now
        return block

    def release(self, key: str) -> None:
        self.down.discard(key)
        self.since = None
        if not self.down:
            self.fired = False

    def poll(self, now: float) -> bool:
        if self.since is not None and not self.fired and now - self.since >= COMBO_HOLD_S:
            self.fired = True
            return True
        return False


class Repeater:
    """Held navigation keys repeat after REPEAT_DELAY_S, every REPEAT_EVERY_S (own timer: does not depend on the
    game sending repeat events)."""

    def __init__(self) -> None:
        self.key: str | None = None
        self.next = 0.0

    def press(self, key: str, now: float) -> None:
        self.key, self.next = key, now + REPEAT_DELAY_S

    def release(self, key: str) -> None:
        if key == self.key:
            self.key = None

    def poll(self, now: float) -> str | None:
        if self.key is None or now < self.next:
            return None
        self.next = now + REPEAT_EVERY_S
        return self.key


def calibration_label(cal: int, progress: float, offset: tuple[float, ...], auto: bool) -> str:
    """Panel text from bl4gyro_info's calibration result and offset. Manual calibration isn't saved between sessions,
    so a new session shows what automatic calibration has learned (any non-zero offset)."""
    if cal == 0:
        if any(offset):
            return "Auto-calibrated"
        return "Calibrating automatically - rest the controller in a menu" if auto else "Not calibrated yet"
    return {1: f"Measuring {progress * 100:.0f}% - don't touch it",
            2: "Calibrated",
            3: "It moved - kept the old calibration. Try again.",
            4: "Not lying flat - kept the old calibration. Try again.",
            5: "No motion data - is the controller connected?"}.get(cal, "Not calibrated yet")


def parse_number(text: str) -> float | None:
    """Accepts '2.5', '2,5', ' 3 '. Returns None for anything that is not a finite number."""
    try:
        value = float(text.strip().replace(",", "."))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def snap(value: float, lo: float, hi: float, step: float) -> float:
    """Clamps to [lo, hi] and rounds to the step grid (from lo), without float noise."""
    value = min(max(value, lo), hi)
    value = lo + round((value - lo) / step) * step
    decimals = max(0, -math.floor(math.log10(step))) if step < 1 else 0
    return round(min(max(value, lo), hi), decimals + 2)


def sanitize(value: Any, default: Any, lo: float | None = None, hi: float | None = None,
             choices: tuple | None = None) -> Any:
    """Safe recovery for a value read from the settings file: wrong type or out of range -> clamped or default."""
    if choices is not None:
        return value if value in choices else default
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return default
    return min(max(value, lo), hi) if lo is not None and hi is not None else value


def first_run(settings: dict | None) -> bool:
    """mods_base only auto-enables mods whose saved 'enabled' is true; a missing file or key = first launch."""
    return not isinstance(settings, dict) or "enabled" not in settings


def link_vertical_default(saved_options: dict) -> bool | None:
    """Migration from 0.1 (separate sliders only): link the vertical axis only if both were equal, so the aim feels
    the same after the update. None = the file already has the option (or no file): keep it."""
    if "Link vertical" in saved_options or "Horizontal sensitivity" not in saved_options:
        return None
    return saved_options.get("Horizontal sensitivity") == saved_options.get("Vertical sensitivity", 2.0)


# --- panel menu model ---------------------------------------------------------------------------------------------

@dataclass
class Row:
    label: str
    kind: str  # toggle | choice | slider | action | section | info
    get: Callable[[], Any] = lambda: None
    set: Callable[[Any], None] | None = None
    help: str | Callable[[], str] = ""
    lo: float = 0.0
    hi: float = 1.0
    step: float = 0.1
    fine: float = 0.01
    choices: tuple = ()
    target: str = ""  # section opened by a 'section' row
    confirm: str = ""  # question asked before an action runs
    visible: Callable[[], bool] = lambda: True
    fmt: str = "{:.2f}"


@dataclass
class Menu:
    """Panel navigation independent of rendering. Sections are lists of rows; the open section and the focused row
    are remembered (position) so reopening returns to the same place."""

    sections: dict[str, list[Row]]
    section: str = "Main"
    index: int = 0
    trail: list[tuple[str, int]] = field(default_factory=list)
    asking: Row | None = None  # action waiting for confirmation
    entry: str | None = None  # numeric text being typed, None when not typing
    message: str = ""

    def rows(self) -> list[Row]:
        return [r for r in self.sections[self.section] if r.visible()]

    def focused(self) -> Row:
        rows = self.rows()
        self.index = min(max(self.index, 0), len(rows) - 1)
        return rows[self.index]

    def move(self, delta: int) -> None:
        if self.asking or self.entry is not None:
            return
        rows = self.rows()
        self.index = (self.index + delta) % len(rows)
        while rows[self.index].kind == "info" and any(r.kind != "info" for r in rows):
            self.index = (self.index + (1 if delta >= 0 else -1)) % len(rows)
        self.message = ""

    def adjust(self, direction: int, fine: bool = False) -> None:
        row = self.focused()
        if self.asking or self.entry is not None or row.set is None:
            return
        if row.kind == "toggle":
            row.set(not row.get())
        elif row.kind == "choice":
            i = row.choices.index(row.get()) if row.get() in row.choices else 0
            row.set(row.choices[(i + direction) % len(row.choices)])
        elif row.kind == "slider":
            row.set(snap(row.get() + direction * (row.fine if fine else row.step), row.lo, row.hi, row.fine))

    def confirm(self) -> str | None:
        """A / Enter. Returns 'run' after an action executed (or was confirmed), else None."""
        row = self.focused()
        if self.entry is not None:
            return self.commit_entry()
        if self.asking is not None:
            asked, self.asking = self.asking, None
            asked.set(None)
            return "run"
        if row.kind == "section":
            self.trail.append((self.section, self.index))
            self.section, self.index = row.target, 0
            self.move(0)
        elif row.kind == "action" and row.set is not None:
            if row.confirm:
                self.asking = row
            else:
                row.set(None)
                return "run"
        elif row.kind in ("toggle", "choice"):
            self.adjust(1)
        return None

    def back(self) -> bool:
        """B / Esc. Returns True when the panel should close."""
        if self.entry is not None:
            self.entry = None
            return False
        if self.asking is not None:
            self.asking = None
            return False
        if self.trail:
            self.section, self.index = self.trail.pop()
            return False
        return True

    def type_char(self, ch: str) -> None:
        """Keyboard digits on a slider start typing a value; A / Enter applies it."""
        if self.entry is None and self.focused().kind == "slider" and not self.asking:
            self.entry = ""
        if self.entry is not None and len(self.entry) < 8 and (ch.isdigit() or ch in ".,-"):
            self.entry += ch

    def erase(self) -> None:
        if self.entry:
            self.entry = self.entry[:-1]

    def commit_entry(self) -> None:
        row, text, self.entry = self.focused(), self.entry or "", None
        value = parse_number(text)
        if value is None:
            self.message = f"'{text}' is not a number"
        elif row.set is not None:
            row.set(snap(value, row.lo, row.hi, row.fine))
            if not row.lo <= value <= row.hi:
                self.message = f"Limited to {row.fmt.format(row.lo)} - {row.fmt.format(row.hi)}"
        return None

    def value_text(self, row: Row) -> str:
        if row.kind == "toggle":
            return "On" if row.get() else "Off"
        if row.kind == "slider":
            if self.entry is not None and row is self.focused():
                return f"[{self.entry}_]"
            return row.fmt.format(row.get())
        if row.kind in ("choice", "info"):
            return str(row.get())
        return ""
