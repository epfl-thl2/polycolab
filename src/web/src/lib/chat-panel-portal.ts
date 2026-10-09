export function chatPanelPortal(node: HTMLElement, active = true) {
  const origin = document.createComment('chat panel origin');
  node.before(origin);
  let frame = 0;
  const move = () => {
    if (!active) {
      if (origin.parentElement && node.parentNode !== origin.parentNode) origin.after(node);
      node.hidden = true;
      return;
    }
    node.hidden = false;
    const placement = matchMedia('(max-width: 760px)').matches ? 'mobile' : 'desktop';
    const host = document.querySelector<HTMLElement>(`[data-chat-panel-host="${placement}"]`);
    if (host) {
      if (node.parentElement !== host) host.append(node);
    } else {
      if (origin.parentElement && node.parentNode !== origin.parentNode) origin.after(node);
      node.hidden = true;
    }
  };
  const schedule = () => {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      move();
    });
  };
  const observer = new MutationObserver(schedule);
  observer.observe(document.body, { childList: true, subtree: true });
  window.addEventListener('resize', schedule);
  move();
  return {
    update(value: boolean) {
      active = value;
      move();
    },
    destroy() {
      observer.disconnect();
      window.removeEventListener('resize', schedule);
      if (frame) cancelAnimationFrame(frame);
      node.remove();
      origin.remove();
    },
  };
}
