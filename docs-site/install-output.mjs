import { access, cp, mkdir, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const source = fileURLToPath(new URL('./site/', import.meta.url));
const target = fileURLToPath(new URL('../src/web/dist/docs/', import.meta.url));
const previewClient = fileURLToPath(
  new URL('../src/web/.svelte-kit/output/client/', import.meta.url),
);

await rm(target, { recursive: true, force: true });
await mkdir(target, { recursive: true });
await cp(source, target, { recursive: true });

try {
  await access(previewClient);
  const previewTarget = `${previewClient}docs`;
  await rm(previewTarget, { recursive: true, force: true });
  await cp(source, previewTarget, { recursive: true });
} catch {
  // A standalone docs build does not require an existing SvelteKit preview tree.
}
