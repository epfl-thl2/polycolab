import { expect, test } from '../fixtures';
import { mockAccount } from '../helpers/account';
import type { LibraryPublic } from '../../../../src/web/src/lib/library-api';

const project = {
  id: '11111111-1111-4111-8111-111111111111',
  name: 'Spectral gaps',
  description: 'Exploring expansion in finite graphs.',
  file_mode: 'basic',
  visibility: 'PUBLIC',
  current_user_role: 'OWNER',
  member_count: 3,
  archived_at: null,
  created_at: '2026-11-14T12:00:00Z',
  updated_at: '2026-11-14T12:00:00Z',
};
const item: LibraryPublic = {
  id: '22222222-2222-4222-8222-222222222222',
  kind: 'PROMPT',
  archived: false,
  source_item_id: null,
  source_version_id: null,
  version: {
    id: '33333333-3333-4333-8333-333333333333',
    item_id: '22222222-2222-4222-8222-222222222222',
    number: 1,
    author_name: 'Ada',
    author_user_id: '11111111-1111-4111-8111-111111111111',
    published_at: '2026-11-14T12:00:00Z',
    content: {
      title: 'Review a proof',
      description: 'Check each inference.',
      content: 'Review every assumption.',
      instructions: '',
      license: 'CC-BY-4.0',
      runtime: '',
      source_reference: '',
      source_url: '',
      tags: [],
    },
  },
};

test('home searches member projects and library items with direct result links', async ({
  page,
}, info) => {
  await mockAccount(page, true);
  await page.setViewportSize({ width: 1440, height: 1050 });
  const scopes: (string | null)[] = [];
  await page.route('**/api/v1/projects?*', (route) => {
    scopes.push(new URL(route.request().url()).searchParams.get('scope'));
    return route.fulfill({ json: { items: [project], next_cursor: null, total: 1 } });
  });
  await page.route('**/api/v1/library?*', (route) =>
    route.fulfill({ json: { items: [item], next_cursor: null } }),
  );
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'What are you researching?' })).toBeVisible();
  const onboard = page.getByRole('button', { name: 'Onboard your agent', exact: true });
  await expect(onboard.locator('img')).toHaveCount(4);
  await expect
    .poll(() =>
      onboard
        .locator('img')
        .evaluateAll((images) =>
          images.every(
            (image) =>
              (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0,
          ),
        ),
    )
    .toBe(true);
  await expect(
    page.getByRole('heading', { name: 'Your tools. A shared place to work.' }),
  ).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Build something together' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: /Spectral gaps/ })).toHaveAttribute(
    'href',
    `/projects/${project.id}`,
  );
  await expect(page.getByRole('link', { name: /Review a proof/ })).toHaveAttribute(
    'href',
    `/library/items/${item.id}`,
  );
  await expect(page.getByRole('link', { name: 'Conversation history', exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('home-desktop.png'), fullPage: true });
  await page.keyboard.press('Control+k');
  await expect(page.getByRole('textbox', { name: 'Search', exact: true })).toBeFocused();
  const emptySuggestions = page.getByRole('region', { name: 'Search suggestions' });
  await expect(emptySuggestions.getByRole('heading', { name: 'Search tips' })).toBeVisible();
  await expect(emptySuggestions.getByText('Recents', { exact: true })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('search-tips-desktop.png') });
  await page.keyboard.press('Escape');
  await expect(emptySuggestions).toHaveCount(0);
  await page.keyboard.press('Control+k');
  await expect(emptySuggestions).toBeVisible();
  await page.getByRole('textbox', { name: 'Search', exact: true }).fill(' spectral & gaps ');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  const suggestions = page.getByRole('region', { name: 'Search suggestions' });
  await expect(suggestions.getByRole('link', { name: 'Spectral gaps' })).toBeVisible();
  await expect(suggestions.getByRole('link', { name: 'Review a proof' })).toBeVisible();
  await expect(suggestions.getByRole('link')).toHaveCount(2);
  await expect(suggestions.getByRole('link', { name: 'Spectral gaps' })).toHaveAttribute(
    'href',
    `/projects/${project.id}`,
  );
  await expect(suggestions.getByRole('link', { name: 'Review a proof' })).toHaveAttribute(
    'href',
    `/library/items/${item.id}`,
  );
  await page.keyboard.press('Escape');
  await page.getByRole('link', { name: 'Your projects', exact: true }).click();
  await expect(page).toHaveURL('/projects');
  await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'New project', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  expect(scopes.every((scope) => scope === 'member')).toBe(true);
});

