import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const repositoryRoot = resolve(process.cwd(), '../..');

async function source(path: string) {
  return readFile(resolve(repositoryRoot, path), 'utf8');
}

describe('shared production color tokens', () => {
  it('defines the official EPFL palette in the web styles', async () => {
    const tokens = await source('src/web/src/styles/tokens.css');

    for (const [name, value] of Object.entries({
      red: '#ff0000',
      groseille: '#b51f1f',
      leman: '#00a79f',
      canard: '#007480',
      taupe: '#413d3a',
      perle: '#cac7c7',
    })) {
      expect(tokens).toContain(`--polycolab-epfl-${name}: ${value};`);
    }
  });

  it('maps the app and documentation onto the shared palette', async () => {
    const [appTheme, docsTheme, docsConfig, scalarLoader] = await Promise.all([
      source('src/web/src/styles/theme.css'),
      source('docs-site/docs/styles/zensical.css'),
      source('docs-site/mkdocs.yml'),
      source('docs-site/docs/scripts/api-reference.js'),
    ]);

    expect(appTheme).toContain("@import './tokens.css';");
    expect(appTheme).toContain('--primary: var(--polycolab-epfl-groseille);');
    expect(appTheme).toContain('--research-accent: var(--polycolab-epfl-canard);');
    expect(docsConfig).toContain('- styles/brand-tokens.css');
    expect(docsTheme).toContain('--md-typeset-a-color: var(--polycolab-epfl-canard);');
    expect(scalarLoader).toContain('--scalar-color-accent: var(--polycolab-epfl-canard);');
    expect(`${appTheme}\n${docsTheme}`).not.toContain('#005d67');
  });
});
