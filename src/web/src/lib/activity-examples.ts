import type { ActivitySource, SubmissionView } from './activity-view';

// Explicit opt-in illustration; these are never represented as saved research.
export const exampleActivitySource: ActivitySource = {
  async submissions(filters) {
    const ago = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();
    const items: SubmissionView[] = [
      {
        id: 'example-attempt',
        title: 'Testing a bound for regular graphs',
        summary: 'An attempt records a failed bound and the examples that break it.',
        kind: 'attempt',
        actorKind: 'agent',
        author: 'Research agent',
        sponsor: 'Example researcher',
        project: 'Spectral gaps',
        createdAt: ago(1),
        revisionLabel: 'Revision 1',
      },
      {
        id: 'example-comment',
        title: 'A missing assumption in the argument',
        summary: 'A researcher asks whether the proof requires a connected graph.',
        kind: 'comment',
        actorKind: 'human',
        author: 'Example researcher',
        project: 'Spectral gaps',
        createdAt: ago(3),
        revisionLabel: 'On revision 2',
      },
      {
        id: 'example-proof',
        title: 'An alternative induction argument',
        summary: 'A new proof sketch separates the base case from the induction step.',
        kind: 'proof',
        actorKind: 'human',
        author: 'Example collaborator',
        project: 'Combinatorial identities',
        createdAt: ago(30),
        revisionLabel: 'Revision 1',
      },
      {
        id: 'example-evidence',
        title: 'Small-case enumeration results',
        summary: 'Attached computational evidence for inspection; it does not establish a proof.',
        kind: 'evidence',
        actorKind: 'agent',
        author: 'Computation agent',
        sponsor: 'Example collaborator',
        project: 'Combinatorial identities',
        createdAt: ago(50),
        revisionLabel: 'On revision 3',
      },
    ];
    return {
      items: items.filter(
        (item) =>
          (filters.actor === 'all' || item.actorKind === filters.actor) &&
          (filters.kind === 'all' || item.kind === filters.kind) &&
          (filters.window !== 'day' || Date.parse(item.createdAt) > Date.now() - 86_400_000),
      ),
    };
  },
  async projects(window) {
    const day = window === 'day';
    return {
      items: [
        {
          id: 'example-spectral',
          name: 'Spectral gaps',
          description: 'Investigating bounds and counterexamples for finite graphs.',
          contributors: day ? 2 : 4,
          submissions: day ? 2 : 7,
          attempts: day ? 1 : 3,
          comments: day ? 1 : 8,
          lastActiveAt: new Date(Date.now() - 3_600_000).toISOString(),
        },
        ...(day
          ? []
          : [
              {
                id: 'example-identities',
                name: 'Combinatorial identities',
                description: 'Comparing constructive and inductive arguments.',
                contributors: 2,
                submissions: 4,
                attempts: 1,
                comments: 3,
                lastActiveAt: new Date(Date.now() - 108_000_000).toISOString(),
              },
            ]),
      ],
    };
  },
};
