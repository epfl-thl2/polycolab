import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import AssuranceActions from '../../../src/web/src/ui/AssuranceActions.svelte';

afterEach(cleanup);

it('retains a failed endorsement draft and reuses its retry key', async () => {
  const endorse = vi.fn().mockRejectedValue({ status: 409 });
  render(AssuranceActions, {
    props: {
      revisionId: 'proof-r2',
      statementTargets: [],
      endorse,
      assessCorrespondence: vi.fn(),
    },
  });

  const rationale = screen.getByLabelText('Endorsement rationale');
  await fireEvent.input(rationale, { target: { value: 'The argument is clear.' } });
  const save = screen.getByRole('button', { name: 'Save endorsement decision' });
  await fireEvent.click(save);
  await screen.findByRole('alert');
  expect((rationale as HTMLTextAreaElement).value).toBe('The argument is clear.');
  await fireEvent.click(save);

  await waitFor(() => expect(endorse).toHaveBeenCalledTimes(2));
  expect(endorse.mock.calls[0]![0]).toEqual({
    project_id: undefined,
    object_version_id: 'proof-r2',
    active: true,
    rationale: 'The argument is clear.',
  });
  expect(endorse.mock.calls[1]![1]).toBe(endorse.mock.calls[0]![1]);
});

it('records correspondence independently against the selected exact statement', async () => {
  const assessCorrespondence = vi.fn().mockResolvedValue({});
  render(AssuranceActions, {
    props: {
      revisionId: 'formalization-r4',
      projectId: 'project-1',
      statementTargets: [
        { revisionId: 'claim-r2', title: 'Earlier formulation' },
        { revisionId: 'claim-r3', title: 'Current formulation' },
      ],
      endorse: vi.fn(),
      assessCorrespondence,
    },
  });

  await fireEvent.change(screen.getByLabelText('Exact statement'), {
    target: { value: 'claim-r3' },
  });
  await fireEvent.change(screen.getByLabelText('Correspondence assessment'), {
    target: { value: 'PARTIAL' },
  });
  await fireEvent.input(screen.getByLabelText('Correspondence rationale'), {
    target: { value: 'The finiteness assumption is omitted.' },
  });
  await fireEvent.click(screen.getByRole('button', { name: 'Save correspondence assessment' }));

  await screen.findByRole('status');
  expect(assessCorrespondence).toHaveBeenCalledWith(
    {
      project_id: 'project-1',
      object_version_id: 'formalization-r4',
      statement_object_version_id: 'claim-r3',
      status: 'PARTIAL',
      rationale: 'The finiteness assumption is omitted.',
    },
    expect.any(String),
  );
  expect((screen.getByLabelText('Correspondence rationale') as HTMLTextAreaElement).value).toBe('');
});
