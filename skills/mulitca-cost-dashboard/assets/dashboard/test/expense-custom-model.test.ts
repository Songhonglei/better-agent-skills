import { describe, expect, it, vi } from 'vitest';

import type { Database } from '../src/db/client.js';
import { canonicalModelPriceKey, ExpenseService } from '../src/expenses/service.js';
import { appConfig, expenseIssueUsage, expenseRuntimeUsage, expenseTaskUsage } from '../src/db/schema.js';

const collectedAt = new Date('2026-10-23T08:00:00Z');

function price(model: string, inputPerMillion = 2, overrides: Record<string, unknown> = {}) {
  return {
    id: model, provider: 'price-provider', model, canonicalKey: canonicalModelPriceKey('price-provider', model),
    displayName: model, currency: 'USD' as const, usdExchangeRate: 1,
    inputPerMillion, outputPerMillion: 4, cacheReadPerMillion: 1, cacheWritePerMillion: 3,
    effectiveFrom: '2026-01-01', effectiveTo: null, updatedBy: 'test', updatedAt: collectedAt,
    ...overrides,
  };
}

async function summarize(model: string, prices: ReturnType<typeof price>[]) {
  const row = {
    runtimeId: 'r1', runtimeName: 'Runtime', usageDate: '2026-10-23', provider: 'example', model,
    inputTokens: 1_000_000, outputTokens: 1_000_000, cacheReadTokens: 1_000_000, cacheWriteTokens: 1_000_000, collectedAt,
  };
  const task = { ...row, taskId: 'task-1', agentId: 'agent-1', agentName: 'Agent', delegationPath: [] };
  const resultSets = new Map<unknown, unknown[]>([
    [expenseRuntimeUsage, [row]], [expenseTaskUsage, [task]], [expenseIssueUsage, []], [appConfig, []],
  ]);
  const select = vi.fn(() => ({
    from: (table: unknown) => {
      const rows = resultSets.get(table) ?? [];
      return {
        then: (resolve: (value: unknown[]) => unknown) => resolve(rows),
        where: () => Object.assign(Promise.resolve(rows), { limit: async () => rows }),
      };
    },
  }));
  const service = new ExpenseService({ select } as unknown as Database);
  vi.spyOn(service, 'prices').mockResolvedValue(prices);
  vi.spyOn(service, 'cnyPerUsd').mockResolvedValue(1);
  return await service.summary({ start: '2026-10-01', end: '2026-10-23' }) as {
    total: { costUsd: number; pricedTokens: number; unpricedTokens: number };
    unpricedModels: Array<{ model: string }>;
  };
}

describe('custom model suffix pricing', () => {
  it.each([
    ['custom:team-glm-5.3', 'glm-5.3'],
    ['custom:team-qwen3.8-max', 'qwen3.8-max'],
    ['custom:team-deepseek-v4-pro', 'deepseek-v4-pro'],
    ['custom:team-kimi-k3', 'kimi-k3'],
    [' CUSTOM:团队-team-GLM-5.3 ', 'glm-5.3'],
    ['custom:glm-5.3', 'glm-5.3'],
    ['custom:team/new-model-7', 'new-model-7'],
    ['custom:team-claude-sonnet-4-6', 'claude-4.6-sonnet-google'],
  ])('prices %s using %s', async (model, priceModel) => {
    const summary = await summarize(model, [price(priceModel)]);
    expect(summary.total).toMatchObject({ costUsd: 10, pricedTokens: 4_000_000, unpricedTokens: 0 });
    expect(summary.unpricedModels).toEqual([]);
  });

  it('keeps a configured exact custom price ahead of suffix prices', async () => {
    const model = 'custom:team-glm-5.3';
    const summary = await summarize(model, [price('glm-5.3'), price(model, 7, {
      provider: 'example', canonicalKey: canonicalModelPriceKey('example', model),
    })]);
    expect(summary.total.costUsd).toBe(15);
  });

  it('chooses the longest known suffix even when a shorter suffix is also priced', async () => {
    const summary = await summarize('custom:team-qwen3.8-max', [price('max', 50), price('qwen3.8-max')]);
    expect(summary.total.costUsd).toBe(10);
  });

  it('keeps provider-specific prices ahead of cross-provider suffix matches', async () => {
    const summary = await summarize('custom:team-glm-5.3', [price('glm-5.3', 50), price('glm-5.3', 2, {
      provider: 'zhipu', canonicalKey: canonicalModelPriceKey('zhipu', 'glm-5.3'),
    })]);
    expect(summary.total.costUsd).toBe(10);
  });

  it('keeps conflicting suffix prices unpriced instead of falling back to a shorter model', async () => {
    const summary = await summarize('custom:team-qwen3.8-max', [price('max'), price('qwen3.8-max'), price('qwen3.8-max', 3, {
      provider: 'other', canonicalKey: canonicalModelPriceKey('other', 'qwen3.8-max'),
    })]);
    expect(summary.total).toMatchObject({ costUsd: 0, unpricedTokens: 4_000_000 });
  });

  it.each([
    { effectiveFrom: '2026-10-24' },
    { effectiveTo: '2026-10-22' },
  ])('respects suffix price validity %j without falling back to a shorter model', async (validity) => {
    const summary = await summarize('custom:team-qwen3.8-max', [price('max'), price('qwen3.8-max', 2, validity)]);
    expect(summary.total).toMatchObject({ costUsd: 0, unpricedTokens: 4_000_000 });
  });

  it('uses the latest effective suffix price', async () => {
    const summary = await summarize('custom:team-glm-5.3', [
      price('glm-5.3', 1), price('glm-5.3', 2, { effectiveFrom: '2026-10-01' }),
    ]);
    expect(summary.total.costUsd).toBe(10);
  });

  it.each([
    'custom:TeamPrivateAdapter',
    'custom:TeamPrivateHarness',
    'custom:team-notglm-5.3',
    'custom:team-glm-5.30',
    'custom:team-glm-5.3-preview',
    'team-glm-5.3',
  ])('does not guess a model for %s', async (model) => {
    const summary = await summarize(model, [price('glm-5.3')]);
    expect(summary.total).toMatchObject({ costUsd: 0, unpricedTokens: 4_000_000 });
    expect(summary.unpricedModels).toEqual([expect.objectContaining({ model })]);
  });
});
