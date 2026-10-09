<script lang="ts">
  import * as Field from '../lib/components/ui/field';
  import * as Alert from '../lib/components/ui/alert';
  import { Textarea } from '../lib/components/ui/textarea';
  import { Button } from '../lib/components/ui/button';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import { explain } from '../svelte-lib/context';

  type ProgressStatus = 'POTENTIAL' | 'PARTIAL' | 'COMPLETE' | 'STALLED' | 'FAILED';

  let {
    targetRevisionId,
    comment,
    progress,
    onSaved,
  }: {
    targetRevisionId: string;
    comment: (body: string, retryKey: string) => Promise<unknown>;
    progress: (status: ProgressStatus, detail: string, retryKey: string) => Promise<unknown>;
    onSaved: () => Promise<void>;
  } = $props();

  let commentBody = $state('');
  let progressStatus = $state<ProgressStatus>('PARTIAL');
  let progressDetail = $state('');
  let commentBusy = $state(false);
  let progressBusy = $state(false);
  let commentError = $state('');
  let progressError = $state('');
  let status = $state('');
  let commentReceipt: { body: string; key: string } | undefined;
  let progressReceipt: { body: string; key: string } | undefined;

  function retry(
    previous: { body: string; key: string } | undefined,
    body: string,
  ): { body: string; key: string } {
    return previous?.body === body ? previous : { body, key: crypto.randomUUID() };
  }

  async function submitComment() {
    commentReceipt = retry(commentReceipt, commentBody);
    commentBusy = true;
    commentError = '';
    status = '';
    try {
      await comment(commentBody, commentReceipt.key);
      commentBody = '';
      commentReceipt = undefined;
      await onSaved();
      status = 'Comment added to the exact version.';
    } catch (cause) {
      commentError = `${explain(cause)} Your comment draft is retained.`;
    } finally {
      commentBusy = false;
    }
  }

  async function submitProgress() {
    const body = JSON.stringify({ progressStatus, progressDetail });
    progressReceipt = retry(progressReceipt, body);
    progressBusy = true;
    progressError = '';
    status = '';
    try {
      await progress(progressStatus, progressDetail, progressReceipt.key);
      progressDetail = '';
      progressReceipt = undefined;
      await onSaved();
      status = 'Progress reported for the exact version.';
    } catch (cause) {
      progressError = `${explain(cause)} Your progress draft is retained.`;
    } finally {
      progressBusy = false;
    }
  }
</script>

<section class="panel" aria-labelledby={`research-actions-${targetRevisionId}`}>
  <h3 id={`research-actions-${targetRevisionId}`}>Contribute to this exact version</h3>
  <p class="muted">Comments and progress are independent append-only activity streams.</p>
  {#if status}<p role="status">{status}</p>{/if}
  <div class="forms">
    <form
      onsubmit={(event) => {
        event.preventDefault();
        void submitComment();
      }}
    >
      <Field.Label
        >Comment<Textarea required maxlength={100000} bind:value={commentBody}
        ></Textarea></Field.Label
      >
      {#if commentError}<Alert.Root variant="destructive" role="alert">{commentError}</Alert.Root
        >{/if}
      <Button type="submit" disabled={commentBusy}>Add comment</Button>
    </form>
    <form
      onsubmit={(event) => {
        event.preventDefault();
        void submitProgress();
      }}
    >
      <Field.Label
        >Reported progress<NativeSelect bind:value={progressStatus}
          ><option value="POTENTIAL">Potential</option><option value="PARTIAL">Partial</option
          ><option value="COMPLETE">Complete</option><option value="STALLED">Stalled</option><option
            value="FAILED">Failed</option
          ></NativeSelect
        ></Field.Label
      >
      <Field.Label
        >Progress detail<Textarea required maxlength={100000} bind:value={progressDetail}
        ></Textarea></Field.Label
      >
      {#if progressError}<Alert.Root variant="destructive" role="alert">{progressError}</Alert.Root
        >{/if}
      <Button type="submit" disabled={progressBusy}>Report progress</Button>
    </form>
  </div>
</section>

<style>
  section,
  form {
    display: grid;
    gap: 0.75rem;
  }
  .forms {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 18rem), 1fr));
    gap: 1rem;
  }
  h3,
  p {
    margin-top: 0;
  }
</style>
