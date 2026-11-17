import { randomBytes } from 'node:crypto';
import { chmodSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { afterAll, expect, it } from 'vitest';
import { readSecret } from '../src/config.js';

const directory = mkdtempSync(resolve(tmpdir(), 'dashboard-secret-test-'));
const secretFile = resolve(directory, 'secret');
afterAll(() => rmSync(directory, { recursive: true, force: true }));

it('accepts administrator passwords from 12 characters and rejects shorter ones', () => {
  writeFileSync(secretFile, randomBytes(6).toString('hex'), { mode: 0o600 });
  expect(readSecret(secretFile, 12)).toHaveLength(12);
  writeFileSync(secretFile, randomBytes(5).toString('hex'));
  expect(() => readSecret(secretFile, 12)).toThrow('at least 12 characters');
});

it('keeps the default collector secret minimum at 32 characters', () => {
  writeFileSync(secretFile, randomBytes(16).toString('hex'));
  expect(readSecret(secretFile)).toHaveLength(32);
  writeFileSync(secretFile, randomBytes(15).toString('hex'));
  expect(() => readSecret(secretFile)).toThrow('at least 32 characters');
});

it.skipIf(process.platform === 'win32')('enforces private permissions for administrator passwords', () => {
  writeFileSync(secretFile, randomBytes(16).toString('hex'));
  chmodSync(secretFile, 0o644);
  expect(() => readSecret(secretFile, 12)).toThrow('mode 400 or 600');
  chmodSync(secretFile, 0o400);
  expect(readSecret(secretFile, 12)).toHaveLength(32);
});
