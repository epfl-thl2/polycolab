<script lang="ts">
  import { onDestroy } from 'svelte';
  import * as AlertDialog from '../lib/components/ui/alert-dialog';
  import { Button } from '../lib/components/ui/button';
  import type { Confirmation } from '../svelte-lib/confirmation.svelte';
  let { confirmation }: { confirmation: Confirmation } = $props();
  onDestroy(() => confirmation.finish(false));
</script>

<AlertDialog.Root
  open={confirmation.open}
  onOpenChange={(open) => {
    if (!open) confirmation.finish(false);
  }}
>
  <AlertDialog.Content
    onCloseAutoFocus={(event) => {
      event.preventDefault();
      confirmation.restoreFocus();
    }}
  >
    <AlertDialog.Header>
      <AlertDialog.Title>Confirm action</AlertDialog.Title>
      <AlertDialog.Description>{confirmation.message}</AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <Button variant="outline" onclick={() => confirmation.finish(false)}>Cancel</Button>
      <Button variant="destructive" onclick={() => confirmation.finish(true)}>Confirm</Button>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
