export function teamHref(slug: string | null | undefined): string | null {
  if (!slug) return null;
  return `/teams/${encodeURIComponent(slug)}`;
}

export function teamSlugFromPath(pathname: string): string | null {
  const match = /^\/teams\/([^/]+)\/?$/.exec(pathname);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return null;
  }
}
