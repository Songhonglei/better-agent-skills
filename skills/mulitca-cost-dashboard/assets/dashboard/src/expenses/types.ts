export type TokenBreakdown = {
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheWriteTokens: number;
};

export type RuntimeUsageInput = TokenBreakdown & {
  runtimeId: string;
  runtimeName: string;
  usageDate: string;
  provider: string;
  model: string;
};

export type TaskUsageInput = Omit<RuntimeUsageInput, 'runtimeId' | 'runtimeName'> & {
  taskId: string;
  agentId: string;
  agentName: string;
  runtimeId?: string;
  runtimeName?: string;
  issueId?: string;
  projectId?: string;
  projectName?: string;
  initiator?: string;
  delegationPath?: string[];
};

export type RuntimeRegistryInput = {
  id: string;
  name: string;
  status: string;
};

export type IssueModelUsageInput = TokenBreakdown & {
  usageDate: string;
  provider: string;
  model: string;
};

export type IssueUsageInput = TokenBreakdown & {
  issueId: string;
  identifier: string;
  title: string;
  projectId?: string;
  projectName?: string;
  assigneeAgentId?: string;
  assigneeAgentName?: string;
  agentAttributionSource?: string;
  creatorType?: string;
  creatorId?: string;
  creatorName?: string;
  initiatorId?: string;
  initiatorName?: string;
  initiatorEmail?: string;
  initiatorPrecise?: boolean;
  initiatorSource?: string;
  uncostedInputTokens: number;
  uncostedOutputTokens: number;
  uncostedCacheReadTokens: number;
  uncostedCacheWriteTokens: number;
  costUsdTicks: number;
  lastActivityAt: string;
  modelUsage?: IssueModelUsageInput[];
};

export type WorkspaceUsageSnapshot = {
  schemaVersion: 1;
  collectedAt: string;
  runtimeUsage: RuntimeUsageInput[];
  taskUsage: TaskUsageInput[];
  issueUsage?: IssueUsageInput[];
  runtimes?: RuntimeRegistryInput[];
  skippedOffline?: number;
  failures?: UsageCollectionFailure[];
};

export type UsageCollectionFailure = {
  stage: string;
  entityId?: string;
  message: string;
};

export type UsageSnapshotScope = {
  queryWindow: { startDate: string; endDate: string };
  collectionScope: {
    runtimeListSucceeded: boolean;
    runtimeIds: string[];
    successfulRuntimeIds: string[];
    failedRuntimeIds: string[];
  };
};

export type UsageSnapshotMetadata = UsageSnapshotScope & {
  schemaVersion: 2;
  snapshotId: string;
  uploadId: string;
  collectedAt: string;
  expectedRows: { runtime: number; task: number; issue: number };
  runtimes: RuntimeRegistryInput[];
  skippedOffline: number;
};

export type AssembledUsageSnapshot = UsageSnapshotMetadata & {
  runtimeUsage: RuntimeUsageInput[];
  taskUsage: TaskUsageInput[];
  issueUsage: IssueUsageInput[];
  failures: UsageCollectionFailure[];
};

export type UsageSnapshotChunk = AssembledUsageSnapshot & {
  chunk: { index: number; total: number; final: boolean };
};

export type UsageUploadCommit = UsageSnapshotScope & {
  uploadId: string;
  collectedAt: string;
  identityHash: string;
  receivedChunks: number;
  failureCount: number;
};

export type UsageUploadReceipt = {
  snapshotId: string;
  uploadId: string;
  receivedChunks: number;
  committed: boolean;
  runtimeRows?: number;
  taskRows?: number;
  issueRows?: number;
  failureCount?: number;
  collectedAt?: string;
};

export type ExpensePriceInput = {
  id?: string;
  provider: string;
  model: string;
  displayName: string;
  currency: 'USD' | 'CNY';
  usdExchangeRate: number;
  inputPerMillion: number;
  outputPerMillion: number;
  cacheReadPerMillion: number;
  cacheWritePerMillion: number;
  effectiveFrom: string;
  effectiveTo?: string | null;
};
