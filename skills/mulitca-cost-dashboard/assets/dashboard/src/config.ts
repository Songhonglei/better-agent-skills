import { readFileSync, statSync } from 'node:fs';
import { resolve } from 'node:path';
import { z } from 'zod';

const schema = z.object({
  DATABASE_URL: z.string().min(1),
  ADMIN_SECRET_FILE: z.string().min(1),
  INGEST_SECRET_FILE: z.string().min(1),
  HOST: z.string().default('127.0.0.1'),
  PORT: z.coerce.number().int().min(1).max(65535).default(4318),
  MAX_PAYLOAD_BYTES: z.coerce.number().int().min(1048576).max(104857600).default(67108864),
});

export function readSecret(path: string): string {
  const absolute = resolve(path);
  const stat = statSync(absolute);
  if (!stat.isFile() || (process.platform !== 'win32' && ![0o400, 0o600].includes(stat.mode & 0o777))) {
    throw new Error('Secret file must be a regular file with mode 400 or 600');
  }
  const secret = readFileSync(absolute, 'utf8').trim();
  if (secret.length < 32) throw new Error('Secret file must contain at least 32 characters');
  return secret;
}

export function loadConfig() {
  const parsed = schema.safeParse(process.env);
  if (!parsed.success) {
    throw new Error(`Invalid configuration fields: ${parsed.error.issues.map((issue) => issue.path.join('.')).join(', ')}. Run npm run setup and check .env`);
  }
  return parsed.data;
}
