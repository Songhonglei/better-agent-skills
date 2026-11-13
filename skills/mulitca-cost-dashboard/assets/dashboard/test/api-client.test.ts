import { afterEach, expect, it, vi } from 'vitest';
import { api } from '../web/src/api/client.js';

afterEach(() => vi.unstubAllGlobals());

it('gives a recovery hint when the dashboard connection fails', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
  await expect(api.expenses({ start: '2026-11-11', end: '2026-11-12', granularity: 'day' }))
    .rejects.toThrow('无法连接大盘，请检查服务和网络后重试');
});
