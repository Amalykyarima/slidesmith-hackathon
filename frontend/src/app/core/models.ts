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

export interface Generation {
  id: string;
  title: string;
  mode: 'ai' | 'mock';
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
