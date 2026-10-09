import { afterEach, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/svelte';
import About from '../../../src/web/src/ui/About.svelte';

afterEach(cleanup);

it('renders About without duplicate navigation', () => {
  render(About);
  expect(screen.getByRole('heading', { level: 1, name: 'About' })).toBeTruthy();
  expect(screen.getByRole('article', { name: 'Polycolab' })).toBeTruthy();
  expect(screen.queryByRole('link')).toBeNull();
});
