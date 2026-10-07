class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = ResizeObserverStub;

Object.defineProperty(window, 'matchMedia', {
  configurable: true,
  value: (media: string): MediaQueryList => ({
    matches: false,
    media,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => true,
  }),
});

const originalGetComputedStyle = window.getComputedStyle;
window.getComputedStyle = ((element: Element, pseudo?: string | null) => {
  try {
    return originalGetComputedStyle.call(window, element, pseudo);
  } catch (error) {
    // jsdom 27's internal style resolver crashes on SVG/MathML elements when
    // Testing Library checks their accessibility state. Those elements are
    // visible by default in this fixture, so return the relevant defaults.
    if (error instanceof TypeError && /forEach called on null or undefined/.test(error.message)) {
      const style = new CSSStyleDeclaration();
      style.display = '';
      style.visibility = 'visible';
      style.setProperty('content-visibility', 'visible');
      return style;
    }
    throw error;
  }
}) as typeof window.getComputedStyle;
