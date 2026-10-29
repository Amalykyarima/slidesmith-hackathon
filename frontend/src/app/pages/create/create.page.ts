import { Component, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { ApiService, errorMessage } from '../../core/api.service';
import { GenerateRequest, Generation, SlideStyle, UploadedImage } from '../../core/models';

/** One numbered slide; its page number is its position in the list. */
interface Row {
  key: number;
  details: string;
  image: UploadedImage | null;
  uploading: boolean;
  error: string | null;
}

const DRAFT_KEY = 'slidesmith.draft.v1';

@Component({
  selector: 'app-create-page',
  imports: [FormsModule, RouterLink],
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

  protected readonly cover = signal(true);
  protected readonly title = signal('');
  protected readonly subtitle = signal('');
  protected readonly topic = signal('');
  protected readonly instructions = signal('');
  protected readonly rows = signal<Row[]>([this.blankRow()]);

  protected readonly generating = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly result = signal<Generation | null>(null);

  /** Key of the row being dragged, for drag-to-reorder. */
  protected readonly dragKey = signal<number | null>(null);

  protected readonly filledRows = computed(() => this.rows().filter((r) => r.details.trim() || r.image));

  protected readonly canSubmit = computed(
    () =>
      !!this.styleId() &&
      this.filledRows().length > 0 &&
      (!this.cover() || !!this.title().trim()) &&
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
        cover: this.cover(),
        title: this.title(),
        subtitle: this.subtitle(),
        topic: this.topic(),
        instructions: this.instructions(),
        rows: this.rows().map(({ details, image }) => ({ details, image })),
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
  private blankRow(): Row {
    return { key: this.nextKey++, details: '', image: null, uploading: false, error: null };
  }

  private restoreDraft(): void {
    try {
      const raw = localStorage.getItem(DRAFT_KEY);
      if (!raw) return;
      const d = JSON.parse(raw);
      this.styleId.set(d.styleId ?? null);
      this.cover.set(d.cover ?? true);
      this.title.set(d.title ?? '');
      this.subtitle.set(d.subtitle ?? '');
      this.topic.set(d.topic ?? '');
      this.instructions.set(d.instructions ?? '');
      if (Array.isArray(d.rows) && d.rows.length) {
        // Older drafts carried typed page numbers: keep their order.
        const saved: { page?: number; details?: string; image?: UploadedImage | null }[] = [...d.rows];
        saved.sort((a, b) => (a.page ?? 0) - (b.page ?? 0));
        this.rows.set(
          saved.map((r) => ({
            ...this.blankRow(),
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
    this.rows.update((rows) => [...rows, this.blankRow()]);
  }

  protected removeRow(key: number): void {
    const row = this.rows().find((r) => r.key === key);
    if (row?.image) void firstValueFrom(this.api.deleteImage(row.image.id)).catch(() => undefined);
    this.rows.update((rows) => (rows.length > 1 ? rows.filter((r) => r.key !== key) : [this.blankRow()]));
  }

  protected patch(key: number, changes: Partial<Row>): void {
    this.rows.update((rows) => rows.map((r) => (r.key === key ? { ...r, ...changes } : r)));
  }

  /** Moves a slide to `index` in the list (used by the arrow buttons and drag-and-drop). */
  protected moveRow(key: number, index: number): void {
    this.rows.update((rows) => {
      const from = rows.findIndex((r) => r.key === key);
      if (from < 0 || index < 0 || index >= rows.length || index === from) return rows;
      const next = [...rows];
      const [row] = next.splice(from, 1);
      next.splice(index, 0, row);
      return next;
    });
  }

  protected dropOn(index: number, event: DragEvent): void {
    event.preventDefault();
    const key = this.dragKey();
    if (key !== null) this.moveRow(key, index);
    this.dragKey.set(null);
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
      cover: this.cover(),
      title: this.title().trim(),
      subtitle: this.cover() ? this.subtitle().trim() : '',
      topic: this.topic().trim(),
      instructions: this.instructions().trim(),
      // Pages follow the list order; empty rows are skipped without leaving gaps.
      slides: this.filledRows().map((r, i) => ({ page: i + 1, details: r.details.trim(), image_id: r.image?.id ?? null })),
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

  protected newDeck(): void {
    this.result.set(null);
    this.cover.set(true);
    this.title.set('');
    this.subtitle.set('');
    this.topic.set('');
    this.instructions.set('');
    this.rows.set([this.blankRow()]);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  protected selectedStyle = computed(() => this.styles().find((s) => s.id === this.styleId()) ?? null);
}
