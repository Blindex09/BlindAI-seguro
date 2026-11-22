'use strict';

// Logger simples em arquivo, com rotacao no inicio (5 MB -> .1).

const fs = require('fs');
const path = require('path');

const MAX_BYTES = 5 * 1024 * 1024;

function rotateIfLarge(file) {
  try {
    if (fs.statSync(file).size > MAX_BYTES) {
      fs.renameSync(file, `${file}.1`);
    }
  } catch (_) {
    // arquivo ainda nao existe
  }
}

function createLogger(dir, name) {
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, name);
  rotateIfLarge(file);
  const stream = fs.createWriteStream(file, { flags: 'a' });
  stream.on('error', () => {});

  const stamp = () => new Date().toISOString();
  const write = (level, message) => {
    stream.write(`${stamp()} [${level}] ${message}\n`);
  };

  return {
    file,
    dir,
    info: (m) => write('info', m),
    warn: (m) => write('warn', m),
    error: (m) => write('error', m),
    // Grava saida bruta de um processo filho, uma linha por entrada.
    raw(source, text) {
      for (const line of String(text).split(/\r?\n/)) {
        if (line.trim()) write(source, line);
      }
    },
    close() {
      try {
        stream.end();
      } catch (_) {
        // ignorado
      }
    },
  };
}

module.exports = { createLogger };
