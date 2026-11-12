import { z } from 'zod';
import type { FastifyInstance } from 'fastify';

import { verifyCollectorRequest, type CollectorNonceStore } from '../security/collector-signature.js';
import { ExpensePriceConflictError, type ExpenseService } from './service.js';
import { ExpenseSnapshotConflictError } from './usage-v2.js';
import type { WorkspaceUsageSnapshot, UsageSnapshotChunk } from './types.js';

const tokenFields = {
  inputTokens: z.number().int().nonnegative(),
  outputTokens: z.number().int().nonnegative(),
  cacheReadTokens: z.number().int().nonnegative(),
  cacheWriteTokens: z.number().int().nonnegative(),
};
const runtimeUsage = z.object({
  runtimeId: z.string().min(1), runtimeName: z.string().min(1), usageDate: z.string().date(),
  provider: z.string().min(1), model: z.string().min(1), ...tokenFields,
});
const taskUsage = z.object({
  taskId: z.string().min(1), agentId: z.string().min(1), agentName: z.string().min(1),
  runtimeId: z.string().optional(), runtimeName: z.string().optional(), usageDate: z.string().date(),
  provider: z.string().min(1), model: z.string().min(1), ...tokenFields,
  issueId: z.string().optional(), projectId: z.string().optional(), projectName: z.string().optional(),
  initiator: z.string().optional(), delegationPath: z.array(z.string()).optional(),
});
const issueUsage = z.object({
  issueId: z.string().min(1), identifier: z.string().min(1), title: z.string().min(1),
  projectId: z.string().optional(), projectName: z.string().optional(),
  assigneeAgentId: z.string().optional(), assigneeAgentName: z.string().optional(),
  agentAttributionSource: z.string().optional(),
  creatorType: z.string().optional(), creatorId: z.string().optional(), creatorName: z.string().optional(),
  initiatorId: z.string().optional(), initiatorName: z.string().optional(), initiatorEmail: z.string().optional(),
  initiatorPrecise: z.boolean().optional(), initiatorSource: z.string().optional(),
  ...tokenFields,
  uncostedInputTokens: z.number().int().nonnegative(), uncostedOutputTokens: z.number().int().nonnegative(),
  uncostedCacheReadTokens: z.number().int().nonnegative(), uncostedCacheWriteTokens: z.number().int().nonnegative(),
  costUsdTicks: z.number().int().nonnegative(), lastActivityAt: z.string().datetime(),
  modelUsage: z.array(z.object({
    usageDate: z.string().date(), provider: z.string().min(1), model: z.string().min(1), ...tokenFields,
  })).optional(),
});
const snapshotSchemaV1 = z.object({
  schemaVersion: z.literal(1), collectedAt: z.string().datetime(),
  runtimeUsage: z.array(runtimeUsage), taskUsage: z.array(taskUsage),
  issueUsage: z.array(issueUsage).optional(),
  runtimes: z.array(z.object({ id: z.string().min(1), name: z.string().min(1), status: z.string().min(1) })).optional(),
  skippedOffline: z.number().int().nonnegative().optional(),
  failures: z.array(z.object({ stage: z.string().min(1), entityId: z.string().optional(), message: z.string().min(1) })).optional(),
});
const snapshotSchemaV2 = z.object({
  schemaVersion: z.literal(2),
  snapshotId: z.string().uuid(), uploadId: z.string().uuid(), collectedAt: z.string().datetime(),
  queryWindow: z.object({ startDate: z.string().date(), endDate: z.string().date() }).strict(),
  collectionScope: z.object({
    runtimeListSucceeded: z.boolean(),
    runtimeIds: z.array(z.string().min(1)),
    successfulRuntimeIds: z.array(z.string().min(1)),
    failedRuntimeIds: z.array(z.string().min(1)),
  }).strict(),
  expectedRows: z.object({
    runtime: z.number().int().nonnegative().max(1_000_000),
    task: z.number().int().nonnegative().max(1_000_000),
    issue: z.number().int().nonnegative().max(1_000_000),
  }).strict(),
  chunk: z.object({ index: z.number().int().nonnegative(), total: z.number().int().positive().max(10_000), final: z.boolean() }).strict(),
  runtimeUsage: z.array(runtimeUsage), taskUsage: z.array(taskUsage), issueUsage: z.array(issueUsage),
  runtimes: z.array(z.object({ id: z.string().min(1), name: z.string().min(1), status: z.string().min(1) })),
  skippedOffline: z.number().int().nonnegative(),
  failures: z.array(z.object({ stage: z.string().min(1), entityId: z.string().optional(), message: z.string().min(1) })),
}).strict().superRefine((value, context) => {
  if (value.chunk.index >= value.chunk.total)
    context.addIssue({ code: z.ZodIssueCode.custom, path: ['chunk', 'index'], message: 'index 必须小于 total' });
});
const priceSchema = z.object({
  id: z.string().min(1).optional(), provider: z.string().min(1), model: z.string().min(1), displayName: z.string().min(1),
  currency: z.enum(['USD', 'CNY']), usdExchangeRate: z.number().positive(),
  inputPerMillion: z.number().nonnegative(), outputPerMillion: z.number().nonnegative(),
  cacheReadPerMillion: z.number().nonnegative(), cacheWritePerMillion: z.number().nonnegative(),
  effectiveFrom: z.string().date(), effectiveTo: z.string().date().nullable().optional(),
}).superRefine((price, context) => {
  if (price.effectiveTo && price.effectiveTo < price.effectiveFrom) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ['effectiveTo'], message: '失效日期不能早于生效日期' });
  }
});
const bulkPriceSchema = z.object({ prices: z.array(priceSchema).min(1).max(500) });
const exchangeRateSchema = z.object({ cnyPerUsd: z.number().positive().max(100) });
const expenseQuerySchema = z.object({
  start: z.string().date().optional(),
  end: z.string().date().optional(),
  granularity: z.enum(['day', 'week', 'month']).optional(),
}).superRefine((query, context) => {
  if (query.start && query.end && query.start > query.end) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ['end'], message: '结束日期不能早于开始日期' });
  }
});

