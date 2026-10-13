import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
import { createCureProviderFromEnv } from './cure-provider.mjs';

let input = '';
for await (const chunk of process.stdin) input += chunk;
const config = JSON.parse(input);
const provider = createCureProviderFromEnv({
  AI_SERVER_BASE_URL: config.origin, DUNDEUNI_AI_SERVICE_TOKEN: 'MOCK_ONLY_NOT_A_SECRET',
});
const result = await provider.analyze({
  buffer: await readFile(config.path), mimetype: config.mime, originalname: 'functional-test.png',
});
if (config.expectedScore !== undefined) assert.equal(result.aiGenerationScore, config.expectedScore);
assert.ok(Number.isInteger(result.aiGenerationScore));
assert.ok(result.aiGenerationScore >= 0 && result.aiGenerationScore <= 100);
assert.ok(result.modelVersion.startsWith('CuRe-'));
assert.ok(result.reasons.length >= 1);
console.log(JSON.stringify(result));