test('anonymous mobile home has honest empty states and public search', async ({ page }, info) => {
  await mockAccount(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const projectRequest = page.waitForRequest((request) =>
    request.url().includes('/api/v1/projects?'),
  );
  await page.route('**/api/v1/library?*', (route) =>
    route.fulfill({ json: { items: [], next_cursor: null } }),
  );
  await page.goto('/');
  // The public adapter uses the API's default scope; member requests opt in explicitly.
  expect(new URL((await projectRequest).url()).searchParams.get('scope')).toBeNull();
  await expect(page.getByText('Projects will appear here as they are shared.')).toBeVisible();
  await expect(page.getByText('A shared home for prompts, skills, and plugins.')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Conversation history', exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole('button', { name: 'Onboard your agent', exact: true }),
  ).toHaveAttribute('aria-haspopup', 'dialog');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: info.outputPath('home-mobile.png'), fullPage: true });
  await page.getByRole('textbox', { name: 'Search', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Search tips' })).toBeVisible();
  await page.screenshot({ path: info.outputPath('search-tips-mobile.png') });
  await page.getByRole('textbox', { name: 'Search', exact: true }).fill('graphs');
  await page.getByRole('textbox', { name: 'Search', exact: true }).press('Enter');
  const suggestions = page.getByRole('region', { name: 'Search suggestions' });
  await expect(suggestions.getByRole('status')).toHaveCount(0);
  await expect(suggestions.getByRole('heading')).toHaveCount(0);
  await expect(suggestions.getByRole('link')).toHaveCount(0);
  await expect(suggestions.getByText(/No matching/)).toHaveCount(0);
  await expect(suggestions.getByRole('button', { name: /Ask AI/ })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('link', { name: 'Public projects', exact: true }).click();
  await expect(page).toHaveURL('/projects?scope=public');
  await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
});

for (const signedIn of [true, false]) {
  test(`agent setup opens in a modal (${signedIn ? 'member desktop' : 'visitor mobile'})`, async ({
    page,
  }, info) => {
    await mockAccount(page, signedIn);
    await page.setViewportSize({ width: signedIn ? 1280 : 390, height: 844 });
    await page.route('**/api/v1/library?*', (route) =>
      route.fulfill({ json: { items: [], next_cursor: null } }),
    );
    await page.goto('/');
    const pill = page.getByRole('button', { name: 'Onboard your agent', exact: true });
    await pill.click();
    const dialog = page.getByRole('dialog', { name: 'Onboard your agent' });
    await expect(dialog).toBeVisible();
    await expect(page).toHaveURL('/');
    await expect(
      dialog.getByRole('link', { name: signedIn ? 'Open API keys' : 'Sign in to set up a key' }),
    ).toHaveAttribute(
      'href',
      signedIn ? '/settings/api-keys' : '/signin?returnTo=%2Fsettings%2Fapi-keys',
    );
    await expect(
      dialog.getByRole('textbox', { name: 'Agent connection instructions' }),
    ).toHaveValue(new RegExp(`${new URL(page.url()).origin}/SKILL\\.md`));
    await page.keyboard.press('Control+k');
    await expect(page.getByRole('textbox', { name: 'Search', exact: true })).not.toBeFocused();
    // Use deterministic clipboard behavior without needing browser-specific permissions.
    await page.evaluate(() =>
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: {
          writeText: (text: string) => {
            sessionStorage.setItem('copied-instructions', text);
            return Promise.resolve();
          },
        },
      }),
    );
    await dialog.getByRole('button', { name: 'Copy instructions' }).click();
    await expect(dialog.getByRole('status')).toHaveText('Instructions copied.');
    expect(await page.evaluate(() => sessionStorage.getItem('copied-instructions'))).toBe(
      await dialog.getByRole('textbox').inputValue(),
    );
    expect(
      await dialog.evaluate((element) => {
        const bounds = element.getBoundingClientRect();
        return (
          bounds.left >= 0 &&
          bounds.right <= window.innerWidth &&
          bounds.top >= 0 &&
          bounds.bottom <= window.innerHeight
        );
      }),
    ).toBe(true);
    expect(
      await dialog
        .getByRole('textbox')
        .evaluate((element) => element.getBoundingClientRect().width),
    ).toBeGreaterThan(200);
    await page.screenshot({ path: info.outputPath('agent-connect-modal.png') });
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(pill).toBeFocused();
    await pill.click();
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole('status')).toHaveCount(0);
    await page.evaluate(() =>
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: { writeText: () => Promise.reject(new Error('denied')) },
      }),
    );
    await dialog.getByRole('button', { name: 'Copy instructions' }).click();
    await expect(dialog.getByRole('alert')).toContainText('Select and copy the instructions');
    await dialog.getByRole('button', { name: 'Close', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(pill).toBeFocused();
  });
}

