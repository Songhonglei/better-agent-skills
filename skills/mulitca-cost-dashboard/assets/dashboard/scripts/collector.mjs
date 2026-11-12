// Adapted from the maintained Workspace Usage collector 1.4.0.
import { randomUUID } from 'node:crypto';
import { mkdir, rename, unlink, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { homedir } from 'node:os';
import { assertUniqueKeys, expectedRows, usageQueryWindow } from './usage-v2-protocol.mjs';
const DEFAULT_COLLECTOR_BODY_LIMIT_BYTES = 64 * 1024 * 1024;

function record(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : {};
}
function text(row, keys) {
  for (const key of keys) if (typeof row[key] === "string" && row[key]) return row[key];
  return void 0;
}
function number(row, keys) {
  for (const key of keys) {
    const value = Number(row[key]);
    if (Number.isFinite(value) && value >= 0) return Math.trunc(value);
  }
  return 0;
}
function rows(value, preferredKeys = []) {
  if (Array.isArray(value)) return value.map(record).filter((row) => Object.keys(row).length > 0);
  const root = record(value);
  for (const key of preferredKeys) if (Array.isArray(root[key])) return root[key].map(record);
  return [];
}
function date(value) {
  if (!value) return void 0;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? void 0 : parsed.toISOString().slice(0, 10);
}
function timestamp(value) {
  if (!value) return void 0;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? void 0 : parsed.toISOString();
}
function issueActivityTimestamp(issue) {
  const candidates = [
    timestamp(text(issue, ["last_activity_at", "lastActivityAt"])),
    timestamp(text(issue, ["updated_at", "updatedAt"]))
  ].filter((value) => value !== void 0);
  return candidates.sort().at(-1);
}
function tokens(value) {
  const row = record(value);
  return {
    inputTokens: number(row, ["inputTokens", "input_tokens", "input"]),
    outputTokens: number(row, ["outputTokens", "output_tokens", "output"]),
    cacheReadTokens: number(row, ["cacheReadTokens", "cache_read_tokens", "cache_read"]),
    cacheWriteTokens: number(row, ["cacheWriteTokens", "cache_write_tokens", "cache_write"])
  };
}
function issueTokens(value, prefix = "total_") {
  const row = record(value);
  return {
    inputTokens: number(row, [`${prefix}input_tokens`, `${prefix}inputTokens`]),
    outputTokens: number(row, [`${prefix}output_tokens`, `${prefix}outputTokens`]),
    cacheReadTokens: number(row, [`${prefix}cache_read_tokens`, `${prefix}cacheReadTokens`]),
    cacheWriteTokens: number(row, [`${prefix}cache_write_tokens`, `${prefix}cacheWriteTokens`])
  };
}
function providerFor(model, explicit) {
  const value = model.toLowerCase();
  if (value.includes("claude")) return "anthropic";
  if (value.includes("gpt")) return "openai";
  if (value.includes("gemini")) return "google";
  if (value.includes("qwen")) return "aliyun";
  if (value.includes("deepseek")) return "deepseek";
  if (value.includes("kimi")) return "moonshot";
  if (value.includes("glm")) return "zhipu";
  const provided = explicit?.toLowerCase();
  if (provided === "claude") return "anthropic";
  return provided ?? "unknown";
}
function usageRecords(value, inherited = {}) {
  if (Array.isArray(value)) return value.flatMap((entry) => usageRecords(entry, inherited));
  const current = record(value);
  if (!Object.keys(current).length) return [];
  const context = { ...inherited };
  for (const key of ["date", "usage_date", "usageDate", "model", "model_name", "provider"]) if (current[key] !== void 0) context[key] = current[key];
  const usage = tokens(current);
  const found = Object.values(usage).some((count) => count > 0) ? [{ ...context, ...current }] : [];
  return [...found, ...Object.entries(current).flatMap(([key, child]) => ["usage", "daily", "days", "models", "data", "items", "records"].includes(key) ? usageRecords(child, context) : [])];
}
function runtimeUsageRows(runtime, payload) {
  const runtimeId = text(runtime, ["id", "runtime_id", "runtimeId"]);
  if (!runtimeId) return [];
  const runtimeName = entityName(runtime, runtimeId);
  const fallbackModel = text(runtime, ["model", "model_name"]) ?? text(record(runtime.model), ["id", "name"]) ?? "unknown";
  return usageRecords(payload).flatMap((usage) => {
    const usageDate = date(text(usage, ["date", "usage_date", "usageDate", "created_at", "createdAt"]));
    if (!usageDate) return [];
    const model = text(usage, ["model", "model_name"]) ?? fallbackModel;
    return [{ runtimeId, runtimeName, usageDate, model, provider: providerFor(model, text(usage, ["provider"]) ?? text(runtime, ["provider"])), ...tokens(usage) }];
  });
}
function entityName(value, fallback) {
  return text(value, ["custom_name", "customName", "name", "title", "display_name", "displayName"]) ?? fallback;
}
function taskUsageRows(task, agent, projects, issue, runtimeNames) {
  const taskId = text(task, ["taskId", "task_id", "id", "runId", "run_id"]);
  const agentId = text(agent, ["id", "agent_id", "agentId"]);
  if (!taskId || !agentId) return [];
  const usageRows = usageRecords(task.usage ?? task.token_usage ?? task.tokens);
  const usageDate = date(text(task, ["completed_at", "completedAt", "started_at", "startedAt", "created_at", "createdAt"]));
  if (!usageDate || !usageRows.length) return [];
  const runtime = record(agent.runtime);
  const modelValue = record(agent.model);
  const runtimeId = text(agent, ["runtime_id", "runtimeId"]) ?? text(runtime, ["id"]);
  const runtimeName = (runtimeId ? runtimeNames.get(runtimeId) : void 0) ?? text(agent, ["runtime_custom_name", "runtimeCustomName", "runtime_name", "runtimeName"]) ?? text(runtime, ["custom_name", "customName", "name", "title"]);
  const fallbackModel = text(task, ["model", "model_name"]) ?? text(agent, ["model"]) ?? text(modelValue, ["id", "name"]) ?? text(runtime, ["model"]) ?? "unknown";
  const issueId = text(task, ["issue_id", "issueId"]) ?? text(record(task.issue), ["id"]);
  const projectId = text(issue, ["project_id", "projectId"]) ?? text(record(issue.project), ["id"]);
  const delegation = task.delegation_path ?? task.delegationPath ?? task.attribution;
  const delegationPath = Array.isArray(delegation) ? delegation.flatMap((entry) => {
    if (typeof entry === "string") return [entry];
    const label = text(record(entry), ["email", "name", "id"]);
    return label ? [label] : [];
  }) : [];
  const attributionInitiator = record(record(task.attribution).initiator);
  const initiator = text(task, ["initiator", "initiator_email", "created_by", "requested_by"]) ?? text(record(task.creator), ["email", "name"]) ?? text(attributionInitiator, ["email", "name", "id"]);
  const grouped = /* @__PURE__ */ new Map();
  for (const usage of usageRows) {
    const model = text(usage, ["model", "model_name"]) ?? fallbackModel;
    const provider = providerFor(model, text(usage, ["provider"]) ?? text(task, ["provider"]) ?? text(agent, ["provider"]));
    const breakdown = tokens(usage);
    if (total(breakdown) === 0) continue;
    const key = `${provider}\0${model}`;
    const current = grouped.get(key);
    if (current) {
      current.inputTokens += breakdown.inputTokens;
      current.outputTokens += breakdown.outputTokens;
      current.cacheReadTokens += breakdown.cacheReadTokens;
      current.cacheWriteTokens += breakdown.cacheWriteTokens;
      continue;
    }
    grouped.set(key, {
      taskId,
      usageDate,
      agentId,
      agentName: entityName(agent, agentId),
      runtimeId,
      runtimeName,
      provider,
      model,
      issueId,
      projectId,
      projectName: projectId ? projects.get(projectId) : void 0,
      initiator,
      delegationPath,
      ...breakdown
    });
  }
  return [...grouped.values()];
}
function issueInitiator(runs) {
  const candidates = runs.flatMap((run) => {
    const attribution = record(run.attribution);
    const initiator = record(attribution.initiator);
    if (!Object.keys(initiator).length) return [];
    return [{
      id: text(initiator, ["id"]),
      name: text(initiator, ["name"]),
      email: text(initiator, ["email"]),
      precise: attribution.precise === true,
      source: text(attribution, ["source"])
    }];
  });
  return candidates.find((candidate) => candidate.precise) ?? candidates[0];
}
function issueModelUsage(runs) {
  const grouped = /* @__PURE__ */ new Map();
  for (const run of runs) {
    const usageDate = date(text(run, ["completed_at", "completedAt", "started_at", "startedAt", "created_at", "createdAt"]));
    if (!usageDate) continue;
    for (const usage of usageRecords(run.usage ?? run.token_usage ?? run.tokens)) {
      const model = text(usage, ["model", "model_name"]) ?? "unknown";
      const provider = providerFor(model, text(usage, ["provider"]));
      const breakdown = tokens(usage);
      if (total(breakdown) === 0) continue;
      const key = `${usageDate}\0${provider}\0${model}`;
      const current = grouped.get(key);
      if (current) {
        current.inputTokens += breakdown.inputTokens;
        current.outputTokens += breakdown.outputTokens;
        current.cacheReadTokens += breakdown.cacheReadTokens;
        current.cacheWriteTokens += breakdown.cacheWriteTokens;
      } else {
        grouped.set(key, { usageDate, provider, model, ...breakdown });
      }
    }
  }
  return [...grouped.values()];
}
function autopilotMatchers(autopilots) {
  return autopilots.map(record).flatMap((autopilot) => {
    const template = text(autopilot, ["issue_title_template", "issueTitleTemplate", "title", "name"]);
    const createdByType = text(autopilot, ["created_by_type", "createdByType"]);
    const createdById = text(autopilot, ["created_by_id", "createdById"]);
    if (!template || !createdById || createdByType?.toLowerCase() !== "member") return [];
    const source = template.split(/(\{\{[^}]*\}\})/).map((part, index) => index % 2 === 1 ? ".+" : part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("");
    let pattern;
    try {
      pattern = new RegExp(`^${source}$`);
    } catch {
      return [];
    }
    return [{ template, pattern, createdById }];
  }).sort((a, b) => b.template.length - a.template.length);
}
function matchAutopilot(title, matchers) {
  if (!title) return void 0;
  return matchers.find((matcher) => matcher.pattern.test(title));
}
function issueUsageRow(issue, usage, projects, agents, runs, context = {}) {
  const issueId = text(issue, ["id", "issue_id", "issueId"]);
  const lastActivityAt = issueActivityTimestamp(issue);
  if (!issueId || !lastActivityAt) return void 0;
  const projectId = text(issue, ["project_id", "projectId"]) ?? text(record(issue.project), ["id"]);
  const assigneeType = text(issue, ["assignee_type", "assigneeType"]);
  const assigneeId = text(issue, ["assignee_id", "assigneeId"]);
  const assigneeAgentId = assigneeType?.toLowerCase() === "agent" ? assigneeId : void 0;
  const creatorType = text(issue, ["creator_type", "creatorType"]);
  const creatorId = text(issue, ["creator_id", "creatorId"]);
  const memberDir = context.memberDir ?? new Map();
  const runInitiator = issueInitiator(runs);
  let initiator = runInitiator;
  let initiatorSource = runInitiator?.source;
  if (!initiator) {
    const autopilot = matchAutopilot(text(issue, ["title", "name"]), context.matchers ?? []);
    if (autopilot) {
      const person = memberDir.get(autopilot.createdById);
      initiator = { id: autopilot.createdById, name: person?.name, email: person?.email, precise: false };
      initiatorSource = "autopilot-configurator";
    } else if (creatorType?.toLowerCase() === "member" && creatorId) {
      const person = memberDir.get(creatorId);
      initiator = { id: creatorId, name: person?.name ?? creatorId, email: person?.email, precise: false };
      initiatorSource = "issue-creator";
    }
  }
  const executor = context.executors?.get(issueId);
  const creatorIsAgent = creatorType?.toLowerCase() === "agent" && creatorId ? creatorId : void 0;
  const effectiveAgentId = assigneeAgentId ?? executor?.agentId ?? creatorIsAgent;
  const agentAttributionSource = assigneeAgentId ? "assignee" : executor?.agentId ? "task-executor" : creatorIsAgent ? "creator-agent" : void 0;
  const creatorName = creatorId ? memberDir.get(creatorId)?.name ?? agents.get(creatorId) ?? (runInitiator?.id === creatorId ? runInitiator.name ?? runInitiator.email : void 0) ?? creatorId : void 0;
  return {
    issueId,
    identifier: text(issue, ["identifier", "number"]) ?? issueId,
    title: text(issue, ["title", "name"]) ?? issueId,
    projectId,
    projectName: projectId ? projects.get(projectId) : void 0,
    assigneeAgentId: effectiveAgentId,
    assigneeAgentName: effectiveAgentId ? agents.get(effectiveAgentId) ?? effectiveAgentId : void 0,
    agentAttributionSource,
    creatorType,
    creatorId,
    creatorName,
    initiatorId: initiator?.id,
    initiatorName: initiator?.name,
    initiatorEmail: initiator?.email,
    initiatorPrecise: initiator?.precise,
    initiatorSource,
    ...issueTokens(usage),
    uncostedInputTokens: issueTokens(usage, "uncosted_").inputTokens,
    uncostedOutputTokens: issueTokens(usage, "uncosted_").outputTokens,
    uncostedCacheReadTokens: issueTokens(usage, "uncosted_").cacheReadTokens,
    uncostedCacheWriteTokens: issueTokens(usage, "uncosted_").cacheWriteTokens,
    costUsdTicks: number(record(usage), ["cost_usd_ticks", "costUsdTicks"]),
    lastActivityAt,
    modelUsage: issueModelUsage(runs)
  };
}
function total(value) {
  return value.inputTokens + value.outputTokens + value.cacheReadTokens + value.cacheWriteTokens;
}
async function mapLimit(values, limit, mapper) {
  const result = new Array(values.length);
  let cursor = 0;
  await Promise.all(Array.from({ length: Math.min(limit, values.length) }, async () => {
    while (cursor < values.length) {
      const index = cursor++;
      result[index] = await mapper(values[index]);
    }
  }));
  return result;
}
async function collectStep(failures, stage, entityId, operation, fallback) {
  try {
    return await operation();
  } catch (error) {
    failures.push({ stage, entityId, message: error instanceof Error ? error.message : String(error) });
    return fallback;
  }
}
async function collectWorkspaceUsage(multica, days) {
  const queryWindow = usageQueryWindow(days);
  const failures = [];
  const [runtimeList, agentList, projectList, issueList, autopilotList] = await Promise.all([
    collectStep(failures, "runtime-list", void 0, () => multica.listRuntimes(), []),
    collectStep(failures, "agent-list", void 0, () => multica.listAgents(), []),
    collectStep(failures, "project-list", void 0, () => multica.listProjects(), []),
    collectStep(failures, "issue-list", void 0, () => multica.listWorkspaceIssues(), []),
    collectStep(failures, "autopilot-list", void 0, () => multica.listAutopilots(), [])
  ]);
  const runtimes = runtimeList.map(record);
  if (runtimes.some((runtime) => !text(runtime, ["id", "runtime_id", "runtimeId"])))
    throw new Error("Multica runtime list contains an item without an ID; refusing an unsafe V2 replace scope");
  const runtimeRegistry = runtimes.flatMap((runtime) => {
    const id = text(runtime, ["id", "runtime_id", "runtimeId"]);
    if (!id) return [];
    return [{ id, name: entityName(runtime, id), status: text(runtime, ["status"])?.toLowerCase() ?? "unknown" }];
  });
  if (new Set(runtimeRegistry.map((runtime) => runtime.id)).size !== runtimeRegistry.length)
    throw new Error("Multica runtime list contains duplicate IDs; refusing an unsafe V2 replace scope");
  const runtimeNames = new Map(runtimeRegistry.map((runtime) => [runtime.id, runtime.name]));
  // Offline runtimes can still have historical usage. Query every runtime returned
  // by the workspace list so a backfill includes costs incurred before shutdown.
  const skippedOffline = 0;
  const projects = new Map(projectList.flatMap((project) => project.id ? [[project.id, project.title ?? project.name ?? project.id]] : []));
  const runtimeResults = await mapLimit(runtimes, 6, async (runtime) => {
    const id = text(runtime, ["id", "runtime_id", "runtimeId"]);
    try {
      return { id, success: true, rows: runtimeUsageRows(runtime, await multica.getRuntimeUsage(id, void 0, days)) };
    } catch (error) {
      failures.push({ stage: "runtime-usage", entityId: id, message: error instanceof Error ? error.message : String(error) });
      return { id, success: false, rows: [] };
    }
  });
  const rawRuntimeUsage = runtimeResults.flatMap((result) => result.rows);
  const runtimeUsage = rawRuntimeUsage.filter((row) => row.usageDate >= queryWindow.startDate && row.usageDate <= queryWindow.endDate);
  if (runtimeUsage.length !== rawRuntimeUsage.length)
    console.log(`runtime window: retained ${runtimeUsage.length}/${rawRuntimeUsage.length} rows in ${queryWindow.startDate}..${queryWindow.endDate}`);
  const collectionScope = {
    runtimeListSucceeded: !failures.some((failure) => failure.stage === "runtime-list"),
    runtimeIds: runtimeRegistry.map((runtime) => runtime.id),
    successfulRuntimeIds: runtimeResults.filter((result) => result.success).map((result) => result.id),
    failedRuntimeIds: runtimeResults.filter((result) => !result.success).map((result) => result.id)
  };
  const agents = await mapLimit(agentList.map(record), 6, async (agent) => {
    const id = text(agent, ["id", "agent_id", "agentId"]);
    return id ? record(await collectStep(failures, "agent-get", id, () => multica.getAgent(id), agent)) : agent;
  });
  const agentNames = new Map(agents.flatMap((agent) => {
    const id = text(agent, ["id", "agent_id", "agentId"]);
    return id ? [[id, entityName(agent, id)]] : [];
  }));
  const taskGroups = await mapLimit(agents, 6, async (agent) => {
    const id = text(agent, ["id", "agent_id", "agentId"]);
    return id ? rows(await collectStep(failures, "agent-tasks", id, () => multica.getAgentTasks(id), []), ["tasks", "runs", "items"]).map((task) => ({ task, agent })) : [];
  });
  const taskEntries = taskGroups.flat().filter(({ task }) => {
    const taskDate = date(text(task, ["completed_at", "completedAt", "started_at", "startedAt", "created_at", "createdAt"]));
    return taskDate && taskDate >= new Date(Date.now() - (days - 1) * 864e5).toISOString().slice(0, 10);
  });
  const issueIds = [...new Set(taskEntries.flatMap(({ task }) => {
    const id = text(task, ["issue_id", "issueId"]) ?? text(record(task.issue), ["id"]);
    return id ? [id] : [];
  }))];
  const issues = new Map(issueList.map(record).flatMap((issue) => {
    const id = text(issue, ["id", "issue_id", "issueId"]);
    return id ? [[id, issue]] : [];
  }));
  const missingIssueIds = issueIds.filter((id) => !issues.has(id));
  for (const [id, issue] of await mapLimit(missingIssueIds, 8, async (id2) => [id2, await collectStep(failures, "issue-get", id2, async () => record(await multica.getIssue(id2)), {})])) {
    issues.set(id, issue);
  }
  const taskUsage = taskEntries.flatMap(({ task, agent }) => {
    const issueId = text(task, ["issue_id", "issueId"]) ?? text(record(task.issue), ["id"]);
    return taskUsageRows(task, agent, projects, issueId ? issues.get(issueId) ?? {} : {}, runtimeNames);
  });
  const today = (/* @__PURE__ */ new Date()).toISOString().slice(0, 10);
  const cutoff = new Date(Date.now() - (days - 1) * 864e5).toISOString().slice(0, 10);
  const recentIssues = [...issues.values()].filter((issue) => {
    const activityDate = date(issueActivityTimestamp(issue));
    return activityDate !== void 0 && activityDate >= cutoff && activityDate <= today;
  });
  const executorTokens = new Map();
  for (const row of taskUsage) {
    if (!row.issueId || !row.agentId) continue;
    const perAgent = executorTokens.get(row.issueId) ?? new Map();
    perAgent.set(row.agentId, (perAgent.get(row.agentId) ?? 0) + total(row));
    executorTokens.set(row.issueId, perAgent);
  }
  const issueExecutors = new Map([...executorTokens].map(([issueId, perAgent]) => {
    let best;
    for (const [agentId, agentTokens] of perAgent) {
      if (!best || agentTokens > best.tokens) best = { agentId, tokens: agentTokens };
    }
    return [issueId, best];
  }));
  const matchers = autopilotMatchers(autopilotList);
  const issueFetches = (await mapLimit(recentIssues, 6, async (issue) => {
    const issueId = text(issue, ["id", "issue_id", "issueId"]);
    if (!issueId) return void 0;
    const usage = await collectStep(failures, "issue-usage", issueId, () => multica.getIssueUsage(issueId), void 0);
    if (usage === void 0) return void 0;
    const runPayload = await collectStep(failures, "issue-runs", issueId, () => multica.getIssueRuns(issueId), void 0);
    if (runPayload === void 0) return void 0;
    const runs = rows(runPayload, ["runs", "items"]);
    return { issue, usage, runs };
  })).filter((entry) => entry !== void 0);
  const memberDir = new Map();
  for (const { runs } of issueFetches) {
    for (const run of runs) {
      const attribution = record(run.attribution);
      for (const key of ["initiator", "originator"]) {
        const person = record(attribution[key]);
        const id = text(person, ["id"]);
        if (id && !memberDir.has(id)) memberDir.set(id, { name: text(person, ["name"]), email: text(person, ["email"]) });
      }
    }
  }
  const issueUsage = issueFetches.map(({ issue, usage, runs }) => issueUsageRow(issue, usage, projects, agentNames, runs, { executors: issueExecutors, matchers, memberDir })).filter((row) => row !== void 0);
  const finalWindow = usageQueryWindow(days);
  if (finalWindow.startDate !== queryWindow.startDate || finalWindow.endDate !== queryWindow.endDate)
    throw new Error("Multica 查询跨越 UTC/北京时间日期边界；拒绝提交不一致的 V2 快照，请重试");
  const snapshot = {
    schemaVersion: 2,
    snapshotId: randomUUID(),
    collectedAt: (/* @__PURE__ */ new Date()).toISOString(),
    queryWindow,
    collectionScope,
    runtimeUsage,
    taskUsage,
    issueUsage,
    runtimes: runtimeRegistry,
    skippedOffline,
    failures
  };
  snapshot.expectedRows = expectedRows(snapshot);
  assertUniqueKeys(snapshot);
  return snapshot;
}
function requiredValue(argv, index, option) {
  const value = argv[index + 1];
  if (!value || value.startsWith("--")) throw new Error(`${option} 需要参数值`);
  if (!value.trim()) throw new Error(`${option} 不能为空`);
  return value;
}
function positiveInteger(value, fallback, name) {
  if (value === void 0) return fallback;
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) throw new Error(`${name} 必须是正整数`);
  return parsed;
}
function parseWorkspaceUsageArguments(argv, environment = process.env) {
  let daysValue;
  let dashboardUrl;
  let secretFile;
  let snapshotPath;
  for (let index = 0; index < argv.length; index += 1) {
    const option = argv[index];
    const value = requiredValue(argv, index, option);
    index += 1;
    if (option === "--days") daysValue = value;
    else if (option === "--dashboard-url") dashboardUrl = value;
    else if (option === "--secret-file") secretFile = value;
    else if (option === "--snapshot-path") snapshotPath = value;
    else throw new Error(`未知参数：${option}`);
  }
  const days = Number(daysValue ?? environment.USAGE_LOOKBACK_DAYS ?? 2);
  if (!Number.isInteger(days) || days < 1 || days > 365) throw new Error("--days 必须是 1 到 365 的整数");
  return {
    days,
    dashboardUrl: dashboardUrl ?? environment.COST_DASHBOARD_URL,
    secretFile: secretFile ?? environment.INGEST_SECRET_FILE,
    snapshotPath: snapshotPath ?? environment.USAGE_SNAPSHOT_PATH ?? resolve(homedir(), ".local/share/mulitca-cost-dashboard/usage.json"),
    maxPayloadBytes: positiveInteger(
      environment.MAX_PAYLOAD_BYTES,
      DEFAULT_COLLECTOR_BODY_LIMIT_BYTES,
      "MAX_PAYLOAD_BYTES"
    )
  };
}
async function writeWorkspaceUsageSnapshot(snapshotPath, snapshot) {
  await mkdir(dirname(snapshotPath), { recursive: true });
  const temporary = `${snapshotPath}.${process.pid}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(snapshot)}
`, { mode: 384, flag: "wx" });
    await rename(temporary, snapshotPath);
  } finally {
    await unlink(temporary).catch((error) => {
      if (error.code !== "ENOENT") throw error;
    });
  }
}
export { collectWorkspaceUsage, parseWorkspaceUsageArguments, writeWorkspaceUsageSnapshot };
