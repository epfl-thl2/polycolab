// SvelteKit navigation lifecycle stand-in for component tests.
export function beforeNavigate(_callback: (navigation: { cancel: () => void }) => void) {
  void _callback;
}
