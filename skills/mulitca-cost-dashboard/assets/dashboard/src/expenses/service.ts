import { randomUUID } from 'node:crypto';
import { and, asc, eq, gt, gte, inArray, like, lt, lte, sql } from 'drizzle-orm';

import type { Database } from '../db/client.js';
import { appConfig, expenseIssueUsage, expenseModelPrices, expenseRuntimeUsage, expenseTaskUsage } from '../db/schema.js';
import type { PgTable, PgColumn, PgInsertValue, PgUpdateSetSource } from 'drizzle-orm/pg-core';
import { hashCollectorPayload } from '../security/collector-signature.js';
import { assembleUsageChunks, ExpenseSnapshotConflictError, scopesOverlap, snapshotIdentityHash, uploadChunkKey, uploadChunkPrefix, uploadCommitKey, uploadCommitPrefix, validateUsageChunk } from './usage-v2.js';
import type { UsageSnapshotChunk, UsageSnapshotMetadata, UsageUploadCommit, UsageUploadReceipt } from './types.js';
import type { ExpensePriceInput, RuntimeUsageInput, TaskUsageInput, TokenBreakdown, WorkspaceUsageSnapshot } from './types.js';

export const expenseLastCollectionConfigKey = 'expense_last_collection';
export const expenseCnyPerUsdConfigKey = 'expense_cny_per_usd';
export const defaultCnyPerUsd = 6.8;

export class ExpensePriceConflictError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ExpensePriceConflictError';
  }
}

type PriceRow = typeof expenseModelPrices.$inferSelect;
type RuntimeRow = typeof expenseRuntimeUsage.$inferSelect;
type TaskRow = typeof expenseTaskUsage.$inferSelect;
type IssueRow = typeof expenseIssueUsage.$inferSelect;
type ModelUsageRow = TokenBreakdown & { usageDate: string; provider: string; model: string };
type IssueDetailRow = IssueRow & ModelUsageRow & { modelAvailable: boolean };
type PricedUsage = TokenBreakdown & { costUsd: number; pricedTokens: number; unpricedTokens: number };
type PriceIndex = { byProviderModel: Map<string, PriceRow[]>; byModel: Map<string, PriceRow[]> };
type CostedRow<T> = { row: T; usage: PricedUsage };

const emptyUsage = (): PricedUsage => ({ inputTokens: 0, outputTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0, costUsd: 0, pricedTokens: 0, unpricedTokens: 0 });
const unknownAgent = '未归属智能体';
const unknownProject = '未归属项目';
const unknownInitiator = '未归属发起人';
const globalRouteProviders: Record<string, string> = {
  anthropic: 'anthropic',
  openai: 'openai',
  google: 'google',
  aliyun: 'aliyun',
  deepseek: 'deepseek',
  moonshot: 'moonshot',
  zhipu: 'zhipu',
};

function totalTokens(row: TokenBreakdown): number {
  return row.inputTokens + row.outputTokens + row.cacheReadTokens + row.cacheWriteTokens;
}

function normalized(value: string): string {
  return value.toLowerCase().replaceAll('（', '(').replaceAll('）', ')').replace(/\(thinking\)|\(high\)|\(low\)/g, '').replace(/[^a-z0-9.]+/g, '').replace(/(thinking|high|low)$/, '');
}

function globalRoute(model: string): { alias: string; provider?: string; model: string } | undefined {
  const match = /^global\.([a-z0-9_-]+)\.(.+)$/i.exec(model.trim());
  if (!match) return undefined;
  const providerAlias = match[1].toLowerCase();
  return { alias: `global.${providerAlias}`, provider: globalRouteProviders[providerAlias], model: match[2] };
}

export function canonicalModelPriceKey(provider: string, model: string): string {
  return `${normalized(provider)}::${normalized(model)}`;
}

function pricingProvider(provider: string, model: string): string {
  const route = globalRoute(model);
  if (route?.provider) return route.provider;
  const value = model.toLowerCase();
  if (value.includes('claude')) return 'anthropic';
  if (value.includes('gpt')) return 'openai';
  if (value.includes('gemini')) return 'google';
  if (value.includes('qwen')) return 'aliyun';
  if (value.includes('deepseek')) return 'deepseek';
  if (value.includes('kimi')) return 'moonshot';
  if (value.includes('glm')) return 'zhipu';
  return provider;
}

const modelPriceAliases: Record<string, string> = {
  'claude-sonnet-4-6': 'claude-4.6-sonnet',
};

function pricingModel(model: string): string {
  const route = globalRoute(model);
  let value = (route?.provider ? route.model : model).trim().toLowerCase()
    .replace(/-(google|ms|bytedance)$/, '');
  value = modelPriceAliases[value] ?? value;
  const legacyOpus = /^claude-opus-(\d+)[.-](\d+)$/.exec(value);
  if (legacyOpus) value = `claude-${legacyOpus[1]}.${legacyOpus[2]}-opus`;
  return value;
}

function priceLookupKeys(provider: string, model: string): string[] {
  return [...new Set([
    canonicalModelPriceKey(provider, model),
    canonicalModelPriceKey(pricingProvider(provider, model), pricingModel(model)),
  ])];
}

