'use strict';

// node --check em main.js, preload.js, src/**/*.js e scripts/**/*.js.
// Uso: node scripts/check-syntax.js   (npm run lint)

const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');

function collectFiles() {
  const files = [path.join(ROOT, 'main.js'), path.join(ROOT, 'preload.js')];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith('.js')) files.push(full);
    }
  };
  walk(path.join(ROOT, 'src'));
  walk(path.join(ROOT, 'scripts'));
  return files;
}

function checkSyntax() {
  const files = collectFiles();
  const errors = [];
  for (const file of files) {
    const r = spawnSync(process.execPath, ['--check', file], { encoding: 'utf8' });
    if (r.status !== 0) errors.push(`${path.relative(ROOT, file)}\n${r.stderr}`);
  }
  return { count: files.length, errors };
}

module.exports = { checkSyntax };

if (require.main === module) {
  const { count, errors } = checkSyntax();
  if (errors.length) {
    console.error(errors.join('\n'));
    process.exit(1);
  }
  console.log(`sintaxe ok em ${count} arquivos`);
}
