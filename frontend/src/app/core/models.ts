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
  title: string;
  topic: string;
  instructions: string;
  slides: SlideSpec[];
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
}

export interface BuildRequest {
  style_id: string;
  title: string;
  slides: BuildSlide[];
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
}

export interface Health {
  ok: boolean;
  ai_enabled: boolean;
  model: string | null;
  previews_enabled: boolean;
}
