import { afterEach, expect, it } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/svelte';
import PythonEvidence from '../../../src/web/src/ui/PythonEvidence.svelte';
import LeanEvidence from '../../../src/web/src/ui/LeanEvidence.svelte';

afterEach(cleanup);
const target = {
  objectId: 'proof',
  revisionId: 'proof-r2',
  kind: 'PROOF' as const,
  title: 'Proof',
  href: '/proof-r2',
};

it('keeps Python process, mathematical scope, logs and certificate verification separate', () => {
  render(PythonEvidence, {
    props: {
      evidence: {
        jobId: 'python-1',
        state: 'COMPLETED',
        target,
        scope: 'BOUNDED_SEARCH',
        environment: 'python@digest',
        inputs: [target],
        stdout: 'found 20 examples',
        stderr: '',
        logsTruncated: true,
        resources: [{ label: 'CPU', value: '1 s' }],
        artifacts: [
          {
            artifactId: 'artifact-a',
            digest: 'sha256:abc',
            byteLength: 42,
            mediaType: 'text/plain',
            state: 'COMMITTED',
            role: 'CERTIFICATE',
            researchRevision: target,
            researchAttempt: {
              ...target,
              objectId: 'attempt',
              revisionId: 'attempt-r1',
              kind: 'RESEARCH_ATTEMPT',
              title: 'Certificate attempt',
            },
            provenance: [],
            downloadAvailable: true,
          },
        ],
        rerunInstructions: 'python main.py --seed 1',
        attribution: { actorKind: 'AGENT', displayName: 'solver' },
        historical: true,
        certificateGenerationJobId: 'generate-1',
      },
    },
  });
  expect(screen.getByText(/successful process is not a mathematical result/)).toBeTruthy();
  expect(screen.getByText(/Logs were truncated/)).toBeTruthy();
  expect(screen.getByText(/not been independently verified/)).toBeTruthy();
  expect(screen.getByText(/Historical evidence/)).toBeTruthy();
  expect(screen.getByText('python main.py --seed 1')).toBeTruthy();
  expect(screen.getByText(/artifact-a/).textContent).toContain('proof-r2');
  expect(screen.getByText(/artifact-a/).textContent).toContain('attempt-r1');
});

it.each(['FAILED', 'CANCELLED', 'TIMED_OUT'] as const)(
  'retains bounded diagnostics and rerun identity for %s Python evidence',
  (state) => {
    render(PythonEvidence, {
      props: {
        evidence: {
          jobId: `python-${state}`,
          state,
          target,
          scope: 'REPRODUCTION',
          environment: 'python@digest',
          inputs: [],
          stdout: '',
          stderr: 'bounded diagnostic',
          logsTruncated: false,
          resources: [{ label: 'Wall time', value: '30 s' }],
          artifacts: [],
          rerunInstructions: 'python main.py --seed 7',
          attribution: { actorKind: 'HUMAN', displayName: 'Ada' },
          historical: false,
        },
      },
    });
    expect(screen.getByText(state.replace('_', ' '), { selector: 'strong' })).toBeTruthy();
    expect(screen.getByText('bounded diagnostic')).toBeTruthy();
    expect(screen.getByText('python main.py --seed 7')).toBeTruthy();
  },
);

it('shows multiple Lean declarations and prevents unconditional labels with axioms or unfinished work', () => {
  render(LeanEvidence, {
    props: {
      formalizations: [
        {
          jobId: 'lean-job-1',
          resultId: 'lean-result-1',
          formalizationRevision: {
            ...target,
            objectId: 'formalization',
            revisionId: 'formal-r1',
            kind: 'FORMALIZATION',
            title: 'Lean route',
          },
          targetRevision: target,
          environment: 'lean@digest',
          state: 'COMPLETED',
          attribution: { actorKind: 'HUMAN', displayName: 'Ada' },
          historical: false,
          cache: { reused: true, authorizationScope: 'PROJECT' },
          declarations: [
            {
              declarationId: 'declaration-1',
              modulePath: 'Polycolab/Tree.lean',
              name: 'Polycolab.Tree.tree_bipartite',
              compilation: 'COMPILED',
              proofPolicyOutcome: 'CONDITIONAL',
              policyVersion: 'lean-policy-v3',
              unfinished: true,
              axioms: [{ name: 'sorryAx', policy: 'UNRESOLVED' }],
              correspondenceHistory: [
                {
                  status: 'PARTIAL',
                  author: 'Grace',
                  createdAt: '2026-09-08',
                  formalizationRevisionId: 'formal-r1',
                  informalTargetRevisionId: 'proof-r2',
                },
              ],
              diagnostics: [],
            },
            {
              declarationId: 'declaration-2',
              modulePath: 'Polycolab/Tree.lean',
              name: 'Polycolab.Tree.leaf_exists',
              compilation: 'COMPILED',
              proofPolicyOutcome: 'UNCONDITIONAL',
              policyVersion: 'lean-policy-v3',
              unfinished: false,
              axioms: [{ name: 'Classical.choice', policy: 'ALLOWED' }],
              correspondenceHistory: [],
              diagnostics: [],
            },
          ],
        },
        {
          jobId: 'lean-job-2',
          resultId: 'lean-result-2',
          formalizationRevision: {
            ...target,
            objectId: 'formalization-two',
            revisionId: 'formal-r2',
            kind: 'FORMALIZATION',
            title: 'Alternative Lean route',
          },
          targetRevision: target,
          environment: 'lean@digest-two',
          state: 'FAILED',
          attribution: { actorKind: 'AGENT', displayName: 'formalizer' },
          historical: true,
          cache: { reused: false, authorizationScope: 'PROJECT' },
          declarations: [],
        },
      ],
    },
  });
  const first = screen.getByRole('region', { name: 'Polycolab.Tree.tree_bipartite' });
  expect(within(first).getByText(/CONDITIONAL · policy lean-policy-v3/)).toBeTruthy();
  expect(within(first).getByText('sorryAx · UNRESOLVED')).toBeTruthy();
  const correspondence = within(first).getByText('PARTIAL').closest('li');
  expect(correspondence?.textContent).toContain('by Grace');
  expect(correspondence?.textContent).toContain('formal-r1 ↔ proof-r2');
  const second = screen.getByRole('region', { name: 'Polycolab.Tree.leaf_exists' });
  expect(within(second).getByText(/UNCONDITIONAL · policy lean-policy-v3/)).toBeTruthy();
  expect(within(second).getByText('Classical.choice · ALLOWED')).toBeTruthy();
  expect(within(second).getByText(/No human correspondence assessment/)).toBeTruthy();
  expect(screen.getByText(/independent history/)).toBeTruthy();
  expect(screen.getByRole('heading', { name: 'Alternative Lean route' })).toBeTruthy();
  expect(screen.getAllByText(/Internal cache keys are not exposed/)).toHaveLength(2);
  expect(screen.queryByText('safe-key')).toBeNull();
});
