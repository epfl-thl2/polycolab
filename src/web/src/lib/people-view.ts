// Presentation models for a future dedicated public-profile API, not account DTOs.
export type PersonView = {
  id: string;
  displayName: string;
  handle: string;
  bio: string;
  interests: string[];
  contributions?: { title: string; summary: string; href?: string }[];
  projects: { name: string; href?: string }[];
};
export interface PeopleSource {
  getProfile(id: string): Promise<PersonView | undefined>;
  search(query: string, cursor?: string): Promise<{ items: PersonView[]; nextCursor?: string }>;
}
export const examplePeopleSource: PeopleSource = {
  async getProfile(id) {
    return (await examplePeopleSource.search('')).items.find((person) => person.id === id);
  },
  async search(query) {
    const people: PersonView[] = [
      {
        id: 'example-ada',
        displayName: 'Ada Example',
        handle: 'ada-example',
        bio: 'An illustrative researcher interested in combinatorics and constructive proofs.',
        interests: ['Combinatorics', 'Graph theory'],
        contributions: [
          {
            title: 'An approach to a spectral bound',
            summary: 'An illustrative proof sketch exploring the role of connectedness.',
          },
        ],
        projects: [{ name: 'Spectral gaps' }],
      },
      {
        id: 'example-noor',
        displayName: 'Noor Example',
        handle: 'noor-example',
        bio: 'An illustrative collaborator exploring formalization and proof structure.',
        interests: ['Lean', 'Logic'],
        projects: [{ name: 'Formal proof workshop' }],
      },
      {
        id: 'example-alex',
        displayName: 'Alex Example',
        handle: 'alex-example',
        bio: 'An illustrative researcher studying complexity and algorithmic arguments.',
        interests: ['Complexity', 'Algorithms'],
        projects: [{ name: 'Combinatorial identities' }],
      },
    ];
    const term = query.trim().toLocaleLowerCase();
    return {
      items: people.filter((person) =>
        [person.displayName, person.handle, person.bio, ...person.interests]
          .join(' ')
          .toLocaleLowerCase()
          .includes(term),
      ),
    };
  },
};