test('home keeps navigation available when projects fail and supports retry', async ({ page }) => {
  await mockAccount(page, true);
  let fail = true;
  await page.route('**/api/v1/projects?*', (route) =>
    fail
      ? route.fulfill({ status: 503, json: { detail: 'unavailable' } })
      : route.fulfill({ json: { items: [project], next_cursor: null, total: 1 } }),
  );
  await page.route('**/api/v1/library?*', (route) =>
    route.fulfill({ json: { items: [], next_cursor: null } }),
  );
  await page.goto('/');
  await expect(page.getByText('Could not load projects.')).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole('link', { name: 'Conversation history', exact: true })).toBeVisible();
  fail = false;
  await page.getByRole('button', { name: 'Try again', exact: true }).click();
  await expect(page.getByRole('link', { name: /Spectral gaps/ })).toBeVisible();
  await expect(page.getByText('Could not load projects.')).toHaveCount(0);
});

test('search offers general research chat using the platform model', async ({ page }, info) => {
  await mockAccount(page, true);
  await page.route('**/api/v1/library?*', (route) =>
    route.fulfill({ json: { items: [item], next_cursor: null } }),
  );
  await page.route('**/api/v1/platform-models', (route) =>
    route.fulfill({
      json: [
        {
          id: 'aaaaaaaa-1111-4111-8111-111111111111',
          catalog_id: 'quick',
          display_name: 'Polycolab Quick',
          model_id: 'fast-model',
          uses: ['research_helper'],
          harnesses: [],
          default_for: ['research_helper'],
        },
        {
          id: 'aaaaaaaa-2222-4222-8222-222222222222',
          catalog_id: 'capable',
          display_name: 'Polycolab Capable',
          model_id: 'capable-model',
          uses: ['research_helper'],
          harnesses: [],
          default_for: [],
        },
      ],
    }),
  );
  let personalConnectionRequests = 0;
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/account/provider-connections'))
      personalConnectionRequests++;
  });
  const requests: {
    model_id?: string;
    messages: { role: string; content: string }[];
  }[] = [];
  let fail = false;
  await page.route('**/api/v1/research-helper/messages', (route) => {
    requests.push(route.request().postDataJSON());
    return route.fulfill(
      fail
        ? { status: 502, json: { error: { code: 'research_helper_provider_unavailable' } } }
        : { json: { content: 'Start by defining **falsifiable predictions**.' } },
    );
  });
  await page.goto('/');
  const search = page.getByRole('textbox', { name: 'Search', exact: true });
  await search.fill('How can I test this hypothesis?');
  const dropdown = page.getByRole('region', { name: 'Search suggestions' });
  await expect(dropdown.getByRole('button', { name: /Ask AI/ })).toBeVisible();
  await expect(dropdown.getByRole('link', { name: 'Review a proof' })).toBeVisible();
  await page.screenshot({ path: info.outputPath('search-dropdown.png') });
  await search.press('ArrowDown');
  await expect(dropdown.getByRole('button', { name: /Ask AI/ })).toBeFocused();
  await page.keyboard.press('Enter');
  const dialog = page.getByRole('dialog', { name: 'Research assistant' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('textbox', { name: 'Message' })).toHaveValue(
    'How can I test this hypothesis?',
  );
  await expect(dialog.getByRole('combobox', { name: 'Provider connection' })).toHaveCount(0);
  await dialog.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(dialog.getByText('falsifiable predictions')).toBeVisible();
  expect(personalConnectionRequests).toBe(0);
  expect(requests[0]).toEqual({
    model_id: 'quick',
    messages: [{ role: 'user', content: 'How can I test this hypothesis?' }],
  });
  await dialog.getByRole('button', { name: 'Choose research model' }).click();
  await page.getByRole('menuitemradio', { name: 'Polycolab Capable' }).click();
  await dialog.getByRole('textbox', { name: 'Message' }).fill('What should I measure?');
  await dialog.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(dialog.getByText('falsifiable predictions')).toHaveCount(2);
  expect(requests[1].model_id).toBe('capable');
  expect(requests[1].messages.map((message) => message.role)).toEqual([
    'user',
    'assistant',
    'user',
  ]);
  fail = true;
  await dialog.getByRole('textbox', { name: 'Message' }).fill('Keep this failed question');
  await dialog.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('Your question is still here');
  await expect(dialog.getByRole('textbox', { name: 'Message' })).toHaveValue(
    'Keep this failed question',
  );
  await page.screenshot({ path: info.outputPath('research-assistant.png') });
  await dialog.getByRole('button', { name: 'New chat' }).click();
  await expect(dialog.getByText('falsifiable predictions')).toHaveCount(0);
  await page.keyboard.press('Escape');
  await expect(search).toBeFocused();
  await search.press('Escape');
  await expect(dropdown).toHaveCount(0);
  await search.press('ArrowDown');
  await expect(dropdown.getByRole('button', { name: /Ask AI/ })).toBeFocused();
  await page.keyboard.press('ArrowUp');
  await expect(search).toBeFocused();
  await search.fill('');
  await expect(dropdown.getByRole('heading', { name: 'Search tips' })).toBeVisible();
  await expect(dropdown.getByRole('button', { name: /Ask AI/ })).toHaveCount(0);
});

test('mobile search shows unconfigured platform helper and keeps Library navigation', async ({
  page,
}, info) => {
  await mockAccount(page, true);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route('**/api/v1/library?*', (route) =>
    route.fulfill({ json: { items: [], next_cursor: null } }),
  );
  await page.route('**/api/v1/config', (route) =>
    route.fulfill({
      json: { agent_execution: false, email_recovery: false, research_helper: false },
    }),
  );
  await page.goto('/');
  await page.getByRole('textbox', { name: 'Search', exact: true }).fill('literature');
  const dropdown = page.getByRole('region', { name: 'Search suggestions' });
  await dropdown.getByRole('button', { name: /Ask AI/ }).click();
  const dialog = page.getByRole('dialog', { name: 'Research assistant' });
  await expect(dialog.getByRole('status')).toHaveText(
    'The research assistant is not available yet.',
  );
  await expect(dialog.getByRole('link', { name: 'Add provider connection' })).toHaveCount(0);
  await expect(dialog.getByRole('button', { name: 'Send message' })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('research-assistant-mobile.png') });
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await page.keyboard.press('Escape');
  await page.getByRole('heading', { name: 'Library', exact: true }).getByRole('link').click();
  await expect(page).toHaveURL('/library');
});
