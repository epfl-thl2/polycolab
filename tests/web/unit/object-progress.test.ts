import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import ObjectProgress from '../../../web/src/ui/ObjectProgress.svelte';
import { contextKey } from '../../../web/src/svelte-lib/context';
import { claimVersion, proofVersion } from './version-fixtures';

afterEach(cleanup);

function setup(version = proofVersion(), canWrite = true) {
  const createVersion = vi.fn().mockResolvedValue({ current_object_version: version });
  const onsaved = vi.fn();
  render(ObjectProgress, {
    props: { version, projectId: 'workspace', canWrite, onsaved },
    context: new Map([
      [
        contextKey,
        {
          api: { createVersion },
          query: { setQueryData: vi.fn(), invalidateQueries: vi.fn().mockResolvedValue(undefined) },
        },
      ],
    ]),
  });
  return { createVersion, onsaved };
}

it('saves proof progress as a new version preserving content and exact pins', async () => {
  const version = proofVersion();
  const { createVersion, onsaved } = setup(version);
  expect(
    (screen.getByRole('button', { name: 'Report progress' }) as HTMLButtonElement).disabled,
  ).toBe(true);
  await fireEvent.change(screen.getByRole('combobox'), { target: { value: 'PARTIAL' } });
  await fireEvent.click(screen.getByRole('button', { name: 'Report progress' }));
  await waitFor(() => expect(onsaved).toHaveBeenCalled());
  const [objectId, write] = createVersion.mock.calls[0];
  expect(objectId).toBe(version.object_id);
  expect(write.expected_current_object_version_id).toBe(version.id);
  expect(write.snapshot.content).toMatchObject({
    ...version.content,
    reported_progress: 'PARTIAL',
  });
  expect(
    write.snapshot.structural_relationships.map(
      (pin: { target_object_version_id: string }) => pin.target_object_version_id,
    ),
  ).toEqual(['claim-r3', 'claim-r3']);
});

it('retains the draft and displays a conflict without overwriting a newer version', async () => {
  const { createVersion, onsaved } = setup();
  createVersion.mockRejectedValue({ status: 409 });
  await fireEvent.change(screen.getByRole('combobox'), { target: { value: 'STALLED' } });
  await fireEvent.click(screen.getByRole('button', { name: 'Report progress' }));
  expect((await screen.findByRole('alert')).textContent).toContain(
    'changed while you were editing',
  );
  expect((screen.getByRole('combobox') as HTMLSelectElement).value).toBe('STALLED');
  expect(onsaved).not.toHaveBeenCalled();
});

it('shows progress without editing controls for readers', () => {
  setup(proofVersion(), false);
  expect(screen.getByText('Reported progress: Complete')).toBeTruthy();
  expect(screen.queryByRole('combobox')).toBeNull();
});

it('allows failed progress without an explanation', async () => {
  const version = claimVersion();
  const createVersion = vi.fn().mockResolvedValue({ current_object_version: version });
  render(ObjectProgress, {
    props: { version, projectId: 'workspace', canWrite: true },
    context: new Map([
      [
        contextKey,
        { api: { createVersion }, query: { setQueryData: vi.fn(), invalidateQueries: vi.fn() } },
      ],
    ]),
  });
  await fireEvent.change(screen.getByRole('combobox'), { target: { value: 'FAILED' } });
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).required).toBe(false);
  await fireEvent.click(screen.getByRole('button', { name: 'Report progress' }));
  await waitFor(() => expect(createVersion).toHaveBeenCalled());
  expect(createVersion.mock.calls[0][1].snapshot.content).toMatchObject({
    reported_outcome: 'FAILED',
    explanation_md: '',
    content_md: version.content.content_md,
  });
});
