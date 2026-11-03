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
  video_url?: string | null;
}

export interface GenerateRequest {
  style_id: string;
  title: string;
  topic: string;
  instructions: string;
  slides: SlideSpec[];
  /** yyyy-mm-dd */
  lesson_date?: string;
}

export interface SlideContent {
  page: number;
  kind: SlideKind;
  title: string;
  subtitle: string;
  bullets: string[];
  notes: string;
  role?: string;
}

/** A finished slide sent word for word to POST /api/build (no AI). */
export interface BuildSlide {
  page: number;
  kind: SlideKind;
  title: string;
  bullets: string[];
  notes: string;
  role: string;
  image_id: string | null;
  video_url?: string | null;
}

export interface BuildRequest {
  style_id: string;
  title: string;
  slides: BuildSlide[];
  lesson_date?: string;
}

export interface Generation {
  id: string;
  title: string;
  mode: 'ai' | 'mock' | 'exact';
  style_id: string;
  created_at: string;
  slides: SlideContent[];
  warnings: string[];
  download_url: string;
  preview_status: PreviewStatus;
  previews: string[];
  rev?: number;
  /** Slides whose thumbnails are being redrawn after an edit. */
  updating?: number[];
}

/** One run of text with its look, as the slide editor shows and saves it (sizes in points). */
export interface SceneRun {
  text: string;
  size: number;
  color: string;
  bold: boolean;
  italic: boolean;
  underline: boolean;
  font?: string | null;
}

export interface SceneParagraph {
  align: 'l' | 'ctr' | 'r' | 'just' | string;
  level: number;
  bullet: string | null;
  runs: SceneRun[];
}

/** A text box or picture on a slide. Positions and sizes in EMU (914400 per inch). */
export interface SceneShape {
  id: number;
  kind: 'text' | 'picture';
  x: number;
  y: number;
  w: number;
  h: number;
  rotation: number;
  /** Its frame is part of the background (style/gradient fill): text editable, not movable. */
  fixed: boolean;
  fill?: string | null;
  border?: { color: string; width: number } | null;
  anchor?: string;
  insets?: { l: number; t: number; r: number; b: number };
  paragraphs?: SceneParagraph[];
  src?: string;
}

export interface SlideScene {
  number: number;
  count: number;
  width: number;
  height: number;
  background: string | null;
  /** The background is still being drawn: fetch it from slideBackground(). */
  background_pending?: boolean;
  rev: number;
  shapes: SceneShape[];
}

export interface ShapeEdit {
  id: number;
  x?: number;
  y?: number;
  w?: number;
  h?: number;
  paragraphs?: { runs: Partial<SceneRun>[] }[];
}

export interface Health {
  ok: boolean;
  ai_enabled: boolean;
  model: string | null;
  previews_enabled: boolean;
}
