// Account entry points keep a local destination through sign-in and registration.
export function accountReturnPath(value: string | null | undefined) {
  if (
    !value?.startsWith('/') ||
    value.startsWith('//') ||
    value.includes('\\') ||
    [...value].some((character) => character.charCodeAt(0) <= 32)
  )
    return '/projects';
  const origin = 'https://polycolab.invalid';
  try {
    const url = new URL(value, origin);
    if (
      url.origin !== origin ||
      url.pathname.startsWith('//') ||
      /^\/(signin|signup|auth|oidc)(\/|$)/.test(decodeURIComponent(url.pathname))
    )
      return '/projects';
    return url.pathname.replace(/^\/workspaces(?=\/|$)/, '/projects') + url.search + url.hash;
  } catch {
    return '/projects';
  }
}

export function accountHref(mode: 'signin' | 'signup', destination?: string) {
  const returnTo = accountReturnPath(destination);
  return `/${mode}${returnTo === '/projects' ? '' : `?${new URLSearchParams({ returnTo })}`}`;
}
