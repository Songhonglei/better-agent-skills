// TEST_DATABASE_URL=postgresql://... npm run test:integration
// Creates and removes its own randomly named schema in the selected test database.
import assert from 'node:assert/strict';
import { randomUUID, randomBytes } from 'node:crypto';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { test } from 'node:test';
import { Pool } from 'pg';
import { createApp } from '../dist/app.js';
import { createDatabase } from '../dist/db/client.js';
import { migrate } from '../dist/db/migrate.js';
import { signCollectorRequest } from '../dist/security/collector-signature.js';
import { collectWorkspaceUsage, parseWorkspaceUsageArguments } from '../scripts/collector.mjs';
import { MulticaClient } from '../scripts/multica-client.mjs';
import { uploadSnapshot } from '../scripts/collect.mjs';
import { makeChunk } from '../scripts/usage-v2-protocol.mjs';

test('self-hosted collection, authentication, pricing and atomic V2 ingestion', async (t) => {
  assert.ok(process.env.TEST_DATABASE_URL, 'Set TEST_DATABASE_URL to a test PostgreSQL database');
  const schema = `dashboard_test_${randomBytes(8).toString('hex')}`;
  const base = new Pool({ connectionString: process.env.TEST_DATABASE_URL });
  const url = new URL(process.env.TEST_DATABASE_URL);
  url.searchParams.set('options', `-c search_path=${schema}`);
  const { db, pool } = createDatabase(url.toString());
  const directory = await mkdtemp(resolve(tmpdir(), 'multica-cost-test-'));
  const secret = randomBytes(32).toString('hex');
  const secretFile = resolve(directory, 'ingest-secret');
  const admin = randomBytes(32).toString('hex');
  const authorization = `Basic ${Buffer.from(`admin:${admin}`).toString('base64')}`;
  let app;
  try {
    await base.query(`create schema "${schema}"`);
    await Promise.all([migrate(pool), migrate(pool)]);
    await writeFile(secretFile, secret, { mode: 0o600 });
    app = await createApp({ db, adminSecret: admin, ingestSecret: secret });
    const address = await app.listen({ host: '127.0.0.1', port: 0 });
    const options = { dashboardUrl: address, secretFile, maxPayloadBytes: 67108864 };
    const date = new Date().toISOString().slice(0, 10);
    const now = new Date().toISOString();
    const usage = { provider: 'example', model: 'example-model', inputTokens: 1000000, outputTokens: 500000, cacheReadTokens: 0, cacheWriteTokens: 0 };
    const commands = [];
    let failRuns = false;
    const runner = {
      async run(_bin, args) {
        commands.push(args);
        const operation = args.slice(0, 2).join(' ');
        if (failRuns && operation === 'issue runs') throw new Error('Example source failure');
        const data = {
          'runtime list': [{ id: 'runtime-1', custom_name: 'Example Runtime', status: 'offline' }],
          'runtime usage': [{ ...usage, date }],
          'agent list': [{ id: 'agent-1', name: 'Example Agent', runtime_id: 'runtime-1' }],
          'agent get': { id: 'agent-1', name: 'Example Agent', runtime_id: 'runtime-1' },
          'agent tasks': [{ id: 'task-1', issue_id: 'issue-1', completed_at: now, usage }],
          'project list': [{ id: 'project-1', name: 'Example Project' }],
          'issue list': { total: 1, issues: [{ id: 'issue-1', identifier: 'EX-1', title: 'Example Issue', updated_at: now, project_id: 'project-1' }] },
          'issue usage': { total_input_tokens: usage.inputTokens, total_output_tokens: usage.outputTokens },
          'issue runs': [{ id: 'task-1', completed_at: now, usage, attribution: { precise: true, initiator: { id: 'member-1', name: 'Example User', email: 'user@example.com' } } }],
          'autopilot list': [],
        }[operation];
        assert.notEqual(data, undefined, `Unexpected CLI command ${operation}`);
        return { stdout: JSON.stringify(data), stderr: '', exitCode: 0 };
      },
    };
    let snapshot;
    await t.test('collector uses default CLI profile and all-workspace scope', async () => {
      snapshot = await collectWorkspaceUsage(new MulticaClient({ multica: { bin: 'multica' } }, runner), 2);
      assert.equal(snapshot.failures.length, 0);
      assert.equal(snapshot.issueUsage.length, 1);
      assert.equal(snapshot.taskUsage.length, 1);
      assert.equal(snapshot.runtimeUsage.length, 1);
      assert.equal(commands.some((command) => command.includes('--profile')), false);
      assert.equal(commands.find((command) => command[0] === 'issue' && command[1] === 'list').includes('--project'), false);
      const named = new MulticaClient({ multica: { bin: 'multica', profile: 'example-profile' } }, runner);
      await named.listRuntimes();
      assert.ok(commands.at(-1).includes('example-profile'));
      assert.equal(parseWorkspaceUsageArguments(['--days', '365'], {}).days, 365);
      assert.throws(() => parseWorkspaceUsageArguments(['--days', '366'], {}));
      failRuns = true;
      const partial = await collectWorkspaceUsage(new MulticaClient({ multica: { bin: 'multica' } }, runner), 2);
      assert.equal(partial.issueUsage.length, 0);
      assert.ok(partial.failures.some((failure) => failure.stage === 'issue-runs'));
      failRuns = false;
    });
    await t.test('page and price writes require administrator authentication', async () => {
      assert.equal((await app.inject({ url: '/' })).statusCode, 401);
      assert.equal((await app.inject({ url: '/api/expenses' })).statusCode, 401);
      assert.equal((await app.inject({ method: 'PUT', url: '/api/expenses/prices', payload: {} })).statusCode, 401);
      assert.equal((await app.inject({ url: '/', headers: { authorization } })).statusCode, 200);
      assert.equal((await app.inject({ url: '/health' })).statusCode, 200);
      assert.equal((await app.inject({ url: '/assets/..%2F.env', headers: { authorization } })).statusCode, 404);
      assert.equal((await app.inject({ method: 'PUT', url: '/api/expenses/exchange-rate', headers: { authorization, origin: 'https://other.example' }, payload: { cnyPerUsd: 7 } })).statusCode, 403);
    });
    await t.test('collector commits over HTTP and same snapshot is idempotent', async () => {
      const receipt = await uploadSnapshot(snapshot, options);
      assert.equal(receipt.committed, true);
      assert.equal(receipt.issueRows, 1);
      await uploadSnapshot(snapshot, options);
      const count = await pool.query('select count(*)::int as n from expense_issue_usage');
      assert.equal(count.rows[0].n, 1);
    });
    const query = `/api/expenses?start=${date}&end=${date}`;
    async function summary() { return (await app.inject({ url: query, headers: { authorization } })).json(); }
    await t.test('Issue and Task are deduplicated and missing prices remain visible', async () => {
      const result = await summary();
      assert.equal(result.total.inputTokens, 1000000);
      assert.equal(result.total.outputTokens, 500000);
      assert.equal(result.total.costUsd, 0);
      assert.equal(result.total.unpricedTokens, 1500000);
      assert.equal(result.runtimeTokens, 1500000);
    });
    await t.test('versioned price save recalculates collected usage', async () => {
      const response = await app.inject({ method: 'PUT', url: '/api/expenses/prices', headers: { authorization }, payload: {
        provider: 'example', model: 'example-model', displayName: 'Example Model', currency: 'USD', usdExchangeRate: 1,
        inputPerMillion: 2, outputPerMillion: 4, cacheReadPerMillion: 0, cacheWritePerMillion: 0, effectiveFrom: date,
      } });
      assert.equal(response.statusCode, 200, response.body);
      assert.equal((await summary()).total.costUsd, 4);
      assert.equal((await summary()).total.unpricedTokens, 0);
      assert.equal((await app.inject({ method: 'PUT', url: '/api/expenses/exchange-rate', headers: { authorization }, payload: { cnyPerUsd: 7 } })).statusCode, 200);
    });
    async function signed(body, headers) {
      const path = '/api/collector/usage-snapshots';
      return app.inject({ method: 'POST', url: path, payload: body, headers: headers ?? signCollectorRequest({ secret, method: 'POST', path, body }) });
    }
    await t.test('invalid signatures and reused nonces are rejected', async () => {
      const body = makeChunk(snapshot, randomUUID(), 0, 1, snapshot);
      assert.equal((await app.inject({ method: 'POST', url: '/api/collector/usage-snapshots', payload: body })).statusCode, 401);
      const headers = signCollectorRequest({ secret, method: 'POST', path: '/api/collector/usage-snapshots', body });
      assert.equal((await signed(body, headers)).statusCode, 200);
      assert.equal((await signed(body, headers)).statusCode, 401);
    });
    await t.test('out-of-order chunks commit only after the whole batch arrives', async () => {
      const next = { ...snapshot, snapshotId: randomUUID(), collectedAt: new Date(Date.now() + 1000).toISOString() };
      const uploadId = randomUUID();
      const last = makeChunk(next, uploadId, 1, 2, { runtimeUsage: [], taskUsage: next.taskUsage, issueUsage: next.issueUsage });
      const first = makeChunk(next, uploadId, 0, 2, { runtimeUsage: next.runtimeUsage, taskUsage: [], issueUsage: [] });
      const pending = await signed(last);
      assert.equal(pending.statusCode, 200, pending.body);
      assert.equal(pending.json().committed, false);
      const committed = await signed(first);
      assert.equal(committed.statusCode, 200, committed.body);
      assert.equal(committed.json().committed, true);
      assert.equal((await summary()).total.costUsd, 4);
    });
    await t.test('failed runtime retains historical rows and stale snapshots cannot overwrite', async () => {
      const partial = { ...snapshot, snapshotId: randomUUID(), collectedAt: new Date(Date.now() + 2000).toISOString(),
        runtimeUsage: [], expectedRows: { ...snapshot.expectedRows, runtime: 0 },
        collectionScope: { ...snapshot.collectionScope, successfulRuntimeIds: [], failedRuntimeIds: ['runtime-1'] },
        failures: [{ stage: 'runtime-usage', entityId: 'runtime-1', message: 'Example failure' }],
      };
      const response = await signed(makeChunk(partial, randomUUID(), 0, 1, partial));
      assert.equal(response.statusCode, 200, response.body);
      assert.equal((await summary()).runtimeTokens, 1500000);
      const stale = { ...snapshot, snapshotId: randomUUID() };
      assert.equal((await signed(makeChunk(stale, randomUUID(), 0, 1, stale))).statusCode, 409);
    });
    await t.test('successful zero-use runtime window clears previously stored runtime rows', async () => {
      const zero = { ...snapshot, snapshotId: randomUUID(), collectedAt: new Date(Date.now() + 3000).toISOString(),
        runtimeUsage: [], expectedRows: { ...snapshot.expectedRows, runtime: 0 },
      };
      const response = await signed(makeChunk(zero, randomUUID(), 0, 1, zero));
      assert.equal(response.statusCode, 200, response.body);
      assert.equal((await summary()).runtimeTokens, 0);
      assert.equal((await summary()).total.costUsd, 4);
    });
  } finally {
    if (app) await app.close();
    await pool.end();
    await base.query(`drop schema if exists "${schema}" cascade`);
    await base.end();
    await rm(directory, { recursive: true, force: true });
  }
});
