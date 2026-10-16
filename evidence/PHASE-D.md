# Phase D — usability: installer, in-game panel, activation modes (2026-10-15/16)

Goal: a player installs, starts the game, plays with gyro and tunes sensitivity and ADS with the controller only,
without console commands. Version 0.2.0. Game build 25372571, oak2-mod-manager 0.3, mods_base 1.12, keybinds 1.1.
Tester: the project owner, DualSense through Steam Input (`PS5`, ~49 motion packets/s), 1080p.

## Investigation (before choosing the UI)

| Question | Finding | Source |
|---|---|---|
| Graphical mod menu available? | No: oak2-mod-manager 0.3 ships `console_mod_menu` only | installed `sdk_mods/*.sdkmod` |
| Can the mod draw on a HUD canvas? | No: `HUD:ReceiveDrawHUD` never runs during gameplay | `B-calls-summary.txt` |
| Game UI tech | UMG (`GbxUIUMGTickWidget:BP_TickWidget` every frame) | `B-calls-summary.txt` |
| Why the mod started disabled | mods_base auto-enables only when the saved `enabled` is true; a new install has no file | `mods_base/mod.py`, `settings.py` |
| Persistence | `sdk_mods/settings/NativeGyro.json`: options by identifier, keybinds, `enabled` | mods_base, installed file |
| Default combo conflicts | every pad button has a gameplay action; L3 = sprint, R3 = melee, View = status menu, Menu = pause | `B-mappings.txt` |

## In-game spikes (probe F10, hot-reloaded)

| Check | Result |
|---|---|
| `WidgetBlueprintLibrary.Create(UserWidget)` + WidgetTree + Border/VerticalBox/TextBlock + `AddToViewport` | ✓ drawn by the game, text, font size and colors set from Python; viewport scale 0.5 at 1080p |
| keybinds hook (`UGbxEnhancedPlayerInput::InputKey`) | sees keyboard, mouse and the stick clicks (L3 + R3 combo opened the panel, its R3 press was blocked); **does not see** D-pad, face buttons, triggers, View/Menu |
| `PlayerController.IsInputKeyDown` | sees mouse/keyboard and L3 only, not the other pad buttons |
| `register_keybind(None, ...)` (catch-all) | not accepted by keybinds 1.1 (`key: str` required) |
| `EnhancedInputLocalPlayerSubsystem.HasMappingContext` / `RemoveMappingContext` | not exposed to reflection in this build |
| `GameplayStatics.SetGamePaused(pc, True)` | ✓ pauses (`IsGamePaused` True); a mouse click made while paused was replayed on unpause |
| Paused + pawn `DisableInput` | controller trigger no longer fires; View/Menu still opened game menus → also `pc.DisableInput(pc)` → ✓ |

Result: pad buttons are read by `bl4gyro.dll` (`bl4gyro_buttons`: XInput = Steam Input's virtual pad, or SDL for the
HID pad); the panel opens only in gameplay, pauses the game, disables pawn + controller input, and blocks every
keyboard/mouse key through the hook.

## Drift with gyro on (diagnosed from a trace)

Report: camera slowly turning left with the controller still. `trace.csv` (60 s, controller on the table, then held):

| Window | Raw gyro yaw (deg/s) | Camera yaw injected |
|---|---|---|
| on the table, every 5 s window | −0.005 … −0.009 | −4.13 … −4.17° per 5 s (≈ −0.83 deg/s) |
| held still | −0.087 … +0.060 | same −0.83 deg/s |

The DualSense through Steam arrives almost bias-free; the mod was subtracting a ~0.8 deg/s offset learned while the
controller was in the hand (the earlier calibrate-now runs and auto-calibration with the panel open). A
*Calibrate now* on the table removed the drift (tester). Fix: calibration only counts when the controller lies flat
and still (5 s countdown "lay it flat", 4 s measuring, rejected if the raw spread > 3 deg/s or not flat),
auto-calibration off while the panel is open, offset shown in Diagnostics and logged on every change.

## Automated tests (pass)

`build.cmd`: `core_tests` (incl. calibration ok/moved/not flat/progress/offset), `dll_replay` (incl. `bl4gyro_info`
and `bl4gyro_buttons`), `mod_logic` (precedence, combo, repeat, numbers, settings recovery/migration, menu),
`scripts` (package, install/update keeping settings, oak2 download refusals, uninstall keeping/removing settings,
other mods untouched).

## Manual checklist (in game, tester)

| Check | Result |
|---|---|
| First launch after updating from 0.1: mod on, welcome card once, settings kept (0.1 sensitivity 3.0 migrated) | ✓ |
| Panel drawn in the game UI, title "BORDERLANDS 4 GYRO - MAIN", fixed width, aligned columns | ✓ (after 5 layout rounds) |
| L3 + R3 opens the panel, no melee | ✓ |
| Navigation with D-pad / A / B, keyboard arrows / Enter / Esc | ✓ |
| Panel open: controller and keyboard/mouse don't act in game, no game menus, no replayed click after closing | ✓ |
| Sensitivity Grouped / Individual, ADS multiplier, live change | ✓ |
| Calibrate now: countdown, "Calibrated" on the table; drift gone | ✓ |
| Installed with `install.ps1` over 0.1 (settings kept, probe removed) | ✓ |
| Button hints follow the last device; real button names (Steam `GetActionOriginFromXboxOrigin` / SDL labels, so Steam's Nintendo-layout setting is respected) | pending |
| Activation modes ADS only / Hold button with a gyro button | pending |
| Unplug / replug the controller: message once, gyro back | pending |
| Installer window (`Install.cmd`): detection, Browse, game running warning, uninstall keeping settings | pending |
| Fresh install with no oak2-mod-manager (pinned download) | pending |
| TT Max (Switch mode) and Switch 2 Pro: button reading and hint names | pending |
