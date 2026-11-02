import {
  Component,
  DestroyRef,
  ElementRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService, errorMessage } from '../../core/api.service';
import { Generation, SceneParagraph, SceneRun, SceneShape, ShapeEdit, SlideScene } from '../../core/models';

const EMU_PER_PT = 12700;
/** Resolves once the browser has the image (so it appears all at once, not in strips). */
function preload(url: string): Promise<void> {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = img.onerror = () => resolve();
    img.src = url;
  });
}

const SIZES = [10, 12, 14, 16, 18, 20, 24, 28, 32, 36, 40, 44, 48, 54, 60, 72];
type Corner = 'nw' | 'ne' | 'sw' | 'se';
type Run = Pick<SceneRun, 'text' | 'size' | 'color' | 'bold' | 'italic' | 'underline'>;

interface Piece extends SceneShape {
  /** Position and size when the slide was loaded or last saved. */
  orig: { x: number; y: number; w: number; h: number };
}

interface Gesture {
  id: number;
  mode: 'move' | Corner;
  startX: number;
  startY: number;
  box: { x: number; y: number; w: number; h: number };
  moved: boolean;
}

/**
 * Edits one slide of a generated deck directly on the slide: drag text boxes and
 * pictures, resize pictures (and text boxes) from the corners, and format selected
 * text (size, colour, bold, italic, underline). Saving writes into the .pptx.
 */
