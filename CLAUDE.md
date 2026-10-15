# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Native gyro aim for Borderlands 4 (PC, Steam). The controller's real gyro is added to the game camera through the
game's own look input (`AddYawInput`/`AddPitchInput`). There is no mouse or stick emulation. The main target is the
GuliKit TT Max in Switch mode, and the tested game build is Steam `25372571` (`TESTED_BUILD` in the mod).

User-facing docs (`README.md`, `docs/`, `CONTEXT.md`, `evidence/*.md`) and commit messages are in **pt-BR**. Code,
comments and identifiers are in English. Commit subjects start with the project phase, e.g. `C: ...`
(A = hardware diagnosis, B = in-game probe, C = the mod).

## Commands

Windows only. The build uses MSVC, CMake 3.24+ and Ninja.

```
build.cmd                 # vswhere -> vcvars64 -> cmake --preset release, build, ctest
build.cmd -R core_tests   # extra args are passed to ctest
```

From PowerShell or bash, run it as `cmd /c build.cmd`. The `release` preset is `RelWithDebInfo` and builds into
`build\release\`: `bl4gyro.dll`, `core_tests.exe` and `ttmax-diag.exe` (with `SDL3.dll` copied next to it).

There are three CTest tests:
- `core_tests` (`tests/core_tests.cpp`) uses a homemade `CHECK` macro and has no filter. Each test is a function
  called from `main()`, so a new test has to be added to that list.
- `dll_replay` (`python -I tests\dll_replay_check.py build\release\bl4gyro.dll`) drives the DLL through ctypes with
  the replay backend. It checks that the camera total is the same at 30 and 144 fps. It is registered only if CMake
  finds Python 3.
- `scripts` (`tests\scripts_check.ps1`) runs package, game-folder detection, install and uninstall against a fake
  Steam install in a temp folder. It needs the built DLL.

No linter or formatter is configured. The C++ builds with `/W4 /permissive-`.

Install, package and tools:
- `powershell -ExecutionPolicy Bypass -File scripts\install.ps1 [-GameDir ...]` installs the mod. The game must be
  closed and oak2-mod-manager v0.3 must already be installed. The game folder is found through Steam
  (`scripts\steam-game-dir.ps1`, `Find-GameDir`). `scripts\uninstall.ps1 [-RemoveModManager]` removes it.
- `scripts\package.ps1` (run after `build.cmd`) writes `dist\NativeGyro-<__version__>.zip` and prints SHA-256
  hashes. The version comes from `__version__` in `mod/NativeGyro/__init__.py`. `install.ps1`/`uninstall.ps1` work
  both from the repo and from inside the extracted zip. A file the package needs must be added to `package.ps1` and
  to the expected list in `tests\scripts_check.ps1`.
- `build\release\ttmax-diag.exe hid|sdl|steam [--label NAME] [--steam-dll PATH]` writes `evidence\A-NAME.*`. Its
  default `steam_api64.dll` path is hard-coded to `<Steam library>\...\Borderlands 4`. The guided run is
  `scripts\phase-a.ps1`.
- `python tools/analyze_trace.py <trace.csv>` analyzes an in-game Debug trace. `python tools/analyze_diag.py
  evidence/A-<label>.csv` analyzes a ttmax-diag capture.

## Architecture

The mod has two halves joined by a small C interface (`BL4GYRO_API` exports, loaded with ctypes):

1. **`bl4gyro.dll`** (`core/bl4gyro.cpp` on top of the `gyro_core` static lib). It runs a sensor thread at about
   1 kHz that polls `ISteamInput::GetMotionData` through the game's already-loaded `steam_api64.dll`, using flat
   exports with no Steamworks SDK (`core/steam_motion.*`). A new packet goes through `gyro::from_steam`, then
   `gyro::Processor` (GamepadMotionHelpers: calibration, Player/Local space, tightening, smoothing), then
   `gyro::RateHold`.
2. **`mod/NativeGyro/__init__.py`** is an sdkmod that runs in oak2-mod-manager's embedded Python. It hooks
   `CameraModifier:BlueprintModifyCamera` on the game thread. On each camera update it reads the gate and ADS
   state, calls `bl4gyro_take`, then calls `AddYawInput(yaw / 2.5)` and `AddPitchInput(pitch / -2.5)`.

The same `gyro_core` is used by `ttmax-diag` (with SDL3 input, through `from_sdl`) and by the unit tests.
`CONTEXT.md` defines the domain terms (gate, gyro delta, camera delta, rate hold, motion packet). The rationale and
measurements behind each design choice are in `docs/TECHNICAL.md` and `evidence/PHASE-{A,B,C}.md`.

### Cross-file contracts

- **Settings are passed by string key.** `bl4gyro_set(key, double)` maps keys onto `gyro::Settings`/`gyro::Camera`
  and returns 0 for an unknown key. The mod ignores that return value, so a typo fails silently. Adding an option
  takes all of these: the struct field in `core/gyro.hpp`, a branch in `bl4gyro_set`, the option in the mod, and
  a line in `_push_settings()`.
- **ctypes signatures are declared twice**, in the mod's `_load_dll()` and in `load()` in
  `tests/dll_replay_check.py`. Keep both in sync with the exports.
- **Axis conventions.** `Sample` uses SDL axes (X right, Y up, Z toward the player, counter-clockwise positive).
  `Delta` uses the camera convention (yaw right +, pitch up +). The Steam-to-SDL mapping in `from_steam`, including
  the roll sign, was measured on the real controller (`evidence/A-switch-steam-api.*`). Don't flip a sign without
  new evidence.
- **`YAW_SCALE = 2.5` and `PITCH_SCALE = -2.5`** are BL4's legacy input scales, measured on the tested build. If a
  patch changes them, re-measure with `tools/probe`.

### Measured invariants (don't regress)

- Auto-calibration uses GamepadMotionHelpers **Stillness** only, never SensorFusion, because the accelerometer
  reads about 9% high. It runs **only while the gate is closed**: when it ran during aiming, a slow 24° pan came
  out as 8.5°. The test `slow_pan_is_kept_while_auto_calibration_is_suspended` covers this.
- Delivery is `RateHold`. It holds the last angular velocity, integrates it at frame time, and keeps it for at
  most `kHoldS = 0.1` s. In game, Steam sends only about 48 packets/s, with gaps. Per-packet deltas and the removed
  `Pacer` were both measured and were worse (see `evidence/PHASE-C.md`).
- The mod **drains `bl4gyro_take` on every camera update, even with the gate closed**, so motion made in menus
  never jumps into the camera later.
- The gate is open only when all of these hold: the pawn inherits `OakCharacter` (on foot; vehicles are untested
  and gyro is off there), there is no mouse cursor, look input is not ignored, the game is not paused, and the view
  target is the pawn. ADS comes from `ZoomState.State`.
- Steam returns all-zero motion while the game window isn't focused, and `steam::has_data` filters it out.
- The DLL never writes game memory, and the game side uses only reflection. The CRT is linked statically because
  the DLL lives inside the game process. After 100 consecutive errors, the per-frame hook removes itself.

### Dev aids

- If `replay.csv` (ttmax-diag CSV format) is in the installed mod folder, the DLL replays it instead of reading the
  controller. `dll_replay` uses the same path.
- The **Debug trace** option writes `trace.csv` next to the mod, with rows `P` (packet), `T` (drain),
  `R` (ControlRotation per frame, written by the mod through `bl4gyro_trace_line`) and `L` (loop rate). The DLL
  also logs to `bl4gyro.log` in the mod folder.
- `tools/probe/` is the Phase B in-game probe, for development only. It binds keys that move the camera, so it is
  never shipped, and `install.ps1` deletes `sdk_mods\NativeGyroProbe`. Press Insert in game to hot-reload
  `impl.py`.
- The mod imports `unrealsdk`/`mods_base`, which exist only inside the game, so its Python can't run outside BL4.
  Test the DLL's behavior through `dll_replay` instead.

## Third party

`third_party/GamepadMotionHelpers` (v10, MIT) is vendored. Don't edit it. SDL3 3.4.16 is fetched by CMake with a
pinned SHA-256 and is used only by `ttmax-diag`. oak2-mod-manager, unrealsdk and pyunrealsdk (LGPL-3.0) are never
redistributed, and `package.ps1` must not include them.