function indexPrices(prices: PriceRow[]): PriceIndex {
  const index: PriceIndex = { byProviderModel: new Map(), byModel: new Map() };
  for (const price of prices) {
    const key = price.canonicalKey || canonicalModelPriceKey(price.provider, price.model);
    const modelKey = normalized(pricingModel(price.model));
    for (const [lookup, lookupKey] of [[index.byProviderModel, key], [index.byModel, modelKey]] as const) {
      const versions = lookup.get(lookupKey) ?? [];
      versions.push(price);
      lookup.set(lookupKey, versions);
    }
  }
  for (const lookup of [index.byProviderModel, index.byModel]) {
    for (const versions of lookup.values()) versions.sort((left, right) => right.effectiveFrom.localeCompare(left.effectiveFrom));
  }
  return index;
}

function priceFor(prices: PriceIndex, provider: string, model: string, usageDate: string): PriceRow | undefined {
  for (const key of priceLookupKeys(provider, model)) {
    const rate = prices.byProviderModel.get(key)?.find((price) => price.effectiveFrom <= usageDate
      && (!price.effectiveTo || price.effectiveTo >= usageDate));
    if (rate) return rate;
  }
  const modelKey = normalized(pricingModel(model));
  if (!prices.byModel.has(modelKey) && /^custom:/i.test(model.trim())) {
    const customModel = model.trim().slice('custom:'.length);
    // Try complete suffixes longest first; never shorten a known model because
    // its prices conflict or do not cover the usage date.
    const suffixes = [customModel, ...Array.from(customModel.matchAll(/[-:/_\s]+/g), (match) => customModel.slice(match.index! + match[0].length))];
    for (const suffix of suffixes) {
      if (suffix && prices.byModel.has(normalized(pricingModel(suffix)))) {
        return priceFor(prices, provider, suffix, usageDate);
      }
    }
  }
  const candidates = prices.byModel.get(modelKey)?.filter((price) => price.effectiveFrom <= usageDate
    && (!price.effectiveTo || price.effectiveTo >= usageDate)) ?? [];
  const latestByPriceKey = new Map<string, PriceRow>();
  for (const candidate of candidates) {
    const key = candidate.canonicalKey || canonicalModelPriceKey(candidate.provider, candidate.model);
    if (!latestByPriceKey.has(key)) latestByPriceKey.set(key, candidate);
  }
  const rates = [...latestByPriceKey.values()];
  const first = rates[0];
  if (!first) return undefined;
  const samePrice = (price: PriceRow) => price.currency === first.currency
    && price.inputPerMillion === first.inputPerMillion
    && price.outputPerMillion === first.outputPerMillion
    && price.cacheReadPerMillion === first.cacheReadPerMillion
    && price.cacheWritePerMillion === first.cacheWritePerMillion;
  return rates.every(samePrice) ? first : undefined;
}

function pricedTokens(row: TokenBreakdown, provider: string, model: string, usageDate: string, prices: PriceIndex, cnyPerUsd: number): PricedUsage {
  const rate = priceFor(prices, provider, model, usageDate);
  const tokens = totalTokens(row);
  if (!rate) return { ...emptyUsage(), ...row, unpricedTokens: tokens };
  const exchange = rate.currency === 'USD' ? 1 : 1 / cnyPerUsd;
  return {
    inputTokens: row.inputTokens,
    outputTokens: row.outputTokens,
    cacheReadTokens: row.cacheReadTokens,
    cacheWriteTokens: row.cacheWriteTokens,
    costUsd: exchange * (
      row.inputTokens * rate.inputPerMillion
      + row.outputTokens * rate.outputPerMillion
      + row.cacheReadTokens * rate.cacheReadPerMillion
      + row.cacheWriteTokens * rate.cacheWritePerMillion
    ) / 1_000_000,
    pricedTokens: tokens,
    unpricedTokens: 0,
  };
}

function priced(row: ModelUsageRow, prices: PriceIndex, cnyPerUsd: number): PricedUsage {
  return pricedTokens(row, row.provider, row.model, row.usageDate, prices, cnyPerUsd);
}

function add(target: PricedUsage, value: PricedUsage): PricedUsage {
  target.inputTokens += value.inputTokens;
  target.outputTokens += value.outputTokens;
  target.cacheReadTokens += value.cacheReadTokens;
  target.cacheWriteTokens += value.cacheWriteTokens;
  target.costUsd += value.costUsd;
  target.pricedTokens += value.pricedTokens;
  target.unpricedTokens += value.unpricedTokens;
  return target;
}

function periodKey(dateValue: string, granularity: 'day' | 'week' | 'month'): string {
  if (granularity === 'day') return dateValue;
  if (granularity === 'month') return dateValue.slice(0, 7);
  const date = new Date(`${dateValue}T00:00:00Z`);
  const day = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() - day + 1);
  return date.toISOString().slice(0, 10);
}

function costRows<T extends ModelUsageRow>(rows: T[], prices: PriceIndex, cnyPerUsd: number): Array<CostedRow<T>> {
  return rows.map((row) => ({ row, usage: priced(row, prices, cnyPerUsd) }));
}

