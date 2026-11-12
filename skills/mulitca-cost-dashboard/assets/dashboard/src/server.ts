import { createApp } from './app.js';
import { loadConfig, readSecret } from './config.js';
import { createDatabase } from './db/client.js';

async function main() {
  const config = loadConfig();
  const { db, pool } = createDatabase(config.DATABASE_URL);
  const app = await createApp({
    db,
    adminSecret: readSecret(config.ADMIN_SECRET_FILE),
    ingestSecret: readSecret(config.INGEST_SECRET_FILE),
    bodyLimit: config.MAX_PAYLOAD_BYTES,
  });
  app.addHook('onClose', async () => { await pool.end(); });
  for (const signal of ['SIGTERM', 'SIGINT']) {
    process.once(signal, () => { void app.close(); });
  }
  await app.listen({ host: config.HOST, port: config.PORT });
  console.log(`Multica Cost Dashboard listening on ${config.HOST}:${config.PORT}`);
}

main().catch(() => {
  console.error('Startup failed. Check .env, secret file permissions, database connectivity and npm run migrate.');
  process.exit(1);
});
