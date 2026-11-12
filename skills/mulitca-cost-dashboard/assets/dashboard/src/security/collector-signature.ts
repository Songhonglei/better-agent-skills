import { createHash, createHmac, randomUUID, timingSafeEqual } from 'node:crypto';

export const collectorTimestampHeader = 'x-collector-timestamp';
export const collectorNonceHeader = 'x-collector-nonce';
export const collectorSignatureHeader = 'x-collector-signature';

export interface CollectorNonceStore {
  claim(nonce: string, expiresAt: Date): Promise<boolean>;
}

function stableJson(value: unknown): string {
  if (value === undefined) return '';
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record).sort().filter((key) => record[key] !== undefined).map((key) => (
    `${JSON.stringify(key)}:${stableJson(record[key])}`
  )).join(',')}}`;
}

export function serializeCollectorBody(body: unknown): string | undefined {
  return body === undefined ? undefined : stableJson(body);
}

export function hashCollectorPayload(body: unknown): string {
  return createHash('sha256').update(serializeCollectorBody(body) ?? '').digest('hex');
}

function canonicalRequest(input: {
  timestamp: string;
  nonce: string;
  method: string;
  path: string;
  body: unknown;
}): string {
  return [input.timestamp, input.nonce, input.method.toUpperCase(), input.path, hashCollectorPayload(input.body)].join('\n');
}

function signature(secret: string, request: Parameters<typeof canonicalRequest>[0]): string {
  return createHmac('sha256', secret).update(canonicalRequest(request)).digest('hex');
}

export type CollectorSignatureHeaders = Record<
  typeof collectorTimestampHeader | typeof collectorNonceHeader | typeof collectorSignatureHeader,
  string
>;

export function signCollectorRequest(input: {
  secret: string;
  method: string;
  path: string;
  body?: unknown;
  timestamp?: string;
  nonce?: string;
}): CollectorSignatureHeaders {
  const timestamp = input.timestamp ?? String(Date.now());
  const nonce = input.nonce ?? randomUUID();
  return {
    [collectorTimestampHeader]: timestamp,
    [collectorNonceHeader]: nonce,
    [collectorSignatureHeader]: signature(input.secret, {
      timestamp,
      nonce,
      method: input.method,
      path: input.path,
      body: input.body,
    }),
  };
}

function header(headers: Record<string, string | string[] | undefined>, name: string): string {
  const value = headers[name] ?? headers[name.toLocaleLowerCase()];
  if (typeof value !== 'string' || !value) throw new Error(`缺少 ${name}`);
  return value;
}

export async function verifyCollectorRequest(input: {
  secret: string;
  method: string;
  path: string;
  body?: unknown;
  headers: Record<string, string | string[] | undefined>;
  nonces: CollectorNonceStore;
  now?: () => Date;
  maxSkewMs?: number;
}): Promise<void> {
  const timestamp = header(input.headers, collectorTimestampHeader);
  const nonce = header(input.headers, collectorNonceHeader);
  const actual = header(input.headers, collectorSignatureHeader);
  const timestampMs = Number(timestamp);
  const now = (input.now ?? (() => new Date()))();
  const maxSkewMs = input.maxSkewMs ?? 5 * 60 * 1000;
  if (!Number.isSafeInteger(timestampMs) || Math.abs(now.getTime() - timestampMs) > maxSkewMs) {
    throw new Error('采集请求已过期');
  }
  const expected = signature(input.secret, {
    timestamp,
    nonce,
    method: input.method,
    path: input.path,
    body: input.body,
  });
  const expectedBuffer = Buffer.from(expected, 'hex');
  const actualBuffer = /^[a-f0-9]{64}$/i.test(actual) ? Buffer.from(actual, 'hex') : Buffer.alloc(0);
  if (expectedBuffer.length !== actualBuffer.length || !timingSafeEqual(expectedBuffer, actualBuffer)) {
    throw new Error('采集请求签名无效');
  }
  const claimed = await input.nonces.claim(nonce, new Date(timestampMs + maxSkewMs));
  if (!claimed) throw new Error('检测到重复采集请求');
}
