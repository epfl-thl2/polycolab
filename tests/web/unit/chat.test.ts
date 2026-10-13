import { afterEach, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import Chat from '../../../src/web/src/ui/Chat.svelte';

afterEach(cleanup);

it('shows the planned journey without accepting messages or credentials', async () => {
  render(Chat);
  expect(screen.getByText('Planned')).toBeTruthy();
  expect(screen.getByRole('status').textContent).toContain('coming soon');
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(true);
  await fireEvent.click(screen.getByText('Conversation history'));
  for (const name of ['New chat', 'Attach context', 'Send message']) {
    expect((screen.getByRole('button', { name }) as HTMLButtonElement).disabled).toBe(true);
  }
  expect(screen.queryByLabelText(/password|api key/i)).toBeNull();
  expect(screen.getByRole('link', { name: 'Connect an external agent' }).getAttribute('href')).toBe(
    '/agents/connections',
  );
  expect(screen.getByRole('link', { name: 'Browse projects' }).getAttribute('href')).toBe(
    '/projects?scope=public',
  );
  expect(screen.getByText(/saved research is public/)).toBeTruthy();
});
