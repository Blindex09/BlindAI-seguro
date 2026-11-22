'use strict';

// Icone gerado em memoria (disco azul claro com um "B" escuro), para tray e janela.
// Evita depender de arquivos de imagem; troque por um .ico/.png real quando houver arte.

const { nativeImage } = require('electron');

function createIcon(size = 32) {
  const buf = Buffer.alloc(size * size * 4);
  const c = (size - 1) / 2;
  const radius = size / 2 - 1;

  const inLetter = (x, y) => {
    const u = x / size;
    const v = y / size;
    const stem = u >= 0.32 && u <= 0.43 && v >= 0.24 && v <= 0.76;
    const topBar = u >= 0.32 && u <= 0.62 && v >= 0.24 && v <= 0.33;
    const midBar = u >= 0.32 && u <= 0.62 && v >= 0.46 && v <= 0.54;
    const botBar = u >= 0.32 && u <= 0.64 && v >= 0.67 && v <= 0.76;
    const rightTop = u >= 0.55 && u <= 0.66 && v >= 0.28 && v <= 0.50;
    const rightBot = u >= 0.57 && u <= 0.68 && v >= 0.50 && v <= 0.72;
    return stem || topBar || midBar || botBar || rightTop || rightBot;
  };

  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const dist = Math.hypot(x - c, y - c);
      const alpha = Math.max(0, Math.min(1, radius + 0.5 - dist));
      const offset = (y * size + x) * 4;
      // BGRA
      if (inLetter(x, y)) {
        buf[offset] = 0x2a;
        buf[offset + 1] = 0x17;
        buf[offset + 2] = 0x0f;
      } else {
        buf[offset] = 0xf8;
        buf[offset + 1] = 0xbd;
        buf[offset + 2] = 0x38;
      }
      buf[offset + 3] = Math.round(alpha * 255);
    }
  }
  return nativeImage.createFromBitmap(buf, { width: size, height: size });
}

module.exports = { createIcon };
