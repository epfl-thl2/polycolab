const container = document.getElementById('polycolab-api-reference');

const scalarThemeCss = String.raw`
  .scalar-app { --refs-header-height: 64px; }
  .light-mode {
    --scalar-background-1: var(--polycolab-white);
    --scalar-background-2: var(--polycolab-surface-subtle);
    --scalar-background-3: var(--polycolab-surface-muted);
    --scalar-background-accent: var(--polycolab-canard-soft);
    --scalar-color-1: var(--polycolab-ink);
    --scalar-color-2: var(--polycolab-ink-subtle);
    --scalar-color-3: var(--polycolab-epfl-taupe);
    --scalar-color-accent: var(--polycolab-epfl-canard);
    --scalar-border-color: var(--polycolab-border);
    --scalar-link-color: var(--polycolab-epfl-canard);
    --scalar-link-color-hover: var(--polycolab-canard-strong);
    --scalar-sidebar-color-active: var(--polycolab-epfl-canard);
    --scalar-sidebar-item-active-background: var(--polycolab-canard-soft);
    --scalar-button-1: var(--polycolab-epfl-canard);
    --scalar-button-1-hover: var(--polycolab-canard-strong);
    --scalar-button-1-color: var(--polycolab-white);
    --scalar-color-danger: var(--polycolab-danger);
  }
  .dark-mode {
    --scalar-background-1: var(--polycolab-dark-surface);
    --scalar-background-2: var(--polycolab-dark-surface-raised);
    --scalar-background-3: var(--polycolab-dark-surface-muted);
    --scalar-background-accent: color-mix(
      in srgb,
      var(--polycolab-epfl-leman) 16%,
      transparent
    );
    --scalar-color-1: var(--polycolab-dark-foreground);
    --scalar-color-2: var(--polycolab-dark-foreground-muted);
    --scalar-color-3: var(--polycolab-epfl-perle);
    --scalar-color-accent: var(--polycolab-epfl-leman);
    --scalar-border-color: var(--polycolab-dark-border);
    --scalar-link-color: var(--polycolab-epfl-leman);
    --scalar-link-color-hover: var(--polycolab-white);
    --scalar-sidebar-color-active: var(--polycolab-epfl-leman);
    --scalar-sidebar-item-active-background: color-mix(
      in srgb,
      var(--polycolab-epfl-leman) 12%,
      transparent
    );
    --scalar-button-1: var(--polycolab-epfl-leman);
    --scalar-button-1-hover: var(--polycolab-epfl-canard);
    --scalar-button-1-color: var(--polycolab-dark-surface);
    --scalar-color-danger: var(--polycolab-epfl-red);
  }
  a[href='https://www.scalar.com'] { display: none; }
`;

if (container) {
  // Scalar supplies its own typography. Removing Zensical's prose class from
  // this page prevents its element-level content rules from leaking into Scalar.
  container.closest('.md-content__inner')?.classList.remove('md-typeset');

  const isDark = () => document.body.dataset.mdColorScheme === 'slate';
  let mountedDarkMode;
  let reference;

  const mountReference = async () => {
    if (!window.Scalar) return;
    const darkMode = isDark();
    if (darkMode === mountedDarkMode) return;

    const scrollPosition = window.scrollY;
    reference?.unmount?.();
    container.replaceChildren();
    reference = await window.Scalar.createApiReference(container, {
      url: '/api/openapi.json',
      proxyUrl: '',
      telemetry: false,
      isEditable: false,
      persistAuth: false,
      showDeveloperTools: 'never',
      customCss: scalarThemeCss,
      defaultOpenFirstTag: false,
      hideClientButton: true,
      hideDarkModeToggle: true,
      darkMode,
      generateHeadingSlug: (heading) =>
        heading.slug === 'start-here' ? '' : `#description/${heading.slug}`,
      hideTestRequestButton: true,
      agent: { disabled: true },
      mcp: { disabled: true },
      pluginUrls: [],
    });
    mountedDarkMode = darkMode;
    requestAnimationFrame(() => window.scrollTo(0, scrollPosition));
  };

  const scalar = document.createElement('script');
  scalar.src =
    'https://cdn.jsdelivr.net/npm/@scalar/api-reference@1.62.6/dist/browser/standalone.js';
  scalar.integrity = 'sha384-N7JUv0+P4dgRu102bnNFxOXOXp2ROTMToXk71fUs0MNI1wZpfxZYHVAJTnVMS19o';
  scalar.crossOrigin = 'anonymous';
  scalar.addEventListener('load', mountReference);
  scalar.addEventListener('error', () => {
    container.textContent = 'The API reference could not be loaded.';
  });
  document.head.append(scalar);

  new MutationObserver(mountReference).observe(document.body, {
    attributes: true,
    attributeFilter: ['data-md-color-scheme'],
  });
}
