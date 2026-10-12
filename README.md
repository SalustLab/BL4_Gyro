# Native Gyro Aim — Borderlands 4

Mira por movimento **nativa** para o Borderlands 4 no PC. A rotação real do giroscópio do controle é somada à
câmera do próprio jogo, pelo mesmo caminho do look input (`AddYawInput`/`AddPitchInput`). Não há emulação de mouse
nem de analógico: o analógico direito continua funcionando junto e os ícones não trocam para teclado/mouse.

Prioridade: **GuliKit TT Max (NS69)** em Switch mode. Testado no Steam build **25372571**.

## Requisitos

- Borderlands 4 (Steam).
- [oak2-mod-manager](https://github.com/bl-sdk/oak2-mod-manager/releases) **v0.3** instalado na pasta do jogo.
- Controle com giroscópio reconhecido pelo Steam Input. No TT Max: **Switch mode** (duplo clique em Mode),
  Bluetooth testado.
- Steam > Configurações > Controle: suporte a **Nintendo Switch** ativado. Não configure gyro como mouse no Steam.

## Instalação

```
build.cmd                                                   (compila e roda os testes)
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 [-GameDir "...\Borderlands 4"]
```

No jogo: console (tecla definida no oak2; aqui F6) → `mods` → **Native Gyro Aim** → `E`. Depois disso o mod liga
sozinho nas próximas vezes. Para ver o texto do menu, abra o console grande (tecla do console duas vezes).

**Calibração:** com o jogo em foco, abra o menu de pausa e deixe o controle parado na mesa por ~3 s. A calibração
automática só roda com o jogo pausado ou em menus, nunca durante a mira. Também há "Calibrate now" nas opções.

## Opções (menu do mod)

| Opção | Padrão | Efeito |
|---|---|---|
| Horizontal / Vertical sensitivity | 1,25 | graus de câmera por grau de controle |
| ADS sensitivity multiplier | 1,0 | multiplica as duas sensibilidades mirando |
| Invert horizontal / vertical | Off | |
| Gyro space | Player | Player: girar funciona como você segurar o controle; Local: só o eixo do próprio controle |
| Automatic calibration | On | remove drift em menus/pausa com o controle parado |
| Calibrate now | — | 3 s com o controle parado |
| Tightening / Smoothing threshold | 0 | atenuação/suavização só de movimentos abaixo do limiar (°/s) |
| Debug trace | Off | grava `trace.csv` para diagnóstico (`tools/analyze_trace.py`) |
| Show status | — | controle detectado, leituras/s, laços/s |

## Desinstalação

```
powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1                       (só este mod)
powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1 -RemoveModManager     (também o oak2, pelo manifesto)
```

## Diagnóstico do controle

`build\release\ttmax-diag.exe hid | sdl | steam` lista as interfaces HID, lê o IMU via SDL3 ou via Steam Input
(como o BL4) e grava evidências em `evidence\`. O roteiro guiado está em `scripts\phase-a.ps1`; use `-BluetoothOnly`
se só tiver Bluetooth.

## Documentação

- `docs/TECHNICAL.md`: arquitetura, medições e decisões.
- `docs/LIMITATIONS.md`: limites de hardware, Steam e jogo, e riscos.
- `evidence/`: resultados das Fases A, B e C (CSV, logs e resumos).
- `CONTEXT.md`: glossário.

## Terceiros

- GamepadMotionHelpers v10 (MIT, vendorizado em `third_party/`).
- SDL3 3.4.16 (zlib), baixado no build, só no diagnóstico.
- oak2-mod-manager / unrealsdk / pyunrealsdk (LGPL-3.0): não redistribuídos, instalados pelo usuário.
- Referências de design: Returnal-Native-Gyro, GyroUE/GyroLib, NeonGyro (MIT) e GyroWiki. Nenhum código copiado.
