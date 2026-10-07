<script lang="ts">
  let { compact = false, descriptionId }: { compact?: boolean; descriptionId?: string } = $props();
</script>

<span class="brand-wordmark" class:compact>
  <span class="wordmark-name">Polycolab</span><sup
    id={descriptionId}
    title="Polycolab is in alpha development"
    ><span class="sr-only">Alpha development</span><span aria-hidden="true">α</span></sup
  >
</span>

<style>
  .brand-wordmark {
    display: inline-flex;
    align-items: baseline;
    gap: 2px;
    white-space: nowrap;
    font-weight: 600;
    letter-spacing: -0.04em;
  }
  sup {
    position: relative;
    top: -0.5em;
    font-family: 'Cambria Math', 'STIX Two Math', 'Times New Roman', serif;
    font-size: 0.75em;
    font-style: italic;
    font-weight: 400;
    line-height: 0;
    letter-spacing: 0;
  }
  @media (max-width: 1279px) {
    .brand-wordmark.compact {
      display: none;
    }
  }
</style>
