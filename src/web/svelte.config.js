import process from 'node:process';
import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

export default {
  preprocess: vitePreprocess(),
  kit: {
    outDir: process.env.POLYCOLAB_SVELTE_OUT_DIR || '.svelte-kit',
    adapter: adapter({ pages: 'dist', assets: 'dist', fallback: 'index.html' }),
  },
};
