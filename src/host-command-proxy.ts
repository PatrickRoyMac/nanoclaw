/**
 * Host Command Proxy
 *
 * Listens on a Unix socket and executes shell commands on behalf of containers.
 * Containers send JSON { cmd, timeout? } and receive JSON { stdout, stderr, exitCode }.
 *
 * The socket is bind-mounted read-write into every container at /host/cmd.sock.
 * Only containers that are explicitly given the mount can connect — there is no
 * network exposure.
 *
 * All executed commands are logged for auditability.
 */

import { exec } from 'child_process';
import fs from 'fs';
import { createServer, Server } from 'net';

import { logger } from './logger.js';

export const HOST_CMD_SOCKET_PATH = '/tmp/nanoclaw-host.sock';
const MAX_TIMEOUT_MS = 120_000;
const MAX_OUTPUT_BYTES = 1024 * 1024; // 1 MB

interface CmdRequest {
  cmd: string;
  timeout?: number;
}

interface CmdResponse {
  stdout: string;
  stderr: string;
  exitCode: number;
}

let server: Server | null = null;

export function startHostCommandProxy(): void {
  // Remove stale socket from a previous run
  if (fs.existsSync(HOST_CMD_SOCKET_PATH)) {
    fs.unlinkSync(HOST_CMD_SOCKET_PATH);
  }

  server = createServer({ allowHalfOpen: true }, (socket) => {
    let raw = '';

    socket.on('data', (chunk) => {
      raw += chunk.toString();
    });

    socket.on('end', () => {
      let req: CmdRequest;
      try {
        req = JSON.parse(raw);
      } catch {
        const err: CmdResponse = { stdout: '', stderr: 'Invalid JSON request', exitCode: 1 };
        socket.write(JSON.stringify(err));
        socket.end();
        return;
      }

      const cmd = String(req.cmd || '').trim();
      if (!cmd) {
        const err: CmdResponse = { stdout: '', stderr: 'Empty command', exitCode: 1 };
        socket.write(JSON.stringify(err));
        socket.end();
        return;
      }

      const timeout = Math.min(req.timeout ?? 30_000, MAX_TIMEOUT_MS);

      logger.info({ cmd }, 'Host command proxy: executing');

      exec(cmd, { timeout, maxBuffer: MAX_OUTPUT_BYTES, shell: '/bin/bash' }, (err, stdout, stderr) => {
        const exitCode = err?.code ?? (err ? 1 : 0);
        if (exitCode !== 0) {
          logger.warn({ cmd, exitCode }, 'Host command proxy: non-zero exit');
        }
        const response: CmdResponse = { stdout, stderr, exitCode };
        socket.write(JSON.stringify(response));
        socket.end();
      });
    });

    socket.on('error', (err) => {
      logger.debug({ err: err.message }, 'Host command proxy: socket error');
    });
  });

  server.listen(HOST_CMD_SOCKET_PATH, () => {
    // Allow the container's node user (uid 1000) to connect
    fs.chmodSync(HOST_CMD_SOCKET_PATH, 0o777);
    logger.info({ socketPath: HOST_CMD_SOCKET_PATH }, 'Host command proxy started');
  });

  server.on('error', (err) => {
    logger.error({ err }, 'Host command proxy error');
  });
}

export function stopHostCommandProxy(): void {
  server?.close();
  if (fs.existsSync(HOST_CMD_SOCKET_PATH)) {
    fs.unlinkSync(HOST_CMD_SOCKET_PATH);
  }
}