function aggregateRows<T>(rows: Array<CostedRow<T>>, key: (row: T) => string): Array<PricedUsage & { key: string }> {
  const groups = new Map<string, PricedUsage>();
  for (const { row, usage } of rows) add(groups.get(key(row)) ?? (() => { const value = emptyUsage(); groups.set(key(row), value); return value; })(), usage);
  return [...groups].map(([groupKey, usage]) => ({ key: groupKey, ...usage })).sort((left, right) => right.costUsd - left.costUsd);
}

function mergeAggregates(...groups: Array<Array<PricedUsage & { key: string }>>): Array<PricedUsage & { key: string }> {
  const merged = new Map<string, PricedUsage>();
  for (const rows of groups) {
    for (const row of rows) add(merged.get(row.key) ?? (() => { const value = emptyUsage(); merged.set(row.key, value); return value; })(), row);
  }
  return [...merged].map(([key, usage]) => ({ key, ...usage })).sort((left, right) => right.costUsd - left.costUsd || right.pricedTokens + right.unpricedTokens - left.pricedTokens - left.unpricedTokens);
}

function issueUsageRows(rows: IssueRow[], start: string, end: string): IssueDetailRow[] {
  const result: IssueDetailRow[] = [];
  for (const row of rows) {
    if (row.modelUsage.length) {
      for (const usage of row.modelUsage) {
        if (usage.usageDate >= start && usage.usageDate <= end) result.push({ ...row, ...usage, modelAvailable: true });
      }
      continue;
    }
    const usageDate = row.lastActivityAt.toISOString().slice(0, 10);
    if (usageDate >= start && usageDate <= end) result.push({ ...row, usageDate, provider: '', model: '', modelAvailable: false });
  }
  return result;
}

function costIssueRows(rows: IssueDetailRow[], prices: PriceIndex, cnyPerUsd: number): Array<CostedRow<IssueDetailRow>> {
  return rows.map((row) => {
    if (row.modelAvailable) return { row, usage: pricedTokens(row, row.provider, row.model, row.usageDate, prices, cnyPerUsd) };
    return { row, usage: {
      inputTokens: row.inputTokens,
      outputTokens: row.outputTokens,
      cacheReadTokens: row.cacheReadTokens,
      cacheWriteTokens: row.cacheWriteTokens,
      costUsd: 0,
      pricedTokens: 0,
      unpricedTokens: totalTokens(row),
    } };
  });
}

function issueInitiator(row: IssueRow): string {
  if (row.initiatorName) return row.initiatorName;
  if (row.initiatorEmail) return row.initiatorEmail;
  if (row.initiatorId) return row.initiatorId;
  if (row.creatorType && row.creatorType.toLowerCase() !== 'agent') return row.creatorName || row.creatorId || unknownInitiator;
  return unknownInitiator;
}

function initiatorAccount(value?: string | null): string | undefined {
  const trimmed = value?.trim().toLowerCase();
  if (!trimmed) return undefined;
  const account = trimmed.includes('@') ? trimmed.slice(0, trimmed.indexOf('@')) : trimmed;
  return /^[a-z0-9][a-z0-9._-]*$/.test(account) ? account : undefined;
}

function initiatorDirectory(rows: IssueRow[]): Map<string, string> {
  const directory = new Map<string, string>();
  for (const row of rows) {
    const initiatorName = row.initiatorName?.trim();
    if (initiatorName && !initiatorAccount(initiatorName)) {
      for (const alias of [row.initiatorEmail, row.initiatorId]) {
        const account = initiatorAccount(alias);
        if (account) directory.set(account, initiatorName);
      }
    }
    const creatorName = row.creatorType?.toLowerCase() === 'agent' ? undefined : row.creatorName?.trim();
    if (creatorName && !initiatorAccount(creatorName)) {
      const account = initiatorAccount(row.creatorId);
      if (account) directory.set(account, creatorName);
    }
  }
  return directory;
}

function presentedInitiator(value: string, directory: Map<string, string>, accounts: Map<string, string>): string {
  const account = initiatorAccount(value);
  const name = account ? directory.get(account) : undefined;
  if (!account || !name || name === value) return value;
  accounts.set(name, account);
  return name;
}

function allocationPart(total: PricedUsage, ratio: number): PricedUsage {
  return {
    inputTokens: Math.round(total.inputTokens * ratio),
    outputTokens: Math.round(total.outputTokens * ratio),
    cacheReadTokens: Math.round(total.cacheReadTokens * ratio),
    cacheWriteTokens: Math.round(total.cacheWriteTokens * ratio),
    costUsd: total.costUsd * ratio,
    pricedTokens: Math.round(total.pricedTokens * ratio),
    unpricedTokens: Math.round(total.unpricedTokens * ratio),
  };
}

function subtract(target: PricedUsage, value: PricedUsage): PricedUsage {
  target.inputTokens -= value.inputTokens;
  target.outputTokens -= value.outputTokens;
  target.cacheReadTokens -= value.cacheReadTokens;
  target.cacheWriteTokens -= value.cacheWriteTokens;
  target.costUsd -= value.costUsd;
  target.pricedTokens -= value.pricedTokens;
  target.unpricedTokens -= value.unpricedTokens;
  return target;
}

