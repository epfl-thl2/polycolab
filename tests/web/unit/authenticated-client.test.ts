import { expect, it } from 'vitest';
import { result } from '../../../src/web/src/lib/authenticated-client';
import { explain } from '../../../src/web/src/svelte-lib/context';

it('preserves normalized generated-client error codes for actionable presentation', async () => {
  const failure = result(
    Promise.resolve({
      error: {
        error: {
          code: 'artifact_digest_mismatch',
          request_id: 'request-a',
        },
      },
      response: new Response(null, { status: 422 }),
    }),
  );

  await expect(failure).rejects.toMatchObject({
    status: 422,
    code: 'artifact_digest_mismatch',
  });
  await expect(failure).rejects.not.toHaveProperty('requestId');
});

it('turns normalized conflicts and artifact failures into bounded recovery guidance', () => {
  expect(explain({ status: 409, code: 'conflict' })).toContain('saved state or access changed');
  expect(explain({ status: 422, code: 'artifact_size_limit' })).toContain('smaller file');
  expect(explain({ status: 503, code: 'artifact_storage_unavailable' })).toContain(
    'temporarily unavailable',
  );
  expect(explain({ status: 503, code: 'credential_unavailable' })).toContain('secure key service');
  expect(explain({ status: 422, code: 'provider_rejected' })).toContain(
    'provider rejected validation',
  );
});