@Component({
  selector: 'app-slide-canvas',
  template: `
    <dialog #dialog class="canvas-dialog" (cancel)="$event.preventDefault(); onEscape()" aria-labelledby="canvas-title">
      <header class="bar">
        <div class="nav">
          <button type="button" class="btn btn-sm" [disabled]="number() <= 1 || dirty() || saving()" (click)="go(-1)"
                  [title]="dirty() ? 'Save your changes first' : 'Previous slide'" aria-label="Previous slide">‹</button>
          <h2 id="canvas-title">Slide {{ number() }} <span class="muted">of {{ count() }}</span></h2>
          <button type="button" class="btn btn-sm" [disabled]="number() >= count() || dirty() || saving()" (click)="go(1)"
                  [title]="dirty() ? 'Save your changes first' : 'Next slide'" aria-label="Next slide">›</button>
        </div>

        <div class="toolbar" role="toolbar" aria-label="Text formatting" [class.off]="editingId() === null">
          <label class="size">
            <span class="sr-only">Font size</span>
            <select (mousedown)="keepSelection()" (change)="applySize($any($event.target).value)"
                    [disabled]="editingId() === null" title="Font size">
              @for (s of sizeOptions(); track s) {
                <option [value]="s" [selected]="s === fmtSize()">{{ s }}</option>
              }
            </select>
          </label>
          <label class="color" title="Text colour">
            <span class="sr-only">Text colour</span>
            <input type="color" [value]="fmtColor()" (mousedown)="keepSelection()" (input)="applyColor($any($event.target).value)"
                   [disabled]="editingId() === null" />
          </label>
          <button type="button" class="fmt" [class.on]="fmtBold()" [attr.aria-pressed]="fmtBold()" (mousedown)="$event.preventDefault()"
                  (click)="toggle('bold')" [disabled]="editingId() === null" title="Bold (Ctrl+B)"><b>B</b></button>
          <button type="button" class="fmt" [class.on]="fmtItalic()" [attr.aria-pressed]="fmtItalic()" (mousedown)="$event.preventDefault()"
                  (click)="toggle('italic')" [disabled]="editingId() === null" title="Italic (Ctrl+I)"><i>I</i></button>
          <button type="button" class="fmt" [class.on]="fmtUnderline()" [attr.aria-pressed]="fmtUnderline()" (mousedown)="$event.preventDefault()"
                  (click)="toggle('underline')" [disabled]="editingId() === null" title="Underline (Ctrl+U)"><u>U</u></button>
        </div>

        <div class="actions">
          @if (!confirmClose()) {
            <span class="status" [attr.data-state]="saveState()" role="status" aria-live="polite">
              @switch (saveState()) {
                @case ('saving') { <span class="spinner"></span> Saving… }
                @case ('dirty') { <span class="dot" aria-hidden="true"></span> Unsaved changes }
                @case ('saved') { <span aria-hidden="true">✓</span> All changes saved }
              }
            </span>
          }
          @if (confirmClose()) {
            <span class="small">Discard unsaved changes?</span>
            <button type="button" class="btn btn-sm danger" (click)="close.emit()">Discard</button>
            <button type="button" class="btn btn-sm" (click)="confirmClose.set(false)">Keep editing</button>
          } @else {
            <button type="button" class="btn btn-sm" [disabled]="!dirty() || saving()" (click)="reset()">Undo changes</button>
            <button type="button" class="btn btn-sm btn-primary save-btn" [disabled]="!dirty() || saving()" (click)="save()"
                    title="Save (Ctrl+S)">
              @if (saving()) {
                <span class="spinner"></span> Saving…
              } @else {
                Save
              }
            </button>
            <button type="button" class="btn btn-icon" aria-label="Close" (click)="requestClose()">✕</button>
          }
        </div>
      </header>

      @if (error(); as msg) {
        <div class="alert alert-error" role="alert">{{ msg }}</div>
      }

      <div class="work" (pointerdown)="backgroundDown($event)">
        @if (!scene()) {
          <div class="stage placeholder" [style.aspect-ratio]="'16 / 9'">
            @if (thumbs()[number() - 1]; as t) {
              <img [src]="t" alt="" />
            }
            <span class="chip"><span class="spinner"></span> Opening slide {{ number() }}…</span>
          </div>
        } @else {
          <div
            #stage
            class="stage"
            [style.aspect-ratio]="scene()!.width + ' / ' + scene()!.height"
            [style.background-image]="scene()!.background ? 'url(' + scene()!.background + ')' : null"
            [style.--pt]="ptPx() + 'px'"
            [class.busy]="saving()"
          >
            @if (!scene()!.background && scene()!.background_pending) {
              <span class="chip bg-chip"><span class="spinner"></span> Drawing the slide's design… you can start editing</span>
            }
            @for (p of pieces(); track p.id) {
              <div
                class="piece"
                [class.text]="p.kind === 'text'"
                [class.picture]="p.kind === 'picture'"
                [class.selected]="selectedId() === p.id"
                [class.editing]="editingId() === p.id"
                [class.fixed]="p.fixed"
                [style.left.%]="(p.x / scene()!.width) * 100"
                [style.top.%]="(p.y / scene()!.height) * 100"
                [style.width.%]="(p.w / scene()!.width) * 100"
                [style.height.%]="(p.h / scene()!.height) * 100"
                [style.transform]="p.rotation ? 'rotate(' + p.rotation + 'deg)' : null"
                [style.background]="p.fill || null"
                [style.border]="p.border ? 'calc(var(--pt) * ' + p.border.width / 12700 + ') solid ' + p.border.color : null"
                tabindex="0"
                role="button"
                [attr.aria-label]="(p.kind === 'picture' ? 'Picture' : 'Text box') + (p.fixed ? '' : '. Drag to move') + '. Double-click text to edit.'"
                (pointerdown)="pieceDown($event, p)"
                (dblclick)="startEditing(p)"
                (keydown)="pieceKey($event, p)"
              >
                @if (p.kind === 'picture') {
                  <img [src]="p.src" alt="" draggable="false" />
                } @else {
                  <div
                    class="text-inner"
                    [attr.data-id]="p.id"
                    [attr.data-anchor]="p.anchor || 't'"
                    [attr.contenteditable]="editingId() === p.id ? 'true' : 'false'"
                    [style.padding]="pad(p)"
                    (input)="markText(p.id)"
                    (keydown)="textKey($event)"
                  ></div>
                }
                @if (selectedId() === p.id && !p.fixed && editingId() !== p.id && canResize(p)) {
                  @for (c of corners; track c) {
                    <span class="handle {{ c }}" (pointerdown)="handleDown($event, p, c)" aria-hidden="true"></span>
                  }
                }
              </div>
            }
          </div>
          <p class="hint small muted">
            Drag a text box or picture to move it · drag a picture's corners to resize · double-click text to edit,
            then select words to format them · arrow keys nudge the selected item.
            @if (!scene()!.background && !scene()!.background_pending) {
              <br />The slide's background could not be drawn here; the saved slide keeps it.
            }
          </p>
        }
      </div>
      @if (toast(); as t) {
        <div class="toast" role="status">{{ t }}</div>
      }
    </dialog>
  `,
  styles: `
    .canvas-dialog {
      width: 100vw; max-width: 100vw; height: 100vh; max-height: 100vh; margin: 0; padding: 0; border: 0;
      background: #e9edf1; color: var(--ink); display: flex; flex-direction: column;
    }
    .canvas-dialog:not([open]) { display: none; }
    .canvas-dialog::backdrop { background: rgba(16, 24, 40, 0.5); }
    .bar {
      display: flex; align-items: center; gap: 12px; flex-wrap: wrap; justify-content: space-between;
      padding: 10px 16px; background: #fff; border-bottom: 1px solid var(--border);
    }
    .nav { display: flex; align-items: center; gap: 8px; }
    .nav h2 { margin: 0; font-size: 16px; white-space: nowrap; }
    .toolbar { display: flex; align-items: center; gap: 6px; padding: 4px; border: 1px solid var(--border); border-radius: 10px; background: #fff; }
    .toolbar.off { opacity: 0.55; }
    .toolbar select { height: 34px; border: 1px solid var(--border); border-radius: 6px; padding: 0 6px; font: inherit; background: #fff; }
    .toolbar input[type='color'] { width: 38px; height: 34px; padding: 2px; border: 1px solid var(--border); border-radius: 6px; background: #fff; cursor: pointer; }
    .fmt { width: 34px; height: 34px; border: 1px solid var(--border); border-radius: 6px; background: #fff; font: inherit; font-size: 16px; cursor: pointer; color: var(--ink); }
    .fmt.on { background: var(--primary-soft); border-color: var(--primary); color: var(--primary-dark); }
    .fmt:disabled, .toolbar select:disabled, .toolbar input:disabled { cursor: not-allowed; }
    .actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .status { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; padding: 5px 10px; border-radius: 999px; white-space: nowrap; }
    .status:empty { display: none; }
    .status[data-state='dirty'] { background: #fff4e5; color: #9a5b00; }
    .status[data-state='saving'] { background: var(--primary-soft); color: var(--primary-dark); }
    .status[data-state='saved'] { background: #e7f6ec; color: #1e7b3c; }
    .status .dot { width: 8px; height: 8px; border-radius: 50%; background: #e08a00; }
    .status .spinner, .chip .spinner { width: 13px; height: 13px; }
    .save-btn { min-width: 76px; justify-content: center; }
    .chip {
      position: absolute; left: 50%; top: 12px; transform: translateX(-50%); z-index: 3; display: inline-flex; align-items: center; gap: 8px;
      background: rgba(255, 255, 255, 0.95); border: 1px solid var(--border); border-radius: 999px; padding: 6px 12px;
      font-size: 13px; color: var(--ink); box-shadow: 0 2px 8px rgba(16, 24, 40, 0.12); white-space: nowrap; pointer-events: none;
    }
    .placeholder { overflow: hidden; }
    .placeholder img { width: 100%; height: 100%; object-fit: contain; display: block; filter: saturate(0.85); opacity: 0.75; }
    .placeholder .chip { top: 50%; transform: translate(-50%, -50%); }
    .stage.busy { pointer-events: none; }
    .stage.busy::after { content: ''; position: absolute; inset: 0; background: rgba(255, 255, 255, 0.35); z-index: 4; }
    .stage { transition: background-image 0.2s; }
    .toast {
      position: fixed; left: 50%; top: 76px; transform: translateX(-50%); z-index: 10; background: #1e7b3c; color: #fff;
      padding: 10px 16px; border-radius: 10px; font-weight: 600; font-size: 14px; box-shadow: 0 8px 24px rgba(16, 24, 40, 0.25);
      animation: toast-in 0.18s ease-out;
    }
    @keyframes toast-in { from { opacity: 0; transform: translate(-50%, -8px); } }
    .danger { background: var(--danger); border-color: var(--danger); color: #fff; }
    .alert { margin: 10px 16px 0; }
    .work { flex: 1; overflow: auto; padding: 20px; display: flex; flex-direction: column; align-items: center; gap: 10px; }
    .stage {
      position: relative; width: min(100%, calc((100vh - 170px) * 16 / 9)); background: #fff center / 100% 100% no-repeat;
      box-shadow: 0 6px 24px rgba(16, 24, 40, 0.18); user-select: none; touch-action: none; overflow: visible;
    }
    .hint { max-width: 900px; text-align: center; }
    .piece { position: absolute; box-sizing: border-box; cursor: move; outline: none; }
    .piece.fixed { cursor: default; }
    .piece:hover:not(.editing) { box-shadow: 0 0 0 1px rgba(15, 118, 110, 0.6); }
    .piece.selected { box-shadow: 0 0 0 2px var(--primary); }
    .piece.editing { cursor: text; box-shadow: 0 0 0 2px var(--primary), 0 0 0 5px rgba(15, 118, 110, 0.18); }
    .piece:focus-visible { box-shadow: 0 0 0 3px rgba(15, 118, 110, 0.6); }
    .piece img { width: 100%; height: 100%; display: block; pointer-events: none; }
    .text-inner {
      width: 100%; height: 100%; box-sizing: border-box; display: flex; flex-direction: column; overflow: visible;
      line-height: 1.2; word-wrap: break-word; outline: none; color: #000;
    }
    .text-inner[data-anchor='ctr'] { justify-content: center; }
    .text-inner[data-anchor='b'] { justify-content: flex-end; }
    .piece.editing .text-inner { user-select: text; -webkit-user-select: text; }
    :host ::ng-deep .text-inner .p { margin: 0 0 calc(var(--pt) * 4) 0; min-height: 1em; }
    :host ::ng-deep .text-inner .p[data-bullet]::before { content: attr(data-bullet) '\\00a0\\00a0'; }
    :host ::ng-deep .text-inner { counter-reset: num; }
    :host ::ng-deep .text-inner .p.num { counter-increment: num; }
    :host ::ng-deep .text-inner .p.num::before { content: counter(num) '.\\00a0\\00a0'; }
    .handle {
      position: absolute; width: 14px; height: 14px; background: #fff; border: 2px solid var(--primary); border-radius: 3px;
      z-index: 2; touch-action: none;
    }
    .handle.nw { left: -8px; top: -8px; cursor: nwse-resize; }
    .handle.ne { right: -8px; top: -8px; cursor: nesw-resize; }
    .handle.sw { left: -8px; bottom: -8px; cursor: nesw-resize; }
    .handle.se { right: -8px; bottom: -8px; cursor: nwse-resize; }
    .sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
    @media (max-width: 760px) {
      .bar { padding: 8px 52px 8px 10px; position: relative; gap: 8px; }
      .actions .btn-icon { position: absolute; right: 8px; top: 8px; }
      .actions { flex-wrap: nowrap; }
      .actions .btn { white-space: nowrap; }
      .status { font-size: 12px; padding: 4px 8px; }
      .toast { top: auto; bottom: 16px; max-width: calc(100vw - 32px); white-space: nowrap; }
      .chip { font-size: 12px; white-space: normal; text-align: center; width: max-content; max-width: 90%; }
      .work { padding: 10px; }
      .stage { width: 100%; }
      .handle { width: 20px; height: 20px; }
      .handle.nw { left: -11px; top: -11px; } .handle.ne { right: -11px; top: -11px; }
      .handle.sw { left: -11px; bottom: -11px; } .handle.se { right: -11px; bottom: -11px; }
    }
  `,
})
export class SlideCanvas {
  private readonly api = inject(ApiService);
  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly destroyRef = inject(DestroyRef);
  private readonly dialog = viewChild.required<ElementRef<HTMLDialogElement>>('dialog');
  private readonly stageRef = viewChild<ElementRef<HTMLDivElement>>('stage');

