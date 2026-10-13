import { expect, type Page } from '@playwright/test';

/** Existing save/draft journeys also cover the accessible plain-text fallback. */
export async function plainFileEditor(page: Page) {
  const field = page.locator('.source-editor textarea[aria-label="File contents"]');
  await expect(page.getByLabel('File actions', { exact: true })).toBeVisible();
  if (!(await field.isVisible())) {
    const menu = page.getByLabel('File actions', { exact: true });
    const toggle = page.getByRole('menuitem', { name: 'Use text editor', exact: true });
    if (!(await toggle.isVisible())) await menu.click();
    await toggle.click();
  }
  await expect(field).toBeVisible();
  return field;
}
