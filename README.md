# Native Gyro Aim — Borderlands 4

Mira por movimento **nativa** para o Borderlands 4 no PC. A rotação real do giroscópio do controle é somada à
câmera do próprio jogo, pelo mesmo caminho do look input (`AddYawInput`/`AddPitchInput`). Não há emulação de mouse
nem de analógico: o analógico direito continua funcionando junto e os ícones não trocam para teclado/mouse.

Testado no Steam build **25372571**.

## Controles

| Modo | Como o mod lê o gyro | Testado em jogo | Deve funcionar (não verificado) |
|---|---|---|---|
| **Controle genérico com gyro** | Steam Input | **GuliKit TT Max (NS69)** em Switch mode, Bluetooth | Pro Controller original do Switch (mesmo protocolo e tipo Steam do TT Max), Steam Controller (2026) e outros controles com gyro que a Steam Input reconhece |
| **DualSense** | HID direto (Steam Input desligado para PlayStation) ou Steam Input | DualSense por Bluetooth e USB, nos dois caminhos; vibração e gatilhos adaptáveis continuam funcionando | — |
| **Switch 2 Pro Controller** | HID direto, via [Switch2Connect](https://github.com/TommyWabg/Switch2Connect) em modo DualSense | Switch 2 Pro Controller | — |

O mod usa a Steam Input quando ela entrega um controle ao jogo. Se não entrega nenhum (ex.: DualSense com Steam
Input desligado, já que o BL4 suporta PlayStation nativamente), ele lê o controle direto pelo HID. `Show status`
mostra qual fonte está em uso (`ps5 (HID)` = HID direto).

## Requisitos

- Borderlands 4 (Steam).
- [oak2-mod-manager](https://github.com/bl-sdk/oak2-mod-manager/releases) **v0.3** instalado na pasta do jogo.
- Um controle com giroscópio (veja [Controles](#controles)).
- Controle genérico com gyro (TT Max): **Switch mode** (duplo clique em Mode) e, em Steam > Configurações >
  Controle, suporte a **Nintendo Switch** ativado.
- DualSense: funciona com o suporte a PlayStation da Steam desligado para o jogo (o BL4 recebe o controle nativo)
  ou ligado.
- Switch 2 Pro Controller: Switch2Connect em modo **PS5/DualSense**, com o gyro interno do app (mouse/analógico)
  desligado.
- Não configure gyro como mouse na Steam nem em outro app: a rotação dobraria.

## Instalação

Com o jogo fechado, baixe `NativeGyro-<versão>.zip` em Releases, extraia e, dentro da pasta extraída, rode:

```
powershell -ExecutionPolicy Bypass -File install.ps1
```

O script acha a pasta do jogo em qualquer biblioteca da Steam. Se não achar, informe a pasta:
`install.ps1 -GameDir "D:\...\Borderlands 4"`. Instalação manual: copie a pasta `NativeGyro` para
`<pasta do jogo>\sdk_mods\`. Não compacte nem renomeie a pasta: o mod carrega o `bl4gyro.dll` e o `SDL3.dll` de dentro dela.

No jogo: console (tecla definida no oak2; aqui F6) → `mods` → **Native Gyro Aim** → `E`. Depois disso o mod liga
sozinho nas próximas vezes. Para ver o texto do menu, abra o console grande (tecla do console duas vezes).

**Calibração:** com o jogo em foco, abra o menu de pausa e deixe o controle parado na mesa por ~3 s. A calibração
automática só roda com o jogo pausado ou em menus, nunca durante a mira. Também há "Calibrate now" nas opções.

## Opções (menu do mod)

| Opção | Padrão | Efeito |
|---|---|---|
| Horizontal / Vertical sensitivity | 2,0 | graus de câmera por grau de controle (o testador usa 3,0) |
| ADS sensitivity multiplier | 1,0 | multiplica as duas sensibilidades mirando |
| Invert horizontal / vertical | Off | |
| Gyro space | Player | Player: girar funciona como você segurar o controle; Local: só o eixo do próprio controle |
| Automatic calibration | On | remove drift em menus/pausa com o controle parado |
| Calibrate now | — | 3 s com o controle parado |
| Tightening / Smoothing threshold | 0 | atenuação/suavização só de movimentos abaixo do limiar (°/s) |
| Debug trace | Off | grava `trace.csv` para diagnóstico (`tools/analyze_trace.py`) |
| Show status | — | controle detectado, leituras/s, laços/s |

## Desinstalação

Na pasta extraída do zip (ou em `scripts\`, no repositório), com o jogo fechado:

```
powershell -ExecutionPolicy Bypass -File uninstall.ps1                       (só este mod)
powershell -ExecutionPolicy Bypass -File uninstall.ps1 -RemoveModManager     (também o oak2 v0.3, pelo manifesto)
```

Os arquivos do jogo e de outros mods não são tocados. Também aceita `-GameDir`.

## Desenvolvimento

```
build.cmd                                                   (compila e roda os testes)
powershell -ExecutionPolicy Bypass -File scripts\install.ps1      (instala direto do build)
powershell -ExecutionPolicy Bypass -File scripts\package.ps1      (gera dist\NativeGyro-<versão>.zip e os SHA-256)
```

Antes de publicar uma release: `build.cmd` sem falhas, gerar o zip, enviar o `bl4gyro.dll` ao VirusTotal e publicar
os SHA-256 junto com a release.

## Diagnóstico do controle

`build\release\ttmax-diag.exe hid | sdl | steam` lista as interfaces HID, lê o IMU via SDL3 ou via Steam Input
(como o BL4) e grava evidências em `evidence\`. O roteiro guiado está em `scripts\phase-a.ps1`; use `-BluetoothOnly`
se só tiver Bluetooth.

## Documentação

- `docs/TECHNICAL.md`: arquitetura, medições e decisões.
- `docs/LIMITATIONS.md`: limites de hardware, Steam e jogo, e riscos.
- `evidence/`: resultados das Fases A, B e C (CSV, logs e resumos).
- `CONTEXT.md`: glossário.

## Licença

Código aberto sob a licença MIT (`LICENSE`).

## Terceiros

- GamepadMotionHelpers v10 (MIT, vendorizado em `third_party/`).
- SDL3 3.4.16 (zlib), baixado no build; o `SDL3.dll` vai no pacote para a leitura HID direta e é usado no
  diagnóstico.
- oak2-mod-manager / unrealsdk / pyunrealsdk (LGPL-3.0): não redistribuídos, instalados pelo usuário.
- Referências de design: Returnal-Native-Gyro, GyroUE/GyroLib, NeonGyro (MIT) e GyroWiki. Nenhum código copiado.