  readonly generationId = input.required<string>();
  /** 1-based slide number to open first. */
  readonly start = input.required<number>();
  /** Thumbnails of the deck, shown while a slide opens. */
  readonly thumbs = input<string[]>([]);
  readonly saved = output<Generation>();
  readonly close = output<void>();

  protected readonly corners: Corner[] = ['nw', 'ne', 'sw', 'se'];
  protected readonly number = signal(1);
  protected readonly scene = signal<SlideScene | null>(null);
  protected readonly pieces = signal<Piece[]>([]);
  protected readonly count = signal(1);
  protected readonly selectedId = signal<number | null>(null);
  protected readonly editingId = signal<number | null>(null);
  protected readonly stageWidth = signal(0);
  protected readonly ptPx = computed(() => {
    const s = this.scene();
    return s && this.stageWidth() ? this.stageWidth() / (s.width / EMU_PER_PT) : 1;
  });
  protected readonly saving = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly toast = signal<string | null>(null);
  private readonly savedOnce = signal(false);
  protected readonly saveState = computed(() =>
    this.saving() ? 'saving' : this.dirty() ? 'dirty' : this.savedOnce() ? 'saved' : 'clean',
  );
  protected readonly confirmClose = signal(false);
  private readonly textDirty = signal<ReadonlySet<number>>(new Set());
  protected readonly dirty = computed(
    () =>
      this.textDirty().size > 0 ||
      this.pieces().some((p) => p.x !== p.orig.x || p.y !== p.orig.y || p.w !== p.orig.w || p.h !== p.orig.h),
  );

