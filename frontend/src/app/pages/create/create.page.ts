import { Component, DestroyRef, computed, effect, inject, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { ApiService, errorMessage } from '../../core/api.service';
import { BuildRequest, GenerateRequest, Generation, Health, Layout, SlideStyle, StyleLayouts, UploadedImage } from '../../core/models';
import { Lightbox } from '../../shared/lightbox';
import { COVER_KEY, EditSlide, blankSlide, fromContent, isEmpty, layoutKind, notesOf, plain, signature, toBuildSlide } from './deck';
import { BuiltState, SlideCard } from './slide-card';
import { SlidePreview } from './slide-preview';

const DRAFT_KEY = 'slidesmith.draft.v2';
const OLD_DRAFT_KEY = 'slidesmith.draft.v1';
const LAYOUT_NAMES: Record<Layout['kind'], string> = { title: 'Cover', content: 'Content', image: 'Picture', section: 'Section break' };

/** What the last build contained, to tell which slides changed since. */
interface Built {
  styleId: string;
  /** The whole deck's signature when it was sent. */
  sig: string;
  /** Card keys in built order (the cover is COVER_KEY). */
  keys: number[];
  sigs: Record<number, string>;
}

@Component({
  selector: 'app-create-page',
  imports: [FormsModule, RouterLink, Lightbox, SlideCard, SlidePreview],
  templateUrl: './create.page.html',
  styleUrl: './create.page.css',
})
export class CreatePage {
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private nextKey = 1;
  private pollTimer: ReturnType<typeof setTimeout> | undefined;
  private layoutTimer: ReturnType<typeof setTimeout> | undefined;

  protected readonly layoutNames = LAYOUT_NAMES;
  protected readonly coverKey = COVER_KEY;

  protected readonly health = signal<Health | null>(null);
  protected readonly styles = signal<SlideStyle[]>([]);
  protected readonly stylesLoaded = signal(false);
  protected readonly styleId = signal<string | null>(null);
  protected readonly layouts = signal<StyleLayouts | null>(null);
  protected readonly layoutsError = signal<string | null>(null);

  protected readonly cover = signal(true);
  protected readonly coverSlide = signal<EditSlide>(blankSlide(COVER_KEY, 'title'));
  protected readonly slides = signal<EditSlide[]>([blankSlide(this.nextKey++)]);
  protected readonly topic = signal('');
  protected readonly instructions = signal('');
  /** Upload state per card key. */
  protected readonly uploads = signal<Record<number, { uploading: boolean; error: string | null }>>({});

  protected readonly busy = signal<'ai' | 'build' | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly result = signal<Generation | null>(null);
  protected readonly built = signal<Built | null>(null);
  /** Index of the built preview open full-size, or null. */
  protected readonly viewing = signal<number | null>(null);
  /** Key of the card being dragged, for drag-to-reorder. */
  protected readonly dragKey = signal<number | null>(null);

  protected readonly selectedStyle = computed(() => this.styles().find((s) => s.id === this.styleId()) ?? null);
  protected readonly fonts = computed(() => this.selectedStyle()?.profile.fonts ?? []);
  protected readonly size = computed<[number, number]>(() => this.layouts()?.slide_size_in ?? this.selectedStyle()?.profile.slide_size_in ?? [13.33, 7.5]);
  protected readonly tone = computed(() => this.layouts()?.background_tone ?? this.selectedStyle()?.profile.background_tone ?? 'light');
  protected readonly fallback = computed(() => {
    const palette = this.selectedStyle()?.profile.palette ?? [];
    return this.tone() === 'dark' && palette[0] ? '#' + palette[0] : '#ffffff';
  });
  protected readonly layoutLoading = computed(() => !this.layouts() || this.layouts()!.status === 'pending');

  /** The slides that will be built, in order, with their page numbers (0 = cover). */
  protected readonly deck = computed(() => {
    const items: { slide: EditSlide; page: number }[] = [];
    if (this.cover()) items.push({ slide: this.coverSlide(), page: 0 });
    this.slides()
      .filter((s) => !isEmpty(s))
      .forEach((slide, i) => items.push({ slide, page: i + 1 }));
    return items;
  });
  private readonly deckSig = computed(() => JSON.stringify([this.styleId(), this.deck().map((d) => signature(d.slide, d.page))]));
  /** Something changed since the last build (or nothing has been built yet). */
  protected readonly dirty = computed(() => this.deckSig() !== this.built()?.sig);
  protected readonly uploading = computed(() => Object.values(this.uploads()).some((u) => u.uploading));
  protected readonly coverTitle = computed(() => plain(this.coverSlide().title).trim());

  /** Why Apply can't run right now, or null when it can. */
  protected readonly blocker = computed(() => {
    if (!this.styleId()) return 'Choose a style first.';
    if (this.cover() && !this.coverTitle()) return 'Give the cover slide a title.';
    if (!this.slides().some((s) => !isEmpty(s)) && !this.cover()) return 'Add something to at least one slide.';
    if (this.uploading()) return 'Waiting for pictures to upload…';
    return null;
  });
  protected readonly canApply = computed(() => !this.blocker() && !this.busy() && this.dirty());
  protected readonly canWrite = computed(() => !this.blocker() && !this.busy() && this.slides().some((s) => notesOf(s)));

  constructor() {
    this.restoreDraft();
    void this.loadStyles();
    void firstValueFrom(this.api.health()).then((h) => this.health.set(h), () => undefined);

    // Load the blank template whenever the style changes.
    effect(() => {
      const id = this.styleId();
      untracked(() => this.loadLayouts(id, 0));
    });

    // Keep what the teacher typed if they refresh or navigate away.
    effect(() => {
      const draft = {
        styleId: this.styleId(),
        cover: this.cover(),
        coverSlide: this.coverSlide(),
        slides: this.slides(),
        topic: this.topic(),
        instructions: this.instructions(),
      };
      try {
        localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
      } catch {
        /* storage full or blocked: not critical */
      }
    });

    this.destroyRef.onDestroy(() => {
      clearTimeout(this.pollTimer);
      clearTimeout(this.layoutTimer);
    });
  }

  // ------------------------------------------------------------------ setup
  private restoreDraft(): void {
    try {
      const raw = localStorage.getItem(DRAFT_KEY);
      if (raw) {
        const d = JSON.parse(raw);
        this.styleId.set(d.styleId ?? null);
        this.cover.set(d.cover ?? true);
        if (d.coverSlide) this.coverSlide.set({ ...blankSlide(COVER_KEY, 'title'), ...d.coverSlide, key: COVER_KEY });
        if (Array.isArray(d.slides) && d.slides.length) {
          this.slides.set(d.slides.map((s: Partial<EditSlide>) => ({ ...blankSlide(this.nextKey), ...s, key: this.nextKey++ })));
        }
        this.topic.set(d.topic ?? '');
        this.instructions.set(d.instructions ?? '');
        return;
      }
      // Drafts from before the editor: plain notes per slide.
      const old = localStorage.getItem(OLD_DRAFT_KEY);
      if (!old) return;
      const d = JSON.parse(old);
      this.styleId.set(d.styleId ?? null);
      this.cover.set(d.cover ?? true);
      this.coverSlide.update((c) => ({ ...c, title: d.title ? [{ text: d.title }] : [], body: d.subtitle ? [[{ text: d.subtitle }]] : [] }));
      this.topic.set(d.topic ?? '');
      this.instructions.set(d.instructions ?? '');
      if (Array.isArray(d.rows) && d.rows.length) {
        this.slides.set(
          d.rows.map((r: { details?: string; image?: UploadedImage | null }) => ({
            ...blankSlide(this.nextKey++),
            body: (r.details ?? '').split('\n').filter((l) => l.trim()).map((text) => [{ text }]),
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

  /** Fetches the style's blank slides; keeps asking while they render. */
  private loadLayouts(id: string | null, attempt: number): void {
    clearTimeout(this.layoutTimer);
    if (attempt === 0) {
      this.layouts.set(null);
      this.layoutsError.set(null);
    }
    if (!id) return;
    firstValueFrom(this.api.layouts(id)).then(
      (data) => {
        if (this.styleId() !== id) return;
        this.layouts.set(data);
        if (data.status === 'pending' && attempt < 60) this.layoutTimer = setTimeout(() => this.loadLayouts(id, attempt + 1), 1500);
      },
      (err) => this.styleId() === id && this.layoutsError.set(errorMessage(err)),
    );
  }

  protected layoutFor(s: EditSlide, cover: boolean): Layout | null {
    const kind = layoutKind(s, cover);
    return this.layouts()?.layouts.find((l) => l.kind === kind) ?? null;
  }

  // ----------------------------------------------------------------- slides
  protected patchCover(changes: Partial<EditSlide>): void {
    this.coverSlide.update((s) => ({ ...s, ...changes }));
  }

  protected patch(key: number, changes: Partial<EditSlide>): void {
    this.slides.update((list) => list.map((s) => (s.key === key ? { ...s, ...changes } : s)));
  }

  protected addSlide(): void {
    this.slides.update((list) => [...list, blankSlide(this.nextKey++)]);
  }

  protected removeSlide(key: number): void {
    const slide = this.slides().find((s) => s.key === key);
    if (slide?.image) void firstValueFrom(this.api.deleteImage(slide.image.id)).catch(() => undefined);
    this.slides.update((list) => (list.length > 1 ? list.filter((s) => s.key !== key) : [blankSlide(this.nextKey++)]));
  }

  /** Moves a slide to `index` in the list (used by the arrow buttons and drag-and-drop). */
  protected moveSlide(key: number, index: number): void {
    this.slides.update((list) => {
      const from = list.findIndex((s) => s.key === key);
      if (from < 0 || index < 0 || index >= list.length || index === from) return list;
      const next = [...list];
      const [slide] = next.splice(from, 1);
      next.splice(index, 0, slide);
      return next;
    });
  }

  protected dragStart(key: number, event: DragEvent): void {
    event.dataTransfer?.setData('text/plain', '');
    this.dragKey.set(key);
  }

  protected dropOn(index: number, event: DragEvent): void {
    const key = this.dragKey();
    if (key === null) return; // text dropped into a field: leave it to the browser
    event.preventDefault();
    this.moveSlide(key, index);
    this.dragKey.set(null);
  }

  protected async attach(key: number, file: File): Promise<void> {
    if (!file.type.startsWith('image/')) {
      this.setUpload(key, false, 'Please choose an image file (PNG, JPG, GIF or WEBP).');
      return;
    }
    this.setUpload(key, true, null);
    try {
      const image = await firstValueFrom(this.api.uploadImage(file));
      this.patch(key, { image });
      this.setUpload(key, false, null);
    } catch (err) {
      this.setUpload(key, false, errorMessage(err));
    }
  }

  protected detach(key: number): void {
    const slide = this.slides().find((s) => s.key === key);
    if (slide?.image) void firstValueFrom(this.api.deleteImage(slide.image.id)).catch(() => undefined);
    this.patch(key, { image: null, image_position: 'auto' });
  }

  private setUpload(key: number, uploading: boolean, error: string | null): void {
    this.uploads.update((u) => ({ ...u, [key]: { uploading, error } }));
  }

  /** Page label for a card: empty slides get no number, since they're skipped. */
  protected labelOf(s: EditSlide): string {
    const at = this.deck().find((d) => d.slide.key === s.key);
    return at ? `Slide ${at.page}` : 'Slide (empty)';
  }

  // ------------------------------------------------------------------ build
  /** The AI writes the slide text from the rough notes, then the deck is built straight away. */
  protected async writeWithAi(): Promise<void> {
    const styleId = this.styleId();
    if (!styleId || !this.canWrite()) return;
    const rows = this.slides().filter((s) => !isEmpty(s));
    const request: GenerateRequest = {
      style_id: styleId,
      cover: this.cover(),
      title: this.coverTitle(),
      subtitle: this.cover() ? notesOf({ ...this.coverSlide(), title: [] }) : '',
      topic: this.topic().trim(),
      instructions: this.instructions().trim(),
      slides: rows.map((s, i) => ({ page: i + 1, details: notesOf(s), image_id: s.image?.id ?? null })),
    };
    this.error.set(null);
    this.busy.set('ai');
    try {
      const draft = await firstValueFrom(this.api.draft(request));
      const byKey = new Map(rows.map((s, i) => [s.key, draft.slides.find((c) => c.page === i + 1)]));
      this.slides.update((list) =>
        list.map((s) => {
          const written = byKey.get(s.key);
          return written ? fromContent(s, written, this.cover()) : s;
        }),
      );
    } catch (err) {
      this.error.set(errorMessage(err));
      this.busy.set(null);
      return;
    }
    this.busy.set(null);
    await this.apply();
  }

  /** Builds the slides exactly as shown and renders the real previews. */
  protected async apply(): Promise<void> {
    const styleId = this.styleId();
    if (!styleId || !this.canApply()) return;
    const deck = this.deck();
    const request: BuildRequest = {
      style_id: styleId,
      title: this.coverTitle() || plain(deck[0]?.slide.title ?? []).trim(),
      slides: deck.map((d) => toBuildSlide(d.slide, d.page)),
    };
    // Snapshot now: edits made while building aren't part of this build.
    const snapshot: Built = {
      styleId,
      sig: this.deckSig(),
      keys: deck.map((d) => d.slide.key),
      sigs: Object.fromEntries(deck.map((d) => [d.slide.key, signature(d.slide, d.page)])),
    };
    this.error.set(null);
    this.busy.set('build');
    clearTimeout(this.pollTimer);
    try {
      const generation = await firstValueFrom(this.api.build(request));
      this.result.set(generation);
      this.built.set(snapshot);
      this.pollPreviews(generation.id, 0);
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.busy.set(null);
    }
  }

  private pollPreviews(id: string, attempt: number): void {
    const current = this.result();
    if (!current || current.id !== id || current.preview_status !== 'pending' || attempt > 60) return;
    this.pollTimer = setTimeout(async () => {
      try {
        const fresh = await firstValueFrom(this.api.getGeneration(id));
        if (this.result()?.id === id) this.result.set(fresh);
      } catch {
        /* keep trying quietly */
      }
      this.pollPreviews(id, attempt + 1);
    }, 1500);
  }

  /** What a card's preview shows: the built slide while it matches, else the live drawing. */
  protected builtState(s: EditSlide, page: number | null): BuiltState {
    const built = this.built();
    const result = this.result();
    if (!built || !result || page === null) return { image: null, stale: true, rendering: false };
    const index = built.keys.indexOf(s.key);
    const stale = index < 0 || built.styleId !== this.styleId() || built.sigs[s.key] !== signature(s, page);
    return { image: result.previews[index] ?? null, stale, rendering: !stale && result.preview_status === 'pending' };
  }

  protected pageOf(s: EditSlide): number | null {
    return this.deck().find((d) => d.slide.key === s.key)?.page ?? null;
  }

  protected openBuilt(key: number): void {
    const index = this.built()?.keys.indexOf(key) ?? -1;
    if (index >= 0) this.viewing.set(index);
  }

  protected previewCaptions(r: Generation): string[] {
    return r.slides.map((s) => (s.page === 0 ? `Cover · ${s.title}` : `Slide ${s.page}${s.title ? ' · ' + s.title : ''}`));
  }

  protected newDeck(): void {
    clearTimeout(this.pollTimer);
    this.viewing.set(null);
    this.result.set(null);
    this.built.set(null);
    this.cover.set(true);
    this.coverSlide.set(blankSlide(COVER_KEY, 'title'));
    this.slides.set([blankSlide(this.nextKey++)]);
    this.uploads.set({});
    this.topic.set('');
    this.instructions.set('');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  protected blank(kind: Layout['kind']): EditSlide {
    return blankSlide(-1, kind === 'image' ? 'content' : kind);
  }
}
