<script lang="ts">
  let { value }: { value: string } = $props();
</script>

<div class="file-diff" role="region" aria-label="File differences">
  {#each value.split('\n') as line, index (index)}
    <div
      class="diff-line"
      class:added={line.startsWith('+') && !line.startsWith('+++')}
      class:removed={line.startsWith('-') && !line.startsWith('---')}
      class:diff-heading={line.startsWith('@@') || line.startsWith('diff --git')}
    >
      <code>{line || ' '}</code>
    </div>
  {/each}
</div>

<style>
  .file-diff {
    overflow: auto;
    margin: 0;
    padding: 0.6rem 0;
    font:
      0.75rem/1.65 ui-monospace,
      SFMono-Regular,
      Consolas,
      monospace;
    tab-size: 2;
  }
  .diff-line {
    min-width: max-content;
    padding: 0 0.9rem;
    white-space: pre;
  }
  code {
    font: inherit;
  }
  .added {
    background: var(--success-soft);
    color: var(--success);
  }
  .removed {
    background: var(--danger-soft);
    color: var(--danger);
  }
  .diff-heading {
    background: var(--muted);
    color: var(--muted-foreground);
  }
</style>
