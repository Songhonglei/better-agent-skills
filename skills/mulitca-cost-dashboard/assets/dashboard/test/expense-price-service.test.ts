import { describe, expect, it, vi } from 'vitest';

import type { Database } from '../src/db/client.js';
import { canonicalModelPriceKey, expenseCnyPerUsdConfigKey, ExpensePriceConflictError, ExpenseService } from '../src/expenses/service.js';
import type { ExpensePriceInput } from '../src/expenses/types.js';

const price = (model: string): ExpensePriceInput => ({
  provider: 'openai', model, displayName: model, currency: 'USD', usdExchangeRate: 1,
  inputPerMillion: 1, outputPerMillion: 2, cacheReadPerMillion: .1, cacheWritePerMillion: 0,
  effectiveFrom: '2026-09-20',
});

describe('ExpenseService prices', () => {
  it('normalizes provider and model variants into one canonical key', () => {
    expect(canonicalModelPriceKey(' OpenAI ', 'GPT-5 (Thinking)')).toBe('openai::gpt5');
    expect(canonicalModelPriceKey('open-ai', 'gpt_5-high')).toBe('openai::gpt5');
  });

  it('saves a price batch in one transaction', async () => {
    let inserted: Record<string, unknown> = {};
    const tx = {
      select: vi.fn((selection?: unknown) => ({
        from: () => ({ where: () => ({ limit: async () => selection ? [] : [{ ...inserted }] }) }),
      })),
      insert: vi.fn(() => ({
        values: (value: Record<string, unknown>) => {
          inserted = value;
          return { onConflictDoUpdate: async () => undefined };
        },
      })),
    };
    const transaction = vi.fn(async (operation) => operation(tx));
    const service = new ExpenseService({ transaction } as unknown as Database);

    const saved = await service.savePrices([price('gpt-a'), price('gpt-b')], 'admin@example.com');

    expect(transaction).toHaveBeenCalledOnce();
    expect(tx.insert).toHaveBeenCalledTimes(2);
    expect(saved.map((row) => row.model)).toEqual(['gpt-a', 'gpt-b']);
  });

  it('rejects a duplicate provider, model, and effective date before writing', async () => {
    const tx = {
      select: vi.fn(() => ({ from: () => ({ where: () => ({ limit: async () => [{ id: 'existing' }] }) }) })),
      insert: vi.fn(),
    };
    const service = new ExpenseService({ transaction: async (operation: (value: typeof tx) => unknown) => operation(tx) } as unknown as Database);

    await expect(service.savePrices([price('gpt-a')], 'admin@example.com')).rejects.toBeInstanceOf(ExpensePriceConflictError);
    expect(tx.insert).not.toHaveBeenCalled();
  });

  it('persists the global CNY exchange rate', async () => {
    let written: Record<string, unknown> = {};
    const db = {
      insert: vi.fn(() => ({
        values: (value: Record<string, unknown>) => {
          written = value;
          return { onConflictDoUpdate: async () => undefined };
        },
      })),
    } as unknown as Database;
    const service = new ExpenseService(db);

    await expect(service.saveCnyPerUsd(6.8, 'admin@example.com')).resolves.toEqual({ cnyPerUsd: 6.8 });
    expect(written).toMatchObject({
      key: expenseCnyPerUsdConfigKey,
      value: { cnyPerUsd: 6.8 },
      updatedBy: 'admin@example.com',
    });
  });

  it('loads a persisted CNY exchange rate and falls back to 6.8', async () => {
    const configured = new ExpenseService({
      select: () => ({ from: () => ({ where: () => ({ limit: async () => [{ value: { cnyPerUsd: 6.9 } }] }) }) }),
    } as unknown as Database);
    const missing = new ExpenseService({
      select: () => ({ from: () => ({ where: () => ({ limit: async () => [] }) }) }),
    } as unknown as Database);

    await expect(configured.cnyPerUsd()).resolves.toBe(6.9);
    await expect(missing.cnyPerUsd()).resolves.toBe(6.8);
  });
});
