import { sql } from 'drizzle-orm';
import {
  bigint,
  boolean,
  date,
  doublePrecision,
  index,
  jsonb,
  pgTable,
  primaryKey,
  text,
  timestamp,
  uniqueIndex,
} from 'drizzle-orm/pg-core';

export const collectorNonces = pgTable('collector_nonces', {
  nonce: text('nonce').primaryKey(),
  expiresAt: timestamp('expires_at', { withTimezone: true }).notNull(),
  createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
}, (table) => [index('collector_nonces_expires_at_idx').on(table.expiresAt)]);

export const appConfig = pgTable('app_config', {
  key: text('key').primaryKey(),
  value: jsonb('value').notNull(),
  updatedBy: text('updated_by'),
  updatedAt: timestamp('updated_at', { withTimezone: true }).notNull().defaultNow(),
});

export const expenseModelPrices = pgTable('expense_model_prices', {
  id: text('id').primaryKey(),
  provider: text('provider').notNull(),
  model: text('model').notNull(),
  canonicalKey: text('canonical_key').generatedAlwaysAs(sql`(
    regexp_replace(regexp_replace(regexp_replace(lower(translate("provider", '（）', '()')), '\\((thinking|high|low)\\)', '', 'g'), '[^a-z0-9.]+', '', 'g'), '(thinking|high|low)$', '')
    || '::' ||
    regexp_replace(regexp_replace(regexp_replace(lower(translate("model", '（）', '()')), '\\((thinking|high|low)\\)', '', 'g'), '[^a-z0-9.]+', '', 'g'), '(thinking|high|low)$', '')
  )`),
  displayName: text('display_name').notNull(),
  currency: text('currency').notNull().default('USD'),
  usdExchangeRate: doublePrecision('usd_exchange_rate').notNull().default(1),
  inputPerMillion: doublePrecision('input_per_million').notNull(),
  outputPerMillion: doublePrecision('output_per_million').notNull(),
  cacheReadPerMillion: doublePrecision('cache_read_per_million').notNull(),
  cacheWritePerMillion: doublePrecision('cache_write_per_million').notNull(),
  effectiveFrom: date('effective_from').notNull(),
  effectiveTo: date('effective_to'),
  updatedBy: text('updated_by'),
  updatedAt: timestamp('updated_at', { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  uniqueIndex('expense_model_prices_canonical_from_idx').on(table.canonicalKey, table.effectiveFrom),
  index('expense_model_prices_lookup_idx').on(table.provider, table.model, table.effectiveFrom, table.effectiveTo),
]);

export const expenseRuntimeUsage = pgTable('expense_runtime_usage', {
  runtimeId: text('runtime_id').notNull(),
  runtimeName: text('runtime_name').notNull(),
  usageDate: date('usage_date').notNull(),
  provider: text('provider').notNull(),
  model: text('model').notNull(),
  inputTokens: bigint('input_tokens', { mode: 'number' }).notNull().default(0),
  outputTokens: bigint('output_tokens', { mode: 'number' }).notNull().default(0),
  cacheReadTokens: bigint('cache_read_tokens', { mode: 'number' }).notNull().default(0),
  cacheWriteTokens: bigint('cache_write_tokens', { mode: 'number' }).notNull().default(0),
  collectedAt: timestamp('collected_at', { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  primaryKey({ columns: [table.runtimeId, table.usageDate, table.provider, table.model] }),
  index('expense_runtime_usage_date_idx').on(table.usageDate),
]);

export const expenseTaskUsage = pgTable('expense_task_usage', {
  taskId: text('task_id').notNull(),
  usageDate: date('usage_date').notNull(),
  agentId: text('agent_id').notNull(),
  agentName: text('agent_name').notNull(),
  runtimeId: text('runtime_id'),
  runtimeName: text('runtime_name'),
  provider: text('provider').notNull(),
  model: text('model').notNull(),
  issueId: text('issue_id'),
  projectId: text('project_id'),
  projectName: text('project_name'),
  initiator: text('initiator'),
  delegationPath: jsonb('delegation_path').notNull().default(sql`'[]'::jsonb`),
  inputTokens: bigint('input_tokens', { mode: 'number' }).notNull().default(0),
  outputTokens: bigint('output_tokens', { mode: 'number' }).notNull().default(0),
  cacheReadTokens: bigint('cache_read_tokens', { mode: 'number' }).notNull().default(0),
  cacheWriteTokens: bigint('cache_write_tokens', { mode: 'number' }).notNull().default(0),
  collectedAt: timestamp('collected_at', { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  primaryKey({ columns: [table.taskId, table.provider, table.model] }),
  index('expense_task_usage_date_idx').on(table.usageDate),
  index('expense_task_usage_agent_idx').on(table.agentId),
  index('expense_task_usage_project_idx').on(table.projectId),
  index('expense_task_usage_initiator_idx').on(table.initiator),
]);

export const expenseIssueUsage = pgTable('expense_issue_usage', {
  issueId: text('issue_id').primaryKey(),
  identifier: text('identifier').notNull(),
  title: text('title').notNull(),
  projectId: text('project_id'),
  projectName: text('project_name'),
  assigneeAgentId: text('assignee_agent_id'),
  assigneeAgentName: text('assignee_agent_name'),
  agentAttributionSource: text('agent_attribution_source'),
  creatorType: text('creator_type'),
  creatorId: text('creator_id'),
  creatorName: text('creator_name'),
  initiatorId: text('initiator_id'),
  initiatorName: text('initiator_name'),
  initiatorEmail: text('initiator_email'),
  initiatorPrecise: boolean('initiator_precise'),
  initiatorSource: text('initiator_source'),
  inputTokens: bigint('input_tokens', { mode: 'number' }).notNull().default(0),
  outputTokens: bigint('output_tokens', { mode: 'number' }).notNull().default(0),
  cacheReadTokens: bigint('cache_read_tokens', { mode: 'number' }).notNull().default(0),
  cacheWriteTokens: bigint('cache_write_tokens', { mode: 'number' }).notNull().default(0),
  uncostedInputTokens: bigint('uncosted_input_tokens', { mode: 'number' }).notNull().default(0),
  uncostedOutputTokens: bigint('uncosted_output_tokens', { mode: 'number' }).notNull().default(0),
  uncostedCacheReadTokens: bigint('uncosted_cache_read_tokens', { mode: 'number' }).notNull().default(0),
  uncostedCacheWriteTokens: bigint('uncosted_cache_write_tokens', { mode: 'number' }).notNull().default(0),
  costUsdTicks: bigint('cost_usd_ticks', { mode: 'number' }).notNull().default(0),
  modelUsage: jsonb('model_usage').$type<Array<{
    usageDate: string;
    provider: string;
    model: string;
    inputTokens: number;
    outputTokens: number;
    cacheReadTokens: number;
    cacheWriteTokens: number;
  }>>().notNull().default([]),
  lastActivityAt: timestamp('last_activity_at', { withTimezone: true }).notNull(),
  collectedAt: timestamp('collected_at', { withTimezone: true }).notNull().defaultNow(),
}, (table) => [
  index('expense_issue_usage_activity_idx').on(table.lastActivityAt),
  index('expense_issue_usage_agent_idx').on(table.assigneeAgentId),
  index('expense_issue_usage_project_idx').on(table.projectId),
  index('expense_issue_usage_creator_idx').on(table.creatorId),
]);
