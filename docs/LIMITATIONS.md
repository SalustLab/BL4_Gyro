# Limitações e riscos

## Controle genérico com gyro (testado: GuliKit TT Max)

Modo para controles lidos pela Steam Input. O TT Max em Switch mode é o controle testado; os itens abaixo são dele.
O **Pro Controller original** do Switch usa o mesmo protocolo e o mesmo tipo Steam (`SwitchProController`) e deve
funcionar igual, provavelmente com acelerômetro melhor (calibração de fábrica), mas não foi verificado.

- **Gyro só em Switch mode.** Em PC (XInput) mode o controle não envia IMU ao PC; o "Motion Aim Assist" interno só
  move o analógico direito. Medido por Bluetooth (`evidence/PHASE-A.md`).
- **Gatilhos digitais em Switch mode.** O protocolo do Pro Controller transmite ZL/ZR como bits. Não existe modo com
  gatilho analógico e gyro ao mesmo tempo. USB e 2,4 GHz não foram testados, por falta de cabo e dongle.
- **Botões traseiros** (G1–G4) não são expostos como botões próprios em nenhum modo, só por remapeamento no firmware.
- **Acelerômetro com ~9% de erro de escala** (1,09 g em repouso). Só a direção da gravidade é usada (Player Space),
  e a calibração não usa o acelerômetro.

## Steam e outros controles

- **Duas fontes de movimento.** Se a Steam Input entrega um controle ao jogo, ela é usada. Se não entrega nenhum
  (ex.: DualSense com Steam Input desligado), o mod lê o HID direto pelo SDL3 (`Show status` mostra `ps5 (HID)`).
  Com Steam Input ligado para PlayStation, o DualSense usa a Steam (testado em jogo, ~48 leituras/s, mesmos
  sinais de eixo do Pro Controller).
- **Switch 2 Pro Controller via Switch2Connect** (modo DualSense USB, Steam Input desligado para PlayStation):
  testado em jogo, ~65 leituras/s pelo HID (o IMU repete a leitura nos relatórios de 1 kHz).
- **DualSense original** com Steam Input desligado para PlayStation: testado em jogo por Bluetooth (~630 leituras/s
  pelo HID) e por USB (~250 leituras/s); vibração (haptics) e gatilhos adaptáveis continuam funcionando com o mod
  ativo.
- **Steam Input é obrigatório** para o TT Max em Switch mode: é ele que traduz botões, sticks e vibração para o BL4, e é a fonte
  do movimento dentro do jogo. É preciso ativar "Nintendo Switch" em Steam > Configurações > Controle. A saída de
  gyro do template padrão do BL4 já é "nenhuma"; não configurar gyro como mouse no Steam, senão a rotação dobra.
- **Movimento só com o jogo em foco.** Ao alternar de janela o gyro para, e a calibração automática no menu também
  precisa do jogo em foco.
- **~48 leituras/s dentro do jogo**, com lacunas de 40–500 ms ~2×/s. A velocidade mantida esconde isso, mas
  rotações muito bruscas dentro de uma lacuna (até 100 ms) usam a velocidade anterior até a próxima leitura.
  Fora do jogo o mesmo controle dá ~830 amostras/s via SDL.

## Jogo

- **Build testada: Steam 25372571.** Outra build gera aviso no console. A injeção é por reflexão, mas uma mudança nas
  escalas de input do BL4 (hoje ×2,5 / ×−2,5) alteraria a sensibilidade: refazer a medição com `tools/probe`.
- **Depende do oak2-mod-manager.** Um patch do BL4 pode quebrá-lo até o bl-sdk atualizar. Nesse caso o jogo abre
  sem mods.
- **Gyro desligado fora do personagem a pé** (veículos), e também com cursor visível, em pausa, com look input
  ignorado ou com a câmera fora do personagem.
- **Testado em jogo** (`evidence/PHASE-C.md`): gyro + analógico, ADS, menus/mapa/inventário, troca de arma,
  vibração, ícones, reconexão do controle, desligar/religar o mod, morte/loading, instalação pelo zip de release
  (sem `-GameDir`).
- **Não testado:** veículos, cutscenes e diálogos, co-op, Epic Store, Pro Controller original e Steam Controller
  (2026) (devem funcionar pela Steam Input ou pelo HID, mas não foram verificados), sessões longas (>1,5 h),
  replay com FPS travado em 30/60/144 dentro do jogo (coberto só pelo teste do DLL).
- **Co-op online:** a Take-Two declara não agir contra mods single-player e não comerciais. Use offline ou em sessão
  solo; um mod que mexe na mira em partida pública pode ser interpretado como vantagem.

## Projeto

- Sensibilidade padrão 2,0 (o testador joga em 3,0) e smoothing/tightening desligados são valores escolhidos por um único testador,
  não parâmetros validados de forma geral.
- Modos ADS-only, Hip-only, Hold, Toggle, Ratchet, World Space e Flick Stick ainda não existem (Fase E).
