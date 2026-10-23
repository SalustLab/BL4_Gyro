# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Borderlands 4 Gyro (**BL4 Gyro**): gyro aim for Borderlands 4 (PC, Steam). The controller's real gyro is added to the
game camera through the game's own look input (`AddYawInput`/`AddPitchInput`); there is no mouse or stick emulation.
Tested controllers: GuliKit TT Max in Switch mode (via Steam Input), DualSense (HID or Steam Input) and Switch 2 Pro
via Switch2Connect (HID). The tested game build is Steam `25372571` (`TESTED_BUILD` in the mod).

Names: mod folder and module `BL4Gyro`, settings `BL4Gyro.json`, log prefix `[BL4Gyro]`, release
`bl4-gyro_<version>.zip`. Never use the old name "NativeGyro" / "Native Gyro".

Everything is in **English**: code, comments, identifiers, `README.md`, in-game text and commit messages. Commit
subjects start with the project phase, e.g. `D: ...` (C = the mod, D = usability: panel, modes, release).

The repo is public and minimal: keep it to what builds, tests and ships the mod. No local paths, machine details,
captures or evidence files (`/captures/`, `trace.csv`, `replay.csv` are git-ignored).

## Commands

Windows only. The build uses MSVC, CMake 3.24+ and Ninja.

```
build.cmd                 # vswhere -> vcvars64 -> cmake --preset release, build, ctest
build.cmd -R core_tests   # extra args are passed to ctest
```

