import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { BookOpenCheck, CalendarDays, Check, ChevronLeft, ChevronRight, CircleDollarSign, ClipboardPaste, Copy, Database, FileJson, Gauge, Info, LockKeyhole, Pencil, Plus, Save, TriangleAlert, X } from 'lucide-react';
import type { DashboardApi, ExpensePrice, ExpenseSettings, ExpenseSummary, ExpenseUsage } from '../../api/client.js';
import { copyText } from '../../lib/clipboard.js';

const dimensions = [
  ['agent', '智能体'], ['project', '项目'], ['initiator', '发起人'], ['model', '模型'],
] as const;
const emptyTotal = { costUsd: 0, inputTokens: 0, outputTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0, pricedTokens: 0, unpricedTokens: 0 };
const breakdownPageSize = 20;
export const defaultCnyPerUsd = 6.8;
export const priceJsonExample = JSON.stringify({
  prices: [
    {
      provider: 'example', model: 'example-model', displayName: '示例模型（请替换）', currency: 'USD',
      input: 2, output: 10, cacheRead: 0.2, cacheWrite: 2.5, effectiveFrom: '2026-01-01',
    },
    {
      provider: 'example', model: 'example-model-cny', displayName: '示例人民币模型（请替换）', currency: 'CNY',
      input: 2, output: 8, cacheRead: 0.2, cacheWrite: 2.5, effectiveFrom: '2026-01-01',
    },
  ],
}, null, 2);

