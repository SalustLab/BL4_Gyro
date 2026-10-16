# 0001 — The in-game panel is a UMG widget built by reflection

Status: accepted, validated in game (`evidence/PHASE-D.md`).

## Context

Players must set up the gyro with the controller only. oak2-mod-manager v0.3 ships only a console mod menu, and no
graphical mod menu exists for BL4. BL4 draws no HUD canvas: `HUD:ReceiveDrawHUD` never runs in the recorded call log
(`evidence/B-calls-summary.txt`), while UMG widgets tick every frame. The DLL must never write game memory.

## Decision

Build the panel from Python as a UMG `UserWidget` (`WidgetBlueprintLibrary.Create`), fill its `WidgetTree` with a
Border > VerticalBox > TextBlocks, and `AddToViewport`. Keyboard/mouse input comes from oak2's `keybinds` module
(InputKey hook, `Block` to keep events from the game). Pad buttons, which that hook doesn't see in BL4, are read by
`bl4gyro.dll`; since they can't be blocked, the panel pauses the game and disables the pawn's and the player
controller's input while open.

## Alternatives rejected

- **HUD canvas drawing**: the game never calls the HUD draw event.
- **Present/DirectX hook overlay (e.g. Dear ImGui)**: patches the renderer, breaks "the DLL never writes game
  memory", ties the mod to D3D12 details and a heavy dependency.
- **Topmost Win32 window from the DLL**: works without the game, but is invisible in exclusive fullscreen, can steal
  focus (Steam then sends no motion) and is not part of the game UI. Kept only as the fallback if UMG proves
  impossible; never both.

## Consequences

- Rendering, scaling and layering are the game's; text-only layout (no custom art).
- A game patch that changes UMG classes may break the panel; the console mod menu stays as a fallback for every
  option.
- The panel code can only be verified in game; its logic lives in `state.py` so it is tested outside the game.
