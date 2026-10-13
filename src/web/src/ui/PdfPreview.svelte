<script lang="ts">
  import { onMount } from 'svelte';
  import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist';
  import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
  import { Button } from '../lib/components/ui/button';

  let { url }: { url: string } = $props();
  let container: HTMLDivElement;
  let canvas: HTMLCanvasElement;
  let previousRender: Promise<void> = Promise.resolve();
  let renderedPage = $state(0);
  let document = $state.raw<PDFDocumentProxy>();
  let pageNumber = $state(1);
  let width = $state(600);
  let message = $state('Loading PDF…');

  onMount(() => {
    let disposed = false;
    let loading: { destroy: () => Promise<void> } | undefined;
    const observer = new ResizeObserver(([entry]) => {
      width = Math.max(100, Math.floor(entry.contentRect.width));
    });
    observer.observe(container);
    void import('pdfjs-dist')
      .then(async (pdfjs) => {
        if (disposed) return;
        pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
        const task = pdfjs.getDocument({ url, maxImageSize: 16_000_000 });
        loading = task;
        const pdf = await task.promise;
        if (!disposed) document = pdf;
      })
      .catch(() => {
        if (!disposed) message = 'Could not preview this PDF. Use Download PDF to open it.';
      });
    return () => {
      disposed = true;
      observer.disconnect();
      void loading?.destroy();
    };
  });

  $effect(() => {
    const pdf = document;
    const number = pageNumber;
    const availableWidth = width;
    if (!pdf) return;
    let cancelled = false;
    let task: RenderTask | undefined;
    message = 'Rendering PDF…';
    renderedPage = 0;
    void pdf
      .getPage(number)
      .then(async (page) => {
        await previousRender.catch(() => {});
        if (cancelled) return;
        const natural = page.getViewport({ scale: 1 });
        const scale = Math.min(2, availableWidth / natural.width);
        const viewport = page.getViewport({ scale });
        canvas.width = Math.ceil(viewport.width);
        canvas.height = Math.ceil(viewport.height);
        task = page.render({ canvas, viewport });
        previousRender = task.promise;
        await previousRender;
        if (!cancelled) {
          renderedPage = number;
          message = '';
        }
      })
      .catch(() => {
        if (!cancelled) message = 'Could not render this page. Use Download PDF to open it.';
      });
    return () => {
      cancelled = true;
      task?.cancel();
    };
  });
</script>

<div class="pdf-preview" aria-label="Compiled PDF">
  {#if document}
    <nav aria-label="PDF pages">
      <Button size="sm" variant="outline" disabled={pageNumber === 1} onclick={() => pageNumber--}
        >Previous page</Button
      >
      <span>Page {pageNumber} of {document.numPages}</span>
      <Button
        size="sm"
        variant="outline"
        disabled={pageNumber === document.numPages}
        onclick={() => pageNumber++}>Next page</Button
      >
    </nav>
  {/if}
  {#if message}<p>{message}</p>{/if}
  <div
    class="pdf-page"
    bind:this={container}
    role="img"
    aria-label={`PDF page ${renderedPage}`}
    style:visibility={renderedPage ? 'visible' : 'hidden'}
  >
    <canvas bind:this={canvas} aria-hidden="true"></canvas>
  </div>
</div>

<style>
  .pdf-preview {
    flex: 1;
    min-height: 300px;
  }
  nav {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    margin-bottom: 0.5rem;
  }
  .pdf-page {
    width: 100%;
  }
  .pdf-page canvas {
    display: block;
    max-width: 100%;
    height: auto;
    background: white;
    margin: auto;
  }
</style>