From PowerShell or bash, run it as `cmd /c build.cmd`. The `release` preset is `RelWithDebInfo` and builds into
`build\release\`: `bl4gyro.dll` (with `SDL3.dll` copied next to it) and `core_tests.exe`.

There are four CTest tests:
- `core_tests` (`tests/core_tests.cpp`) uses a homemade `CHECK` macro and has no filter. Each test is a function
  called from `main()`, so a new test has to be added to that list.
- `dll_replay` (`python -I tests\dll_replay_check.py build\release\bl4gyro.dll`) drives the DLL through ctypes with
  the replay backend. It checks that the camera total is the same at 30 and 144 fps, and `bl4gyro_info` (source,
  calibration result). It is registered only if CMake finds Python 3.
- `mod_logic` (`python -I tests\mod_logic_check.py`) runs `mod/BL4Gyro/state.py` outside the game: injection
  precedence, combo, key repeat, number parsing, settings recovery/migration, button names, the panel's menu model.
  Also needs Python 3.
- `scripts` (`tests\scripts_check.ps1`) builds the release zip, checks its exact entries (all under
  `sdk_mods/BL4Gyro/`, `/` separators), then extracts it over an older install in a fake game folder (files match
  the build, every mod's settings kept). It needs the built DLL.

No linter or formatter is configured. The C++ builds with `/W4 /permissive-`.

Release:
- There is no installer. Players install oak2-mod-manager themselves, then extract the release zip into the
  Borderlands 4 folder; uninstall is deleting `sdk_mods\BL4Gyro`. Dev installs do the same with
  `Expand-Archive dist\bl4-gyro_<v>.zip "<game folder>" -Force`.
- `scripts\package.ps1` (run after `build.cmd`) writes `dist\bl4-gyro_<__version__>.zip` and prints SHA-256
  hashes. The version comes from `__version__` in `mod/BL4Gyro/__init__.py`. Every entry is
  `sdk_mods/BL4Gyro/<file>` with `/` separators (built with `System.IO.Compression`, not `Compress-Archive`,
  which writes `\` on PowerShell 5.1). The zip never contains `sdk_mods/settings`, so extracting over an install keeps
  the settings. A file the package needs must be added to `package.ps1` and to the expected list in
  `tests\scripts_check.ps1`.

## Architecture

The mod has two halves joined by a small C interface (`BL4GYRO_API` exports, loaded with ctypes):

1. **`bl4gyro.dll`** (`core/bl4gyro.cpp` on top of the `gyro_core` static lib). It runs a sensor thread at about
   1 kHz that polls `ISteamInput::GetMotionData` through the game's already-loaded `steam_api64.dll`, using flat
   exports with no Steamworks SDK (`core/steam_motion.*`). When Steam Input hands the game no controller (e.g. a
   DualSense with Steam Input off), or lists one that sends no motion for `kSteamSilentS` = 3 s while the game has
   focus (that handle is then skipped until it disconnects), it falls back to the pad's HID through SDL3 (HIDAPI drivers only, one source
   at a time, `gyro::from_sdl`, repeated `sensor_timestamp`s dropped). A new packet goes through `gyro::from_steam`,
   then `gyro::Processor` (GamepadMotionHelpers: calibration, Player/Local space, tightening, smoothing), then
   `gyro::RateHold`.
2. **`mod/BL4Gyro/__init__.py`** is an sdkmod that runs in oak2-mod-manager's embedded Python. It hooks
   `CameraModifier:BlueprintModifyCamera` on the game thread. On each camera update it reads the gate and ADS
   state, calls `bl4gyro_take`, decides with `state.should_inject` (gyro enabled, panel open, calibrating, activation
   mode, gyro button, gate), then calls `AddYawInput(yaw / 2.5)` and `AddPitchInput(pitch / -2.5)`.
   **`panel.py`** is the in-game panel: a UMG `UserWidget` built by reflection (the game draws it with its own UI
   renderer and DPI scaling), toasts and the Quickstart page. Keyboard/mouse and the L3/R3 combo come from oak2's
   `keybinds` module (`register_keybind`, `Block`); the other pad buttons from `bl4gyro_buttons` (that hook doesn't
   see them in BL4, so they can't be blocked: the panel opens only in gameplay, pauses the game and disables pawn +
   controller input). It has its own hook id on the same camera-update hook, so it keeps working if the camera hook
   removes itself. **`state.py`** holds all the logic that doesn't need the game and imports no unrealsdk.

Terms: the **gate** is "camera input may be injected now"; a **motion packet** is one sensor reading; **rate hold**
is the delivery described below.

### Cross-file contracts

- **Settings are passed by string key.** `bl4gyro_set(key, double)` maps keys onto `gyro::Settings`/`gyro::Camera`
  and returns 0 for an unknown key. The mod ignores that return value, so a typo fails silently. Adding an option
  takes all of these: the struct field in `core/gyro.hpp`, a branch in `bl4gyro_set`, the option in the mod, a
  line in `_push_settings()`, its tuple in `SLIDERS`/`BOOLS`/`SPINNERS` (recovery and restore defaults), and a row
  in `panel._build_menu()`. Mod-only options (mode, gyro enabled, combo, button names) skip the DLL steps.
- **Option identifiers are saved keys.** mods_base stores options by identifier in
  `sdk_mods/settings/BL4Gyro.json`. Never rename an identifier (change `display_name` instead); a renamed or new
  meaning needs a migration like `state.link_vertical_default`. First run = no `enabled` key (`state.first_run`).
- **`bl4gyro_info`** returns numbers by position (source, packets/s, seconds since the last packet, calibration
  progress, calibration result, gyro offset x/y/z); the mod's `info()` names them. Keep the order documented in
  `core/bl4gyro.cpp`. **`bl4gyro_buttons`** bits are listed there and in `panel.PAD_BITS`; keep both in sync.
  **`bl4gyro_button_names`** gives the printed names ("confirm|back|LB|RB" by position) from Steam's
  `GetActionOriginFromXboxOrigin` (`steam::origin_label`, values from isteaminput.h) or SDL's button labels;
  `state.pad_labels` applies the Button names option over them.
- **ctypes signatures are declared twice**, in the mod's `_load_dll()` and in `load()` in
  `tests/dll_replay_check.py`. Keep both in sync with the exports.
- **Axis conventions.** `Sample` uses SDL axes (X right, Y up, Z toward the player, counter-clockwise positive).
  `Delta` uses the camera convention (yaw right +, pitch up +). The Steam-to-SDL mapping in `from_steam`, including
  the roll sign, was measured on the real controller. Don't flip a sign without a new measurement.
- **`YAW_SCALE = 2.5` and `PITCH_SCALE = -2.5`** are BL4's legacy input scales, measured on the tested build
  (`AddYawInput(10)` turns 25°). If a patch changes them, re-measure.

### Measured invariants (don't regress)

- Auto-calibration uses GamepadMotionHelpers **Stillness** only, never SensorFusion, because the accelerometer
  reads about 9% high. It runs **only while the gate is closed**: when it ran during aiming, a slow 24° pan came
  out as 8.5°. The test `slow_pan_is_kept_while_auto_calibration_is_suspended` covers this.
- Delivery is `RateHold`. It holds the last angular velocity, integrates it at frame time, and keeps it for at
  most `kHoldS = 0.1` s. In game, Steam sends only about 48 packets/s, with gaps. Per-packet deltas and a frame
  pacer were both measured and were worse.
- The mod **drains `bl4gyro_take` on every camera update, even with the gate closed**, so motion made in menus,
  with the panel open or while suspended never jumps into the camera later.
- Auto-calibration runs only with the **game gate closed and the panel closed**; the gyro button and the
  activation mode never turn it on. Manual calibration only counts when the controller lies flat and still.
- While the panel is open, **key releases always pass to the game** (no stuck keys), and everything done on open
  (pause, `DisableInput`, or the counted `SetIgnoreMoveInput/SetIgnoreLookInput`) is undone exactly once on close.
  Panel actions run on the next camera update, never inside a keybind callback.
- The gate is open only when all of these hold: the pawn inherits `OakCharacter` (on foot; vehicles are untested
  and gyro is off there), there is no mouse cursor, look input is not ignored, the game is not paused, and the view
  target is the pawn. ADS comes from `ZoomState.State`.
- Steam returns all-zero motion while the game window isn't focused, and `steam::has_data` filters it out.
- The DLL never writes game memory, and the game side uses only reflection. The CRT is linked statically because
  the DLL lives inside the game process. After 100 consecutive errors, the per-frame hook removes itself.

### Dev aids

- If `replay.csv` (columns `elapsed_s,segment,sample_t_s,gyro_pitch_dps,gyro_yaw_dps,gyro_roll_dps,accel_x_g,
  accel_y_g,accel_z_g`) is in the installed mod folder, the DLL replays it instead of reading the controller.
  `dll_replay` uses the same path.
- The **Debug trace** option writes `trace.csv` next to the mod, with rows `P` (packet), `T` (drain),
  `R` (ControlRotation per frame, written by the mod through `bl4gyro_trace_line`) and `L` (loop rate). The DLL
  also logs to `bl4gyro.log` in the mod folder.
- The mod imports `unrealsdk`/`mods_base`, which exist only inside the game, so its Python can't run outside BL4.
  Test the DLL's behavior through `dll_replay` instead.

## Third party

`third_party/GamepadMotionHelpers` (v10, MIT) is vendored. Don't edit it. SDL3 3.4.16 is fetched by CMake with a
pinned SHA-256 and is used by `bl4gyro.dll`'s HID fallback, so `SDL3.dll` (zlib) ships next to `bl4gyro.dll` in the
package and the install. oak2-mod-manager, unrealsdk and pyunrealsdk (LGPL-3.0) are never redistributed, and
`package.ps1` must not include them.
