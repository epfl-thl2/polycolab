import { afterEach, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import ProofStructureFields from '../../../web/src/ui/ProofStructureFields.svelte';

afterEach(cleanup);

it('builds an ordered exact premise set and rejects duplicates and self-dependency', async () => {
  render(ProofStructureFields, {
    props: { conclusionRevisionId: 'claim-r3', premiseRevisionIds: [] },
  });

  const premise = screen.getByLabelText('Exact premise version ID');
  const add = screen.getByRole('button', { name: 'Add premise' });
  await fireEvent.input(premise, { target: { value: 'lemma-r1' } });
  await fireEvent.click(add);
  expect(screen.getByText('lemma-r1')).toBeTruthy();

  await fireEvent.input(premise, { target: { value: 'lemma-r1' } });
  await fireEvent.click(add);
  expect(screen.getByRole('alert').textContent).toContain('already included');
  expect(screen.getAllByText('lemma-r1')).toHaveLength(1);

  await fireEvent.input(premise, { target: { value: 'claim-r3' } });
  await fireEvent.click(add);
  expect(screen.getByRole('alert').textContent).toContain('cannot also be its own premise');
});

it('keeps research attempts outside the proof-sketch dependency structure', () => {
  render(ProofStructureFields, {
    props: { conclusionRevisionId: 'claim-r3', premiseRevisionIds: [] },
  });

  expect(screen.getByText(/separate stable proof sketch/)).toBeTruthy();
  expect(screen.getByText(/Research attempts do not belong/)).toBeTruthy();
});

it('offers a specifically named keyboard-operable removal control', async () => {
  render(ProofStructureFields, {
    props: { conclusionRevisionId: 'claim-r3', premiseRevisionIds: ['lemma-r1'] },
  });

  await fireEvent.click(screen.getByRole('button', { name: 'Remove premise lemma-r1' }));
  expect(screen.queryByText('lemma-r1')).toBeNull();
  expect(screen.getByText(/Add at least one exact premise version/)).toBeTruthy();
});