  // toolbar state for the current selection
  protected readonly fmtSize = signal(24);
  protected readonly fmtColor = signal('#000000');
  protected readonly fmtBold = signal(false);
  protected readonly fmtItalic = signal(false);
  protected readonly fmtUnderline = signal(false);
  protected readonly sizeOptions = computed(() => [...new Set([...SIZES, this.fmtSize()])].sort((a, b) => a - b));

  private baselines = new Map<number, string>();
  private gesture: Gesture | null = null;
  private savedRange: Range | null = null;
  private resizeObserver: ResizeObserver | null = null;

  constructor() {
    effect(() => {
      const d = this.dialog().nativeElement;
      if (!d.open) d.showModal();
    });
    effect(() => {
      const start = this.start();
      this.generationId();
      untracked(() => {
        this.number.set(start);
        void this.load();
      });
    });
    // Track the stage's width so 1pt on the slide = ptPx() pixels on screen.
    effect(() => {
      const stage = this.stageRef()?.nativeElement;
      this.resizeObserver?.disconnect();
      if (!stage) return;
      this.resizeObserver = new ResizeObserver(([entry]) => this.stageWidth.set(entry.contentRect.width));
      this.resizeObserver.observe(stage);
    });
    const onSelection = () => this.readSelectionFormat();
    document.addEventListener('selectionchange', onSelection);
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault(); // not the browser's "save page"
        if (this.dirty() && !this.saving()) void this.save();
      }
    };
    window.addEventListener('keydown', onKey);
    const onMove = (e: PointerEvent) => this.pointerMove(e);
    const onUp = () => this.pointerUp();
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    this.destroyRef.onDestroy(() => {
      document.removeEventListener('selectionchange', onSelection);
      window.removeEventListener('keydown', onKey);
      clearTimeout(this.toastTimer);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      this.resizeObserver?.disconnect();
    });
  }

  // ------------------------------------------------------------------ loading
  private async load(): Promise<void> {
    const n = this.number();
    const ready = this.cache.get(n)?.value;
    if (!ready) this.scene.set(null);
    this.error.set(null);
    this.selectedId.set(null);
    this.editingId.set(null);
    this.textDirty.set(new Set());
    try {
      const s = ready ?? (await this.fetchScene(n));
      if (n !== this.number()) return; // moved on while it loaded
      this.scene.set(s);
      this.count.set(s.count);
      this.pieces.set(s.shapes.map((sh) => ({ ...sh, orig: { x: sh.x, y: sh.y, w: sh.w, h: sh.h } })));
      setTimeout(() => this.fillText(), 0);
      if (!s.background && s.background_pending) void this.fetchBackground(n);
      this.prefetchAround(n);
    } catch (err) {
      if (n === this.number()) this.error.set(errorMessage(err));
    }
  }

  /** Slides already fetched (or on their way), so moving between slides is instant. */
  private readonly cache = new Map<number, { promise: Promise<SlideScene>; value?: SlideScene }>();

  private fetchScene(n: number): Promise<SlideScene> {
    const hit = this.cache.get(n);
    if (hit) return hit.promise;
    const entry: { promise: Promise<SlideScene>; value?: SlideScene } = {
      promise: firstValueFrom(this.api.slideScene(this.generationId(), n)),
    };
    entry.promise.then(
      (s) => (entry.value = s),
      () => this.cache.delete(n),
    );
    this.cache.set(n, entry);
    return entry.promise;
  }

  /** The slide's design is drawn on the server; ask for it, then fade it in. */
  private async fetchBackground(n: number): Promise<void> {
    let url: string | null = null;
    try {
      url = (await firstValueFrom(this.api.slideBackground(this.generationId(), n))).background;
      if (url) await preload(url);
    } catch {
      url = null;
    }
    const patch = (s: SlideScene): SlideScene => ({ ...s, background: url, background_pending: false });
    const entry = this.cache.get(n);
    if (entry?.value) entry.value = patch(entry.value);
    if (this.number() === n) this.scene.update((s) => (s ? patch(s) : s));
  }

  private prefetchAround(n: number): void {
    for (const m of [n + 1, n - 1]) {
      if (m < 1 || m > this.count() || this.cache.has(m)) continue;
      this.fetchScene(m).then(
        (s) => {
          if (s.background) void preload(s.background);
          else if (s.background_pending) void this.fetchBackground(m);
          for (const sh of s.shapes) if (sh.src) void preload(sh.src);
        },
        () => undefined,
      );
    }
  }

  private toastTimer?: ReturnType<typeof setTimeout>;
  private showToast(message: string): void {
    clearTimeout(this.toastTimer);
    this.toast.set(message);
    this.toastTimer = setTimeout(() => this.toast.set(null), 2600);
  }

  /** Put each text box's formatted text into its element (Angular leaves it alone afterwards). */
  private fillText(): void {
    this.baselines.clear();
    for (const p of this.pieces()) {
      if (p.kind !== 'text') continue;
      const el = this.textEl(p.id);
      if (!el) continue;
      el.innerHTML = paragraphsHtml(p.paragraphs ?? []);
      this.baselines.set(p.id, JSON.stringify(this.serialize(el)));
    }
  }

  protected go(step: number): void {
    const next = this.number() + step;
    if (next < 1 || next > this.count() || this.dirty()) return;
    this.number.set(next);
    void this.load();
  }

  // --------------------------------------------------------- moving & sizing
  protected canResize(p: Piece): boolean {
    return Math.round(p.rotation) % 180 === 0;
  }

  protected pieceDown(e: PointerEvent, p: Piece): void {
    if (this.editingId() === p.id) return; // clicks inside the text being edited place the caret
    if (this.editingId() !== null) this.stopEditing();
    this.selectedId.set(p.id);
    (e.currentTarget as HTMLElement).focus({ preventScroll: true });
    if (p.fixed || e.button !== 0) return;
    e.preventDefault();
    this.gesture = { id: p.id, mode: 'move', startX: e.clientX, startY: e.clientY, box: { x: p.x, y: p.y, w: p.w, h: p.h }, moved: false };
  }

  protected handleDown(e: PointerEvent, p: Piece, corner: Corner): void {
    e.stopPropagation();
    e.preventDefault();
    this.gesture = { id: p.id, mode: corner, startX: e.clientX, startY: e.clientY, box: { x: p.x, y: p.y, w: p.w, h: p.h }, moved: false };
  }

  protected backgroundDown(e: PointerEvent): void {
    const target = e.target as HTMLElement;
    if (target.closest('.piece')) return;
    if (this.editingId() !== null) this.stopEditing();
    this.selectedId.set(null);
  }

  private pointerMove(e: PointerEvent): void {
    const g = this.gesture;
    const s = this.scene();
    if (!g || !s || !this.stageWidth()) return;
    const emuPerPx = s.width / this.stageWidth();
    const dx = (e.clientX - g.startX) * emuPerPx;
    const dy = (e.clientY - g.startY) * emuPerPx;
    if (!g.moved && Math.hypot(e.clientX - g.startX, e.clientY - g.startY) < 3) return;
    g.moved = true;
    const minSize = 0.04 * s.width;
    this.updatePiece(g.id, (p) => {
      const b = g.box;
      if (g.mode === 'move') {
        return {
          x: Math.round(clamp(b.x + dx, -b.w / 2, s.width - b.w / 2)),
          y: Math.round(clamp(b.y + dy, -b.h / 2, s.height - b.h / 2)),
        };
      }
      const left = g.mode === 'nw' || g.mode === 'sw';
      const top = g.mode === 'nw' || g.mode === 'ne';
      let w = Math.max(minSize, b.w + (left ? -dx : dx));
      let h = Math.max(minSize, b.h + (top ? -dy : dy));
      if (p.kind === 'picture') {
        // keep the picture's proportions: follow whichever direction moved more
        const ratio = b.h / b.w;
        if (Math.abs(dx) * ratio >= Math.abs(dy)) h = w * ratio;
        else w = h / ratio;
      }
      return {
        w: Math.round(w),
        h: Math.round(h),
        x: Math.round(left ? b.x + b.w - w : b.x),
        y: Math.round(top ? b.y + b.h - h : b.y),
      };
    });
  }

  private pointerUp(): void {
    this.gesture = null;
  }

  protected pieceKey(e: KeyboardEvent, p: Piece): void {
    if (this.editingId() === p.id || p.fixed) return;
    const s = this.scene();
    if (!s) return;
    const step = (e.shiftKey ? 0.05 : 0.005) * s.width;
    const moves: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (e.key === 'Enter' && p.kind === 'text') {
      e.preventDefault();
      this.startEditing(p);
      return;
    }
    const m = moves[e.key];
    if (!m) return;
    e.preventDefault();
    this.selectedId.set(p.id);
    this.updatePiece(p.id, (q) => ({ x: Math.round(q.x + m[0]), y: Math.round(q.y + m[1]) }));
  }

  private updatePiece(id: number, change: (p: Piece) => Partial<Piece>): void {
    this.pieces.update((list) => list.map((p) => (p.id === id ? { ...p, ...change(p) } : p)));
  }

  // ------------------------------------------------------------ text editing
  protected startEditing(p: Piece): void {
    if (p.kind !== 'text') return;
    this.selectedId.set(p.id);
    this.editingId.set(p.id);
    setTimeout(() => {
      const el = this.textEl(p.id);
      if (!el) return;
      el.focus();
      document.execCommand('defaultParagraphSeparator', false, 'div');
      const range = document.createRange();
      range.selectNodeContents(el);
      range.collapse(false);
      const sel = window.getSelection();
      sel?.removeAllRanges();
      sel?.addRange(range);
    }, 0);
  }

  private stopEditing(): void {
    const id = this.editingId();
    if (id !== null) this.markText(id);
    this.editingId.set(null);
    this.savedRange = null;
    window.getSelection()?.removeAllRanges();
  }

  protected textKey(e: KeyboardEvent): void {
    const mod = e.ctrlKey || e.metaKey;
    if (mod && ['b', 'i', 'u'].includes(e.key.toLowerCase())) {
      e.preventDefault();
      this.toggle(({ b: 'bold', i: 'italic', u: 'underline' } as const)[e.key.toLowerCase() as 'b' | 'i' | 'u']);
    }
    e.stopPropagation(); // arrow keys move the caret, not the box
  }

  protected markText(id: number): void {
    const el = this.textEl(id);
    if (!el) return;
    const changed = JSON.stringify(this.serialize(el)) !== this.baselines.get(id);
    const next = new Set(this.textDirty());
    if (changed) next.add(id);
    else next.delete(id);
    this.textDirty.set(next);
  }

  protected onEscape(): void {
    if (this.editingId() !== null) {
      this.stopEditing();
      return;
    }
    if (this.selectedId() !== null) {
      this.selectedId.set(null);
      return;
    }
    this.requestClose();
  }

  protected requestClose(): void {
    if (this.dirty()) this.confirmClose.set(true);
    else this.close.emit();
  }

  // -------------------------------------------------------------- formatting
  /** Remember the selection before a toolbar control takes focus. */
  protected keepSelection(): void {
    const sel = window.getSelection();
    const el = this.editingEl();
    if (sel && sel.rangeCount && el && el.contains(sel.getRangeAt(0).commonAncestorContainer)) {
      this.savedRange = sel.getRangeAt(0).cloneRange();
    }
  }

  private restoreSelection(): HTMLElement | null {
    const el = this.editingEl();
    if (!el) return null;
    el.focus();
    const sel = window.getSelection();
    let range = this.savedRange;
    if (!range && sel?.rangeCount && el.contains(sel.getRangeAt(0).commonAncestorContainer)) range = sel.getRangeAt(0);
    if (!range || range.collapsed) {
      // nothing selected: format the whole text box
      range = document.createRange();
      range.selectNodeContents(el);
    }
    sel?.removeAllRanges();
    sel?.addRange(range);
    return el;
  }

  protected toggle(cmd: 'bold' | 'italic' | 'underline'): void {
    const el = this.restoreSelection();
    if (!el) return;
    document.execCommand('styleWithCSS', false, 'true');
    document.execCommand(cmd);
    this.afterFormat(el);
  }

  protected applySize(value: string): void {
    const pt = Number(value);
    if (!pt) return;
    this.wrapSelection((span) => {
      span.style.fontSize = `calc(var(--pt) * ${pt})`;
    });
    this.fmtSize.set(pt);
  }

  protected applyColor(hex: string): void {
    this.wrapSelection((span) => {
      span.style.color = hex;
    });
    this.fmtColor.set(hex);
  }

  /**
   * Give the selected text one style by wrapping each selected piece of text in its own
   * span. The innermost style wins, so nothing else about the text changes (no browser
   * formatting commands, which also strip sizes from surrounding text).
   */
  private wrapSelection(style: (span: HTMLSpanElement) => void): void {
    const el = this.restoreSelection();
    const sel = window.getSelection();
    if (!el || !sel || !sel.rangeCount) return;
    const range = sel.getRangeAt(0);
    const texts: Text[] = [];
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (n.textContent && range.intersectsNode(n)) texts.push(n as Text);
    }
    const bounds = texts.map((t) => ({
      t,
      start: t === range.startContainer ? range.startOffset : 0,
      end: t === range.endContainer ? range.endOffset : t.length,
    }));
    const spans: HTMLSpanElement[] = [];
    for (const { t, start, end } of bounds) {
      if (end <= start) continue;
      if (end < t.length) t.splitText(end);
      const piece = start > 0 ? t.splitText(start) : t;
      const span = document.createElement('span');
      style(span);
      piece.replaceWith(span);
      span.appendChild(piece);
      spans.push(span);
    }
    if (spans.length) {
      const next = document.createRange();
      next.setStart(spans[0].firstChild!, 0);
      const last = spans[spans.length - 1].firstChild as Text;
      next.setEnd(last, last.length);
      sel.removeAllRanges();
      sel.addRange(next);
      this.savedRange = next.cloneRange();
    }
    this.afterFormat(el);
  }

  private afterFormat(el: HTMLElement): void {
    const id = Number(el.dataset['id']);
    this.markText(id);
    this.readSelectionFormat();
  }

  private readSelectionFormat(): void {
    const el = this.editingEl();
    const sel = window.getSelection();
    if (!el || !sel || !sel.rangeCount) return;
    const range = sel.getRangeAt(0);
    let node: Node = range.startContainer;
    if (!el.contains(node)) return;
    this.savedRange = range.cloneRange();
    // A caret between elements (e.g. on a new line) takes the look of the nearest text.
    if (node.nodeType !== Node.TEXT_NODE) {
      const kids = node.childNodes;
      const near = kids[range.startOffset] ?? kids[range.startOffset - 1];
      if (near) {
        const walker = document.createTreeWalker(near, NodeFilter.SHOW_TEXT);
        node = walker.nextNode() ?? near;
      }
    }
    const target = (node.nodeType === Node.TEXT_NODE ? node.parentElement : (node as HTMLElement)) ?? el;
    const look = this.lookOf(target, el);
    this.fmtSize.set(look.size);
    this.fmtColor.set(look.color);
    this.fmtBold.set(look.bold);
    this.fmtItalic.set(look.italic);
    this.fmtUnderline.set(look.underline);
  }

  // ----------------------------------------------------------------- saving
  protected reset(): void {
    this.confirmClose.set(false);
    void this.load();
  }

  protected async save(): Promise<void> {
    if (this.editingId() !== null) this.stopEditing();
    const edits: ShapeEdit[] = [];
    for (const p of this.pieces()) {
      const edit: ShapeEdit = { id: p.id };
      if (p.x !== p.orig.x || p.y !== p.orig.y || p.w !== p.orig.w || p.h !== p.orig.h) {
        Object.assign(edit, { x: p.x, y: p.y, w: p.w, h: p.h });
      }
      if (p.kind === 'text' && this.textDirty().has(p.id)) {
        const el = this.textEl(p.id);
        if (el) edit.paragraphs = this.serialize(el);
      }
      if (Object.keys(edit).length > 1) edits.push(edit);
    }
    if (!edits.length) return;
    this.saving.set(true);
    this.error.set(null);
    try {
      const gen = await firstValueFrom(this.api.saveSlide(this.generationId(), this.number(), edits));
      // What is on screen is now the saved state.
      this.pieces.update((list) => list.map((p) => ({ ...p, orig: { x: p.x, y: p.y, w: p.w, h: p.h } })));
      for (const p of this.pieces()) {
        const el = p.kind === 'text' ? this.textEl(p.id) : null;
        if (el) this.baselines.set(p.id, JSON.stringify(this.serialize(el)));
      }
      this.textDirty.set(new Set());
      this.cache.delete(this.number());
      this.saved.emit(gen);
      this.savedOnce.set(true);
      this.showToast('Saved — your download is updated');
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.saving.set(false);
    }
  }

  // ---------------------------------------------------------------- helpers
  protected pad(p: Piece): string {
    const s = this.scene();
    const i = p.insets;
    if (!s || !i) return '0';
    const w = s.width;
    return `${(i.t / w) * 100}% ${(i.r / w) * 100}% ${(i.b / w) * 100}% ${(i.l / w) * 100}%`;
  }

  private textEl(id: number): HTMLElement | null {
    return (this.host.nativeElement as HTMLElement).querySelector(`.text-inner[data-id="${id}"]`);
  }

  private editingEl(): HTMLElement | null {
    const id = this.editingId();
    return id === null ? null : this.textEl(id);
  }

  /** How a piece of text looks on screen, in slide terms (points, hex colour). */
  private lookOf(node: HTMLElement, root: HTMLElement): Omit<Run, 'text'> {
    const cs = getComputedStyle(node);
    let underline = false;
    for (let n: HTMLElement | null = node; n && n !== root.parentElement; n = n.parentElement) {
      if (getComputedStyle(n).textDecorationLine.includes('underline')) {
        underline = true;
        break;
      }
    }
    return {
      size: Math.round((parseFloat(cs.fontSize) / this.ptPx()) * 2) / 2,
      color: rgbToHex(cs.color),
      bold: parseInt(cs.fontWeight, 10) >= 600,
      italic: cs.fontStyle === 'italic' || cs.fontStyle === 'oblique',
      underline,
    };
  }

  /** The text box's content as paragraphs of runs, read from what is on screen. */
  private serialize(root: HTMLElement): { runs: Run[] }[] {
    // Paragraphs are the <div>s; text typed straight into the box forms its own paragraph.
    const groups: Node[][] = [];
    let loose: Node[] | null = null;
    for (const child of Array.from(root.childNodes)) {
      if (child instanceof HTMLElement && /^(DIV|P)$/.test(child.tagName)) {
        loose = null;
        groups.push([child]);
      } else {
        if (!loose) groups.push((loose = []));
        loose.push(child);
      }
    }
    return groups.map((nodes) => {
      const leaves: Node[] = [];
      const collect = (n: Node) => {
        if (n.nodeType === Node.TEXT_NODE || n instanceof HTMLBRElement) leaves.push(n);
        else n.childNodes.forEach(collect);
      };
      nodes.forEach(collect);
      while (leaves.length && leaves[leaves.length - 1] instanceof HTMLBRElement) leaves.pop(); // the browser's placeholder <br>
      const runs: Run[] = [];
      for (const leaf of leaves) {
        const holder = leaf.parentElement && root.contains(leaf.parentElement) ? leaf.parentElement : root;
        if (leaf instanceof HTMLBRElement) runs.push({ ...this.lookOf(holder, root), text: '\n' });
        else if (leaf.textContent) runs.push({ ...this.lookOf(holder, root), text: leaf.textContent.replace(/\u00a0/g, ' ') });
      }
      return { runs: mergeRuns(runs) };
    });
  }
}

