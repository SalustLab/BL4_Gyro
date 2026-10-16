# Native Gyro Aim — documento técnico

Integração de gyro aim nativa no Borderlands 4 (Steam build 25372571, UE 5.5.4 "+Oak2"), com prioridade para o
GuliKit TT Max (NS69). Evidências: `evidence/PHASE-A.md`, `evidence/PHASE-B.md`, `evidence/PHASE-C.md`.

## Arquitetura

```
TT Max (Switch mode) ──BT──► Steam (Switch support) ──► XInput virtual ──► BL4 (botões, sticks, rumble: inalterados)
                               │
                               └─ ISteamInput::GetMotionData (via o steam_api64.dll do próprio jogo)
                                    │ thread do sensor em bl4gyro.dll (~660 laços/s)
                                    ▼
             gyro::from_steam → gyro::Processor (GamepadMotionHelpers: calibração + Player Space, filtros opcionais)
                                    │ Processor::rate()  (°/s, convenção da câmera)
                                    ▼
                       gyro::RateHold (velocidade mantida, thread-safe)
                                    │ bl4gyro_take() via ctypes, 1× por atualização de câmera
                                    ▼
        sdk_mods/NativeGyro (Python, oak2-mod-manager): hook /Script/Engine.CameraModifier:BlueprintModifyCamera
          gate → sensibilidade/ADS/inversão → AddYawInput(yaw/2.5), AddPitchInput(pitch/−2.5)
```

Por que esta forma:

1. **Framework.** UE4SS não roda no BL4 sem patch binário. O bl-sdk (oak2-mod-manager / unrealsdk) mantém as
   assinaturas desta build (PGO e não-PGO, unpack do Denuvo, thread anti-debug).
2. **Sensor no Steam.** O TT Max só expõe IMU em Switch mode, e o BL4 só vê os botões nesse modo via Steam Input.
   Com Steam Input ativo, o overlay esconde o HID físico do processo do jogo; a fonte é então a Steam Input API do
   próprio jogo, chamada pelos exports *flat* do `steam_api64.dll`, sem Steamworks SDK.
   **Fallback HID (SDL3).** Quando a Steam Input não entrega nenhum controle ao jogo (ex.: DualSense com Steam
   Input desligado, já que o BL4 suporta PlayStation nativamente), o DLL lê o HID do controle pelo SDL3, só com os
   drivers HIDAPI (RawInput/XInput/WGI/GameInput/DirectInput desligados; LEDs intocados). Uma fonte por vez: se
   um controle aparecer na Steam Input, o HID é solto. Amostras com o mesmo `sensor_timestamp` são descartadas:
   o Switch2Connect repete a mesma leitura do IMU (~65 Hz) em relatórios de 1 kHz, e `dt = 0` zeraria a
   velocidade mantida (medido: 4678 de 5002 amostras repetidas). Sem foco no jogo, as amostras são ignoradas.
3. **Câmera nativa.** `AddYawInput`/`AddPitchInput` são o caminho do próprio look input. Medido: exato
   (×2.5/×−2.5), sem aceleração/suavização, aplicado no frame seguinte. `SetControlRotation` não persiste: a câmera
   Gbx reescreve a rotação.
4. **ctypes.** O C++ fica onde há custo (sensor, filtros, tempo) e não depende do ABI do Python nem do unrealsdk.

## Componentes

| Arquivo | Papel |
|---|---|
| `core/gyro.hpp/.cpp` | Conversões SDL/Steam → °/s e g (eixos SDL), `Processor`, `RateHold`, `to_camera` |
| `core/steam_motion.hpp/.cpp` | ISteamInput por exports flat; `has_data` (pacote zerado = janela sem foco) |
| `core/bl4gyro.cpp` | `bl4gyro.dll`: thread do sensor (Steam Input, fallback HID por SDL3), replay de CSV, log, trace opcional, ABI C |
| `mod/NativeGyro/__init__.py` | sdkmod: opções, hook por frame, gate, ADS, injeção |
| `diag/ttmax_diag.cpp` | `ttmax-diag.exe`: `hid`, `sdl`, `steam`, com protocolo guiado e evidência CSV |
| `tools/probe/` | probe da Fase B (dev): medições de injeção, call log, membros, mapeamentos, monitor de gate |
| `tools/analyze_diag.py`, `tools/analyze_trace.py` | análise offline das evidências |

