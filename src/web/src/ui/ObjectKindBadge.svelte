<script lang="ts">
  import { objectKindVisual } from '../lib/object-kind-visual';
  let { kind }: { kind: string } = $props();
  const visual = $derived(objectKindVisual(kind));
</script>

<span class="kind-badge" style={`--kind-color:var(${visual.color})`} data-object-kind={kind}>
  <visual.icon size={14} aria-hidden="true" />{visual.label}
</span>

<style>
  .kind-badge {
    display: inline-flex;
    align-items: center;
    justify-self: start;
    gap: 5px;
    width: fit-content;
    padding: 2px 6px;
    border-radius: 4px;
    color: var(--kind-color);
    background: color-mix(in srgb, var(--kind-color) 9%, var(--panel));
    font-size: 11px;
    line-height: 16px;
    font-weight: 400;
    white-space: nowrap;
  }
</style>
