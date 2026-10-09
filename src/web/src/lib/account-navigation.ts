// Account entry points keep a local destination through sign-in and registration.
export function accountReturnPath(value: string | null | undefined) {
  if (
    !value?.startsWith('/') ||
    value.startsWith('//') ||
    value.includes('\\') ||
    [...value].some((character) => character.charCodeAt(0) <= 32)
  )
    return '/workspaces';
  const origin = 'https://polycolab.invalid';
  try {
    const url = new URL(value, origin);
    if (
      url.origin !== origin ||
      url.pathname.startsWith('//') ||
      /^\/(signin|signup|auth|oidc)(\/|$)/.test(decodeURIComponent(url.pathname))
    )
      return '/workspaces';
    return url.pathname + url.search + url.hash;
  } catch {
    return '/workspaces';
  }
}

export function accountHref(mode: 'signin' | 'signup', destination?: string) {
  const returnTo = accountReturnPath(destination);
  return `/${mode}${returnTo === '/workspaces' ? '' : `?${new URLSearchParams({ returnTo })}`}`;
}
