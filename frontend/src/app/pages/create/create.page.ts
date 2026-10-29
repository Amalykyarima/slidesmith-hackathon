import { Component, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { ApiService, errorMessage } from '../../core/api.service';
import { GenerateRequest, Generation, SlideStyle, UploadedImage } from '../../core/models';
import { Lightbox } from '../../shared/lightbox';

interface Row {
  key: number;
  page: number;
  details: string;
  image: UploadedImage | null;
  uploading: boolean;
  error: string | null;
}

const DRAFT_KEY = 'slidesmith.draft.v1';

@Component({
  selector: 'app-create-page',
  imports: [FormsModule, RouterLink, Lightbox],
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
  protected readonly topic = signal('');
  protected readonly instructions = signal('');
  protected readonly rows = signal<Row[]>([this.blankRow(1)]);

  protected readonly generating = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly result = signal<Generation | null>(null);
  /** Index of the result preview open full-size, or null. */
  protected readonly viewing = signal<number | null>(null);

  protected readonly pageProblem = computed(() => {
    const pages = this.rows().map((r) => r.page);
    if (pages.some((p) => !Number.isInteger(p) || p < 1)) return 'Page numbers must be 1 or higher.';
    if (new Set(pages).size !== pages.length) return 'Two slides share the same page number.';
    return null;
  });

  protected readonly filledRows = computed(() => this.rows().filter((r) => r.details.trim() || r.image));

  protected readonly canSubmit = computed(
    () =>
      !!this.styleId() &&
      this.filledRows().length > 0 &&
      !this.pageProblem() &&
      !this.rows().some((r) => r.uploading) &&
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
        rows: this.rows().map(({ page, details, image }) => ({ page, details, image })),
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
    return { key: this.nextKey++, page, details: '', image: null, uploading: false, error: null };
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
      if (Array.isArray(d.rows) && d.rows.length) {
        this.rows.set(
          d.rows.map((r: Pick<Row, 'page' | 'details' | 'image'>) => ({
            ...this.blankRow(r.page),
            details: r.details ?? '',
            image: r.image ?? null,
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

  // --------------------------------------------------------------- generate
  protected async generate(): Promise<void> {
    const styleId = this.styleId();
    if (!styleId || !this.canSubmit()) return;
    this.error.set(null);
    this.generating.set(true);
    clearTimeout(this.pollTimer);

    const request: GenerateRequest = {
      style_id: styleId,
      title: this.title().trim(),
      topic: this.topic().trim(),
      instructions: this.instructions().trim(),
      slides: [...this.filledRows()]
        .sort((a, b) => a.page - b.page)
        .map((r) => ({ page: r.page, details: r.details.trim(), image_id: r.image?.id ?? null })),
    };

    try {
      const generation = await firstValueFrom(this.api.generate(request));
      this.result.set(generation);
      this.pollPreviews(generation.id, 0);
      setTimeout(() => document.getElementById('result')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.generating.set(false);
    }
  }

  private pollPreviews(id: string, attempt: number): void {
    const current = this.result();
    if (!current || current.id !== id || current.preview_status !== 'pending' || attempt > 45) return;
    this.pollTimer = setTimeout(async () => {
      try {
        const fresh = await firstValueFrom(this.api.getGeneration(id));
        if (this.result()?.id === id) this.result.set(fresh);
      } catch {
        /* keep trying quietly */
      }
      this.pollPreviews(id, attempt + 1);
    }, 2000);
  }

  /** Caption per preview: "Cover" or "Slide n · title". */
  protected previewCaptions(r: Generation): string[] {
    return r.previews.map((_, i) => {
      const s = r.slides[i];
      if (!s) return `Slide ${i + 1}`;
      return s.page === 0 ? `Cover · ${s.title}` : `Slide ${s.page}${s.title ? ' · ' + s.title : ''}`;
    });
  }

  protected newDeck(): void {
    this.viewing.set(null);
    this.result.set(null);
    this.title.set('');
    this.topic.set('');
    this.instructions.set('');
    this.rows.set([this.blankRow(1)]);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  protected selectedStyle = computed(() => this.styles().find((s) => s.id === this.styleId()) ?? null);
}
