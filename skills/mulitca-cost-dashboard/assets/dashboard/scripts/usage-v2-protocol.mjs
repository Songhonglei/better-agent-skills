import { randomUUID } from 'node:crypto';

function shanghaiDate(instant) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(instant).map((part) => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function addDays(date, offset) {
  const value = new Date(`${date}T00:00:00.000Z`);
  value.setUTCDate(value.getUTCDate() + offset);
  return value.toISOString().slice(0, 10);
}

export function usageQueryWindow(days, instant = new Date()) {
  if (!Number.isInteger(days) || days < 1 || days > 365)
    throw new Error('--days 必须是 1 到 365 的整数');
  const utcEnd = instant.toISOString().slice(0, 10);
  const shanghaiEnd = shanghaiDate(instant);
  // Multica --days=N includes N preceding dates plus "today". Its server-side
  // timezone is undocumented; claim only dates covered in both UTC and CST.
  return {
    startDate: [addDays(utcEnd, -days), addDays(shanghaiEnd, -days)].sort().at(-1),
    endDate: [utcEnd, shanghaiEnd].sort()[0],
  };
}

export const expectedRows = (snapshot) => ({
  runtime: snapshot.runtimeUsage.length,
  task: snapshot.taskUsage.length,
  issue: snapshot.issueUsage.length,
});

export function makeChunk(snapshot, uploadId, index, total, rows) {
  return {
    schemaVersion: 2,
    snapshotId: snapshot.snapshotId,
    uploadId,
    collectedAt: snapshot.collectedAt,
    queryWindow: snapshot.queryWindow,
    collectionScope: snapshot.collectionScope,
    expectedRows: snapshot.expectedRows,
    chunk: { index, total, final: index === total - 1 },
    runtimeUsage: rows.runtimeUsage,
    taskUsage: rows.taskUsage,
    issueUsage: rows.issueUsage,
    runtimes: snapshot.runtimes,
    skippedOffline: snapshot.skippedOffline,
    failures: index === total - 1 ? snapshot.failures : [],
  };
}

const emptyRows = () => ({ runtimeUsage: [], taskUsage: [], issueUsage: [] });
const byteLength = (value) => Buffer.byteLength(JSON.stringify(value), 'utf8');

export function splitSnapshot(snapshot, budget) {
  if (snapshot.schemaVersion !== 2 || !snapshot.snapshotId || !snapshot.queryWindow || !snapshot.collectionScope)
    throw new Error('仅支持重传含完整 V2 范围元数据的快照');
  if (!['runtimeUsage', 'taskUsage', 'issueUsage', 'runtimes', 'failures'].every((key) => Array.isArray(snapshot[key])))
    throw new Error('V2 快照缺少必需的行数组、Runtime 清单或失败列表');
  const counts = expectedRows(snapshot);
  if (Object.keys(counts).some((kind) => counts[kind] !== snapshot.expectedRows?.[kind]))
    throw new Error('快照 expectedRows 与实际行数不一致');
  assertUniqueKeys(snapshot);
  if (!Number.isSafeInteger(budget) || budget < 1024 * 1024)
    throw new Error('分块预算不能小于 1 MiB');
  const placeholder = randomUUID();
  // Reserve final-chunk failures and generous index/JSON overhead in every chunk.
  const envelopeBytes = byteLength(makeChunk(snapshot, placeholder, 9999, 10000, emptyRows())) + 1024;
  if (envelopeBytes >= budget)
    throw new Error('V2 元数据与失败列表已超过分块预算');
  const batches = [];
  let current = emptyRows();
  let currentBytes = envelopeBytes;
  let count = 0;
  for (const kind of ['runtimeUsage', 'taskUsage', 'issueUsage']) {
    for (const row of snapshot[kind]) {
      const rowBytes = byteLength(row) + 2;
      if (envelopeBytes + rowBytes > budget)
        throw new Error(`${kind} 单行超过分块预算`);
      if (count && currentBytes + rowBytes > budget) {
        batches.push(current);
        current = emptyRows();
        currentBytes = envelopeBytes;
        count = 0;
      }
      current[kind].push(row);
      currentBytes += rowBytes;
      count += 1;
    }
  }
  if (count || batches.length === 0) batches.push(current);
  return batches;
}

export function assertUniqueKeys(snapshot) {
  const groups = [
    ['Runtime', snapshot.runtimeUsage, (row) => `${row.runtimeId}\0${row.usageDate}\0${row.provider}\0${row.model}`],
    ['Task', snapshot.taskUsage, (row) => `${row.taskId}\0${row.provider}\0${row.model}`],
    ['Issue', snapshot.issueUsage, (row) => row.issueId],
  ];
  for (const [name, rows, key] of groups) {
    const keys = new Set();
    for (const row of rows) {
      const value = key(row);
      if (keys.has(value)) throw new Error(`${name} 快照含重复用量键：${value.replaceAll('\0', '/')}`);
      keys.add(value);
    }
  }
}

export function assertCommittedReceipt(receipt, snapshot) {
  if (!receipt || receipt.committed !== true || receipt.snapshotId !== snapshot.snapshotId
    || receipt.runtimeRows !== snapshot.expectedRows.runtime
    || receipt.taskRows !== snapshot.expectedRows.task
    || receipt.issueRows !== snapshot.expectedRows.issue
    || receipt.failureCount !== snapshot.failures.length)
    throw new Error('Dashboard 未返回与完整快照一致的 V2 committed 回执');
}
