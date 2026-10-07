const observedRoots = new WeakSet();

function labelSearchControls(root) {
  const buttons = [...root.querySelectorAll('button:not([aria-label])')];
  if (root instanceof HTMLButtonElement && !root.hasAttribute('aria-label')) buttons.push(root);
  for (const button of buttons) {
    if (button.querySelector('svg.lucide-search')) button.setAttribute('aria-label', 'Search');
    if (button.querySelector('svg.lucide-list-filter'))
      button.setAttribute('aria-label', 'Filter search results');
  }
}

function observeRoot(root) {
  if (!observedRoots.has(root)) {
    observer.observe(root, { childList: true, subtree: true });
    observedRoots.add(root);
  }
  labelSearchControls(root);
  if (root instanceof Element && root.shadowRoot) observeRoot(root.shadowRoot);
  for (const element of root.querySelectorAll('*')) {
    if (element.shadowRoot) observeRoot(element.shadowRoot);
  }
}

const observer = new MutationObserver((records) => {
  for (const record of records) {
    for (const node of record.addedNodes) {
      if (node instanceof Element) observeRoot(node);
    }
  }
});

observeRoot(document.body);
