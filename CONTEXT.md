# Glossary

- **Gyro delta**: the controller's rotation, calibrated and in the chosen space (Player/Local), in degrees.
- **Camera delta**: gyro delta × sensitivity (horizontal/vertical, ADS multiplier, inversion), applied to the game
  camera.
- **Gate** (game gate): the game state that allows (open) or blocks (closed) the gyro. Open only with the character
  on foot, no cursor, not paused, look input not ignored and the camera on the character itself.
- **Gyro enabled**: the player's on/off choice for gyro aiming. Off keeps the mod and its panel available.
- **Activation mode**: when gyro aiming applies during play: *Always*, *ADS only* (only while aiming down sights) or
  *Hold button* (only while the gyro button is held).
- **Gyro button**: a controller button the player picks. In *Hold button* mode it turns the gyro on while held; in
  the other modes it suspends the gyro while held (to re-center the controller).
- **Injection suspended**: the gyro delta is consumed but not applied to the camera, because the gyro is disabled,
  the panel is open, a calibration is running, the gyro button suspends it, the activation mode does not apply or
  the gate is closed. Motion made while suspended is discarded, never applied later.
- **Panel**: the in-game gyro settings screen, driven by the controller or the keyboard.
- **Panel combo**: the controller buttons held together (default L3 + R3, half a second) that open the panel
  during gameplay.
- **Grouped / individual sensitivity**: one sensitivity for both directions, or horizontal and vertical set apart.
- **Automatic calibration**: removing the gyro bias while the controller lies still. Runs only with the gate closed
  and the panel closed.
- **Manual calibration**: an explicit 4 s bias measurement ("Calibrate now") with the controller lying flat, after a
  5 s countdown. Its outcome is *calibrated*, *moved* or *not flat* (the previous calibration is kept in both), or
  *no motion data*.
- **Gyro offset**: the bias being subtracted from the gyro. A wrong offset shows as a slow, steady camera drift.
- **Rate hold**: the last angular velocity received, integrated over each frame's time. It is held for at most
  100 ms without new readings.
- **Motion packet**: one new reading from `ISteamInput::GetMotionData` or the pad's HID (in game, ~48 per second
  through Steam Input).