export type ExpenseRouteDependencies = {
  service: ExpenseService;
  ingestSecret?: string;
  nonces?: CollectorNonceStore;
};

export function registerExpenseRoutes(app: FastifyInstance, dependencies: ExpenseRouteDependencies) {
  app.get('/api/expenses', async (request, reply) => {
    const parsed = expenseQuerySchema.safeParse(request.query);
    if (!parsed.success) return reply.code(400).send({ error: '费用查询条件无效', details: parsed.error.flatten() });
    return dependencies.service.summary(parsed.data);
  });
  app.get('/api/expenses/settings', async (request) => {
    const email = 'admin';
    const [prices, cnyPerUsd, isAdmin] = await Promise.all([
      dependencies.service.prices(), dependencies.service.cnyPerUsd(), Promise.resolve(true),
    ]);
    return { prices, cnyPerUsd, isAdmin, userEmail: email };
  });
  app.put('/api/expenses/exchange-rate', async (request, reply) => {
    const current = { email: 'admin', userId: 'admin' };
    const parsed = exchangeRateSchema.safeParse(request.body);
    if (!parsed.success) return reply.code(400).send({ error: '人民币汇率无效', details: parsed.error.flatten() });
    return dependencies.service.saveCnyPerUsd(parsed.data.cnyPerUsd, current.email ?? current.userId);
  });
  app.put('/api/expenses/prices', async (request, reply) => {
    const current = { email: 'admin', userId: 'admin' };
    const parsed = priceSchema.safeParse(request.body);
    if (!parsed.success) return reply.code(400).send({ error: '价格配置无效', details: parsed.error.flatten() });
    try {
      return await dependencies.service.savePrice(parsed.data, current.email ?? current.userId);
    } catch (error) {
      if (error instanceof ExpensePriceConflictError) return reply.code(409).send({ error: error.message });
      throw error;
    }
  });
  app.post('/api/expenses/prices/bulk', async (request, reply) => {
    const current = { email: 'admin', userId: 'admin' };
    const parsed = bulkPriceSchema.safeParse(request.body);
    if (!parsed.success) return reply.code(400).send({ error: '批量价格配置无效', details: parsed.error.flatten() });
    try {
      return await dependencies.service.savePrices(parsed.data.prices, current.email ?? current.userId);
    } catch (error) {
      if (error instanceof ExpensePriceConflictError) return reply.code(409).send({ error: error.message });
      throw error;
    }
  });
  app.post('/api/collector/usage-snapshots', async (request, reply) => {
    if (!dependencies.ingestSecret || !dependencies.nonces) return reply.code(503).send({ error: '费用采集服务未配置' });
    try {
      await verifyCollectorRequest({
        secret: dependencies.ingestSecret, method: request.method, path: request.url,
        body: request.body, headers: request.headers, nonces: dependencies.nonces,
      });
    } catch (error) {
      return reply.code(401).send({ error: error instanceof Error ? error.message : '费用采集鉴权失败' });
    }
    const isV2 = (request.body as { schemaVersion?: unknown } | undefined)?.schemaVersion === 2;
    const parsed = (isV2 ? snapshotSchemaV2 : snapshotSchemaV1).safeParse(request.body);
    if (!parsed.success)
      return reply.code(400).send({ error: 'usage.json 快照无效', details: parsed.error.flatten() });
    if (!isV2)
      return dependencies.service.ingest(parsed.data as WorkspaceUsageSnapshot);
    try {
      return await dependencies.service.ingestV2(parsed.data as UsageSnapshotChunk);
    } catch (error) {
      if (error instanceof ExpenseSnapshotConflictError)
        return reply.code(409).send({ error: error.message });
      throw error;
    }
  });
}