function agentAggregates(
  issueCosts: Array<CostedRow<IssueDetailRow>>,
  issueRows: IssueRow[],
  taskCosts: Array<CostedRow<TaskRow>>,
  uncoveredTaskCosts: Array<CostedRow<TaskRow>>,
): Array<PricedUsage & { key: string }> {
  const byAgent = new Map<string, PricedUsage>();
  const issueTotals = aggregateRows(issueCosts, (row) => row.issueId);
  const issueRegistry = new Map(issueRows.map((row) => [row.issueId, row]));
  const taskWeights = new Map<string, Map<string, number>>();
  for (const { row, usage } of taskCosts) {
    if (!row.issueId || !issueRegistry.has(row.issueId)) continue;
    const weights = taskWeights.get(row.issueId) ?? new Map<string, number>();
    const agent = row.agentName || row.agentId || unknownAgent;
    weights.set(agent, (weights.get(agent) ?? 0) + totalTokens(usage));
    taskWeights.set(row.issueId, weights);
  }
  const addAgent = (key: string, usage: PricedUsage) => {
    const current = byAgent.get(key) ?? emptyUsage();
    add(current, usage);
    byAgent.set(key, current);
  };
  for (const issueTotal of issueTotals) {
    const issue = issueRegistry.get(issueTotal.key);
    if (!issue) continue;
    const weights = [...(taskWeights.get(issue.issueId) ?? new Map<string, number>())];
    const weightTotal = weights.reduce((sum, [, value]) => sum + value, 0);
    if (!weightTotal) {
      addAgent(issue.assigneeAgentName || issue.assigneeAgentId || unknownAgent, issueTotal);
      continue;
    }
    const remaining = { ...issueTotal };
    weights.forEach(([agent, weight], index) => {
      const portion = index === weights.length - 1 ? remaining : allocationPart(issueTotal, weight / weightTotal);
      addAgent(agent, portion);
      if (index !== weights.length - 1) subtract(remaining, portion);
    });
  }
  for (const { row, usage } of uncoveredTaskCosts) addAgent(row.agentName || row.agentId || unknownAgent, usage);
  return [...byAgent].map(([key, usage]) => ({ key, ...usage }))
    .sort((left, right) => right.costUsd - left.costUsd || totalTokens(right) - totalTokens(left));
}

function runtimeRegistry(value: unknown): Map<string, string> {
  if (value === null || typeof value !== 'object' || !('runtimes' in value) || !Array.isArray(value.runtimes)) return new Map();
  return new Map(value.runtimes.flatMap((entry) => {
    if (entry === null || typeof entry !== 'object' || !('id' in entry) || !('name' in entry)
      || typeof entry.id !== 'string' || typeof entry.name !== 'string') return [];
    return [[entry.id, entry.name] as const];
  }));
}

function collectionRecord(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;
}

function unavailableRuntimeIds(value: unknown): Set<string> {
  const collection = collectionRecord(value);
  if (!collection) return new Set();
  const ids = new Set<string>();
  if (Array.isArray(collection.runtimes)) {
    for (const entry of collection.runtimes) {
      const runtime = collectionRecord(entry);
      if (typeof runtime?.id === 'string' && typeof runtime.status === 'string' && runtime.status.toLowerCase() === 'offline') {
        ids.add(runtime.id);
      }
    }
  }
  if (Array.isArray(collection.failures)) {
    for (const entry of collection.failures) {
      const failure = collectionRecord(entry);
      if (failure?.stage === 'runtime-usage' && typeof failure.entityId === 'string') ids.add(failure.entityId);
    }
  }
  return ids;
}

function collectUnpricedModels(rows: Array<CostedRow<ModelUsageRow>>) {
  const models = new Map<string, { provider: string; model: string; unpricedTokens: number }>();
  for (const { row, usage } of rows) {
    if (!usage.unpricedTokens || !row.provider || !row.model) continue;
    const key = `${row.provider}\u0000${row.model}`;
    const current = models.get(key) ?? { provider: row.provider, model: row.model, unpricedTokens: 0 };
    current.unpricedTokens += usage.unpricedTokens;
    models.set(key, current);
  }
  return [...models.values()].sort((left, right) => right.unpricedTokens - left.unpricedTokens);
}

function collectUnrecognizedModelAliases(rows: Array<CostedRow<ModelUsageRow>>) {
  const aliases = new Map<string, { provider: string; model: string; alias: string; unpricedTokens: number }>();
  for (const { row, usage } of rows) {
    if (!usage.unpricedTokens) continue;
    const route = globalRoute(row.model);
    const alias = route && !route.provider ? route.alias : undefined;
    if (!alias) continue;
    const key = `${row.provider}\u0000${row.model}\u0000${alias}`;
    const current = aliases.get(key) ?? { provider: row.provider, model: row.model, alias, unpricedTokens: 0 };
    current.unpricedTokens += usage.unpricedTokens;
    aliases.set(key, current);
  }
  return [...aliases.values()].sort((left, right) => right.unpricedTokens - left.unpricedTokens);
}

