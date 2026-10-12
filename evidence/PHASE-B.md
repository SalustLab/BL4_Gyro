# Phase B — native camera integration in Borderlands 4 (2026-10-11)

Game: Steam build 25372571 (`++oak2+release+oak2+1.10.0.0`, UE 5.5.4 "+Oak2"), single player.
Framework: bl-sdk oak2-mod-manager v0.3 (unrealsdk 3.2.0, pyunrealsdk 1.10.0, Python 3.14.6), installed per
`B-oak2-install-manifest.txt`, console key F6. Probe: `tools/probe` (hot-reloadable `impl.py`).
Raw evidence: `B-probe.log`, `B-calls-summary.txt`, `B-members.txt`, `B-mappings.txt`.

## Framework on this build

`unrealsdk.log`: every BL4 signature resolved (ProcessEvent, CallFunction, FNamePool, GMalloc, GObjects,
StaticFindObject, LoadPackage, GNatives); console injected; Python mods load; `ctypes` imports in game.

## Camera injection (measured, no controller input during the tests)

| Method | Result | Verdict |
|---|---|---|
| `AddYawInput(10)` + `AddPitchInput(5)` once | ControlRotation **+25.0000° yaw, −12.5000° pitch** after 0.5 s | works; BL4 applies UE legacy scales ×2.5 / ×−2.5 (`bEnableLegacyInputScales = True`), nothing else |
| `AddYawInput(1)` on each of 60 calls of the per-frame hook | **+150.0000°** (60 × 2.5), 94 calls/s | lossless per-frame injection; twice-per-frame calls are harmless |
| `SetControlRotation(yaw+10, bResetCamera=False)` | changed momentarily, **0.0000°** net after 0.5 s | not usable: the Gbx camera rewrites ControlRotation |
| `RotationInput` member | not reflected in BL4 | not usable from reflection |

Injection formula: `AddYawInput(yaw_deg / 2.5)`, `AddPitchInput(-pitch_deg / 2.5)` (camera convention: yaw right +, pitch up +).
This path bypasses the gamepad look modifiers (`GbxInputModifier_Acceleration`, scalar, deltatime on `Action_Look`
/ `Gamepad_Right2D`), so the gyro gets no acceleration while the right stick keeps its own curve and adds on top.

## Per-frame hook

`log_all_calls` over 21.7 s of gameplay: the first-person anim instance updates 971× (≈45 game frames/s);
`/Script/Engine.CameraModifier:BlueprintModifyCamera` runs 1942× per camera modifier (2× per frame) on the game
thread for the player camera. It keeps running while the game is paused or a menu is open, so gating must be explicit.

## Gate signals (per-frame watch, F9)

| State | `bShowMouseCursor` | `IsGamePaused` | `IsLookInputIgnored` | view target = pawn |
|---|---|---|---|---|
| gameplay | False | False | False | True |
| pause menu / inventory / map (3 menus opened) | **True** | **True** | False | True |

ADS: `OakCharacter.ZoomState.State` = `EZoomState` NotZoomed(0) → ZoomingIn(1) → Zoomed(2) → ZoomingOut(3);
`bWantsToZoom` flips on the button press. FOV (`PlayerCameraManager.GetFOVAngle`) goes 110 → 87–90 in ≈0.16 s;
sprint/movement alone moves FOV by up to ~13°, so ADS must come from `ZoomState`, not from FOV.

## Native motion pipeline (B5)

The PC build contains `OakLocalPlayer.Get/Set{Horizontal,Vertical}MotionControls{Look,ADS}Sensitivity`,
`GetMotionControlsSetting` (returns 0 = Off) and `GbxPlayerController.SetMotionControlsEnabled/GetInputMotionState`,
but of 961 Enhanced Input mappings the only ones on motion keys (Tilt, RotationRate, Gravity, Acceleration)
belong to `context_ui_menu_tutorial_catchall`. No gameplay action consumes motion input on PC, so the game's own
gyro path cannot be fed; the mod drives the camera through `AddYawInput/AddPitchInput` instead.

## Not covered

Vehicles (the tester could not enter one), cutscenes/dialogue, death/respawn, co-op.
