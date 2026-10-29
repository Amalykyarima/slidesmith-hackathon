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
export interface Arranged {
  title: Box | null;
  body: Box | null;
  picture: Box | null;
  /** How tall the title and body may grow (fractions of the slide). */
  titleRoom: number | null;
  bodyRoom: number | null;
}

export function arrange(layout: Layout, s: EditSlide, size: [number, number]): Arranged {
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
  // An empty body is dropped by the build, which gives the title more room.
  if (!s.body.some((p) => plain(p).trim())) body = null;
  const moved = body !== layout.body;
  const bodyRoom = body ? (moved ? Math.max(body[3], 1 - 0.35 / h - body[1]) : layout.body_room) : null;
  return { title: layout.title, body, picture, titleRoom: layout.title_room[body ? 0 : 1], bodyRoom };
}

// ----------------------------------------------------------------------------- text fitting
// Mirrors generator.py (fill_text / _fit_pt), so the live preview sizes text like the build.
const CHAR_W_TITLE = 0.66;
const CHAR_W_BODY = 0.56;
const MIN_TITLE_PT = 24;
const MIN_BODY_PT = 14;

function wrappedLines(line: string, cap: number): number {
  let count = 1;
  let used = 0;
  for (const word of line.split(/\s+/).filter(Boolean)) {
    const n = word.length;
    if (used && used + 1 + n <= cap) {
      used += 1 + n;
      continue;
    }
    if (used) count += 1;
    const breaks = n > cap ? Math.floor((n - 1) / cap) : 0;
    count += breaks;
    used = n - breaks * cap;
  }
  return count;
}

function estimateHeight(lines: string[], pt: number, widthPt: number, charW: number): number {
  const cap = Math.max(widthPt / (pt * charW), 1);
  const n = lines.reduce((sum, line) => sum + wrappedLines(line, cap), 0);
  return n * pt * 1.2 + Math.max(lines.length - 1, 0) * pt * 0.3;
}

export interface Fit {
  /** Size for runs the teacher didn't size. */
  pt: number;
  /** Box height after growing, as a fraction of the slide. */
  height: number;
}

/** Size and height a text box ends up with: it grows into `room` first, then the text shrinks. */
export function fitText(
  paragraphs: TextRun[][],
  box: Box,
  room: number | null,
  basePt: number,
  isTitle: boolean,
  size: [number, number],
): Fit {
  const [w, h] = size;
  const lines = paragraphs.map(plain).filter((line) => line.trim());
  const indent = isTitle ? 0 : 18;
  const width = box[2] * w * 72 - 14.4 - indent;
  const boxPt = box[3] * h * 72;
  if (!lines.length || width <= 0 || boxPt <= 7.2) return { pt: basePt, height: box[3] };
  const sized = paragraphs.flat().map((r) => r.size ?? 0).filter((v) => v > 0);
  const charW = isTitle ? CHAR_W_TITLE : CHAR_W_BODY;
  const roomPt = (room ?? box[3]) * h * 72;
  const available = Math.max(boxPt - 7.2, basePt * 1.2, roomPt - 7.2);
  const start = sized.length ? Math.max(...sized) : basePt;
  const min = sized.length ? start : isTitle ? MIN_TITLE_PT : MIN_BODY_PT;
  let pt = start;
  let need = estimateHeight(lines, pt, width, charW);
  while (need > available && pt - 1 >= min) {
    pt -= 1;
    need = estimateHeight(lines, pt, width, charW);
  }
  const grown = Math.min(need + 7.2, Math.max(roomPt, boxPt));
  return { pt: sized.length ? basePt : pt, height: Math.max(box[3], grown / 72 / h) };
}