function isoDate(offsetDays = 0, now = new Date()): string {
  const date = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  date.setDate(date.getDate() + offsetDays);
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${date.getFullYear()}-${month}-${day}`;
}

export function recentThirtyDayRange(now = new Date()): { start: string; end: string } {
  return { start: isoDate(-29, now), end: isoDate(0, now) };
}

function money(value: number): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
}

function compact(value: number): string {
  return new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

function usageTokenTotal(value: Pick<ExpenseUsage, 'inputTokens' | 'outputTokens' | 'cacheReadTokens' | 'cacheWriteTokens'>): number {
  return value.inputTokens + value.outputTokens + value.cacheReadTokens + value.cacheWriteTokens;
}

type PresentedExpenseUsage = ExpenseUsage & { account?: string };

function initiatorAccount(value?: string): string | undefined {
  const trimmed = value?.trim().toLowerCase();
  if (!trimmed) return undefined;
  const account = trimmed.split('@')[0];
  return /^[a-z0-9][a-z0-9._-]*$/.test(account) ? account : undefined;
}

function presentedInitiators(
  rows: ExpenseUsage[],
  serverAccounts: Record<string, string>,
  employeeNames: Record<string, string>,
): PresentedExpenseUsage[] {
  const merged = new Map<string, PresentedExpenseUsage>();
  for (const row of rows) {
    const rawAccount = initiatorAccount(row.key);
    const account = serverAccounts[row.key] ?? rawAccount;
    const key = account && employeeNames[account] ? employeeNames[account] : row.key;
    const current = merged.get(key);
    if (!current) {
      merged.set(key, { ...row, key, account: account && key !== account ? account : undefined });
      continue;
    }
    current.costUsd += row.costUsd;
    current.inputTokens += row.inputTokens;
    current.outputTokens += row.outputTokens;
    current.cacheReadTokens += row.cacheReadTokens;
    current.cacheWriteTokens += row.cacheWriteTokens;
    current.pricedTokens += row.pricedTokens;
    current.unpricedTokens += row.unpricedTokens;
    current.account ??= account;
  }
  return [...merged.values()].sort((left, right) => right.costUsd - left.costUsd || usageTokenTotal(right) - usageTokenTotal(left));
}

function percentage(value: number): string {
  return `${new Intl.NumberFormat('zh-CN', { style: 'percent', maximumFractionDigits: 1 }).format(value)}`;
}

function updatedAt(value?: string): string {
  if (!value) return '等待首次采集';
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date(value));
}

type JsonRecord = Record<string, unknown>;

function jsonRecord(value: unknown): JsonRecord {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : {};
}

function jsonNumber(row: JsonRecord, keys: string[], fallback?: number): number {
  for (const key of keys) {
    if (row[key] === undefined || row[key] === null || row[key] === '') continue;
    const value = Number(row[key]);
    if (Number.isFinite(value) && value >= 0) return value;
    throw new Error(`${key} 必须是非负数字`);
  }
  if (fallback !== undefined) return fallback;
  throw new Error(`缺少 ${keys[0]}`);
}

function looksLikeRate(value: unknown): boolean {
  const row = jsonRecord(value);
  return ['input', 'inputPerMillion', 'output', 'outputPerMillion', 'cacheRead', 'cacheReadPerMillion', 'cacheWrite', 'cacheWritePerMillion'].some((key) => row[key] !== undefined);
}

function normalizeJsonPrice(value: unknown, identity: { provider?: string; model?: string } = {}, cnyPerUsd = defaultCnyPerUsd): ExpensePrice {
  const row = jsonRecord(value);
  const provider = typeof row.provider === 'string' ? row.provider : identity.provider;
  const model = typeof row.model === 'string' ? row.model : identity.model;
  if (!provider || !model) throw new Error('每条价格都需要 provider 和 model');
  const currency = row.currency === 'CNY' ? 'CNY' : 'USD';
  const effectiveTo = typeof row.effectiveTo === 'string' ? row.effectiveTo : typeof row.effective_to === 'string' ? row.effective_to : null;
  return {
    provider,
    model,
    displayName: typeof row.displayName === 'string' ? row.displayName : typeof row.name === 'string' ? row.name : model,
    currency,
    usdExchangeRate: jsonNumber(row, ['usdExchangeRate', 'usd_exchange_rate'], currency === 'USD' ? 1 : 1 / cnyPerUsd),
    inputPerMillion: jsonNumber(row, ['inputPerMillion', 'input', 'input_price']),
    outputPerMillion: jsonNumber(row, ['outputPerMillion', 'output', 'output_price']),
    cacheReadPerMillion: jsonNumber(row, ['cacheReadPerMillion', 'cacheRead', 'cache_read'], 0),
    cacheWritePerMillion: jsonNumber(row, ['cacheWritePerMillion', 'cacheWrite', 'cache_write'], 0),
    effectiveFrom: typeof row.effectiveFrom === 'string' ? row.effectiveFrom : typeof row.effective_from === 'string' ? row.effective_from : isoDate(),
    effectiveTo,
  };
}

export function parsePriceJson(raw: string, cnyPerUsd = defaultCnyPerUsd): ExpensePrice[] {
  const source = raw.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
  if (!source) return [];
  let value: unknown;
  try { value = JSON.parse(source); }
  catch { throw new Error('JSON 格式无效'); }
  if (Array.isArray(value)) return value.map((entry) => normalizeJsonPrice(entry, {}, cnyPerUsd));
  const root = jsonRecord(value);
  if (Array.isArray(root.prices)) return root.prices.map((entry) => normalizeJsonPrice(entry, {}, cnyPerUsd));
  if (typeof root.provider === 'string' && typeof root.model === 'string') return [normalizeJsonPrice(root, {}, cnyPerUsd)];
  const prices: ExpensePrice[] = [];
  for (const [key, entry] of Object.entries(root)) {
    if (key.includes('/') && looksLikeRate(entry)) {
      const separator = key.indexOf('/');
      prices.push(normalizeJsonPrice(entry, { provider: key.slice(0, separator), model: key.slice(separator + 1) }, cnyPerUsd));
      continue;
    }
    const providerModels = jsonRecord(entry);
    for (const [model, rate] of Object.entries(providerModels)) {
      if (looksLikeRate(rate)) prices.push(normalizeJsonPrice(rate, { provider: key, model }, cnyPerUsd));
    }
  }
  if (!prices.length) throw new Error('未识别到价格配置');
  return prices;
}

function trendPeriodKey(dateValue: string, granularity: 'day' | 'week' | 'month'): string {
  if (granularity === 'day') return dateValue;
  if (granularity === 'month') return dateValue.slice(0, 7);
  if (dateValue.length < 10) return dateValue;
  const date = new Date(`${dateValue}T00:00:00Z`);
  const day = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() - day + 1);
  return date.toISOString().slice(0, 10);
}

export function aggregateExpenseTrend(rows: ExpenseUsage[], granularity: 'day' | 'week' | 'month'): ExpenseUsage[] {
  if (granularity === 'day') return rows;
  const groups = new Map<string, ExpenseUsage>();
  for (const row of rows) {
    const key = trendPeriodKey(row.key, granularity);
    const current = groups.get(key) ?? { key, ...emptyTotal };
    current.costUsd += row.costUsd;
    current.inputTokens += row.inputTokens;
    current.outputTokens += row.outputTokens;
    current.cacheReadTokens += row.cacheReadTokens;
    current.cacheWriteTokens += row.cacheWriteTokens;
    current.pricedTokens += row.pricedTokens;
    current.unpricedTokens += row.unpricedTokens;
    groups.set(key, current);
  }
  return [...groups.values()].sort((left, right) => left.key.localeCompare(right.key));
}

function newPriceDraft(prefill?: { provider: string; model: string }, effectiveFrom = isoDate()): ExpensePrice {
  return {
    provider: prefill?.provider ?? '', model: prefill?.model ?? '', displayName: prefill?.model ?? '',
    currency: 'USD', usdExchangeRate: 1,
    inputPerMillion: 0, outputPerMillion: 0, cacheReadPerMillion: 0, cacheWritePerMillion: 0,
    effectiveFrom, effectiveTo: null,
  };
}

function getUnpricedModels(summary?: ExpenseSummary): NonNullable<ExpenseSummary['unpricedModels']> {
  if (summary?.unpricedModels?.length) return summary.unpricedModels;
  return (summary?.breakdowns.model ?? []).filter((row) => row.unpricedTokens > 0).map((row) => {
    const separator = row.key.indexOf(' / ');
    return {
      provider: separator >= 0 ? row.key.slice(0, separator) : '',
      model: separator >= 0 ? row.key.slice(separator + 3) : row.key,
      unpricedTokens: row.unpricedTokens,
    };
  });
}

function TokenLegend({ value }: { value: typeof emptyTotal }) {
  const total = value.inputTokens + value.outputTokens + value.cacheReadTokens + value.cacheWriteTokens || 1;
  const parts = [
    ['输入', value.inputTokens, 'input'], ['输出', value.outputTokens, 'output'], ['缓存读', value.cacheReadTokens, 'cache-read'], ['缓存写', value.cacheWriteTokens, 'cache-write'],
  ] as const;
  return <div className="token-composition">
    <div className="token-stack" aria-label="Token 四维构成">{parts.map(([label, count, kind]) => <i key={kind} className={kind} style={{ width: `${count / total * 100}%` }} title={`${label} ${count.toLocaleString()}`} />)}</div>
    <div className="token-legend">{parts.map(([label, count, kind]) => <span key={kind}><i className={kind} />{label}<b>{compact(count)}</b></span>)}</div>
  </div>;
}

function Trend({ rows }: { rows: ExpenseUsage[] }) {
  const max = Math.max(...rows.map((row) => row.costUsd), 1);
  if (!rows.length) return <div className="expense-empty"><Database size={22} /><span>所选时间范围暂无 usage 快照</span></div>;
  return <div className="expense-trend" role="img" aria-label="费用趋势图">
    {rows.map((row) => <div className="expense-trend-column" key={row.key} title={`${row.key} · ${money(row.costUsd)}`}>
      <span>{money(row.costUsd)}</span><div><i style={{ height: `${Math.max(3, row.costUsd / max * 100)}%` }} /></div><small>{row.key.slice(5)}</small>
    </div>)}
  </div>;
}

function ExpenseCaliber() {
  return <details className="expense-caliber">
    <summary><span><BookOpenCheck size={16} />费用如何计算</span><small>查看数据口径</small></summary>
    <div className="expense-caliber-content">
      <section><strong>统计范围</strong><p>在所选日期范围内，费用、Token、趋势和排行都使用同一套 Issue 全生命周期数据。只有 Issue 数据缺失时才用 Task 补齐，同一笔消耗不会重复计算。</p></section>
      <section><strong>价格换算</strong><p>每条模型用量按发生日期匹配价格表。人民币价格按当前保存的 USD/CNY 汇率换算；修改汇率后，页面会重新计算全部金额。没有匹配价格的 Token 会单独提示，金额暂按 0 计算。</p></section>
      <section><strong>归属规则</strong><p>智能体按实际执行 Task 的 Token 比例分摊；项目跟随 Issue 所属项目；发起人优先使用任务运行记录，其次使用定时任务配置人，最后使用成员创建者。</p></section>
      <section><strong>Runtime 对账</strong><p>Runtime 按日统计。页面单独展示 Runtime 对账覆盖率，查询失败范围可在采集明细中检查。</p></section>
      <dl><div><dt>Token 总量</dt><dd>输入、输出、缓存读、缓存写之和</dd></div><div><dt>归因覆盖率</dt><dd>能够找到业务发起人的 Token 占比</dd></div><div><dt>未归属项目</dt><dd>临时任务没有绑定项目，属于真实业务状态</dd></div></dl>
    </div>
  </details>;
}

function PriceTable({ settings, initialPrice, onInitialPriceConsumed, onSave, onSaveMany, onSaveExchangeRate, onSaved }: {
  settings: ExpenseSettings;
  initialPrice?: ExpensePrice;
  onInitialPriceConsumed(): void;
  onSave(price: ExpensePrice): Promise<ExpensePrice>;
  onSaveMany(prices: ExpensePrice[]): Promise<ExpensePrice[]>;
  onSaveExchangeRate(cnyPerUsd: number): Promise<{ cnyPerUsd: number }>;
  onSaved(): void;
}) {
  const [draft, setDraft] = useState<ExpensePrice | undefined>(initialPrice);
  const [jsonOpen, setJsonOpen] = useState(false);
  const [rateOpen, setRateOpen] = useState(false);
  const [jsonText, setJsonText] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();
  const [cnyPerUsd, setCnyPerUsd] = useState(String(settings.cnyPerUsd));
  const [rateSaving, setRateSaving] = useState(false);
  const [rateStatus, setRateStatus] = useState<'idle' | 'saved' | 'failed'>('idle');
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'failed'>('idle');
  const copyResetTimer = useRef<number | undefined>(undefined);
  const parsedJson = useMemo(() => {
    try { return { prices: parsePriceJson(jsonText, settings.cnyPerUsd), error: undefined }; }
    catch (caught) { return { prices: [], error: caught instanceof Error ? caught.message : 'JSON 格式无效' }; }
  }, [jsonText, settings.cnyPerUsd]);
  useEffect(() => setCnyPerUsd(String(settings.cnyPerUsd)), [settings.cnyPerUsd]);
  useEffect(() => () => {
    if (copyResetTimer.current) window.clearTimeout(copyResetTimer.current);
  }, []);
  useEffect(() => {
    if (!initialPrice) return;
    setDraft(initialPrice);
    setJsonOpen(false);
    onInitialPriceConsumed();
  }, [initialPrice, onInitialPriceConsumed]);
  const startEdit = (price?: ExpensePrice) => setDraft(price ? { ...price } : newPriceDraft());
  const openRateEditor = () => {
    setCnyPerUsd(String(settings.cnyPerUsd));
    setRateStatus('idle');
    setRateOpen(true);
  };
  const update = (key: keyof ExpensePrice, value: string | number) => setDraft((current) => current ? { ...current, [key]: value } : current);
  const save = async () => {
    if (!draft || !settings.isAdmin) return;
    if (draft.effectiveTo && draft.effectiveTo < draft.effectiveFrom) {
      setError('失效日期不能早于生效日期');
      return;
    }
    setSaving(true);
    setError(undefined);
    try { await onSave(draft); setDraft(undefined); onSaved(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : '价格保存失败'); }
    finally { setSaving(false); }
  };
  const importJson = async () => {
    if (!settings.isAdmin || !parsedJson.prices.length) return;
    setSaving(true);
    setError(undefined);
    try {
      await onSaveMany(parsedJson.prices);
      setJsonOpen(false);
      setJsonText('');
      onSaved();
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'JSON 导入失败'); }
    finally { setSaving(false); }
  };
  const saveExchangeRate = async () => {
    const value = Number(cnyPerUsd);
    if (!settings.isAdmin || !Number.isFinite(value) || value <= 0) return;
    setRateSaving(true);
    setRateStatus('idle');
    try {
      await onSaveExchangeRate(value);
      setRateStatus('saved');
      onSaved();
    } catch {
      setRateStatus('failed');
    } finally {
      setRateSaving(false);
    }
  };
  const copyExample = async () => {
    if (copyResetTimer.current) window.clearTimeout(copyResetTimer.current);
    try {
      await copyText(priceJsonExample);
      setCopyStatus('copied');
    } catch {
      setCopyStatus('failed');
    }
    copyResetTimer.current = window.setTimeout(() => setCopyStatus('idle'), 2_000);
  };
  return <section className="expense-settings">
    <div className="expense-section-head"><div><h2>自定义价格</h2><p>价格按生效日期匹配历史用量，新增版本保留价格变更记录。</p></div>
      <div className="expense-actions"><div className="current-rate"><span>当前汇率：</span><strong>{`1 USD = ${settings.cnyPerUsd} CNY`}</strong>{settings.isAdmin && <button className="rate-edit-button" type="button" aria-label="修改汇率" title="修改汇率" onClick={openRateEditor}><Pencil size={14} /></button>}</div>{settings.isAdmin ? <><button className="secondary-action" type="button" onClick={() => { setError(undefined); setJsonOpen(true); }}><ClipboardPaste size={15} />粘贴 JSON</button><button className="primary-action" type="button" onClick={() => startEdit()}><Plus size={15} />新增价格版本</button></> : <span className="admin-lock"><LockKeyhole size={14} />仅管理员可编辑</span>}</div>
    </div>
    <div className="expense-table-wrap"><table className="expense-table"><thead><tr><th>Provider / 模型</th><th>输入</th><th>输出</th><th>缓存读</th><th>缓存写</th><th>币种</th><th>生效区间</th>{settings.isAdmin && <th />}</tr></thead><tbody>
      {settings.prices.map((price) => <tr key={price.id}><td><strong>{price.displayName}</strong><code>{price.provider} / {price.model}</code></td><td>{price.inputPerMillion}</td><td>{price.outputPerMillion}</td><td>{price.cacheReadPerMillion}</td><td>{price.cacheWritePerMillion}</td><td>{price.currency}<small>{price.currency === 'CNY' ? '按全局汇率' : ''}</small></td><td>{price.effectiveFrom}<small>{price.effectiveTo ? `至 ${price.effectiveTo}` : '当前有效'}</small></td>{settings.isAdmin && <td><button className="table-link" type="button" onClick={() => startEdit(price)}>编辑</button></td>}</tr>)}
    </tbody></table></div>
    {draft && createPortal(<div className="price-editor-backdrop"><div className="price-editor" role="dialog" aria-modal="true" aria-label="价格编辑器"><div className="price-editor-head"><strong>{draft.id ? '编辑价格版本' : '新增价格版本'}</strong><button type="button" onClick={() => setDraft(undefined)} aria-label="关闭"><X size={17} /></button></div>
      <div className="price-form">
        <label>Provider<input value={draft.provider} onChange={(event) => update('provider', event.target.value)} /></label><label>模型标识<input value={draft.model} onChange={(event) => update('model', event.target.value)} /></label><label>显示名<input value={draft.displayName} onChange={(event) => update('displayName', event.target.value)} /></label>
        {(['inputPerMillion', 'outputPerMillion', 'cacheReadPerMillion', 'cacheWritePerMillion'] as const).map((key, index) => <label key={key}>{['输入 / 1M', '输出 / 1M', '缓存读 / 1M', '缓存写 / 1M'][index]}<input type="number" min="0" step="0.001" value={draft[key]} onChange={(event) => update(key, Number(event.target.value))} /></label>)}
        <label>币种<select value={draft.currency} onChange={(event) => update('currency', event.target.value)}><option>USD</option><option>CNY</option></select></label>
        <label>生效日期<input type="date" value={draft.effectiveFrom} onChange={(event) => update('effectiveFrom', event.target.value)} /></label><label>失效日期<input type="date" value={draft.effectiveTo ?? ''} onChange={(event) => update('effectiveTo', event.target.value)} /></label>
      </div>{error && <div className="expense-warning" role="alert"><TriangleAlert size={15} />{error}</div>}<div className="price-editor-actions"><button type="button" onClick={() => setDraft(undefined)}>取消</button><button className="primary-action" type="button" disabled={saving || !draft.provider || !draft.model || !draft.displayName || Boolean(draft.effectiveTo && draft.effectiveTo < draft.effectiveFrom)} onClick={() => void save()}><Save size={14} />{saving ? '保存中' : '保存'}</button></div>
    </div></div>, document.body)}
    {rateOpen && createPortal(<div className="price-editor-backdrop"><div className="price-editor exchange-rate-editor" role="dialog" aria-modal="true" aria-label="汇率编辑器"><div className="price-editor-head"><strong>修改人民币汇率</strong><button type="button" onClick={() => setRateOpen(false)} aria-label="关闭"><X size={17} /></button></div>
      <div className="exchange-rate-form"><label><span>USD 对人民币汇率</span><div><b>1 USD =</b><input aria-label="人民币汇率" type="number" min="0.000001" max="100" step="0.0001" autoFocus value={cnyPerUsd} onChange={(event) => { setCnyPerUsd(event.target.value); setRateStatus('idle'); }} /><b>CNY</b></div></label><small>{Number(cnyPerUsd) > 0 ? `1 CNY = $${(1 / Number(cnyPerUsd)).toFixed(6)}` : '请输入有效汇率'}</small></div>
      <div className="price-editor-actions"><span className={`exchange-rate-status is-${rateStatus}`} role="status">{rateStatus === 'saved' ? '已保存并重算' : rateStatus === 'failed' ? '保存失败' : ''}</span><button type="button" onClick={() => setRateOpen(false)}>取消</button><button className="primary-action" type="button" disabled={rateSaving || !Number.isFinite(Number(cnyPerUsd)) || Number(cnyPerUsd) <= 0} onClick={() => void saveExchangeRate()}><Save size={14} />{rateSaving ? '保存中' : '保存汇率'}</button></div>
    </div></div>, document.body)}
    {jsonOpen && createPortal(<div className="price-editor-backdrop"><div className="price-editor" role="dialog" aria-modal="true" aria-label="JSON 价格导入"><div className="price-editor-head"><strong>JSON 价格导入</strong><button type="button" onClick={() => setJsonOpen(false)} aria-label="关闭"><X size={17} /></button></div>
      <div className="json-example-head"><span>多模型样例</span><button className="secondary-action" type="button" onClick={() => void copyExample()} aria-label="复制多模型 JSON 样例" title="复制样例">{copyStatus === 'copied' ? <Check size={14} /> : <Copy size={14} />}<span>{copyStatus === 'copied' ? '已复制' : copyStatus === 'failed' ? '复制失败' : '复制样例'}</span></button></div>
      <pre className="json-example">{priceJsonExample}</pre>
      <textarea className="price-json-input" aria-label="价格 JSON" autoFocus value={jsonText} onChange={(event) => setJsonText(event.target.value)} placeholder="在此粘贴一个或多个模型的 JSON" />
      <div className={`json-recognition ${jsonText && parsedJson.error ? 'is-error' : ''}`}><FileJson size={15} />{!jsonText ? '等待 JSON 内容' : parsedJson.error ? parsedJson.error : `已识别 ${parsedJson.prices.length} 条价格`}</div>
      {!!parsedJson.prices.length && <div className="json-preview">{parsedJson.prices.slice(0, 6).map((price) => <span key={`${price.provider}/${price.model}`}>{price.provider} / {price.model}</span>)}{parsedJson.prices.length > 6 && <span>+{parsedJson.prices.length - 6}</span>}</div>}
      {error && <div className="expense-warning" role="alert"><TriangleAlert size={15} />{error}</div>}<div className="price-editor-actions"><button type="button" onClick={() => setJsonOpen(false)}>取消</button><button className="primary-action" type="button" disabled={saving || !parsedJson.prices.length || Boolean(parsedJson.error)} onClick={() => void importJson()}><Save size={14} />{saving ? '导入中' : `导入 ${parsedJson.prices.length || ''} 条`}</button></div>
    </div></div>, document.body)}
  </section>;
}

export function ExpensesPage({ api }: { api: DashboardApi }) {
  const [initialRange] = useState(() => recentThirtyDayRange());
  const [section, setSection] = useState<'usage' | 'prices'>('usage');
  const [start, setStart] = useState(initialRange.start);
  const [end, setEnd] = useState(initialRange.end);
  const [granularity, setGranularity] = useState<'day' | 'week' | 'month'>('day');
  const [dimension, setDimension] = useState<(typeof dimensions)[number][0]>('agent');
  const [breakdownPage, setBreakdownPage] = useState(0);
  const [pricePrefill, setPricePrefill] = useState<ExpensePrice>();
  const [summary, setSummary] = useState<ExpenseSummary>();
  const [settings, setSettings] = useState<ExpenseSettings>();
  const [collectionOpen, setCollectionOpen] = useState(false);
  const [employeeNames, setEmployeeNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const loadRequest = useRef(0);
  const employeeSearchAttempted = useRef(new Set<string>());
  const load = useCallback(async () => {
    const request = ++loadRequest.current;
    if (start > end) {
      setError('开始日期不能晚于结束日期');
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(undefined);
    try {
      const nextSummary = await api.expenses?.({ start, end, granularity });
      if (request !== loadRequest.current) return;
      if (nextSummary) setSummary(nextSummary);
    } catch (caught) {
      if (request === loadRequest.current) setError(caught instanceof Error ? caught.message : '费用数据加载失败');
    }
    finally { if (request === loadRequest.current) setLoading(false); }
  }, [api, start, end, granularity]);
  const loadSettings = useCallback(async () => {
    try {
      const nextSettings = await api.expenseSettings?.();
      if (nextSettings) setSettings(nextSettings);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '价格配置加载失败');
    }
  }, [api]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { void loadSettings(); }, [loadSettings]);
  useEffect(() => { setBreakdownPage(0); }, [dimension, summary]);
  useEffect(() => {
    if (!summary || !api.employeeSearch) return;
    const accounts = [...new Set([
      ...summary.breakdowns.initiator.flatMap((row) => initiatorAccount(row.key) ?? []),
      ...Object.values(summary.initiatorAccounts ?? {}).flatMap((value) => initiatorAccount(value) ?? []),
    ])].filter((account) => !employeeSearchAttempted.current.has(account));
    if (!accounts.length) return;
    for (const account of accounts) employeeSearchAttempted.current.add(account);
    let active = true;
    void (async () => {
      const found: Record<string, string> = {};
      for (let index = 0; index < accounts.length; index += 4) {
        const entries = await Promise.all(accounts.slice(index, index + 4).map(async (account) => {
          try { return await api.employeeSearch?.(account); }
          catch { return undefined; }
        }));
        for (const entry of entries) if (entry) found[entry.account] = entry.displayName;
      }
      if (active && Object.keys(found).length) setEmployeeNames((current) => ({ ...current, ...found }));
    })();
    return () => { active = false; };
  }, [api, summary]);
  const total = summary?.total ?? emptyTotal;
  const tokenTotal = usageTokenTotal(total);
  const rows = useMemo<PresentedExpenseUsage[]>(() => {
    const source = summary?.breakdowns[dimension] ?? [];
    return dimension === 'initiator'
      ? presentedInitiators(source, summary?.initiatorAccounts ?? {}, employeeNames)
      : source;
  }, [summary, dimension, employeeNames]);
  const maxBreakdownCost = useMemo(() => Math.max(...rows.map((row) => row.costUsd), 0), [rows]);
  const pageCount = Math.max(1, Math.ceil(rows.length / breakdownPageSize));
  const safePage = Math.min(breakdownPage, pageCount - 1);
  const pageRows = useMemo(() => rows.slice(safePage * breakdownPageSize, (safePage + 1) * breakdownPageSize), [rows, safePage]);
  const placeholderRows = Math.max(0, 5 - pageRows.length);
  const unpricedModels = useMemo(() => getUnpricedModels(summary), [summary]);
  const unrecognizedAliases = summary?.unrecognizedModelAliases ?? [];
  const unrecognizedAliasNames = [...new Set(unrecognizedAliases.map((item) => item.alias))];
  const collectionFailures = summary?.collection?.failures ?? [];
  const realFailureCount = collectionFailures.length
    ? collectionFailures.filter((failure) => failure.stage !== 'runtime-usage').length
    : summary?.collection?.failureCount ?? 0;
  const runtimeFailureCount = collectionFailures.filter((failure) => failure.stage === 'runtime-usage').length;
  const skippedOffline = summary?.collection?.skippedOffline ?? 0;
  const unlinkedRuntime = summary?.collection?.unlinkedRuntime ?? { tokenTotal: 0, costUsd: 0 };
  const offlineRuntimes = (summary?.collection?.runtimes ?? []).filter((runtime) => runtime.status.toLowerCase() === 'offline');
  const runtimeNames = useMemo(() => new Map((summary?.collection?.runtimes ?? []).map((runtime) => [runtime.id, runtime.name])), [summary]);
  const trendRows = useMemo(() => summary?.range.granularity === granularity ? summary.trend : aggregateExpenseTrend(summary?.trend ?? [], granularity), [summary, granularity]);
  const clearPricePrefill = useCallback(() => setPricePrefill(undefined), []);
  const openPriceEditor = (model?: { provider: string; model: string }) => {
    if (settings?.isAdmin) setPricePrefill(newPriceDraft(model, start));
    setSection('prices');
  };
  return <div className="expenses-page">
    <div className="expense-page-tabs" role="tablist"><button type="button" className={section === 'usage' ? 'active' : ''} onClick={() => setSection('usage')} role="tab">费用信息</button><button type="button" className={section === 'prices' ? 'active' : ''} onClick={() => setSection('prices')} role="tab">价格设置</button></div>
    {error && <div className="expense-warning" role="alert"><TriangleAlert size={15} />{error}</div>}
    {section === 'prices' ? (settings ? <PriceTable settings={settings} initialPrice={pricePrefill} onInitialPriceConsumed={clearPricePrefill} onSave={api.saveExpensePrice ?? (async () => { throw new Error('价格接口不可用'); })} onSaveMany={api.saveExpensePrices ?? (async () => { throw new Error('批量价格接口不可用'); })} onSaveExchangeRate={api.saveExpenseExchangeRate ?? (async () => { throw new Error('汇率接口不可用'); })} onSaved={() => { void load(); void loadSettings(); }} /> : <div className="expense-empty">{error ? '价格配置加载失败，请刷新页面重试' : '价格配置加载中'}</div>) : <>
      <div className="expense-section-head"><div><h2>费用分析</h2><p>Issue / Task 全生命周期口径 · 更新于 {updatedAt(summary?.collectedAt)}</p></div><div className="expense-filters"><label><CalendarDays size={14} /><input aria-label="开始日期" type="date" max={end} value={start} onChange={(event) => setStart(event.target.value)} /></label><span>至</span><label><input aria-label="结束日期" type="date" min={start} value={end} onChange={(event) => setEnd(event.target.value)} /></label></div></div>
      {loading && !summary ? <div className="expense-empty">费用数据加载中</div> : <>
        {(realFailureCount > 0 || runtimeFailureCount > 0 || skippedOffline > 0) && <button className={`expense-collection-banner ${realFailureCount ? 'is-warning' : 'is-info'}`} type="button" onClick={() => setCollectionOpen(true)}>{realFailureCount ? <TriangleAlert size={15} /> : <Info size={15} />}<span>{realFailureCount ? `最近一次 usage 采集有 ${realFailureCount} 项真实失败` : '最近一次 usage 采集完成'}{runtimeFailureCount ? `；${runtimeFailureCount} 个 Runtime usage 未获取` : ''}{skippedOffline ? `；${skippedOffline} 个 offline runtime 未计入` : ''}</span><strong>查看明细</strong></button>}
        <div className="expense-metrics"><article className="expense-total"><CircleDollarSign size={18} /><span>预估总费用</span><strong>{money(total.costUsd)}</strong><small>按大盘价格表计算</small></article><article><Database size={17} /><span>Token 总量</span><strong>{compact(tokenTotal)}</strong><small>{tokenTotal === 0 ? '暂无用量' : total.unpricedTokens ? `${compact(total.unpricedTokens)} token 暂无价格` : '全部 Token 已匹配价格'}</small></article><article><Check size={17} /><span>归因覆盖率</span><strong>{percentage(summary?.attributionCoverage ?? 0)}</strong><small>能够找到业务发起人的 Token 占比</small></article><article className="runtime-coverage"><Gauge size={17} /><span>Runtime 对账覆盖率</span><strong>{percentage(summary?.runtimeCoverage ?? 0)}</strong><small>Runtime 日用量与 Issue/Task 用量对比</small></article></div>
        {!!total.unpricedTokens && <div className="expense-warning expense-price-warning"><TriangleAlert size={15} /><span>{unrecognizedAliasNames.length ? `发现 ${unrecognizedAliasNames.length} 个未识别的模型路由别名（${unrecognizedAliasNames.join('、')}），相关 token 未计入费用。` : '存在未匹配价格的模型，其 token 已展示但未计入费用。'}</span>{unpricedModels.length <= 1 ? <button type="button" onClick={() => openPriceEditor(unpricedModels[0])}>点此补充</button> : <div className="unpriced-model-actions"><span>点此补充：</span>{unpricedModels.map((model) => <button type="button" key={`${model.provider}/${model.model}`} title={`${model.provider} / ${model.model}`} onClick={() => openPriceEditor(model)}>{model.model}</button>)}</div>}</div>}
        <div className="expense-analysis-grid"><section className="expense-panel expense-trend-panel" aria-busy={loading}><div className="panel-title"><div><span>费用趋势</span><strong>{start} 至 {end}</strong></div><div className="segmented expense-trend-controls" role="group" aria-label="费用趋势时间粒度" title="仅调整费用趋势图的时间粒度">{(['day', 'week', 'month'] as const).map((value) => <button type="button" aria-pressed={granularity === value} className={granularity === value ? 'active' : ''} key={value} onClick={() => setGranularity(value)}>{({ day: '日', week: '周', month: '月' })[value]}</button>)}</div></div><Trend rows={trendRows} /></section><section className="expense-panel"><div className="panel-title"><div><span>Token 构成</span><strong>{compact(tokenTotal)} tokens</strong></div></div><TokenLegend value={total} /></section></div>
        <section className="expense-breakdown"><div className="expense-breakdown-head"><div><span>多维下钻</span><strong>{dimensions.find(([key]) => key === dimension)?.[1]}费用排行</strong></div><div className="segmented dimension-tabs">{dimensions.map(([key, label]) => <button type="button" className={dimension === key ? 'active' : ''} key={key} onClick={() => setDimension(key)}>{label}</button>)}</div></div>
          <div className="expense-table-wrap"><table className="expense-table expense-breakdown-table"><colgroup><col /><col /><col /><col /><col /><col /><col /><col /></colgroup><thead><tr><th>{dimensions.find(([key]) => key === dimension)?.[1]}</th><th>费用</th><th>费用量级</th><th>输入</th><th>输出</th><th>缓存读</th><th>缓存写</th><th>Token 总计</th></tr></thead><tbody>{pageRows.map((row) => <tr key={row.key}><td><strong title={row.account ? `账号：${row.account}` : row.key}>{row.key}</strong></td><td>{money(row.costUsd)}</td><td><div className="share-bar" role="progressbar" aria-label={`${row.key}费用量级`} aria-valuemin={0} aria-valuemax={maxBreakdownCost} aria-valuenow={row.costUsd} title={money(row.costUsd)}><i style={{ width: `${maxBreakdownCost ? row.costUsd / maxBreakdownCost * 100 : 0}%` }} /></div></td><td>{compact(row.inputTokens)}</td><td>{compact(row.outputTokens)}</td><td>{compact(row.cacheReadTokens)}</td><td>{compact(row.cacheWriteTokens)}</td><td className="token-total-cell">{compact(usageTokenTotal(row))}</td></tr>)}{Array.from({ length: placeholderRows }, (_, index) => <tr className="expense-placeholder-row" aria-hidden="true" key={`placeholder-${index}`}><td colSpan={8}>{!rows.length && index === 0 ? '暂无数据' : '\u00a0'}</td></tr>)}</tbody></table></div>
          {rows.length > breakdownPageSize && <div className="coverage-pagination"><span>{rows.length} 条 · 第 {safePage + 1} / {pageCount} 页</span><button className="icon-button" type="button" aria-label="费用排行上一页" title="上一页" disabled={safePage === 0} onClick={() => setBreakdownPage(Math.max(0, safePage - 1))}><ChevronLeft size={16} /></button><button className="icon-button" type="button" aria-label="费用排行下一页" title="下一页" disabled={safePage >= pageCount - 1} onClick={() => setBreakdownPage(Math.min(pageCount - 1, safePage + 1))}><ChevronRight size={16} /></button></div>}
        </section>
        <ExpenseCaliber />
      </>}
    </>}
    {collectionOpen && createPortal(<div className="price-editor-backdrop"><div className="price-editor collection-detail-editor" role="dialog" aria-modal="true" aria-label="Usage 采集明细"><div className="price-editor-head"><strong>Usage 采集明细</strong><button type="button" onClick={() => setCollectionOpen(false)} aria-label="关闭"><X size={17} /></button></div>
      <div className="collection-failure-summary" aria-label="采集失败汇总"><div><span>无法关联 Runtime 的 Token</span><strong title={unlinkedRuntime.tokenTotal.toLocaleString()}>{compact(unlinkedRuntime.tokenTotal)}</strong></div><div><span>无法关联 Runtime 的费用</span><strong>{money(unlinkedRuntime.costUsd)}</strong></div></div>
      <div className="collection-detail-section"><div className="collection-detail-title"><span>失败明细</span><b>{collectionFailures.length}</b></div>{collectionFailures.length ? <ul className="collection-detail-list">{collectionFailures.map((failure, index) => <li key={`${failure.stage}-${failure.entityId ?? index}`}><div><strong>{failure.stage}</strong>{failure.entityId && <span>{runtimeNames.get(failure.entityId) ? `${runtimeNames.get(failure.entityId)} (${failure.entityId})` : failure.entityId}</span>}</div><p>{failure.message}</p></li>)}</ul> : <p className="collection-detail-empty">暂无结构化失败明细</p>}</div>
      {!!skippedOffline && <div className="collection-detail-section"><div className="collection-detail-title"><span>未计入的 Offline Runtime</span><b>{skippedOffline}</b></div>{offlineRuntimes.length ? <ul className="offline-runtime-list">{offlineRuntimes.map((runtime) => <li key={runtime.id}><strong>{runtime.name}</strong><code>{runtime.id}</code></li>)}</ul> : <p className="collection-detail-empty">采集快照未包含 Runtime 注册表</p>}</div>}
      <div className="price-editor-actions"><button type="button" onClick={() => setCollectionOpen(false)}>关闭</button></div>
    </div></div>, document.body)}
  </div>;
}
