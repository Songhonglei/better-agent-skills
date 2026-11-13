export type ExpenseUsage = { key: string; costUsd: number; inputTokens: number; outputTokens: number; cacheReadTokens: number; cacheWriteTokens: number; pricedTokens: number; unpricedTokens: number };
export type ExpenseSummary = {
  range: { start: string; end: string; granularity: 'day' | 'week' | 'month' };
  accountingBasis?: 'issue-task-lifecycle';
  collectedAt?: string;
  collection?: {
    collectedAt?: string; runtimeRows?: number; taskRows?: number; issueRows?: number; skippedOffline?: number; failureCount?: number;
    runtimes?: Array<{ id: string; name: string; status: string }>;
    failures?: Array<{ stage: string; entityId?: string; message: string }>;
    unlinkedRuntime?: { tokenTotal: number; costUsd: number };
  };
  total: Omit<ExpenseUsage, 'key'>;
  attributionCoverage: number;
  attributionCoverageByDimension?: { agent: number; project: number; initiator: number };
  runtimeCoverage?: number;
  runtimeTokens?: number;
  initiatorAccounts?: Record<string, string>;
  unpricedModels?: Array<{ provider: string; model: string; unpricedTokens: number }>;
  unrecognizedModelAliases?: Array<{ provider: string; model: string; alias: string; unpricedTokens: number }>;
  trend: ExpenseUsage[];
  breakdowns: Record<'runtime' | 'model' | 'agent' | 'project' | 'initiator', ExpenseUsage[]>;
};
export type ExpensePrice = {
  id?: string; provider: string; model: string; displayName: string; currency: 'USD' | 'CNY'; usdExchangeRate: number;
  inputPerMillion: number; outputPerMillion: number; cacheReadPerMillion: number; cacheWritePerMillion: number;
  effectiveFrom: string; effectiveTo?: string | null;
};
export type ExpenseSettings = { prices: ExpensePrice[]; cnyPerUsd: number; isAdmin: boolean; userEmail?: string };
export type EmployeeDirectoryEntry = { account: string; displayName: string };

export type DashboardApi = {
  expenses(query: { start: string; end: string; granularity: string }): Promise<ExpenseSummary>;
  expenseSettings(): Promise<ExpenseSettings>;
  saveExpenseExchangeRate(cnyPerUsd: number): Promise<{ cnyPerUsd: number }>;
  saveExpensePrice(price: ExpensePrice): Promise<ExpensePrice>;
  saveExpensePrices(prices: ExpensePrice[]): Promise<ExpensePrice[]>;
  employeeSearch?: (account: string) => Promise<EmployeeDirectoryEntry | undefined>;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init).catch(() => {
    throw new Error('无法连接大盘，请检查服务和网络后重试');
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { error?: string };
    throw new Error(body.error ?? `请求失败 (${response.status})，请检查服务状态后刷新`);
  }
  return response.json() as Promise<T>;
}

function json(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}

export const api: DashboardApi = {
  expenses: (query) => request(`/api/expenses?${new URLSearchParams(query)}`),
  expenseSettings: () => request('/api/expenses/settings'),
  saveExpenseExchangeRate: (cnyPerUsd) => request('/api/expenses/exchange-rate', json('PUT', { cnyPerUsd })),
  saveExpensePrice: (price) => request('/api/expenses/prices', json('PUT', price)),
  saveExpensePrices: (prices) => request('/api/expenses/prices/bulk', json('POST', { prices })),
};
