import { test } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { createHash } from 'node:crypto';
import { CureImageAnalysisProvider, createCureProviderFromEnv } from './cure-provider.mjs';

test('current BE provider mapping, request IDs and input hash validation', async () => {
  const bytes = Buffer.from('contract-test-only');
  let mutate = value => value;
  const server = http.createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    const body = Buffer.concat(chunks).toString();
    const field = name => body.match(new RegExp(`name="${name}"\\r\\n\\r\\n([^\\r]+)`))[1];
    assert.equal(field('models'), 'GENERATION');
    assert.equal(request.headers.authorization, 'Bearer TEST_NOT_A_SECRET');
    response.setHeader('content-type', 'application/json');
    response.end(JSON.stringify(mutate({
      contractVersion: '1.0', requestId: request.headers['x-request-id'],
      analysisId: field('analysisId'), elementId: field('elementId'), sourceType: 'IMAGE',
      analysisImage: { inputSha256: createHash('sha256').update(bytes).digest('hex') },
      requestedModels: ['generation'], status: 'COMPLETED', manipulation: null,
      generation: { status: 'SUCCEEDED', modelName: 'CuRe', displayScore: 80,
        rawScore: { score: 0.8 }, policyVersion: 'TEST-policy', localization: null,
        decision: 'AI_GENERATED_SUSPECTED', modelVersion: 'TEST-CuRe',
        reasons: ['score explanation'], limitations: ['not calibrated'], errorCode: null, error: null },
    })));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const provider = new CureImageAnalysisProvider({
      origin: `http://127.0.0.1:${server.address().port}`, token: 'TEST_NOT_A_SECRET',
    });
    const file = { buffer: bytes, mimetype: 'image/png', originalname: 'test.png' };
    const context = { analysisId: '22222222-2222-4222-8222-222222222222',
      elementId: '33333333-3333-4333-8333-333333333333' };
    const result = await provider.analyze(file, context);
    assert.deepEqual(result, { aiGenerationScore: 80,
      aiRiskLevel: 'AI_GENERATED_SUSPECTED', modelVersion: 'TEST-CuRe',
      reasons: [{ description: 'score explanation' }, { description: 'not calibrated' }] });
    const mutations = [
      body => { body.analysisImage.inputSha256 = 'wrong'; },
      body => { body.analysisId = 'wrong'; },
      body => { body.requestId = 'wrong'; },
      body => { body.manipulation = {}; },
      body => { body.generation.localization = {}; },
      body => { body.generation.rawScore.score = 0.2; },
      body => { body.generation.rawScore.score = 2; },
      body => { body.generation.policyVersion = ''; },
      body => { body.status = 'FAILED'; body.generation.status = 'FAILED';
        body.generation.displayScore = null; },
      body => { body.generation.decision = 'INCONCLUSIVE';
        body.generation.displayScore = null; },
      body => { body.generation.decision = 'CAUTION'; },
    ];
    for (const change of mutations) {
      mutate = body => { change(body); return body; };
      await assert.rejects(provider.analyze(file, context), /Invalid/);
    }
  } finally {
    await new Promise(resolve => server.close(resolve));
  }
});

test('BE environment names and timeout settings fail early when inconsistent', () => {
  const token = 'TEST_NOT_A_SECRET';
  for (const name of ['AI_SERVER_BASE_URL', 'AI_API_URL']) {
    const provider = createCureProviderFromEnv({
      [name]: 'http://localhost:8765', DUNDEUNI_AI_SERVICE_TOKEN: token,
      AI_HTTP_TIMEOUT_MS: '140000',
    });
    assert.equal(provider.origin, 'http://localhost:8765');
    assert.equal(provider.timeoutMs, 140000);
  }
  assert.doesNotThrow(() => createCureProviderFromEnv({
    AI_SERVER_BASE_URL: 'http://localhost:8765', AI_API_URL: 'http://localhost:8765/',
    DUNDEUNI_AI_SERVICE_TOKEN: token,
  }));
  assert.throws(() => createCureProviderFromEnv({
    AI_SERVER_BASE_URL: 'http://localhost:8765', AI_API_URL: 'http://localhost:8000',
    DUNDEUNI_AI_SERVICE_TOKEN: token,
  }), /Conflicting/);
  assert.throws(() => createCureProviderFromEnv({ AI_SERVER_BASE_URL: 'http://localhost:8765' }));
  for (const timeoutMs of [5000, 0, -1, NaN, Infinity, 5.5, '130000']) {
    assert.throws(() => new CureImageAnalysisProvider({
      origin: 'http://localhost:8765', token, timeoutMs,
    }), /configuration/);
  }
  assert.throws(() => new CureImageAnalysisProvider({
    origin: 'http://localhost:8765/api', token,
  }), /configuration/);
});

test('invalid file or non-UUID DB context does not call the AI service', async () => {
  const provider = new CureImageAnalysisProvider({
    origin: 'http://127.0.0.1:1', token: 'TEST_NOT_A_SECRET',
  });
  const file = { buffer: Buffer.from('test'), mimetype: 'image/png', originalname: 'test.png' };
  await assert.rejects(provider.analyze(file, { analysisId: 'id-0' }), /context/);
  await assert.rejects(provider.analyze(file, { sourceType: 'SCREEN' }), /context/);
  await assert.rejects(provider.analyze({ ...file, buffer: Buffer.alloc(0) }), /input file/);
  await assert.rejects(provider.analyze({ ...file, mimetype: 'text/plain' }), /input file/);
});
