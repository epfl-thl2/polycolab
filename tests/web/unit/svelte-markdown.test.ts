import { afterEach, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/svelte';
import Markdown from '../../../src/web/src/ui/Markdown.svelte';
afterEach(cleanup);
it('updates the rendered statement and exposes math to assistive technology', async () => {
  const result = render(Markdown, { content: 'A bound $x^2$' });
  expect(result.container.querySelector('math')).not.toBeNull();
  await result.rerender({ content: '## Revised statement\n\nNew content.' });
  expect(screen.getByRole('heading', { name: 'Revised statement' })).toBeTruthy();
  expect(result.container.querySelector('math')).toBeNull();
});
