'use strict';

// Supervisor do backend (processo filho). Sem dependencia do Electron, para poder
// ser testado isoladamente (scripts/smoke.js).
//
// - escolhe uma porta livre (prefere preferredPort) e a exporta em BLIND_PORT
// - espera o health check responder 2xx dentro de healthTimeoutMs
// - se o backend morrer depois de pronto: reinicia com backoff, no maximo maxRestarts vezes
// - falha na subida inicial NAO e repetida automaticamente (o app mostra erro + "Tentar novamente")
// - stop() encerra a arvore de processos inteira (taskkill /T no Windows)

const { EventEmitter } = require('events');
const childProcess = require('child_process');
const net = require('net');
const http = require('http');

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function makeError(code, message) {
  const err = new Error(message);
  err.code = code;
  return err;
}

// ---------------------------------------------------------------- portas

function canConnect(port, host = '127.0.0.1', timeoutMs = 400) {
  return new Promise((resolve) => {
    const sock = net.connect({ port, host });
    let done = false;
    const finish = (value) => {
      if (done) return;
      done = true;
      sock.destroy();
      resolve(value);
    };
    sock.setTimeout(timeoutMs, () => finish(false));
    sock.once('connect', () => finish(true));
    sock.once('error', () => finish(false));
  });
}

function canBind(port, host) {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.unref();
    srv.once('error', () => resolve(false));
    srv.listen({ port, host }, () => srv.close(() => resolve(true)));
  });
}

// O backend antigo escuta em 0.0.0.0. No Windows, ligar 127.0.0.1:porta pode "funcionar"
// mesmo com outro processo em 0.0.0.0:porta, entao confere conexao e os dois enderecos.
async function isPortFree(port) {
  if (await canConnect(port)) return false;
  if (!(await canBind(port, '127.0.0.1'))) return false;
  return canBind(port, '0.0.0.0');
}