function dateOnly(value: string, fallback: string): string {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : fallback;
}

const v2UploadLock = sql`select pg_advisory_xact_lock(193838, 4221)`;
const chunkTtlMs = 48 * 60 * 60 * 1000;
const upsertBatchSize = 250;
type ExpenseTransaction = Parameters<Parameters<Database['transaction']>[0]>[0];
async function insertBatches<T extends PgTable>(tx: ExpenseTransaction, table: T, rows: PgInsertValue<T>[], target: PgColumn | PgColumn[]) {
  // Preserve v1's per-row optional-field semantics while still batching inserts.
  const groups = new Map<string, PgInsertValue<T>[]>();
  for (const row of rows) {
    const shape = Object.keys(row).sort().join('\0');
    const group = groups.get(shape) ?? [];
    group.push(row);
    groups.set(shape, group);
  }
  for (const group of groups.values()) {
    for (let start = 0; start < group.length; start += upsertBatchSize) {
      const batch = group.slice(start, start + upsertBatchSize);
      const excluded = Object.fromEntries(Object.keys(batch[0]).map((field) => {
        const name = (table as unknown as Record<string, PgColumn>)[field].name;
        return [field, sql.raw(`excluded."${name.replaceAll('"', '""')}"`)];
      }));
      await tx.insert(table).values(batch).onConflictDoUpdate({ target, set: excluded as PgUpdateSetSource<T> });
    }
  }
}
function v2Receipt(snapshot: UsageSnapshotMetadata & { failures: unknown[] }, receivedChunks: number, committed: boolean, failureCount = snapshot.failures.length): UsageUploadReceipt {
  return {
    snapshotId: snapshot.snapshotId,
    uploadId: snapshot.uploadId,
    receivedChunks,
    committed,
    ...(committed ? {
      runtimeRows: snapshot.expectedRows.runtime,
      taskRows: snapshot.expectedRows.task,
      issueRows: snapshot.expectedRows.issue,
      failureCount,
      collectedAt: snapshot.collectedAt,
    } : {}),
  };
}
export class ExpenseService {
  private readonly summaryCache = new Map<string, { expiresAt: number; value: unknown }>();

  constructor(private readonly db: Database) {}

  private clearSummaryCache(): void {
    this.summaryCache.clear();
  }

  async prices(): Promise<PriceRow[]> {
    return this.db.select().from(expenseModelPrices).orderBy(asc(expenseModelPrices.provider), asc(expenseModelPrices.model), asc(expenseModelPrices.effectiveFrom));
  }

  async cnyPerUsd(): Promise<number> {
    const [row] = await this.db.select({ value: appConfig.value }).from(appConfig)
      .where(eq(appConfig.key, expenseCnyPerUsdConfigKey)).limit(1);
    const value = typeof row?.value === 'number'
      ? row.value
      : typeof row?.value === 'object' && row.value !== null && 'cnyPerUsd' in row.value
        ? Number(row.value.cnyPerUsd)
        : Number.NaN;
    return Number.isFinite(value) && value > 0 ? value : defaultCnyPerUsd;
  }

  async saveCnyPerUsd(cnyPerUsd: number, updatedBy: string): Promise<{ cnyPerUsd: number }> {
    await this.db.insert(appConfig).values({
      key: expenseCnyPerUsdConfigKey,
      value: { cnyPerUsd },
      updatedBy,
      updatedAt: new Date(),
    }).onConflictDoUpdate({
      target: appConfig.key,
      set: { value: { cnyPerUsd }, updatedBy, updatedAt: new Date() },
    });
    this.clearSummaryCache();
    return { cnyPerUsd };
  }

  async savePrice(input: ExpensePriceInput, updatedBy: string): Promise<PriceRow> {
    return (await this.savePrices([input], updatedBy))[0];
  }

  async savePrices(inputs: ExpensePriceInput[], updatedBy: string): Promise<PriceRow[]> {
    try {
      const result = await this.db.transaction(async (tx) => {
        const saved: PriceRow[] = [];
        for (const input of inputs) {
          const [duplicate] = await tx.select({ id: expenseModelPrices.id }).from(expenseModelPrices).where(and(
            eq(expenseModelPrices.canonicalKey, canonicalModelPriceKey(input.provider, input.model)),
            eq(expenseModelPrices.effectiveFrom, input.effectiveFrom),
          )).limit(1);
          if (duplicate && duplicate.id !== input.id) {
            throw new ExpensePriceConflictError(`${input.provider} / ${input.model} 在 ${input.effectiveFrom} 已有价格版本，请直接编辑原版本`);
          }
          const id = input.id ?? randomUUID();
          const values = { ...input, id, effectiveTo: input.effectiveTo ?? null, updatedBy, updatedAt: new Date() };
          await tx.insert(expenseModelPrices).values(values).onConflictDoUpdate({
            target: expenseModelPrices.id,
            set: values,
          });
          const [row] = await tx.select().from(expenseModelPrices).where(eq(expenseModelPrices.id, id)).limit(1);
          saved.push(row);
        }
        return saved;
      });
      this.clearSummaryCache();
      return result;
    } catch (error) {
      if (error instanceof ExpensePriceConflictError) throw error;
      if (typeof error === 'object' && error !== null && 'code' in error && error.code === '23505') {
        throw new ExpensePriceConflictError('价格版本已存在，请刷新后编辑原版本');
      }
      throw error;
    }
  }

