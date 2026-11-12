import type { RuntimeUsageInput, TaskUsageInput, IssueUsageInput, UsageSnapshotChunk, UsageSnapshotMetadata, AssembledUsageSnapshot, UsageSnapshotScope } from './types.js';
import { hashCollectorPayload } from '../security/collector-signature.js';

export class ExpenseSnapshotConflictError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ExpenseSnapshotConflictError';
  }
}

export const uploadChunkPrefix = (snapshotId: string, uploadId: string) => `expense_usage_v2_chunk:${snapshotId}:${uploadId}:`;
export const uploadCommitKey = (snapshotId: string) => `expense_usage_v2_commit:${snapshotId}`;
export const uploadCommitPrefix = 'expense_usage_v2_commit:';
export const uploadChunkKey = (snapshotId: string, uploadId: string, index: number) => `${uploadChunkPrefix(snapshotId, uploadId)}${index}`;

function unique<T>(values: T[]) {
  return new Set(values).size === values.length;
}

export function validateUsageChunk(chunk: UsageSnapshotChunk) {
  const scope = chunk.collectionScope;
  const listed = new Set(scope.runtimeIds);
  const succeeded = new Set(scope.successfulRuntimeIds);
  const failed = new Set(scope.failedRuntimeIds);
  if (!unique(scope.runtimeIds) || !unique(scope.successfulRuntimeIds) || !unique(scope.failedRuntimeIds))
    throw new ExpenseSnapshotConflictError('Runtime 范围含重复 ID');
  if (succeeded.size + failed.size !== listed.size || [...succeeded, ...failed].some((id) => !listed.has(id)))
    throw new ExpenseSnapshotConflictError('成功和失败 Runtime 必须恰好划分本次清单');
  if (!scope.runtimeListSucceeded && listed.size > 0)
    throw new ExpenseSnapshotConflictError('Runtime 清单查询失败时不得声明删除范围');
  const registryIds = chunk.runtimes.map((runtime) => runtime.id);
  if (!unique(registryIds) || registryIds.length !== listed.size || registryIds.some((id) => !listed.has(id)))
    throw new ExpenseSnapshotConflictError('Runtime 注册表与查询范围不一致');
  if (chunk.chunk.final !== (chunk.chunk.index === chunk.chunk.total - 1))
    throw new ExpenseSnapshotConflictError('chunk.final 与 index/total 不一致');
  if (!chunk.chunk.final && chunk.failures.length > 0)
    throw new ExpenseSnapshotConflictError('源端失败信息只能放在末块');
  if (chunk.queryWindow.startDate > chunk.queryWindow.endDate)
    throw new ExpenseSnapshotConflictError('Runtime 查询窗口日期倒置');
  for (const row of chunk.runtimeUsage) {
    if (!succeeded.has(row.runtimeId) || row.usageDate < chunk.queryWindow.startDate || row.usageDate > chunk.queryWindow.endDate)
      throw new ExpenseSnapshotConflictError('Runtime 行不在本次成功范围和查询窗口内');
  }
}

function metadata(chunk: UsageSnapshotMetadata): UsageSnapshotMetadata {
  const { schemaVersion, snapshotId, uploadId, collectedAt, queryWindow, collectionScope, expectedRows, runtimes, skippedOffline } = chunk;
  return { schemaVersion, snapshotId, uploadId, collectedAt, queryWindow, collectionScope, expectedRows, runtimes, skippedOffline };
}

export function snapshotIdentityHash(chunk: UsageSnapshotMetadata) {
  const { uploadId, ...identity } = metadata(chunk);
  return hashCollectorPayload(identity);
}

export function assembleUsageChunks(chunks: UsageSnapshotChunk[]): AssembledUsageSnapshot | undefined {
  if (!chunks.length)
    return undefined;
  const first = chunks[0];
  const total = first.chunk.total;
  if (chunks.length !== total)
    return undefined;
  const ordered = [...chunks].sort((left, right) => left.chunk.index - right.chunk.index);
  const metaHash = hashCollectorPayload(metadata(first));
  for (let index = 0; index < total; index += 1) {
    const part = ordered[index];
    if (part.chunk.index !== index || part.chunk.total !== total || hashCollectorPayload(metadata(part)) !== metaHash)
      throw new ExpenseSnapshotConflictError('分块编号或批次元数据不一致');
    validateUsageChunk(part);
  }
  const runtimeUsage = ordered.flatMap((part) => part.runtimeUsage);
  const taskUsage = ordered.flatMap((part) => part.taskUsage);
  const issueUsage = ordered.flatMap((part) => part.issueUsage);
  const expected = first.expectedRows;
  if (runtimeUsage.length !== expected.runtime || taskUsage.length !== expected.task || issueUsage.length !== expected.issue)
    throw new ExpenseSnapshotConflictError('分块到齐但行数与 expectedRows 不一致');
  const keySets: [
    [RuntimeUsageInput[], (row: RuntimeUsageInput) => string],
    [TaskUsageInput[], (row: TaskUsageInput) => string],
    [IssueUsageInput[], (row: IssueUsageInput) => string],
  ] = [
    [runtimeUsage, (row) => `${row.runtimeId}\0${row.usageDate}\0${row.provider}\0${row.model}`],
    [taskUsage, (row) => `${row.taskId}\0${row.provider}\0${row.model}`],
    [issueUsage, (row) => row.issueId],
  ];
  if (keySets.some(([rows, key]) => !unique((rows as unknown[]).map(key as (row: unknown) => string))))
    throw new ExpenseSnapshotConflictError('完整快照含重复用量键');
  return { ...metadata(first), runtimeUsage, taskUsage, issueUsage, failures: ordered.at(-1)!.failures };
}

export function scopesOverlap(left: UsageSnapshotScope, right: UsageSnapshotScope) {
  if (left.queryWindow.endDate < right.queryWindow.startDate || right.queryWindow.endDate < left.queryWindow.startDate)
    return false;
  const ids = new Set(left.collectionScope.successfulRuntimeIds);
  return right.collectionScope.successfulRuntimeIds.some((id) => ids.has(id));
}
