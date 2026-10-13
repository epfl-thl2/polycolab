<script lang="ts">
  import { goto } from '$app/navigation';
  import { canonicalUiLocation } from '../../lib/ui-location';
  import { page } from '$app/state';
  import App from '../../ui/App.svelte';
  $effect(() => {
    const current = page.url.pathname + page.url.search;
    const canonical = canonicalUiLocation(page.url.pathname, page.url.search);
    if (canonical !== current)
      void goto(canonical + page.url.hash, { replaceState: true, noScroll: true, keepFocus: true });
  });
  function navigateQuery(search: string) {
    void goto(page.url.pathname + (search ? `?${search}` : ''), {
      noScroll: true,
      keepFocus: true,
    });
  }
</script>

<App path={page.url.pathname} search={page.url.search} onNavigate={navigateQuery} />
