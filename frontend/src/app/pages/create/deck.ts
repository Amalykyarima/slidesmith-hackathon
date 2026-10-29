import { Box, BuildSlide, ImagePosition, Layout, SlideContent, TextAlign, TextAnchor, TextRun, UploadedImage } from '../../core/models';

export type EditKind = 'title' | 'content' | 'section';

/** One slide in the editor: what the teacher typed and chose. The cover is one too. */
export interface EditSlide {
  key: number;
  kind: EditKind;
  /** The title as runs (one line). */
  title: TextRun[];
  /** One array of runs per line: bullet points, or the subtitle on a cover/section slide. */
  body: TextRun[][];
  notes: string;
  image: UploadedImage | null;
  image_position: ImagePosition;
  text_align: TextAlign;
  text_anchor: TextAnchor;
}

export const COVER_KEY = 0;

export function blankSlide(key: number, kind: EditKind = 'content'): EditSlide {
  return { key, kind, title: [], body: [], notes: '', image: null, image_position: 'auto', text_align: 'auto', text_anchor: 'auto' };
}

export function plain(runs: TextRun[]): string {
  return runs.map((r) => r.text).join('');
}

/** Title and body as plain lines: the rough notes the AI works from. */
export function notesOf(s: EditSlide): string {
  return [plain(s.title), ...s.body.map(plain)].map((line) => line.trim()).filter(Boolean).join('\n');
}

export function isEmpty(s: EditSlide): boolean {
  return !notesOf(s) && !s.image;
}

/** Which blank slide the build will start from (a picture always picks the picture sample). */
export function layoutKind(s: EditSlide, cover: boolean): Layout['kind'] {
  if (cover) return 'title';
  return s.image ? 'image' : s.kind;
}

/** Everything that changes the built slide, so edits since the last build can be spotted. */
export function signature(s: EditSlide, page: number): string {
  return JSON.stringify([page, s.kind, s.title, s.body, s.notes, s.image?.id ?? null, s.image_position, s.text_align, s.text_anchor]);
}

export function toBuildSlide(s: EditSlide, page: number): BuildSlide {
  const lines = s.body.map(plain);
  const subtitle = page === 0 || s.kind !== 'content';
  return {
    page,
    kind: s.kind,
    title: plain(s.title).trim(),
    subtitle: subtitle ? lines.join(' ').trim() : '',
    bullets: subtitle ? [] : lines,
    notes: s.notes,
    title_runs: s.title.length ? s.title : null,
    body_runs: s.body,
    image_position: s.image_position,
    text_align: s.text_align,
    text_anchor: s.text_anchor,
    image_id: s.image?.id ?? null,
  };
}

/** Puts what the AI wrote into an editor slide, keeping the teacher's picture and layout choices. */
export function fromContent(s: EditSlide, c: SlideContent, hasCover: boolean): EditSlide {
  const lines = c.bullets.length ? c.bullets : c.subtitle ? [c.subtitle] : [];
  let kind: EditKind = c.kind === 'image' ? 'content' : c.kind;
  if (kind === 'title' && hasCover) kind = 'section';
  return {
    ...s,
    kind,
    title: c.title ? [{ text: c.title }] : [],
    body: lines.map((text) => [{ text }]),
    notes: c.notes || s.notes,
  };
}

/** Where the title, body and picture land: mirrors the generator's preset positions. */
export function arrange(layout: Layout, s: EditSlide, size: [number, number]): { title: Box | null; body: Box | null; picture: Box | null } {
  const [w, h] = size;
  const gapX = 0.3 / w;
  const gapY = 0.3 / h;
  let body = layout.body;
  let picture: Box | null = null;
  if (s.image && s.image_position !== 'none') {
    const pos = s.image_position;
    if (pos === 'auto') {
      if (layout.picture) picture = layout.picture;
      else if (body) {
        const [l, t, bw, bh] = body;
        const nw = bw * 0.54;
        const il = l + nw + gapX;
        body = [l, t, nw, bh];
        picture = [il, t, Math.max(1 - il - 0.5 / w, 0.2), bh];
      } else picture = [0.5, 0.32, 0.5 - 0.5 / w, 0.6];
    } else {
      const [l, t, aw, ah] = layout.area;
      const sw = aw * 0.45;
      const sh = ah * 0.55;
      const keep = (box: Box): Box | null => (body ? box : null);
      if (pos === 'left') {
        picture = [l, t, sw, ah];
        body = keep([l + sw + gapX, t, aw - sw - gapX, ah]);
      } else if (pos === 'right') {
        body = keep([l, t, aw - sw - gapX, ah]);
        picture = [l + aw - sw, t, sw, ah];
      } else if (pos === 'top') {
        picture = [l, t, aw, sh];
        body = keep([l, t + sh + gapY, aw, ah - sh - gapY]);
      } else {
        picture = layout.area;
        body = null; // bullets move to the speaker notes
      }
    }
  }
  return { title: layout.title, body, picture };
}
