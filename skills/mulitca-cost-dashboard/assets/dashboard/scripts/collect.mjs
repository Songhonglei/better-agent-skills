import { randomUUID } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import { readSecret } from '../dist/config.js';
import { serializeCollectorBody, signCollectorRequest } from '../dist/security/collector-signature.js';
import { collectWorkspaceUsage, parseWorkspaceUsageArguments, writeWorkspaceUsageSnapshot } from './collector.mjs';
import { MulticaClient, CliRunner } from './multica-client.mjs';
import { assertCommittedReceipt, makeChunk, splitSnapshot } from './usage-v2-protocol.mjs';

export async function uploadSnapshot(snapshot, options) {
  let budget = Math.min(8 * 1024 * 1024, Math.floor(options.maxPayloadBytes / 2));
  const secret = readSecret(options.secretFile);
  const base = new URL(options.dashboardUrl);
  if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password || base.pathname !== '/' || base.search || base.hash) {
    throw new Error('COST_DASHBOARD_URL must be an HTTP(S) origin, for example http://127.0.0.1:4318/');
  }
  if (base.protocol !== 'https:' && !['localhost', '127.0.0.1', '[::1]'].includes(base.hostname)) {
    throw new Error('Use HTTPS for a remote dashboard or connect through an SSH tunnel');
  }
  while (true) {
    const chunks = splitSnapshot(snapshot, budget);
    const uploadId = randomUUID();
    let receipt;
    let oversized = false;
    for (let index = 0; index < chunks.length; index += 1) {
      const body = makeChunk(snapshot, uploadId, index, chunks.length, chunks[index]);
      const path = '/api/collector/usage-snapshots';
      const response = await fetch(new URL(path, base), {
        method: 'POST',
        headers: { 'content-type': 'application/json', ...signCollectorRequest({ secret, method: 'POST', path, body }) },
        body: serializeCollectorBody(body),
        signal: AbortSignal.timeout(180000),
        redirect: 'error',
      });
      if (response.status === 413) { oversized = true; break; }
      if (!response.ok) throw new Error(`Upload failed (HTTP ${response.status}). Check the dashboard URL, secret, server clock and database.`);
      receipt = await response.json();
      console.log(`Uploaded chunk ${index + 1}/${chunks.length}`);
    }
    if (!oversized) {
      assertCommittedReceipt(receipt, snapshot);
      return receipt;
    }
    if (budget <= 262144) throw new Error('Upload exceeds body limit at 256 KiB. Increase MAX_PAYLOAD_BYTES on the dashboard.');
    budget = Math.max(262144, Math.floor(budget / 2));
  }
}

async function main() {
  if (process.argv.includes('--help')) {
    console.log('npm run collect -- [--days 1..365] [--dashboard-url URL] [--secret-file PATH] [--snapshot-path PATH]');
    return;
  }
  const options = parseWorkspaceUsageArguments(process.argv.slice(2));
  if (!options.dashboardUrl || !options.secretFile) throw new Error('Set COST_DASHBOARD_URL and INGEST_SECRET_FILE in .env');
  readSecret(options.secretFile);
  const config = { multica: { bin: process.env.MULTICA_BIN || 'multica', profile: process.env.MULTICA_PROFILE || undefined } };
  console.log(`Collecting Workspace usage for ${options.days} days`);
  const snapshot = await collectWorkspaceUsage(new MulticaClient(config, new CliRunner({ timeoutMs: 180000 })), options.days);
  await writeWorkspaceUsageSnapshot(options.snapshotPath, snapshot);
  const receipt = await uploadSnapshot(snapshot, options);
  console.log(`Committed usage snapshot. Runtimes=${receipt.runtimeRows} tasks=${receipt.taskRows} issues=${receipt.issueRows} failures=${receipt.failureCount}`);
  if (snapshot.failures.length) {
    for (const failure of snapshot.failures) console.error(`Partial collection failure at ${failure.stage}. Check Multica access and rerun collection.`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : 'Collection failed');
    process.exitCode = 1;
  });
}
