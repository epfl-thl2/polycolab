<script lang="ts">
  import { ArrowLeft } from '@lucide/svelte';
  import { Button } from '../lib/components/ui/button';
</script>

<main id="main" class="page not-found-page" tabindex="-1">
  <div class="not-found-content">
    <p class="not-found-code" aria-label="Error 404">404</p>
    <h1>Page not found</h1>
    <p class="not-found-description">This page may have moved or isn't available yet.</p>
    <nav aria-label="Page recovery" class="not-found-actions">
      <Button href="/" variant="outline"><ArrowLeft aria-hidden="true" />Return home</Button>
    </nav>
  </div>
</main>

<style>
  .not-found-page {
    display: grid;
    flex: 1;
    place-items: center;
    width: 100%;
    padding-block: 64px;
    text-align: center;
  }
  .not-found-content {
    max-width: 420px;
  }
  .not-found-code {
    margin: 0 0 24px;
    color: var(--brand-strong);
    font-size: clamp(96px, 20vw, 144px);
    font-weight: 500;
    letter-spacing: -0.07em;
    line-height: 1;
  }
  h1 {
    margin: 0 0 12px;
    font-family: inherit;
    font-size: 24px;
    font-weight: 500;
    letter-spacing: -0.025em;
  }
  .not-found-description {
    margin: 0;
    color: var(--muted-foreground);
    font-size: 14px;
  }
  .not-found-actions {
    margin-top: 28px;
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 12px;
  }
  .not-found-actions :global([data-slot='button']) {
    min-height: 40px;
    padding-inline: 16px;
  }
</style>