function ephemeralPort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.once('error', reject);
    srv.listen({ port: 0, host: '127.0.0.1' }, () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

async function findFreePort(preferred) {
  if (preferred > 0 && (await isPortFree(preferred))) return preferred;
  for (let i = 0; i < 10; i += 1) {
    const port = await ephemeralPort();
    if (await isPortFree(port)) return port;
  }
  throw makeError('NOPORT', 'Nao foi possivel encontrar uma porta livre.');
}

// ---------------------------------------------------------------- http / processos

function httpStatus(port, urlPath, timeoutMs) {
  return new Promise((resolve) => {
    const req = http.get(
      { host: '127.0.0.1', port, path: urlPath, timeout: timeoutMs, agent: false },
      (res) => {
        res.resume();
        resolve(res.statusCode);
      },
    );
    req.on('timeout', () => {
      req.destroy();
      resolve(null);
    });
    req.on('error', () => resolve(null));
  });
}

function killProcessTree(child) {
  return new Promise((resolve) => {
    if (!child || !child.pid || child.exitCode !== null) {
      resolve();
      return;
    }
    if (process.platform === 'win32') {
      childProcess.execFile('taskkill', ['/PID', String(child.pid), '/T', '/F'], () => resolve());
      return;
    }
    try {
      process.kill(-child.pid, 'SIGTERM');
    } catch (_) {
      try {
        child.kill('SIGTERM');
      } catch (__) {
        // ja encerrado
      }
    }
    resolve();
  });
}

function describeExit(info, command) {
  if (info.error) {
    if (info.error.code === 'ENOENT') {
      return `Nao foi possivel iniciar "${command}". Verifique se o Python esta instalado ou defina BLIND_PYTHON.`;
    }
    return `Falha ao iniciar o processo: ${info.error.message}`;
  }
  if (info.signal) return `encerrado pelo sinal ${info.signal}`;
  return `encerrado com codigo ${info.code}`;
}

// ---------------------------------------------------------------- supervisor

class BackendSupervisor extends EventEmitter {
  constructor(options = {}) {
    super();
    this.opts = {
      command: 'python',
      args: ['server.py'],
      cwd: process.cwd(),
      env: {},
      preferredPort: 8765,
      healthPath: '/api/status',
      healthTimeoutMs: 30000,
      healthIntervalMs: 400,
      maxRestarts: 3,
      backoffMs: [1000, 2000, 4000],
      stableMs: 60000,
      stopTimeoutMs: 5000,
      spawn: childProcess.spawn,
      killTree: killProcessTree,
      logger: null,
      ...options,
    };
    this.state = 'stopped';
    this.port = null;
    this.error = null;
    this.restarts = 0;
    this.child = null;
    this._exited = null;
    this._stopping = false;
    this._startPromise = null;
    this._restartPromise = null;
    this._stableTimer = null;
    this._wake = null;
    this._tail = [];
  }

  recentOutput(lines = 15) {
    return this._tail.slice(-lines).join('\n');
  }

  _log(level, message) {
    const logger = this.opts.logger;
    if (logger && typeof logger[level] === 'function') logger[level](message);
  }

  _setState(state, extra = {}) {
    if (state === 'stopped' && this.state === 'stopped') return;
    this.state = state;
    if (state === 'ready') this.error = null;
    this.emit('state', {
      state,
      port: this.port,
      error: this.error,
      attempt: this.restarts,
      ...extra,
    });
  }

  _setFailed(err) {
    this.error = err.message;
    this._log('error', `backend falhou: ${err.message}`);
    this._setState('failed', { output: err.output || this.recentOutput() });
  }

  // ---- ciclo de vida publico

  start() {
    if (this.state === 'ready') return Promise.resolve({ port: this.port });
    if (this._startPromise) return this._startPromise;
    const begin = async () => {
      if (this._restartPromise) await this.stop();
      this._stopping = false;
      this.restarts = 0;
      try {
        return await this._launchOnce();
      } catch (err) {
        if (err.code === 'ECANCELLED') throw err;
        this._setFailed(err);
        throw err;
      }
    };
    this._startPromise = begin().finally(() => {
      this._startPromise = null;
    });
    return this._startPromise;
  }

  async restart() {
    await this.stop();
    return this.start();
  }

  async stop() {
    this._stopping = true;
    if (this._wake) this._wake();
    clearTimeout(this._stableTimer);
    const child = this.child;
    const exited = this._exited;
    if (child) {
      await this.opts.killTree(child);
      if (exited) await Promise.race([exited, sleep(this.opts.stopTimeoutMs)]);
    }
    this.child = null;
    if (this._startPromise) await this._startPromise.catch(() => {});
    if (this._restartPromise) await this._restartPromise.catch(() => {});
    this._setState('stopped');
  }

  // ---- internos

  async _launchOnce() {
    const { opts } = this;
    const port = await findFreePort(opts.preferredPort);
    this.port = port;
    this.error = null;
    this._tail = [];
    this._setState('starting');

    const env = { ...process.env, ...opts.env, BLIND_PORT: String(port) };
    let child;
    try {
      child = opts.spawn(opts.command, opts.args, {
        cwd: opts.cwd,
        env,
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe'],
        detached: process.platform !== 'win32',
      });
    } catch (err) {
      throw makeError('SPAWN', describeExit({ error: err }, opts.command));
    }
    this._log('info', `backend iniciado (pid ${child.pid}) na porta ${port}: ${opts.command} ${opts.args.join(' ')}`);
    this.child = child;

    let exitInfo = null;
    const exited = new Promise((resolve) => {
      child.once('exit', (code, signal) => {
        if (!exitInfo) exitInfo = { code, signal };
        resolve(exitInfo);
      });
      child.once('error', (error) => {
        if (!exitInfo) exitInfo = { error };
        resolve(exitInfo);
      });
    });
    this._exited = exited;

    const onData = (source) => (chunk) => {
      const text = String(chunk);
      if (opts.logger) opts.logger.raw(source, text);
      for (const line of text.split(/\r?\n/)) {
        if (line.trim()) this._tail.push(line);
      }
      if (this._tail.length > 200) this._tail.splice(0, this._tail.length - 200);
    };
    if (child.stdout) {
      child.stdout.setEncoding('utf8');
      child.stdout.on('data', onData('backend'));
    }
    if (child.stderr) {
      child.stderr.setEncoding('utf8');
      child.stderr.on('data', onData('backend'));
    }

    try {
      await this._waitHealthy(port, () => exitInfo === null, () => exitInfo);
    } catch (err) {
      await opts.killTree(child);
      this.child = null;
      err.output = this.recentOutput();
      if (this._stopping) throw makeError('ECANCELLED', 'Inicializacao cancelada.');
      throw err;
    }
    if (this._stopping) {
      await opts.killTree(child);
      this.child = null;
      throw makeError('ECANCELLED', 'Inicializacao cancelada.');
    }

    this._setState('ready');
    clearTimeout(this._stableTimer);
    this._stableTimer = setTimeout(() => {
      this.restarts = 0;
    }, opts.stableMs);
    if (this._stableTimer.unref) this._stableTimer.unref();

    exited.then((info) => this._onExit(child, info));
    return { port };
  }

  async _waitHealthy(port, isAlive, getExit) {
    const { opts } = this;
    const deadline = Date.now() + opts.healthTimeoutMs;
    for (;;) {
      if (!isAlive()) {
        throw makeError('EXITED', `O backend encerrou antes de ficar pronto (${describeExit(getExit(), opts.command)}).`);
      }
      const remaining = deadline - Date.now();
      const status = await httpStatus(port, opts.healthPath, Math.max(200, Math.min(2000, remaining)));
      if (status !== null && status >= 200 && status < 300) return;
      if (Date.now() >= deadline) {
        throw makeError('TIMEOUT', `O backend nao respondeu em ${Math.round(opts.healthTimeoutMs / 1000)} segundos na porta ${port}.`);
      }
      await sleep(opts.healthIntervalMs);
    }
  }

  _onExit(child, info) {
    if (child !== this.child) return;
    this.child = null;
    clearTimeout(this._stableTimer);
    if (this._stopping) {
      this._setState('stopped');
      return;
    }
    const reason = describeExit(info, this.opts.command);
    this._log('warn', `backend encerrou inesperadamente: ${reason}`);
    this._restartPromise = this._restartLoop(reason).finally(() => {
      this._restartPromise = null;
    });
  }

  _interruptibleSleep(ms) {
    return new Promise((resolve) => {
      const timer = setTimeout(done, ms);
      const self = this;
      function done() {
        clearTimeout(timer);
        self._wake = null;
        resolve();
      }
      this._wake = done;
    });
  }

  async _restartLoop(initialReason) {
    const { opts } = this;
    let reason = initialReason;
    while (!this._stopping) {
      this.restarts += 1;
      if (this.restarts > opts.maxRestarts) {
        this._setFailed(makeError('EXHAUSTED', `O backend caiu repetidamente (${reason}). Reinicios automaticos esgotados.`));
        return;
      }
      const delay = opts.backoffMs[Math.min(this.restarts - 1, opts.backoffMs.length - 1)];
      this.error = reason;
      this._setState('restarting', { delayMs: delay, reason });
      await this._interruptibleSleep(delay);
      if (this._stopping) return;
      try {
        await this._launchOnce();
        return;
      } catch (err) {
        if (err.code === 'ECANCELLED') return;
        reason = err.message;
      }
    }
  }
}

module.exports = {
  BackendSupervisor,
  findFreePort,
  isPortFree,
  killProcessTree,
  httpStatus,
};
