/** Matches BE PR#4 ImageAnalysisProvider.analyze(file), without Nest dependencies. */
import { createHash, randomUUID } from 'node:crypto';

/** Reads both names found in the BE repository; contradictory URLs fail early. */
export function createCureProviderFromEnv(env = process.env) {
  const base = env.AI_SERVER_BASE_URL?.trim();
  const railway = env.AI_API_URL?.trim();
  if (base && railway && new URL(base).href !== new URL(railway).href) {
    throw new Error('Conflicting AI service URLs');
  }
  return new CureImageAnalysisProvider({
    origin: base || railway,
    token: env.DUNDEUNI_AI_SERVICE_TOKEN,
    timeoutMs: env.AI_HTTP_TIMEOUT_MS === undefined ? 130000 : Number(env.AI_HTTP_TIMEOUT_MS),
  });
}

export class CureImageAnalysisProvider {
  constructor({ origin, token, timeoutMs = 130000 }) {
    const url = new URL(origin);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password ||
        url.search || url.hash || url.pathname !== '/' ||
        typeof token !== 'string' || !token.trim() || /[\r\n]/.test(token) ||
        !Number.isSafeInteger(timeoutMs) || timeoutMs <= 5000) {
      throw new Error('Invalid AI service configuration');
    }
    this.origin = url.origin;
    this.token = token;
    this.timeoutMs = timeoutMs;
  }

  async analyze(file, context = {}) {
    if (!Buffer.isBuffer(file?.buffer) || file.buffer.length === 0 ||
        file.buffer.length > 10 * 1024 * 1024 ||
        !['image/png', 'image/jpeg'].includes(file.mimetype)) {
      throw new Error('Invalid CuRe input file');
    }
    const requestId = randomUUID();
    // PR#4 passes file only. BE can pass its DB analysisId via context after wiring.
    const analysisId = context.analysisId ?? randomUUID();
    const elementId = context.elementId ?? randomUUID();
    const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
    if (!uuid.test(analysisId) || !uuid.test(elementId) ||
        !['IMAGE', 'SCREEN_CROP'].includes(context.sourceType ?? 'IMAGE')) {
      throw new Error('Invalid CuRe analysis context');
    }
    // BE clears file.buffer after analyze resolves. Hash exactly the bytes sent,
    // not BE requestHash (which additionally includes IMAGE and MIME prefixes).
    const hash = createHash('sha256').update(file.buffer).digest('hex');
    const form = new FormData();
    form.set('file', new Blob([file.buffer], { type: file.mimetype }), file.originalname);
    form.set('analysisId', analysisId);
    form.set('elementId', elementId);
    form.set('sourceType', context.sourceType ?? 'IMAGE');
    form.set('models', 'GENERATION');
    form.set('deadlineAt', new Date(Date.now() + this.timeoutMs - 5000).toISOString());
    const response = await fetch(this.origin + '/internal/v1/image-analyses', {
      method: 'POST', body: form,
      headers: { Authorization: `Bearer ${this.token}`, 'X-Request-ID': requestId },
      signal: AbortSignal.timeout(this.timeoutMs),
    });
    if (!response.ok) throw new Error('AI transport failed');
    const body = await response.json();
    const result = body.generation;
    const validText = values => Array.isArray(values) && values.every(v => typeof v === 'string');
    if (body.contractVersion !== '1.0' || body.requestId !== requestId ||
        body.analysisId !== analysisId || body.elementId !== elementId ||
        body.sourceType !== (context.sourceType ?? 'IMAGE') ||
        body.analysisImage?.inputSha256 !== hash || body.status !== 'COMPLETED' ||
        JSON.stringify(body.requestedModels) !== '["generation"]' ||
        body.manipulation !== null || result?.status !== 'SUCCEEDED' ||
        result.modelName !== 'CuRe' || !Number.isInteger(result.displayScore) ||
        result.displayScore < 0 || result.displayScore > 100 ||
        !Number.isFinite(result.rawScore?.score) || result.rawScore.score < 0 ||
        result.rawScore.score > 1 ||
        Math.floor(result.rawScore.score * 100 + 0.5) !== result.displayScore ||
        result.localization !== null ||
        !['AI_GENERATED_SUSPECTED', 'NO_CLEAR_GENERATION_SIGNAL'].includes(result.decision) ||
        typeof result.modelVersion !== 'string' || !result.modelVersion.trim() ||
        typeof result.policyVersion !== 'string' || !result.policyVersion.trim() ||
        !validText(result.reasons) || !validText(result.limitations) ||
        result.error !== null || result.errorCode !== null) {
      throw new Error('Invalid or inconclusive CuRe result');
    }
    return {
      aiGenerationScore: result.displayScore,
      aiRiskLevel: result.decision,
      reasons: [...result.reasons, ...result.limitations].map(description => ({ description })),
      modelVersion: result.modelVersion,
    };
  }
}
