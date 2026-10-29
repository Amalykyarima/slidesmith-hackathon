export type SlideKind = 'title' | 'content' | 'image' | 'section';
export type PreviewStatus = 'pending' | 'ready' | 'unavailable' | 'failed';

export interface StyleProfile {
  slide_count: number;
  slide_size_in: [number, number];
  fonts: string[];
  palette: string[];
  background_tone: 'dark' | 'light' | 'image';
  kinds: Record<string, number>;
  capacity: { max_bullets: number; max_words_per_bullet: number };
}

export interface SlideStyle {
  id: string;
  name: string;
  filename: string;
  created_at: string;
  profile: StyleProfile;
  preview_status: PreviewStatus;
  previews: string[];
}

export interface UploadedImage {
  id: string;
  filename: string;
  width: number;
  height: number;
  url: string;
}

export interface SlideSpec {
  page: number;
  details: string;
  image_id: string | null;
}

export interface GenerateRequest {
  style_id: string;
  /** Adds a cover slide (title + subtitle, as typed) before the numbered slides. */
  cover: boolean;
  title: string;
  subtitle: string;
  topic: string;
  instructions: string;
  slides: SlideSpec[];
}

export type ImagePosition = 'auto' | 'left' | 'right' | 'top' | 'large' | 'none';
export type TextAlign = 'auto' | 'left' | 'center' | 'right';
export type TextAnchor = 'auto' | 'top' | 'middle' | 'bottom';

/** A stretch of text with the teacher's formatting. Unset fields keep the template's style. */
export interface TextRun {
  text: string;
  bold?: boolean | null;
  italic?: boolean | null;
  underline?: boolean | null;
  size?: number | null;
  font?: string | null;
  color?: string | null;
  highlight?: string | null;
}

export interface SlideContent {
  page: number;
  kind: SlideKind;
  title: string;
  subtitle: string;
  bullets: string[];
  notes: string;
  /** Set by the slide editor; replace title / bullets when present. */
  title_runs?: TextRun[] | null;
  body_runs?: TextRun[][] | null;
  image_position?: ImagePosition;
  text_align?: TextAlign;
  text_anchor?: TextAnchor;
}

/** A slide as the editor sends it for building: exactly as shown, plus its picture. */
export interface BuildSlide extends SlideContent {
  image_id: string | null;
}

export interface BuildRequest {
  style_id: string;
  title: string;
  slides: BuildSlide[];
}

/** Slide text the AI (or demo mode) wrote from the teacher's notes; nothing is built yet. */
export interface Draft {
  mode: 'ai' | 'mock';
  slides: SlideContent[];
}

export interface CookRequest {
  style_id: string;
  topic: string;
  description: string;
  /** null: the AI decides. */
  slide_count: number | null;
  image_ids: string[];
}

/** A whole deck the AI planned and wrote; nothing is built yet. */
export interface Cooked {
  mode: 'ai' | 'mock';
  cover: SlideContent;
  slides: (SlideContent & { image_id: string | null })[];
}

/** How a sample's text looks, so the live preview can imitate it. Null: not known. */
export interface TextLook {
  size: number;
  bold: boolean | null;
  italic: boolean | null;
  color: string | null;
  font: string | null;
  align: 'left' | 'center' | 'right' | null;
  anchor: 'top' | 'middle' | 'bottom' | null;
  bullets: boolean;
}

/** Box as fractions of the slide: [left, top, width, height]. */
export type Box = [number, number, number, number];

/** One blank slide of the style and where it puts its title, body and picture. */
export interface Layout {
  kind: 'title' | 'content' | 'image' | 'section';
  title: Box | null;
  body: Box | null;
  picture: Box | null;
  /** Space the body and picture share; preset picture positions split it. */
  area: Box;
  /** How tall the title may grow (fraction of the slide): with the body there, and without it. */
  title_room: [number | null, number | null];
  body_room: number | null;
  title_look: TextLook | null;
  body_look: TextLook | null;
  /** The blank slide rendered, once ready. */
  image: string | null;
}

export interface StyleLayouts {
  status: PreviewStatus;
  slide_size_in: [number, number];
  background_tone: 'dark' | 'light' | 'image';
  layouts: Layout[];
}

export interface Generation {
  id: string;
  title: string;
  /** manual: built from the editor exactly as typed. */
  mode: 'ai' | 'mock' | 'manual';
  style_id: string;
  created_at: string;
  slides: SlideContent[];
  warnings: string[];
  download_url: string;
  /** Pages that have a picture attached (their position can be changed). */
  image_pages: number[];
  preview_status: PreviewStatus;
  previews: string[];
}

export interface Health {
  ok: boolean;
  ai_enabled: boolean;
  model: string | null;
  previews_enabled: boolean;
}
