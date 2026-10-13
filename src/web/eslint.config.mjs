import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import svelte from 'eslint-plugin-svelte';
export default tseslint.config(
  {
    ignores: [
      '.next/**',
      '.astro/**',
      '.svelte-kit*/**',
      'dist/**',
      'node_modules/**',
      'src/lib/api-client/generated/**',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...svelte.configs['flat/recommended'],
  { files: ['**/*.svelte.ts'], languageOptions: { parser: tseslint.parser } },
  {
    files: ['**/*.svelte'],
    languageOptions: { parserOptions: { parser: tseslint.parser } },
    rules: {
      // TypeScript checks these names, including DOM types and Svelte runes.
      'no-undef': 'off',
      // FastAPI's browser/API contract is rooted at /; no subpath deployments.
      'svelte/no-navigation-without-resolve': 'off',
    },
  },
  { files: ['src/ui/Markdown.svelte'], rules: { 'svelte/no-at-html-tags': 'off' } },
);