// --------------------------------------------------------------------------- //
function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

function rgbToHex(rgb: string): string {
  const m = rgb.match(/\d+(\.\d+)?/g);
  if (!m || m.length < 3) return '#000000';
  return '#' + m.slice(0, 3).map((v) => Math.round(Number(v)).toString(16).padStart(2, '0')).join('').toUpperCase();
}

function mergeRuns(runs: Run[]): Run[] {
  const out: Run[] = [];
  for (const r of runs) {
    const last = out[out.length - 1];
    if (last && last.size === r.size && last.color === r.color && last.bold === r.bold && last.italic === r.italic && last.underline === r.underline) {
      last.text += r.text;
    } else {
      out.push({ ...r });
    }
  }
  return out;
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
}

function runStyle(r: SceneRun): string {
  const font = r.font ? `font-family:'${r.font.replace(/['\\]/g, '')}', Carlito, Calibri, sans-serif;` : '';
  return (
    `font-size:calc(var(--pt) * ${r.size});color:${r.color};font-weight:${r.bold ? 700 : 400};` +
    `font-style:${r.italic ? 'italic' : 'normal'};text-decoration-line:${r.underline ? 'underline' : 'none'};${font}`
  );
}

const ALIGN: Record<string, string> = { l: 'left', ctr: 'center', r: 'right', just: 'justify' };

/** Our own markup from the slide's runs; all text is escaped. */
function paragraphsHtml(paragraphs: SceneParagraph[]): string {
  return paragraphs
    .map((p) => {
      const runs = p.runs
        .map((r) => (r.text === '\n' ? '<br>' : `<span style="${runStyle(r)}">${escapeHtml(r.text)}</span>`))
        .join('');
      const first = p.runs[0];
      const empty = !p.runs.some((r) => r.text && r.text !== '\n');
      const sizeStyle = first ? `font-size:calc(var(--pt) * ${first.size});` : '';
      const bullet = p.bullet === '#' ? ' class="p num"' : p.bullet ? ` class="p" data-bullet="${escapeHtml(p.bullet)}"` : ' class="p"';
      const indent = p.level ? `margin-left:${p.level * 1.5}em;` : '';
      return `<div${bullet} style="text-align:${ALIGN[p.align] ?? 'left'};${indent}${sizeStyle}">${empty ? '<br>' : runs}</div>`;
    })
    .join('');
}
