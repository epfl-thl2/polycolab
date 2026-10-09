import { copyFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

export const brandTokensSource = fileURLToPath(
  new URL('../src/web/src/styles/tokens.css', import.meta.url),
);
const target = fileURLToPath(new URL('./docs/styles/brand-tokens.css', import.meta.url));

export async function syncBrandTokens() {
  await mkdir(fileURLToPath(new URL('./docs/styles/', import.meta.url)), { recursive: true });
  await copyFile(brandTokensSource, target);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  await syncBrandTokens();
}