  async ingest(snapshot: WorkspaceUsageSnapshot): Promise<{ runtimeRows: number; taskRows: number; issueRows: number; skippedOffline: number; failureCount: number; collectedAt: string }> {
    const collectedAt = new Date(snapshot.collectedAt);
    await this.db.transaction(async (tx) => {
      await tx.execute(v2UploadLock);
      for (const row of snapshot.runtimeUsage) {
        await tx.insert(expenseRuntimeUsage).values({ ...row, collectedAt }).onConflictDoUpdate({
          target: [expenseRuntimeUsage.runtimeId, expenseRuntimeUsage.usageDate, expenseRuntimeUsage.provider, expenseRuntimeUsage.model],
          set: { ...row, collectedAt },
        });
      }
      for (const row of snapshot.taskUsage) {
        await tx.insert(expenseTaskUsage).values({ ...row, delegationPath: row.delegationPath ?? [], collectedAt }).onConflictDoUpdate({
          target: [expenseTaskUsage.taskId, expenseTaskUsage.provider, expenseTaskUsage.model],
          set: { ...row, delegationPath: row.delegationPath ?? [], collectedAt },
        });
      }
      for (const row of snapshot.issueUsage ?? []) {
        const values = { ...row, lastActivityAt: new Date(row.lastActivityAt), collectedAt };
        await tx.insert(expenseIssueUsage).values(values).onConflictDoUpdate({
          target: expenseIssueUsage.issueId,
          set: values,
        });
      }
      const collection = {
        collectedAt: snapshot.collectedAt,
        runtimeRows: snapshot.runtimeUsage.length,
        taskRows: snapshot.taskUsage.length,
        issueRows: snapshot.issueUsage?.length ?? 0,
        skippedOffline: snapshot.skippedOffline ?? 0,
        runtimes: snapshot.runtimes ?? [],
        failureCount: snapshot.failures?.length ?? 0,
        failures: snapshot.failures ?? [],
      };
      await tx.insert(appConfig).values({
        key: expenseLastCollectionConfigKey,
        value: collection,
        updatedBy: 'usage-collector',
        updatedAt: collectedAt,
      }).onConflictDoUpdate({
        target: appConfig.key,
        set: { value: collection, updatedBy: 'usage-collector', updatedAt: collectedAt },
      });
    });
    this.clearSummaryCache();
    return {
      runtimeRows: snapshot.runtimeUsage.length,
      taskRows: snapshot.taskUsage.length,
      issueRows: snapshot.issueUsage?.length ?? 0,
      skippedOffline: snapshot.skippedOffline ?? 0,
      failureCount: snapshot.failures?.length ?? 0,
      collectedAt: snapshot.collectedAt,
    };
  }

