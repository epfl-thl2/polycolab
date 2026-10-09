import { expect, it } from 'vitest';
import {
  canonicalUiLocation,
  readActivity,
  readPeople,
  readProfile,
  profileQuery,
} from '../../../src/web/src/lib/ui-location';
import {
  excerptBlocks,
  highlightParts,
  renderSearchExcerpt,
} from '../../../src/web/src/lib/search-excerpt';

it('normalizes old routes and invalid filters without enabling examples', () => {
  expect(canonicalUiLocation('/search', '?q=graph&type=workspaces')).toBe(
    '/?q=graph&type=workspaces',
  );
  expect(canonicalUiLocation('/activity/workspaces', '?window=day&preview=examples')).toBe(
    '/activity?view=workspaces&window=day&preview=examples',
  );
  expect(
    canonicalUiLocation(
      '/activity',
      '?view=wrong&window=year&actor=invalid&kind=unknown&preview=yes',
    ),
  ).toBe('/activity');
  expect(readActivity('?actor=agent&preview=examples').examples).toBe(true);
  expect(readPeople('?q=logic&profile=example-noor&preview=examples')).toEqual({
    query: 'logic',
    profile: 'example-noor',
    examples: true,
  });
});

it('preserves profile search and type while normalizing unsupported filters', () => {
  expect(readProfile('?q= spectral &type=formalizations')).toEqual({
    query: 'spectral',
    type: 'formalizations',
    day: undefined,
    year: undefined,
  });
  expect(profileQuery({ query: 'spectral', type: 'research' })).toBe('q=spectral&type=research');
  expect(canonicalUiLocation('/profile', '?type=unknown&q=')).toBe('/profile');
  expect(readProfile(`?q=${'x'.repeat(300)}`).query).toHaveLength(200);
  expect(canonicalUiLocation('/profile', '?type=proofs&year=2024&day=2024-02-29&invalid=1')).toBe(
    '/profile?type=proofs&year=2024&day=2024-02-29',
  );
});

it('keeps complete math blocks and sanitizes excerpts before highlighting plain text', () => {
  const input =
    'A spectral **bound** and $x^2$.\n\n$$\\sum_{i=1}^{n} i$$\n\n<script>alert(1)</script>\n\nextra';
  const html = renderSearchExcerpt(input, 'spectral');
  expect(html).toContain('<mark>spectral</mark>');
  expect(html).toContain('katex');
  expect(html).not.toContain('<script');
  expect(html).not.toContain('extra');
  expect(excerptBlocks(input)).toContain('$$\\sum_{i=1}^{n} i$$');
  expect(
    renderSearchExcerpt('[spectral](javascript:alert(1)) ![x](x "spectral")', 'spectral'),
  ).not.toContain('javascript:');
  expect(renderSearchExcerpt('`spectral` and $spectral$', 'spectral')).not.toContain('<mark>');
  expect(highlightParts('a+b A+B', 'a+b').filter((part) => part.match)).toHaveLength(2);
});

it('preserves history dates and years and rejects impossible or conflicting dates', () => {
  expect(canonicalUiLocation('/profile', '?year=2023&day=2024-02-29&type=proofs')).toBe(
    '/profile?type=proofs&year=2024&day=2024-02-29',
  );
  expect(canonicalUiLocation('/profile', '?year=2023&day=2023-02-29')).toBe('/profile?year=2023');
  expect(canonicalUiLocation('/profile', '?year=9999&day=0000-01-01')).toBe('/profile');
});
