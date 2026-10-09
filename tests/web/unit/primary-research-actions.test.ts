import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';

import PrimaryResearchActions from '../../../src/web/src/ui/PrimaryResearchActions.svelte';

afterEach(cleanup);

it('offers the three primary research starts', async () => {
  const onSelect = vi.fn();
  render(PrimaryResearchActions, { props: { available: true, onSelect } });

  const buttons = screen.getAllByRole('button');
  expect(buttons).toHaveLength(3);
  for (const label of ['State a problem or claim', 'Record an attempt', 'Write a proof sketch'])
    expect(
      (screen.getByRole('button', { name: new RegExp(label) }) as HTMLButtonElement).disabled,
    ).toBe(false);

  await fireEvent.click(screen.getByRole('button', { name: /Record an attempt/ }));
  expect(onSelect).toHaveBeenCalledWith('ATTEMPT');
});

it('disables starts while another creation form is open', () => {
  render(PrimaryResearchActions, { props: { available: false, onSelect: vi.fn() } });

  for (const button of screen.getAllByRole('button'))
    expect((button as HTMLButtonElement).disabled).toBe(true);
  expect(screen.queryByRole('status')).toBeNull();
});