  async ingestV2(part: UsageSnapshotChunk): Promise<UsageUploadReceipt> {
    validateUsageChunk(part);
    const now = new Date();
    const result = await this.db.transaction(async (tx) => {
      // One database lock serializes final commits and v1 writes across app workers.
      await tx.execute(v2UploadLock);
      const commitKey = uploadCommitKey(part.snapshotId);
      const [alreadyCommitted] = await tx.select({ value: appConfig.value }).from(appConfig).where(eq(appConfig.key, commitKey)).limit(1);
      if (alreadyCommitted) {
        const prior = alreadyCommitted.value as UsageUploadCommit;
        if (prior.identityHash !== snapshotIdentityHash(part))
          throw new ExpenseSnapshotConflictError('snapshotId 已被不同快照提交');
        return v2Receipt({ ...part, uploadId: prior.uploadId }, prior.receivedChunks, true, prior.failureCount);
      }
      await tx.delete(appConfig).where(and(like(appConfig.key, 'expense_usage_v2_chunk:%'), lt(appConfig.updatedAt, new Date(now.getTime() - chunkTtlMs))));
      const key = uploadChunkKey(part.snapshotId, part.uploadId, part.chunk.index);
      const digest = hashCollectorPayload(part);
      const [existing] = await tx.select({ value: appConfig.value }).from(appConfig).where(eq(appConfig.key, key)).limit(1);
      if (existing && (existing.value as { digest: string }).digest !== digest)
        throw new ExpenseSnapshotConflictError('相同分块编号的内容已改变');
      if (!existing)
        await tx.insert(appConfig).values({ key, value: { digest, body: part }, updatedBy: 'usage-collector-v2', updatedAt: now });
      const staged = await tx.select({ value: appConfig.value }).from(appConfig).where(like(appConfig.key, `${uploadChunkPrefix(part.snapshotId, part.uploadId)}%`));
      const chunks = staged.map((row) => (row.value as { body: UsageSnapshotChunk }).body);
      const snapshot = assembleUsageChunks(chunks);
      if (!snapshot)
        return v2Receipt(part, chunks.length, false);
      const collectedAt = new Date(snapshot.collectedAt);
      const [latestCollection] = await tx.select({ value: appConfig.value }).from(appConfig).where(eq(appConfig.key, expenseLastCollectionConfigKey)).limit(1);
      if ((latestCollection?.value as { collectedAt?: string } | undefined)?.collectedAt && new Date((latestCollection.value as { collectedAt: string }).collectedAt) > collectedAt)
        throw new ExpenseSnapshotConflictError('已有更新的费用采集批次，拒绝旧快照覆盖');
      const scope = snapshot.collectionScope.successfulRuntimeIds;
      if (scope.length > 0) {
        const affected = and(gte(expenseRuntimeUsage.usageDate, snapshot.queryWindow.startDate), lte(expenseRuntimeUsage.usageDate, snapshot.queryWindow.endDate), inArray(expenseRuntimeUsage.runtimeId, scope));
        const [newerRow] = await tx.select({ runtimeId: expenseRuntimeUsage.runtimeId }).from(expenseRuntimeUsage).where(and(affected, gt(expenseRuntimeUsage.collectedAt, collectedAt))).limit(1);
        if (newerRow)
          throw new ExpenseSnapshotConflictError('已有更新的 Runtime 采集行，拒绝旧快照覆盖');
        const commits = await tx.select({ value: appConfig.value }).from(appConfig).where(like(appConfig.key, `${uploadCommitPrefix}%`));
        if (commits.some(({ value }) => new Date((value as UsageUploadCommit).collectedAt) > collectedAt && scopesOverlap(value as UsageUploadCommit, snapshot)))
          throw new ExpenseSnapshotConflictError('已有更新的零用量窗口提交，拒绝旧快照覆盖');
        await tx.delete(expenseRuntimeUsage).where(affected);
      }
      await insertBatches(tx, expenseRuntimeUsage,
        snapshot.runtimeUsage.map((row) => ({ ...row, collectedAt })),
        [expenseRuntimeUsage.runtimeId, expenseRuntimeUsage.usageDate, expenseRuntimeUsage.provider, expenseRuntimeUsage.model]);
      await insertBatches(tx, expenseTaskUsage,
        snapshot.taskUsage.map((row) => ({ ...row, delegationPath: row.delegationPath ?? [], collectedAt })),
        [expenseTaskUsage.taskId, expenseTaskUsage.provider, expenseTaskUsage.model]);
      await insertBatches(tx, expenseIssueUsage,
        snapshot.issueUsage.map((row) => ({ ...row, modelUsage: row.modelUsage ?? [], lastActivityAt: new Date(row.lastActivityAt), collectedAt })),
        expenseIssueUsage.issueId);
      const collection = {
        schemaVersion: 2,
        snapshotId: snapshot.snapshotId,
        collectedAt: snapshot.collectedAt,
        queryWindow: snapshot.queryWindow,
        runtimeRows: snapshot.expectedRows.runtime,
        taskRows: snapshot.expectedRows.task,
        issueRows: snapshot.expectedRows.issue,
        skippedOffline: snapshot.skippedOffline,
        runtimes: snapshot.runtimes,
        failureCount: snapshot.failures.length,
        failures: snapshot.failures,
      };
      await tx.insert(appConfig).values({ key: expenseLastCollectionConfigKey, value: collection, updatedBy: 'usage-collector-v2', updatedAt: collectedAt }).onConflictDoUpdate({
        target: appConfig.key,
        set: { value: collection, updatedBy: 'usage-collector-v2', updatedAt: collectedAt },
      });
      await tx.insert(appConfig).values({
        key: commitKey,
        value: {
          snapshotId: snapshot.snapshotId, uploadId: snapshot.uploadId,
          collectedAt: snapshot.collectedAt, queryWindow: snapshot.queryWindow,
          collectionScope: snapshot.collectionScope, expectedRows: snapshot.expectedRows,
          identityHash: snapshotIdentityHash(snapshot),
          receivedChunks: chunks.length,
          failureCount: snapshot.failures.length,
        },
        updatedBy: 'usage-collector-v2', updatedAt: now,
      });
      await tx.delete(appConfig).where(like(appConfig.key, `${uploadChunkPrefix(part.snapshotId, part.uploadId)}%`));
      return v2Receipt(snapshot, chunks.length, true);
    });
    if (result.committed)
      this.clearSummaryCache();
    return result;
  }

