import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/svelte';
import CorrectionReview from '../../../src/web/src/ui/CorrectionReview.svelte';
import { contextKey } from '../../../src/web/src/svelte-lib/context';
import { claimVersion } from './version-fixtures';

afterEach(cleanup);

it('links an accepted correction to its exact decided object version', async () => {
  const decision = vi.fn().mockResolvedValue({
    suggestion_object_version_id: 'suggestion-version',
    decided_object_version_id: 'accepted-version',
    action: 'ACCEPT',
    reason: 'Clarified the assumptions',
  });
  const record = claimVersion({
    id: 'suggestion-version',
    kind: 'NOTE',
    catalogue: {
      entry_id: null,
      source: null,
      reported_status: null,
      suggestion: {
        expected_current_object_version_id: 'base-version',
        title: 'Corrected statement',
        content_md: 'Formulation',
        assumptions_md: 'Finite graphs',
        reported_status: 'Open',
        review_rationale: 'Checked the formulation',
        reason: 'Clarify',
      },
    },
  });
  render(CorrectionReview, {
    props: { record },
    context: new Map([[contextKey, { records: { decision }, auth: { signedIn: false } }]]),
  });
  const link = await screen.findByRole('link', { name: 'Accepted exact version' });
  expect(link.getAttribute('href')).toBe('/commons/records/accepted-version');
  expect(decision).toHaveBeenCalledWith('suggestion-version');
});
