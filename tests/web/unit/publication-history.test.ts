import { afterEach, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/svelte';
import PublicationHistory from '../../../web/src/ui/PublicationHistory.svelte';

afterEach(cleanup);

it('shows immutable exact releases without implying admission or later-edit publication', () => {
  render(PublicationHistory, {
    props: {
      manifests: [
        {
          publicationId: 'publication-1',
          digest: 'sha256:manifest',
          publishedAt: '2026-09-07',
          publisher: 'Ada',
          publicHref: '/commons/releases/publication-1',
          members: [
            {
              id: 'proof-r2',
              kind: 'PROOF',
              revisionId: 'proof-r2',
              title: 'Inductive route',
              href: '/commons/records/proof-r2',
              inclusion: 'SELECTED',
            },
          ],
        },
      ],
    },
  });

  expect(screen.getByRole('link', { name: 'Release publication-1' })).toBeTruthy();
  expect(screen.getByText(/Exact manifest digest sha256:manifest/)).toBeTruthy();
  expect(screen.getByText(/Later private versions remain private/)).toBeTruthy();
  expect(screen.getByText(/does not imply catalogue admission/)).toBeTruthy();
});
