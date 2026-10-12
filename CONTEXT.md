# Glossário

- **Gyro delta**: rotação do controle, já calibrada e no espaço escolhido (Player/Local), em graus.
- **Camera delta**: gyro delta × sensibilidade (H/V, multiplicador de ADS, inversão), aplicado à câmera do jogo.
- **Gate**: estado do jogo que permite (aberto) ou bloqueia (fechado) o gyro. Aberto só com o personagem a pé,
  sem cursor, sem pausa, sem look input ignorado e com a câmera no próprio personagem.
- **Calibração automática**: remoção do bias do gyro enquanto o controle está parado. Só roda com o gate fechado.
- **Calibração manual**: medição explícita do bias por 3 s ("Calibrate now"), com o controle parado.
- **Velocidade mantida (rate hold)**: a última velocidade angular recebida, integrada no tempo de cada frame.
  É mantida por no máximo 100 ms sem novas leituras.
- **Pacote de movimento**: uma leitura nova de `ISteamInput::GetMotionData` (dentro do jogo, ~48 por segundo).
