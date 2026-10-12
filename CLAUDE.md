# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Native gyro aim mod for Borderlands 4 (PC/Steam). The controller's real gyro is added to the game camera through the
game's own look-input path (`AddYawInput`/`AddPitchInput`), with no mouse or stick emulation. Target hardware is the
GuliKit TT Max in Switch mode. The tested game build is Steam **25372571** (`TESTED_BUILD` in the mod).

User docs (`README.md`, `docs/`, `CONTEXT.md`, `evidence/*.md`) and commit messages are written in **pt-BR**. Code,
comments and test names are in English. Commits start with the project phase: `A:`, `B:`, `C:` (Phase E is the
planned next set of aim modes).

## Commands

Windows only. The build uses MSVC, CMake and Ninja.

```
build.cmd                      # finds MSVC with vswhere, runs vcvars64, then configure + build + ctest (preset "release")
build.cmd -R dll_replay        # any extra arguments are passed to ctest
```

From PowerShell or bash, run it with `cmd /c build.cmd`. Outputs go to `build\release\`: `bl4gyro.dll`,
`core_tests.exe` and `ttmax-diag.exe` (with `SDL3.dll` copied next to it).

- There are three CTest tests: `core_tests` (C++ with plain `CHECK` asserts), `dll_replay` (Python ctypes test of the
  DLL, registered only if CMake finds Python 3) and `scripts` (`tests\scripts_check.ps1`: package, game folder
  detection, install and uninstall, all against a fake Steam install in a temp folder, never the real game).
- `core_tests` has no test filter. Every test function is called from `main()` in `tests/core_tests.cpp`, so a new
  test has to be added to that list or it never runs.
- To run a test directly: `build\release\core_tests.exe`, or
  `python -I tests\dll_replay_check.py build\release\bl4gyro.dll`.
- No linter or formatter is configured. The C++ builds with `/W4 /permissive-`.
- Install into the game (game must be closed; needs oak2-mod-manager v0.3):
  `powershell -ExecutionPolicy Bypass -File scripts\install.ps1 [-GameDir "...\Borderlands 4"]`.
  Without `-GameDir`, the game folder is found through Steam (`scripts\steam-game-dir.ps1`: registry plus
  `libraryfolders.vdf`). Uninstall with `scripts\uninstall.ps1`; add `-RemoveModManager` to also remove
  oak2-mod-manager, using the file list in `evidence\B-oak2-install-manifest.txt`.
- Release package: `scripts\package.ps1` (after `build.cmd`) writes `dist\NativeGyro-<__version__>.zip` and prints the
  SHA-256 hashes. The same `install.ps1`/`uninstall.ps1` run from inside the extracted zip (package layout: the
  `NativeGyro\` folder and `oak2-install-manifest.txt` sit next to the scripts). A new script that the package needs
  must be added to `package.ps1` and to the expected file list in `tests\scripts_check.ps1`.
- Offline analysis: `python tools/analyze_trace.py <trace.csv>` and
  `python tools/analyze_diag.py evidence/A-<label>.csv`.
- Controller diagnostics: `build\release\ttmax-diag.exe hid | sdl | steam [--label NAME]` writes
  `evidence\A-NAME.*`. The guided run is `scripts\phase-a.ps1`.

Hard-coded machine path: `ttmax-diag` loads the game's `steam_api64.dll` from
`F:\SteamLibrary\steamapps\common\Borderlands 4` (override it with `--steam-dll`).

## Architecture

The mod has two parts that talk through a small C interface loaded with ctypes:

1. **`bl4gyro.dll`** (`core/bl4gyro.cpp` + the `gyro_core` static library). A sensor thread reads
   `ISteamInput::GetMotionData` through the game's own `steam_api64.dll` (flat exports, no Steamworks SDK; see
   `core/steam_motion.*`). Each sample goes through `gyro::from_steam` → `gyro::Processor` (GamepadMotionHelpers:
   calibration, Player/Local space, optional tightening/smoothing) → `gyro::RateHold`.
2. **`mod/NativeGyro/__init__.py`**: the sdkmod, run by the oak2-mod-manager's embedded Python on the game thread.
   It hooks `/Script/Engine.CameraModifier:BlueprintModifyCamera` (once per camera update, also while paused). Each
   call it evaluates the gate and ADS, calls `bl4gyro_take`, and injects `AddYawInput(yaw/2.5)` and
   `AddPitchInput(pitch/-2.5)`.

Domain terms (gate, gyro delta, camera delta, rate hold, motion packet) are defined in `CONTEXT.md`. The
measurements behind the design are in `docs/TECHNICAL.md` and `evidence/PHASE-{A,B,C}.md`.

### Contracts that span several files

- **Settings are passed by name.** `bl4gyro_set(key, double)` in `core/bl4gyro.cpp` maps string keys to
  `gyro::Settings` and `gyro::Camera` fields, and returns 0 for an unknown key. The mod ignores that return value, so
  a typo fails silently. A new option needs all three: the `gyro.hpp` struct field, the `bl4gyro_set` branch, and the
  mod's option plus `_push_settings()`.
- **ctypes signatures are declared twice**: in `_load_dll()` in the mod and in `load()` in
  `tests/dll_replay_check.py`. Keep both in sync with the `BL4GYRO_API` exports.
- **Axis conventions.** The core uses SDL axes (X right, Y up, Z toward the player, counter-clockwise positive).
  `Delta` uses the camera convention (yaw right +, pitch up +). The Steam→SDL mapping in `from_steam`, including
  the roll sign, was measured on real hardware. Do not "fix" a sign without new evidence.
- **The injection scales** `YAW_SCALE = 2.5` and `PITCH_SCALE = -2.5` were measured on the tested build. If a game
  patch changes them, re-measure with `tools/probe`.

### Invariants backed by measurements (don't regress)

- Automatic calibration (GamepadMotionHelpers *Stillness* only, never *SensorFusion*) runs **only while the gate is
  closed**. Running it while aiming eats slow, steady turns; this is covered by the test
  `slow_pan_is_kept_while_auto_calibration_is_suspended`. *SensorFusion* is not used because the accelerometer has
  a ~9% scale error.
- Delivery uses `RateHold`: the last angular velocity, integrated at each frame's time and held for at most 100 ms.
  Two older approaches were measured and are worse: applying each packet's delta on the next frame, and the removed
  `Pacer`. In game, Steam delivers only ~48 packets/s, with gaps.
- The mod **always drains** `bl4gyro_take` every camera update, even when the gate is closed, so motion made in
  menus never jumps into the camera later.
- The gate is open only when all of these hold: the pawn is an `OakCharacter` (on foot, not in a vehicle), no mouse
  cursor, the game is not paused, look input is not ignored, and the view target is the pawn. ADS comes from
  `ZoomState.State`, not from the FOV.
- The DLL never writes game memory, and everything on the game side goes through reflection. The CRT is linked
  statically (`CMAKE_MSVC_RUNTIME_LIBRARY`) because the DLL lives inside the game process. After 100 consecutive
  errors, the per-frame hook removes itself.

### Dev aids

- If a `replay.csv` (in `ttmax-diag` CSV format) is in the installed mod folder, the DLL plays it back instead of
  reading the controller. The `dll_replay` test uses the same backend.
- The **Debug trace** option writes `trace.csv` to the mod folder, with rows of kind `P` (motion packet), `T`
  (camera drain), `R` (ControlRotation per frame) and `L` (sensor loop rate). Read it with
  `tools/analyze_trace.py`.
- `tools/probe/` is the Phase B in-game probe. It is for development only and is never shipped (`install.ps1`
  deletes `sdk_mods\NativeGyroProbe`). Press Insert in game to hot-reload `impl.py`.
- The mod imports `unrealsdk` and `mods_base`, which exist only inside the game. Its Python can't be run or tested
  outside BL4; DLL behavior is tested through `dll_replay` instead.

## Third party

`third_party/GamepadMotionHelpers` (v10, MIT) is vendored; don't edit it. SDL3 3.4.16 is downloaded by FetchContent
with a pinned SHA-256 and is used only by `ttmax-diag`. oak2-mod-manager, unrealsdk and pyunrealsdk (LGPL-3.0) are
never redistributed.
