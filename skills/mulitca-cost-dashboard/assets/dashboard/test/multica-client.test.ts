import { expect, it } from 'vitest';
import { CliRunner } from '../scripts/multica-client.mjs';

it('reports a missing CLI executable with a recovery hint once', async () => {
  const messages: string[] = [];
  const runner = new CliRunner({ logger: { error: (message: string) => messages.push(message) } });
  await expect(runner.run('/nonexistent-multica-validation/bin/multica', [])).rejects.toThrow(/ENOENT.*MULTICA_BIN and PATH/);
  await new Promise((resolve) => setImmediate(resolve));
  expect(messages).toHaveLength(1);
});
