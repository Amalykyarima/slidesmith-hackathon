/** Video links on slides (same rules as backend/app/videos.py). */
export interface VideoLink {
  url: string;
  host: string;
  /** YouTube's 11-character video id, when it is a YouTube link. */
  youtubeId: string | null;
}

const YT_ID = /^[A-Za-z0-9_-]{11}$/;

/** null for an empty box; { error } when it isn't a usable link. */
export function checkVideoLink(raw: string): VideoLink | { error: string } | null {
  let text = raw.trim();
  if (!text) return null;
  if (!text.includes('://')) text = 'https://' + text;
  let u: URL;
  try {
    u = new URL(text);
  } catch {
    return { error: "That doesn't look like a web link. Copy it from the browser's address bar." };
  }
  if (!/^https?:$/.test(u.protocol) || !/^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(u.hostname) || /\s/.test(text)) {
    return { error: "That doesn't look like a web link. Copy it from the browser's address bar." };
  }
  return { url: text, host: u.hostname.replace(/^www\./, ''), youtubeId: youtubeId(u) };
}

function youtubeId(u: URL): string | null {
  const host = u.hostname.replace(/^(www|m|music)\./, '');
  let id: string | null = null;
  if (host === 'youtu.be') id = u.pathname.split('/')[1] ?? null;
  else if (host === 'youtube.com' || host === 'youtube-nocookie.com') {
    if (u.pathname === '/watch') id = u.searchParams.get('v');
    else {
      const [kind, value] = u.pathname.split('/').filter(Boolean);
      if (['shorts', 'embed', 'live', 'v'].includes(kind)) id = value ?? null;
    }
  }
  return id && YT_ID.test(id) ? id : null;
}
