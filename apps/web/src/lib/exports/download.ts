/**
 * Whether a download link from the API may be followed: an https (or, in development, http) link
 * to this project's own Supabase Storage, for the exports bucket only. Anything else is refused,
 * so a compromised or misconfigured API could never turn the download route into an open redirect.
 */
export function isTrustedDownloadLink(link: string, supabaseUrl: string | undefined): boolean {
  if (!supabaseUrl) return false;
  let target: URL;
  let storage: URL;
  try {
    target = new URL(link);
    storage = new URL(supabaseUrl);
  } catch {
    return false;
  }
  if (target.origin !== storage.origin) return false;
  if (
    target.protocol !== "https:" &&
    target.hostname !== "127.0.0.1" &&
    target.hostname !== "localhost"
  ) {
    return false;
  }
  return target.pathname.startsWith("/storage/v1/object/sign/exports/");
}
