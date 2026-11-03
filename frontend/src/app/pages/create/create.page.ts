import { Component, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { ApiService, errorMessage } from '../../core/api.service';
import { BuildSlide, GenerateRequest, Generation, SlideKind, SlideStyle, UploadedImage } from '../../core/models';
import { SlideCanvas } from './slide-canvas';
import { checkVideoLink, VideoLink } from '../../core/video-link';

interface Row {
  key: number;
  page: number;
  details: string;
  image: UploadedImage | null;
  uploading: boolean;
  error: string | null;
  /** Routine slide to copy (e.g. "retrieval"), set by an imported lesson file. */
  role: string;
  /** Speaker notes from an imported lesson file. */
  notes: string;
  /** Video link as typed (shown on the slide as a clickable thumbnail). */
  video: string;
  /** The video link box is open. */
  videoOpen: boolean;
}

/** Shape of a lesson file: { title, slides: [{ page, title, bullets, role, notes }] } or just the slides array. */
interface LessonFileSlide {
  page?: number;
  title?: string;
  subtitle?: string;
  bullets?: unknown;
  role?: string;
  notes?: string;
  video_url?: string;
}

const BULLET_MARK = /^\s*[-•*]\s+/;

const DRAFT_KEY = 'slidesmith.draft.v1';

@Component({
  selector: 'app-create-page',
  imports: [FormsModule, RouterLink, SlideCanvas],
  templateUrl: './create.page.html',
  styleUrl: './create.page.css',
})
export class CreatePage {
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private nextKey = 1;
  private pollTimer: ReturnType<typeof setTimeout> | undefined;

  protected readonly styles = signal<SlideStyle[]>([]);
  protected readonly stylesLoaded = signal(false);
  protected readonly styleId = signal<string | null>(null);

  protected readonly title = signal('');
  /** yyyy-mm-dd. Dates on her sample slides become this one, written her way. */
  protected readonly lessonDate = signal(nextSchoolDay());
  protected readonly lessonDateLabel = computed(() =>
    new Date(this.lessonDate() + 'T12:00:00').toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' }),
  );
  protected readonly nextSchoolDay = nextSchoolDay;
  protected readonly topic = signal('');
  protected readonly instructions = signal('');
  protected readonly rows = signal<Row[]>([this.blankRow(1)]);
  /** On: each page's first line is the title and every further line a bullet, built without the AI. */
  protected readonly exact = signal(false);
  protected readonly notice = signal<string | null>(null);

  protected readonly generating = signal(false);
  /** Seconds since Generate was pressed, so a long wait never looks frozen. */
  protected readonly elapsed = signal(0);
  private elapsedTimer?: ReturnType<typeof setInterval>;
  protected readonly progressNote = computed(() => {
    const t = this.elapsed();
    if (this.exact()) return t < 6 ? 'Putting your text into the style…' : 'Almost done…';
    if (t < 4) return 'Sending your notes…';
    if (t < 35) return 'Writing the text for each slide…';
    if (t < 60) return 'Putting it into your style…';
    return 'Still working: long lessons take a little longer.';
  });
  protected readonly error = signal<string | null>(null);
  protected readonly result = signal<Generation | null>(null);
  /** 1-based number of the slide open in the on-slide editor, or null. */
  protected readonly editingSlide = signal<number | null>(null);

  protected readonly pageProblem = computed(() => {
    const pages = this.rows().map((r) => r.page);
    if (pages.some((p) => !Number.isInteger(p) || p < 1)) return 'Page numbers must be 1 or higher.';
    if (new Set(pages).size !== pages.length) return 'Two slides share the same page number.';
    return null;
  });

  protected readonly filledRows = computed(() => this.rows().filter((r) => r.details.trim() || r.image || r.video.trim()));

  protected readonly canSubmit = computed(
    () =>
      !!this.styleId() &&
      this.filledRows().length > 0 &&
      !this.pageProblem() &&
      !this.rows().some((r) => r.uploading) &&
      !this.rows().some((r) => this.videoError(r)) &&
      !this.generating(),
  );

  constructor() {
    this.restoreDraft();
    void this.loadStyles();

    // Keep what the teacher typed if they refresh or navigate away.
    effect(() => {
      const draft = {
        styleId: this.styleId(),
        title: this.title(),
        topic: this.topic(),
        instructions: this.instructions(),
        exact: this.exact(),
        lessonDate: this.lessonDate(),
        rows: this.rows().map(({ page, details, image, role, notes, video }) => ({ page, details, image, role, notes, video })),
      };
      try {
        localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
      } catch {
        /* storage full or blocked: not critical */
      }
    });

    this.destroyRef.onDestroy(() => clearTimeout(this.pollTimer));
  }

  // ------------------------------------------------------------------ setup
  private blankRow(page: number): Row {
    return { key: this.nextKey++, page, details: '', image: null, uploading: false, error: null, role: '', notes: '', video: '', videoOpen: false };
  }

  private restoreDraft(): void {
    try {
      const raw = localStorage.getItem(DRAFT_KEY);
      if (!raw) return;
      const d = JSON.parse(raw);
      this.styleId.set(d.styleId ?? null);
      this.title.set(d.title ?? '');
      this.topic.set(d.topic ?? '');
      this.instructions.set(d.instructions ?? '');
      this.exact.set(!!d.exact);
      // A date from an old draft that has already passed falls back to the next school day.
      if (typeof d.lessonDate === 'string' && d.lessonDate >= isoDay(new Date())) this.lessonDate.set(d.lessonDate);
      if (Array.isArray(d.rows) && d.rows.length) {
        this.rows.set(
          d.rows.map((r: Partial<Row>) => ({
            ...this.blankRow(r.page ?? 1),
            details: r.details ?? '',
            image: r.image ?? null,
            role: r.role ?? '',
            notes: r.notes ?? '',
            video: r.video ?? '',
            videoOpen: !!r.video,
          })),
        );
      }
    } catch {
      /* ignore corrupt drafts */
    }
  }

  private async loadStyles(): Promise<void> {
    try {
      const list = await firstValueFrom(this.api.listStyles());
      this.styles.set(list);
      const fromLink = this.route.snapshot.queryParamMap.get('style');
      const current = this.styleId();
      const valid = (id: string | null) => !!id && list.some((s) => s.id === id);
      if (valid(fromLink)) this.styleId.set(fromLink);
      else if (!valid(current)) this.styleId.set(list[0]?.id ?? null);
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.stylesLoaded.set(true);
    }
  }

  // ----------------------------------------------------------------- videos
  protected video(r: Row): VideoLink | null {
    const v = checkVideoLink(r.video);
    return v && 'url' in v ? v : null;
  }

  protected videoError(r: Row): string | null {
    const v = checkVideoLink(r.video);
    return v && 'error' in v ? v.error : null;
  }

  protected closeVideo(key: number): void {
    this.patch(key, { video: '', videoOpen: false });
  }

  // ------------------------------------------------------------------- rows
  protected addRow(): void {
    const next = Math.max(0, ...this.rows().map((r) => r.page || 0)) + 1;
    this.rows.update((rows) => [...rows, this.blankRow(next)]);
  }

  protected removeRow(key: number): void {
    const row = this.rows().find((r) => r.key === key);
    if (row?.image) void firstValueFrom(this.api.deleteImage(row.image.id)).catch(() => undefined);
    this.rows.update((rows) => (rows.length > 1 ? rows.filter((r) => r.key !== key) : [this.blankRow(1)]));
  }

  protected patch(key: number, changes: Partial<Row>): void {
    this.rows.update((rows) => rows.map((r) => (r.key === key ? { ...r, ...changes } : r)));
  }

  protected setPage(key: number, value: string): void {
    this.patch(key, { page: Number.parseInt(value, 10) || 0 });
  }

  protected async attach(key: number, event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      this.patch(key, { error: 'Please choose an image file (PNG, JPG, GIF or WEBP).' });
      return;
    }
    this.patch(key, { uploading: true, error: null });
    try {
      const image = await firstValueFrom(this.api.uploadImage(file));
      this.patch(key, { image, uploading: false });
    } catch (err) {
      this.patch(key, { uploading: false, error: errorMessage(err) });
    }
  }

  protected detachImage(key: number): void {
    const row = this.rows().find((r) => r.key === key);
    if (row?.image) void firstValueFrom(this.api.deleteImage(row.image.id)).catch(() => undefined);
    this.patch(key, { image: null });
  }

  // ----------------------------------------------------------- lesson files
  /** Load a lesson file (e.g. alcohol_lesson.json) into the page rows and switch to exact text. */
  protected async importLesson(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    this.error.set(null);
    this.notice.set(null);
    try {
      const data = JSON.parse(await file.text());
      const slides: LessonFileSlide[] = Array.isArray(data) ? data : data?.slides;
      if (!Array.isArray(slides) || slides.length === 0) throw new Error('no slides');
      const rows = slides.map((sl, i) => {
        const bullets = Array.isArray(sl.bullets) ? sl.bullets.filter((b): b is string => typeof b === 'string') : [];
        if (!bullets.length && sl.subtitle) bullets.push(sl.subtitle);
        return {
          ...this.blankRow(Number.isInteger(sl.page) && (sl.page as number) > 0 ? (sl.page as number) : i + 1),
          details: [sl.title ?? '', ...bullets].join('\n').trim(),
          role: typeof sl.role === 'string' ? sl.role : '',
          notes: typeof sl.notes === 'string' ? sl.notes : '',
          video: typeof sl.video_url === 'string' ? sl.video_url : '',
          videoOpen: typeof sl.video_url === 'string' && !!sl.video_url,
        };
      });
      for (const old of this.rows()) {
        if (old.image) void firstValueFrom(this.api.deleteImage(old.image.id)).catch(() => undefined);
      }
      this.rows.set(rows);
      if (!Array.isArray(data) && typeof data.title === 'string') this.title.set(data.title);
      this.exact.set(true);
      this.notice.set(`Loaded ${rows.length} ${rows.length === 1 ? 'slide' : 'slides'} from ${file.name}. Your text will be used exactly as written.`);
    } catch {
      this.error.set(`${file.name} isn't a lesson file SlideSmith can read. It needs a "slides" list with a title and bullets for each page.`);
    }
  }

  /** First line = title, every further line = one bullet. No AI involved. */
  private toExactSlides(): BuildSlide[] {
    const sorted = [...this.filledRows()].sort((a, b) => a.page - b.page);
    return sorted.map((r, i) => {
      const lines = r.details
        .split('\n')
        .map((l) => l.replace(BULLET_MARK, '').trim())
        .filter(Boolean);
      const [title = '', ...bullets] = lines;
      let kind: SlideKind = 'content';
      if (r.image || this.video(r)) kind = 'image';
      else if (!bullets.length) kind = i === 0 ? 'title' : 'section';
      return {
        page: r.page, kind, title, bullets, notes: r.notes, role: r.role,
        image_id: r.image?.id ?? null, video_url: this.video(r)?.url ?? null,
      };
    });
  }

  // --------------------------------------------------------------- generate
  protected async generate(): Promise<void> {
    const styleId = this.styleId();
    if (!styleId || !this.canSubmit()) return;
    this.error.set(null);
    this.notice.set(null);
    this.generating.set(true);
    this.elapsed.set(0);
    clearInterval(this.elapsedTimer);
    this.elapsedTimer = setInterval(() => this.elapsed.update((t) => t + 1), 1000);
    clearTimeout(this.pollTimer);

    const request: GenerateRequest = {
      style_id: styleId,
      title: this.title().trim(),
      lesson_date: this.lessonDate(),
      topic: this.topic().trim(),
      instructions: this.instructions().trim(),
      slides: [...this.filledRows()]
        .sort((a, b) => a.page - b.page)
        .map((r) => ({
          page: r.page, details: r.details.trim(), image_id: r.image?.id ?? null, video_url: this.video(r)?.url ?? null,
        })),
    };

    try {
      const generation = await firstValueFrom(
        this.exact()
          ? this.api.build({ style_id: styleId, title: request.title, slides: this.toExactSlides(), lesson_date: this.lessonDate() })
          : this.api.generate(request),
      );
      this.result.set(generation);
      this.pollPreviews(generation.id, 0);
      setTimeout(() => document.getElementById('result')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      clearInterval(this.elapsedTimer);
      this.generating.set(false);
    }
  }

  private pollPreviews(id: string, attempt: number): void {
    const current = this.result();
    const busy = current?.preview_status === 'pending' || !!current?.updating?.length;
    if (!current || current.id !== id || !busy || attempt > 90) return;
    this.pollTimer = setTimeout(async () => {
      try {
        const fresh = await firstValueFrom(this.api.getGeneration(id));
        // Load changed thumbnails first, so the old picture stays until the new one is ready.
        const old = new Set(this.result()?.previews ?? []);
        await Promise.all(fresh.previews.filter((u) => !old.has(u)).map(preloadImage));
        if (this.result()?.id === id) this.result.set(fresh);
      } catch {
        /* keep trying quietly */
      }
      this.pollPreviews(id, attempt + 1);
    }, attempt < 10 ? 1500 : 3000);
  }

  /** The on-slide editor saved: that slide's thumbnail is redrawn on the server. */
  protected slideSaved(gen: Generation): void {
    clearTimeout(this.pollTimer);
    this.result.set(gen);
    this.pollPreviews(gen.id, 0);
  }

  protected newDeck(): void {
    this.result.set(null);
    this.editingSlide.set(null);
    this.title.set('');
    this.topic.set('');
    this.instructions.set('');
    this.notice.set(null);
    this.rows.set([this.blankRow(1)]);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  private static readonly ROLE_LABELS: Record<string, string> = {
    retrieval: 'Retrieval',
    vocabulary: 'Vocabulary',
    turn_and_talk: 'Turn and Talk',
    we_do: 'We do / MWB',
    you_do: 'You do / Independent',
    homework: 'Homelearning',
    stretch: 'Stretch',
    i_do: 'I do',
    exit: 'Exit routine',
  };

  protected roleLabel(role: string): string {
    return CreatePage.ROLE_LABELS[role] ?? role;
  }

  protected selectedStyle = computed(() => this.styles().find((s) => s.id === this.styleId()) ?? null);
}

function preloadImage(url: string): Promise<void> {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = img.onerror = () => resolve();
    img.src = url;
  });
}

function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** Tomorrow, or Monday after a Friday or weekend. */
function nextSchoolDay(): string {
  const d = new Date();
  do d.setDate(d.getDate() + 1);
  while (d.getDay() === 0 || d.getDay() === 6);
  return isoDay(d);
}