## Detalhes medidos que definem o design

**Eixos e unidades.** `InputMotionData_t.rotVel` vai de int16 a ±2000 °/s; `posAccel` de int16 a ±2 g.
Mapeamento para SDL (X direita, Y cima, Z para o jogador, anti-horário positivo): pitch = `rotVelX`,
yaw = `rotVelZ`, roll = `+rotVelY`. O sinal de roll foi corrigido medindo o bias nos dois caminhos.
Acelerômetro: `(posAccelX, posAccelZ, −posAccelY)`.

**Steam e foco.** O Steam entrega o controle e o movimento apenas à janela em foco (`OnFocusWindowChanged` no
`controller_ui.txt`). Sem foco, `GetMotionData` devolve um pacote todo zerado, tratado como "sem dados".

**Cadência no jogo.** Dentro do BL4 o Steam atualiza o movimento ~48×/s (o laço do sensor roda a ~660/s), com
lacunas de 40–500 ms cerca de 2×/s que não coincidem com engasgos do jogo. Três versões da entrega, comparadas com
o mesmo critério nos traces `evidence/C-trace-*.csv`:

| Entrega | Frames vazios em movimento | Variação frame a frame p50 / p90 |
|---|---|---|
| Delta inteiro no próximo frame | 11% | 0,55 / 2,00 |
| Pacote espalhado pelo intervalo típico (`Pacer`, removido) | 2% | 0,22 / 1,24 |
| **Velocidade mantida (`RateHold`)** | **0%** | **0,15 / 0,75** |

`RateHold` integra a última velocidade no tempo de cada frame, a mantém por no máximo 100 ms e não acrescenta
latência. O total integrado não depende do FPS (teste `dll_replay`: 180,0° a 30 e a 144 fps).

**Calibração.** O bias do TT Max fica em ~+0,17/−0,33/−0,35 °/s (pitch/yaw/roll); o Steam não o remove. Com o
*Stillness* do GamepadMotionHelpers rodando durante a mira, um giro lento e constante de 24° vira 8,5° (teste
`slow_pan_is_kept_while_auto_calibration_is_suspended`). Esse era o sintoma "travado / direções presas". Por isso
a calibração automática roda só com o gate fechado e usa só *Stillness*: o *SensorFusion* corrige pitch/roll pelo
acelerômetro, que tem erro de escala de ~9% neste controle e acompanhou o sintoma "mira subindo". Drift residual
medido em jogo: −0,013 °/s pitch, −0,020 °/s yaw.

**Gate.** Medido em jogo: menus de pausa, inventário e mapa ligam `bShowMouseCursor` e `IsGamePaused`.
`IsLookInputIgnored` não muda nesses menus, mas é checado. O hook de câmera continua rodando em pausa. ADS vem de
`OakCharacter.ZoomState.State` (ZoomingIn/Zoomed), não do FOV: só a corrida já muda o FOV em até 13°. Fora de um
`OakCharacter`, por exemplo num veículo, o gyro fica desligado.

**Falhas seguras.**
- Erros no hook são contados; depois de 100 seguidos o hook se remove.
- Build diferente da testada só gera aviso: o caminho é todo por reflexão, então membros ausentes viram erro
  contido, não escrita em memória.
- O DLL não escreve memória do jogo.

## Build e testes

`build.cmd` usa vswhere + MSVC + CMake/Ninja e roda o CTest:
- `core_tests`: conversões, integração, gaps, independência de FPS, calibração, filtros, velocidade mantida,
  threads.
- `dll_replay`: ABI via ctypes, replay, total exato a 30 e 144 fps.

SDL3 3.4.16 vem por FetchContent com SHA-256 fixado (diagnóstico e fallback HID do DLL; `SDL3.dll`, licença
zlib, vai no pacote ao lado do `bl4gyro.dll`). GamepadMotionHelpers v10 está
vendorizado (MIT).
