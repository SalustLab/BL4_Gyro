"""Phase B probe (dev only, not distributed). Keybinds stay here; the logic lives in impl.py and is
hot-reloaded with Insert, so experiments can change without restarting the game.

  F7 call logging  F8 snapshot  F9 gate watch  F10 UI/input spike  F5/Home per-frame tests D/E  Insert reload impl.py
"""

import importlib

from mods_base import build_mod, keybind

from . import impl


@keybind("Probe: toggle call logging", "F7")
def key_f7() -> None:
    impl.toggle_calls()


@keybind("Probe: snapshot", "F8")
def key_f8() -> None:
    impl.snapshot()


@keybind("Probe: test A", "F9")
def key_f9() -> None:
    impl.test_a()


@keybind("Probe: UI/input spike", "F10")
def key_f10() -> None:
    impl.ui_spike()


@keybind("Probe: test C", "F11")
def key_f11() -> None:
    impl.test_c()


@keybind("Probe: per-frame test D", "F5")
def key_f5() -> None:
    impl.test_d()


@keybind("Probe: per-frame test E", "Home")
def key_home() -> None:
    impl.test_e()


@keybind("Probe: reload impl", "Insert")
def key_insert() -> None:
    importlib.reload(impl)
    impl.on_reload()


mod = build_mod()
mod.enable()  # dev probe: no need to enable it through the menu
impl.on_reload()
