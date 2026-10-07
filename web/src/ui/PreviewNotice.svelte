<script lang="ts">
  import { Button } from '../lib/components/ui/button';
  let {
    message,
    examples = false,
    exampleMessage = 'Fictional content for exploring the layout, not live research or real accounts.',
    onToggle,
  }: {
    message: string;
    examples?: boolean;
    exampleMessage?: string;
    onToggle?: () => void;
  } = $props();
</script>

<div class="notice preview-notice" role="status">
  <p>
    {#if examples}<strong>Example preview.</strong> {exampleMessage}{:else}{message}{/if}
  </p>
  {#if onToggle}<Button variant="outline" onclick={onToggle}
      >{examples ? 'Exit example preview' : 'Preview with examples'}</Button
    >{/if}
</div>

<style>
  .preview-notice {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
  }
  p {
    margin: 0;
  }
  @media (max-width: 600px) {
    .preview-notice {
      align-items: start;
      flex-direction: column;
    }
  }
</style>
