/** One confirmation controller per mounted screen; dismissal always cancels. */
export class Confirmation {
  open = $state(false);
  message = $state('');
  private origin?: HTMLElement;
  private resolve?: (confirmed: boolean) => void;

  ask(message: string): Promise<boolean> {
    this.finish(false);
    this.origin =
      document.activeElement instanceof HTMLElement ? document.activeElement : undefined;
    this.message = message;
    this.open = true;
    return new Promise((resolve) => {
      this.resolve = resolve;
    });
  }

  restoreFocus() {
    const target = this.origin?.isConnected ? this.origin : document.getElementById('main');
    target?.focus();
  }

  finish(confirmed: boolean) {
    this.open = false;
    this.resolve?.(confirmed);
    this.resolve = undefined;
  }
}
