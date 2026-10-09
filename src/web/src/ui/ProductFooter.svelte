<script lang="ts">
  let {
    feedbackUrl: feedbackUrlInput = import.meta.env.VITE_FEEDBACK_URL,
    releaseId: releaseIdInput = import.meta.env.VITE_RELEASE_ID,
  }: { feedbackUrl?: string; releaseId?: string } = $props();

  function safeFeedbackUrl(value: string | undefined) {
    if (!value) return undefined;
    if (value.startsWith('/') && !value.startsWith('//')) return value;
    try {
      const url = new URL(value);
      return ['https:', 'http:', 'mailto:'].includes(url.protocol) ? value : undefined;
    } catch {
      return undefined;
    }
  }

  const feedbackUrl = $derived(safeFeedbackUrl(feedbackUrlInput?.trim()) ?? '/404');
  const releaseId = $derived(releaseIdInput?.trim().slice(0, 64));
  const buildLabel = $derived(
    releaseId && /^[a-f0-9]{12,40}$/i.test(releaseId) ? releaseId.slice(0, 8) : releaseId,
  );
</script>

<footer class="product-footer">
  <div class="product-footer-inner">
    <nav aria-label="Product information">
      <a href="/about">About</a>
      <a href="/docs/" data-sveltekit-reload>Documentation</a>
      <a href="/docs/api/" data-sveltekit-reload>API reference</a>
      <a href="/SKILL.md" data-sveltekit-reload>SKILL.md</a>
      <a href={feedbackUrl} rel="noreferrer">Feedback / Report an issue</a>
    </nav>
    <span class="product-footer-build">
      {#if releaseId}Build <code title={releaseId}>{buildLabel}</code>{:else}Local build{/if}
    </span>
  </div>
</footer>
