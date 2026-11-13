export class MulticaClient {
  constructor(config, runner) {
    this.config = config;
    this.runner = runner;
  }
  async listProjects(signal) {
    const payload = await this.runJson(["project", "list"], signal);
    if (Array.isArray(payload)) return payload;
    if (Array.isArray(payload.projects)) return payload.projects;
    throw new Error("Multica project list returned an unexpected JSON shape");
  }
  async listWorkspaceIssues(signal) {
    return this.listIssues(void 0, signal);
  }
  async listIssues(projectId, signal) {
    const issues = [];
    let offset = 0;
    let total2 = Number.POSITIVE_INFINITY;
    while (offset < total2) {
      const response = await this.runJson([
        "issue",
        "list",
        ...projectId ? ["--project", projectId] : [],
        "--limit",
        "100",
        "--offset",
        String(offset),
        "--sort",
        "created_at",
        "--direction",
        "asc"
      ], signal);
      const page = response.issues;
      if (!Array.isArray(page)) {
        throw new Error("Multica issue list returned an unexpected JSON shape");
      }
      issues.push(...page);
      total2 = response.total ?? issues.length;
      offset += page.length;
      if (page.length === 0) break;
    }
    return issues;
  }
  async getIssue(issueId, signal) {
    return this.runJson(["issue", "get", issueId], signal);
  }
  async getIssueRuns(issueId, signal) {
    const payload = await this.runJson(["issue", "runs", issueId], signal);
    return Array.isArray(payload) ? payload : payload.runs ?? [];
  }
  async getIssueUsage(issueId, signal) {
    return this.runJson(["issue", "usage", issueId], signal);
  }
  async listAgents(signal) {
    return this.listEntity("agent", "list", signal);
  }
  async listRuntimes(signal) {
    return this.listEntity("runtime", "list", signal);
  }
  async listAutopilots(signal) {
    return this.listEntity("autopilot", "list", signal);
  }
  async getRuntimeUsage(runtimeId, signal, days) {
    return this.runJson(["runtime", "usage", runtimeId, ...days ? ["--days", String(days)] : []], signal);
  }
  async getAgent(agentId, signal) {
    return this.runJson(["agent", "get", agentId], signal);
  }
  async getAgentTasks(agentId, signal) {
    return this.runJson(["agent", "tasks", agentId], signal);
  }
  async listEntity(entity, operation, signal) {
    const payload = await this.runJson([entity, operation], signal);
    if (Array.isArray(payload)) return payload;
    const rows2 = payload[`${entity}s`];
    return Array.isArray(rows2) ? rows2 : [];
  }
  async runJson(command, signal) {
    const result = await this.runner.run(
      this.config.multica.bin,
      [...command, ...(this.config.multica.profile ? ["--profile", this.config.multica.profile] : []), "--output", "json"],
      {},
      { signal }
    );
    try {
      const value = JSON.parse(result.stdout);
      if (Array.isArray(value) || value !== null && typeof value === "object") return value;
    } catch {
    }
    throw new Error(`Multica returned malformed JSON for ${command.slice(0, 2).join(" ")}`);
  }
};

import { spawn } from "node:child_process";
class CliCommandError extends Error {
  constructor(message, stdout = "", stderr = "", exitCode) {
    super(message);
    this.stdout = stdout;
    this.stderr = stderr;
    this.exitCode = exitCode;
    this.name = "CliCommandError";
  }
};
export class CliRunner {
  timeoutMs;
  logger;
  constructor(options = {}) {
    this.timeoutMs = options.timeoutMs ?? 12e4;
    this.logger = options.logger ?? console;
  }
  async run(command, args, environment = {}, options = {}) {
    return new Promise((resolve3, reject) => {
      if (options.signal?.aborted) {
        reject(newAbortError());
        return;
      }
      const child = spawn(command, args, {
        cwd: process.cwd(),
        env: { ...process.env, ...environment },
        shell: false,
        stdio: ["ignore", "pipe", "pipe"]
      });
      const stdout = [];
      const stderr = [];
      let settled = false;
      const finish = (callback) => {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        options.signal?.removeEventListener("abort", onAbort);
        callback();
      };
      const onAbort = () => {
        child.kill("SIGTERM");
        const forceKill = setTimeout(() => child.kill("SIGKILL"), 5e3);
        forceKill.unref();
        finish(() => reject(newAbortError()));
      };
      const timeout = setTimeout(() => {
        child.kill("SIGTERM");
        const forceKill = setTimeout(() => child.kill("SIGKILL"), 5000);
        forceKill.unref();
        const message = `CLI command timed out after ${this.timeoutMs}ms`;
        this.logger.error(message);
        finish(() => reject(new CliCommandError(message, Buffer.concat(stdout).toString("utf8"), Buffer.concat(stderr).toString("utf8"))));
      }, this.timeoutMs);
      options.signal?.addEventListener("abort", onAbort, { once: true });
      child.stdout.on("data", (chunk) => stdout.push(chunk));
      child.stderr.on("data", (chunk) => stderr.push(chunk));
      child.once("error", (error) => {
        const message = `CLI command could not be started (${command}: ${error.code ?? "unknown error"}). Check MULTICA_BIN and PATH.`;
        this.logger.error(message);
        finish(() => reject(new CliCommandError(message)));
      });
      child.once("close", (exitCode) => {
        if (settled) return;
        const result = {
          stdout: Buffer.concat(stdout).toString("utf8"),
          stderr: Buffer.concat(stderr).toString("utf8"),
          exitCode: exitCode ?? 1
        };
        if (result.exitCode === 0) {
          finish(() => resolve3(result));
          return;
        }
        const message = `CLI command failed with exit code ${result.exitCode}`;
        const diagnostic = `${result.stderr || result.stdout || ""}`.trim();
        this.logger.error(diagnostic ? `${message}: ${diagnostic.slice(0, 500)}` : message);
        finish(() => reject(new CliCommandError(message, result.stdout, result.stderr, result.exitCode)));
      });
    });
  }
};
function newAbortError() {
  const error = new Error("CLI command aborted");
  error.name = "AbortError";
  return error;
}
