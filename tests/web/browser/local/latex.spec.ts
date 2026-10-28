import { expect, test } from '@playwright/test';
import { plainFileEditor } from '../helpers/project-editor';

test('real LaTeX saves drafts, compiles a private PDF, preserves it after failure, and cancels', async ({
  page,
  request,
  baseURL,
}) => {
  test.skip(process.env.POLYCOLAB_LATEX_BROWSER !== '1', 'Run through tests/system/run_latex.py.');
  test.setTimeout(240_000);
  await page.goto('/signup');
  await page.getByLabel('Username', { exact: true }).fill(`latex${Date.now()}`);
  await page.getByLabel('Password', { exact: true }).fill('latex-browser-test-password');
  await page.getByLabel('Confirm password', { exact: true }).fill('latex-browser-test-password');
  await page.getByRole('main').getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
  const created = await page.request.post('/api/v1/projects', {
    headers: { Origin: baseURL! },
    data: { name: 'LaTeX acceptance', visibility: 'PUBLIC' },
  });
  expect(created.status()).toBe(201);
  const project = await created.json();
  const trees = await (await page.request.get(`/api/v1/projects/${project.id}/worktrees`)).json();
  const root = `/api/v1/projects/${project.id}/worktrees/${trees[0].id}`;
  const source = String.raw`\documentclass{article}\begin{document}Browser compiled document.\newpage Second page.\end{document}`;
  await page.goto(`/projects/${project.id}/files`);
  await page.getByRole('button', { name: 'New file', exact: true }).click();
  await page.getByLabel('File path', { exact: true }).fill('main.tex');
  await (await plainFileEditor(page)).fill(source);
  await page.getByRole('button', { name: 'LaTeX / PDF preview', exact: true }).click();
  const panel = page.getByRole('complementary', { name: 'LaTeX compilation' });
  await expect(panel.getByRole('button', { name: 'Save all & compile', exact: true })).toBeEnabled({
    timeout: 45_000,
  });
  await panel.getByRole('button', { name: 'Save all & compile', exact: true }).click();
  await expect(panel.getByRole('status')).toHaveText('Build: succeeded', { timeout: 120_000 });
  await expect(panel.getByRole('link', { name: 'Download PDF' })).toBeVisible();
  await expect(panel.getByRole('img', { name: 'PDF page 1' })).toBeVisible({ timeout: 30_000 });
  await panel.getByRole('button', { name: 'Next page', exact: true }).click();
  await expect(panel.getByRole('img', { name: 'PDF page 2' })).toBeVisible();
  await panel.getByRole('button', { name: 'Previous page', exact: true }).click();
  await expect(panel.getByRole('img', { name: 'PDF page 1' })).toBeVisible();
  if (process.env.POLYCOLAB_LATEX_SCREENSHOT)
    await page.screenshot({ path: process.env.POLYCOLAB_LATEX_SCREENSHOT, fullPage: true });
  const builds = await (await page.request.get(root + '/latex-builds')).json();
  const pdfPath = root + '/latex-builds/' + builds.builds[0].id + '/outputs/pdf';
  const pdf = await page.request.get(pdfPath);
  expect((await pdf.body()).subarray(0, 5).toString()).toBe('%PDF-');
  expect(pdf.headers()['cache-control']).toBe('private, no-store');
  expect((await request.get(pdfPath)).status()).toBe(401);
  const tree = await (await page.request.get(root)).json();
  expect(tree.head_commit).toBe(trees[0].head_commit);
  expect(tree.changed_files).toEqual([{ path: 'main.tex', status: 'added' }]);
  await page.reload();
  await page.getByRole('button', { name: 'LaTeX / PDF preview', exact: true }).click();
  await expect(panel.getByRole('link', { name: 'Download PDF' })).toBeVisible();
  await page
    .getByRole('navigation', { name: 'File tree' })
    .getByRole('button', { name: /^main\.tex/ })
    .click();
  await (
    await plainFileEditor(page)
  ).fill(source.replace('Browser compiled document.', String.raw`\undefinedcommand`));
  await panel.getByRole('button', { name: 'Save all & compile', exact: true }).click();
  await expect(panel.getByRole('status')).toContainText('Build: failed', { timeout: 120_000 });
  await expect(panel.getByRole('link', { name: 'Download PDF' })).toBeVisible();
  await expect(panel.getByRole('list', { name: 'Compilation errors' })).toBeVisible();
  await (
    await plainFileEditor(page)
  ).fill(source.replace('Browser compiled document.', String.raw`\loop\iftrue\repeat`));
  await panel.getByRole('button', { name: 'Save all & compile', exact: true }).click();
  await expect(panel.getByRole('status')).toContainText('Build: running', { timeout: 30_000 });
  await panel.getByRole('button', { name: 'Cancel build', exact: true }).click();
  await expect(panel.getByRole('status')).toContainText('Build: cancelled');
  await expect(panel.getByRole('link', { name: 'Download PDF' })).toBeVisible();
});
