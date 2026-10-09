<script lang="ts">
  import { onMount } from 'svelte';
  let { value }: { value: string } = $props();
  let now = $state(Date.now());
  const exact = $derived(
    new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }),
  );
  const relative = $derived.by(() => {
    const seconds = (Date.parse(value) - now) / 1000;
    const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
    if (Math.abs(seconds) < 60) return 'just now';
    if (Math.abs(seconds) < 3600) return formatter.format(Math.round(seconds / 60), 'minute');
    if (Math.abs(seconds) < 86400) return formatter.format(Math.round(seconds / 3600), 'hour');
    return formatter.format(Math.round(seconds / 86400), 'day');
  });
  onMount(() => {
    const timer = setInterval(() => (now = Date.now()), 60000);
    return () => clearInterval(timer);
  });
</script>

<time datetime={value} title={exact} aria-label={`${relative}, ${exact}`}>{relative}</time>
