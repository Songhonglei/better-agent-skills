import { randomBytes } from 'node:crypto';
import { mkdir, open, unlink, writeFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { resolve } from 'node:path';

const data = resolve(process.env.DASHBOARD_DATA_DIR ?? resolve(homedir(), '.local/share/mulitca-cost-dashboard'));
const handle = await open('.env', 'wx', 0o600).catch(() => {
  throw new Error('.env already exists or cannot be created. Keep the existing configuration or choose a new installation directory.');
});
const created = [];
try {
  await mkdir(data, { recursive: true, mode: 0o700 });
  for (const name of ['admin-secret', 'ingest-secret']) {
    const path = resolve(data, name);
    await writeFile(path, `${randomBytes(32).toString('hex')}\n`, { flag: 'wx', mode: 0o600 });
    created.push(path);
  }
  const password = randomBytes(24).toString('hex');
  const content = {
    DATABASE_URL: `postgresql://dashboard:${password}@127.0.0.1:55432/dashboard`,
    POSTGRES_PASSWORD: password,
    ADMIN_SECRET_FILE: resolve(data, 'admin-secret'),
    INGEST_SECRET_FILE: resolve(data, 'ingest-secret'),
    USAGE_SNAPSHOT_PATH: resolve(data, 'usage.json'),
    HOST: '127.0.0.1',
    PORT: '4318',
    COST_DASHBOARD_URL: 'http://127.0.0.1:4318/',
    MULTICA_BIN: 'multica',
    MULTICA_PROFILE: '',
    MAX_PAYLOAD_BYTES: '67108864',
  };
  await handle.writeFile(Object.entries(content).map(([key, value]) => `${key}=${JSON.stringify(value)}`).join('\n') + '\n');
  console.log('Configuration created. Start PostgreSQL, then run npm run build, npm run migrate and npm start.');
  console.log('Browser username is admin. Read the password from ADMIN_SECRET_FILE in .env.');
} catch (error) {
  await Promise.all(created.map((path) => unlink(path)));
  await unlink('.env');
  throw error;
} finally {
  await handle.close();
}
