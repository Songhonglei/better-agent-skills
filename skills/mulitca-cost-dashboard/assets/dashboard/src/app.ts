import { timingSafeEqual } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import fastify from 'fastify';
import { sql } from 'drizzle-orm';
import type { Database } from './db/client.js';
import { registerExpenseRoutes } from './expenses/routes.js';
import { ExpenseService } from './expenses/service.js';
import type { CollectorNonceStore } from './security/collector-signature.js';

export async function createApp(options: {
  db: Database;
  adminSecret: string;
  ingestSecret: string;
  bodyLimit?: number;
}) {
  const app = fastify({ bodyLimit: options.bodyLimit ?? 67108864 });
  const expected = Buffer.from(`Basic ${Buffer.from(`admin:${options.adminSecret}`).toString('base64')}`);
  app.addHook('onRequest', async (request, reply) => {
    const path = request.url.split('?')[0];
    if (path === '/health' || path === '/api/collector/usage-snapshots') return;
    const actual = Buffer.from(request.headers.authorization ?? '');
    if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) {
      return reply.header('WWW-Authenticate', 'Basic realm="Multica Cost Dashboard"').code(401).send({ error: '请使用 admin 和管理员密码登录' });
    }
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method) && request.headers.origin) {
      let originHost: string;
      try { originHost = new URL(request.headers.origin).host; }
      catch { return reply.code(403).send({ error: '请求来源无效，请刷新页面' }); }
      if (originHost !== request.headers.host) return reply.code(403).send({ error: '请求来源无效，请从大盘页面操作' });
    }
  });
  app.addHook('onSend', async (_request, reply) => {
    reply.header('X-Content-Type-Options', 'nosniff');
    reply.header('X-Frame-Options', 'DENY');
    reply.header('Referrer-Policy', 'no-referrer');
    reply.header('Cache-Control', 'no-store');
  });
  app.setErrorHandler((error, _request, reply) => {
    const code = (error as { statusCode?: number }).statusCode;
    const status = code && code >= 400 && code < 500 ? code : 500;
    reply.code(status).send({ error: status === 413 ? '快照超过请求大小限制，请减小分块' : '请求失败，请检查输入和服务日志' });
    if (status === 500) console.error('Request failed. Check database connectivity and migration status.');
  });
  const nonces: CollectorNonceStore = {
    async claim(nonce, expiresAt) {
      return options.db.transaction(async (tx) => {
        await tx.execute(sql`delete from collector_nonces where expires_at < now()`);
        const result = await tx.execute(sql`insert into collector_nonces (nonce, expires_at) values (${nonce}, ${expiresAt.toISOString()}) on conflict do nothing returning nonce`);
        return (result.rowCount ?? 0) > 0;
      });
    },
  };
  registerExpenseRoutes(app, { service: new ExpenseService(options.db), ingestSecret: options.ingestSecret, nonces });
  app.get('/health', async () => {
    await options.db.execute(sql`select 1`);
    return { status: 'ok' };
  });
  const webRoot = fileURLToPath(new URL('../web-dist/', import.meta.url));
  app.get('/', async (_request, reply) => {
    return reply.type('text/html; charset=utf-8').send(await readFile(resolve(webRoot, 'index.html')));
  });
  app.get<{ Params: { file: string } }>('/assets/:file', async (request, reply) => {
    const { file } = request.params;
    if (!/^[a-zA-Z0-9_-][a-zA-Z0-9_.-]*\.(js|css)$/.test(file)) return reply.code(404).send();
    try {
      const content = await readFile(resolve(webRoot, 'assets', file));
      return reply.type(file.endsWith('.js') ? 'text/javascript' : 'text/css').send(content);
    } catch {
      return reply.code(404).send();
    }
  });
  return app;
}
