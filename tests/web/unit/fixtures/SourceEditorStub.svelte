<script lang="ts">
  let {
    value = $bindable(),
    readOnly = false,
    onEdit,
  }: {
    value: string;
    readOnly?: boolean;
    onEdit?: () => void;
  } = $props();
</script>

<textarea aria-label="File contents" bind:value readonly={readOnly} oninput={() => onEdit?.()}
></textarea>