  async summary(input: { start?: string; end?: string; granularity?: string }): Promise<unknown> {
    const today = new Date().toISOString().slice(0, 10);
    const startDefault = new Date(Date.now() - 29 * 86_400_000).toISOString().slice(0, 10);
    const start = dateOnly(input.start ?? '', startDefault);
    const end = dateOnly(input.end ?? '', today);
    const granularity = input.granularity === 'week' || input.granularity === 'month' ? input.granularity : 'day';
    const cacheKey = `${start}:${end}:${granularity}`;
    const cached = this.summaryCache.get(cacheKey);
    if (cached && cached.expiresAt > Date.now()) return cached.value;
    if (cached) this.summaryCache.delete(cacheKey);
    const [prices, cnyPerUsd, runtimeRows, taskRows, issueRows, collectionRows] = await Promise.all([
      this.prices(),
      this.cnyPerUsd(),
      this.db.select().from(expenseRuntimeUsage).where(and(gte(expenseRuntimeUsage.usageDate, start), lte(expenseRuntimeUsage.usageDate, end))),
      this.db.select().from(expenseTaskUsage).where(and(gte(expenseTaskUsage.usageDate, start), lte(expenseTaskUsage.usageDate, end))),
      this.db.select().from(expenseIssueUsage),
      this.db.select({ value: appConfig.value }).from(appConfig).where(eq(appConfig.key, expenseLastCollectionConfigKey)).limit(1),
    ]);
    const priceIndex = indexPrices(prices);
    const runtimeCosts = costRows(runtimeRows, priceIndex, cnyPerUsd);
    const taskCosts = costRows(taskRows, priceIndex, cnyPerUsd);
    const issueCosts = costIssueRows(issueUsageRows(issueRows, start, end), priceIndex, cnyPerUsd);
    const coveredIssueIds = new Set(issueRows.map((row) => row.issueId));
    const uncoveredTaskCosts = taskCosts.filter(({ row }) => !row.issueId || !coveredIssueIds.has(row.issueId));
    const canonicalCosts: Array<CostedRow<ModelUsageRow>> = [...issueCosts, ...uncoveredTaskCosts];
    const collection = collectionRows[0]?.value;
    const runtimeNames = runtimeRegistry(collection);
    const unavailableRuntimes = unavailableRuntimeIds(collection);
    const unlinkedRuntimeUsage = taskCosts
      .filter(({ row }) => !row.runtimeId
        || unavailableRuntimes.has(row.runtimeId)
        || (runtimeNames.size > 0 && !runtimeNames.has(row.runtimeId)))
      .reduce((sum, { usage }) => add(sum, usage), emptyUsage());
    const collectionSummary = collectionRecord(collection);
    const collectionWithTotals = collectionSummary ? {
      ...collectionSummary,
      unlinkedRuntime: {
        tokenTotal: totalTokens(unlinkedRuntimeUsage),
        costUsd: unlinkedRuntimeUsage.costUsd,
      },
    } : collection;
    const trend = aggregateRows(canonicalCosts, (row) => periodKey(row.usageDate, granularity)).sort((left, right) => left.key.localeCompare(right.key));
    const total = trend.reduce((sum, row) => add(sum, row), emptyUsage());
    const agent = agentAggregates(issueCosts, issueRows, taskCosts, uncoveredTaskCosts);
    const project = mergeAggregates(
      aggregateRows(issueCosts, (row) => row.projectName || row.projectId || unknownProject),
      aggregateRows(uncoveredTaskCosts, (row) => row.projectName || row.projectId || unknownProject),
    );
    const initiatorNames = initiatorDirectory(issueRows);
    const initiatorAccounts = new Map<string, string>();
    const initiator = mergeAggregates(
      aggregateRows(issueCosts, (row) => presentedInitiator(issueInitiator(row), initiatorNames, initiatorAccounts)),
      aggregateRows(uncoveredTaskCosts, (row) => presentedInitiator(row.initiator || unknownInitiator, initiatorNames, initiatorAccounts)),
    );
    const tokenTotal = totalTokens(total);
    const coverage = (rows: Array<PricedUsage & { key: string }>, unknown: string) => tokenTotal === 0
      ? 0
      : Math.min(1, rows.filter((row) => row.key !== unknown).reduce((sum, row) => sum + totalTokens(row), 0) / tokenTotal);
    const runtimeTotal = runtimeCosts.reduce((sum, { usage }) => add(sum, usage), emptyUsage());
    const result = {
      range: { start, end, granularity },
      accountingBasis: 'issue-task-lifecycle',
      collectedAt: [...runtimeRows, ...taskRows, ...issueRows].map((row) => row.collectedAt.toISOString()).sort().at(-1),
      collection: collectionWithTotals,
      total,
      attributionCoverage: coverage(initiator, unknownInitiator),
      attributionCoverageByDimension: {
        agent: coverage(agent, unknownAgent),
        project: coverage(project, unknownProject),
        initiator: coverage(initiator, unknownInitiator),
      },
      runtimeCoverage: tokenTotal === 0 ? 0 : totalTokens(runtimeTotal) / tokenTotal,
      runtimeTokens: totalTokens(runtimeTotal),
      initiatorAccounts: Object.fromEntries(initiatorAccounts),
      unpricedModels: collectUnpricedModels(canonicalCosts),
      unrecognizedModelAliases: collectUnrecognizedModelAliases(canonicalCosts),
      trend,
      breakdowns: {
        runtime: aggregateRows(runtimeCosts, (row) => runtimeNames.get(row.runtimeId) ?? row.runtimeName ?? row.runtimeId),
        model: aggregateRows(canonicalCosts, (row) => row.provider && row.model ? `${row.provider} / ${row.model}` : '模型信息缺失'),
        agent,
        project,
        initiator,
      },
    };
    if (this.summaryCache.size >= 100) this.summaryCache.delete(this.summaryCache.keys().next().value as string);
    this.summaryCache.set(cacheKey, { expiresAt: Date.now() + 60_000, value: result });
    return result;
  }
}
