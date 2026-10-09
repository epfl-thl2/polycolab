import { afterEach, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/svelte';
import ProductFooter from '../../../src/web/src/ui/ProductFooter.svelte';

afterEach(cleanup);

it('shows configured feedback and release identity without including research content', () => {
  render(ProductFooter, {
    props: {
      feedbackUrl: 'https://feedback.example/form',
      releaseId: 'research-2026.09.09',
    },
  });

  expect(
    screen.getByRole('link', { name: 'Feedback / Report an issue' }).getAttribute('href'),
  ).toBe('https://feedback.example/form');
  expect(screen.getByText('research-2026.09.09')).toBeTruthy();
});

it('drops unsafe feedback URLs', () => {
  render(ProductFooter, { props: { feedbackUrl: 'javascript:alert(1)' } });
  expect(
    screen.getByRole('link', { name: 'Feedback / Report an issue' }).getAttribute('href'),
  ).toBe('/404');
});
