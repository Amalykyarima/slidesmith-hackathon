import { Component, ElementRef, effect, inject, input, output, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ApiService, errorMessage } from '../../core/api.service';
import { SlideContent, StyleSample } from '../../core/models';

export type SlideMove = -1 | 1;

/** Edits one slide of a generated deck: text, notes, picture and layout. Opens as a modal dialog. */
@Component({
  selector: 'app-slide-editor',
  imports: [FormsModule],
  template: `
    <dialog #dialog class="editor" (cancel)="$event.preventDefault(); close.emit()" aria-labelledby="editor-title">
      <header class="ed-head">
        <h2 id="editor-title">Edit slide {{ index() + 1 }} <span class="muted">of {{ total() }}</span></h2>
        <button type="button" class="btn btn-icon" aria-label="Close editor" (click)="close.emit()">✕</button>
      </header>

      <div class="ed-body">
        <div class="ed-preview">
          @if (preview(); as src) {
            <img [src]="src" alt="Current version of this slide" />
          } @else {
            <div class="no-preview muted small">Preview not available for this slide.</div>
          }
          <div class="order">
            <button type="button" class="btn btn-sm" [disabled]="index() === 0 || busy()" (click)="move.emit(-1)">↑ Move up</button>
            <button type="button" class="btn btn-sm" [disabled]="index() === total() - 1 || busy()" (click)="move.emit(1)">↓ Move down</button>
            <button type="button" class="btn btn-sm" [disabled]="busy()" (click)="addAfter.emit()">+ Add slide after</button>
          </div>
        </div>

        <div class="ed-form">
          <label class="field">
            Title
            <input class="input" [(ngModel)]="title" maxlength="300" />
          </label>
          <label class="field">
            Text <span class="hint">one bullet point per line</span>
            <textarea class="input" rows="7" [(ngModel)]="text"></textarea>
          </label>
          <label class="field">
            Speaker notes <span class="hint">(optional)</span>
            <textarea class="input" rows="2" [(ngModel)]="notes"></textarea>
          </label>

          <div class="field">
            Picture
            <div class="pic-row">
              <input #file type="file" accept="image/*" hidden (change)="pickImage($event)" />
              @if (uploading()) {
                <span class="small muted"><span class="spinner"></span> Uploading…</span>
              } @else if (imageId()) {
                <span class="small">{{ imageName() || 'Picture attached' }}</span>
                <button type="button" class="btn btn-sm" (click)="file.click()">Replace</button>
                <button type="button" class="btn btn-sm" (click)="imageId.set(null); imageName.set('')">Remove</button>
              } @else {
                <button type="button" class="btn btn-sm" (click)="file.click()">Add picture</button>
              }
            </div>
            @if (imageError(); as msg) {
              <span class="small err">{{ msg }}</span>
            }
          </div>

          <div class="field">
            Layout <span class="hint">which of your sample slides this page copies</span>
            @if (samples() === null) {
              <span class="small muted"><span class="spinner"></span> Loading your sample slides…</span>
            } @else {
              <div class="layouts" role="radiogroup" aria-label="Layout">
                <button type="button" role="radio" class="layout auto" [class.selected]="sample() === null"
                        [attr.aria-checked]="sample() === null" (click)="sample.set(null)">
                  <span class="auto-box">Auto</span>
                  <span class="layout-name">Best match</span>
                </button>
                @for (s of samples(); track s.index) {
                  <button type="button" role="radio" class="layout" [class.selected]="sample() === s.index"
                          [attr.aria-checked]="sample() === s.index" (click)="sample.set(s.index)"
                          [title]="'Sample slide ' + s.number + (s.title ? ': ' + s.title : '')">
                    @if (s.preview) {
                      <img [src]="s.preview" alt="" loading="lazy" />
                    } @else {
                      <span class="text-thumb">{{ s.title || 'Slide ' + s.number }}</span>
                    }
                    <span class="layout-name">{{ s.number }}. {{ s.title || s.kind }}</span>
                  </button>
                }
              </div>
            }
          </div>
        </div>
      </div>

      <footer class="ed-foot">
        @if (confirmDelete()) {
          <span class="small">Delete this slide?</span>
          <button type="button" class="btn btn-sm danger" [disabled]="busy()" (click)="remove.emit()">Yes, delete</button>
          <button type="button" class="btn btn-sm" (click)="confirmDelete.set(false)">Keep it</button>
        } @else {
          <button type="button" class="btn btn-sm danger-outline" [disabled]="busy() || total() === 1" (click)="confirmDelete.set(true)">Delete slide</button>
        }
        <span class="grow"></span>
        <button type="button" class="btn" (click)="close.emit()">Cancel</button>
        <button type="button" class="btn btn-primary" [disabled]="busy() || uploading()" (click)="submit()">
          @if (busy()) {
            <span class="spinner"></span> Rebuilding…
          } @else {
            Apply changes
          }
        </button>
      </footer>
    </dialog>
  `,
  styles: `
    .editor {
      width: min(1040px, calc(100vw - 32px));
      max-height: calc(100vh - 32px);
      padding: 0;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: 0 20px 50px rgba(16, 24, 40, 0.25);
      color: var(--ink);
    }
    .editor::backdrop { background: rgba(16, 24, 40, 0.45); }
    .ed-head, .ed-foot { display: flex; align-items: center; gap: 10px; padding: 14px 20px; }
    .ed-head { border-bottom: 1px solid var(--border); justify-content: space-between; }
    .ed-head h2 { margin: 0; }
    .ed-foot { border-top: 1px solid var(--border); flex-wrap: wrap; position: sticky; bottom: 0; background: #fff; }
    .ed-body { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); gap: 20px; padding: 18px 20px; }
    .ed-preview img { width: 100%; display: block; border-radius: 8px; border: 1px solid var(--border); }
    .no-preview { aspect-ratio: 16 / 9; display: grid; place-items: center; background: var(--bg); border-radius: 8px; }
    .order { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
    .ed-form { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
    .field { display: flex; flex-direction: column; gap: 6px; font-weight: 600; font-size: 14px; }
    .hint { font-weight: 400; color: var(--muted); font-size: 13px; }
    textarea.input { resize: vertical; font: inherit; }
    .pic-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-weight: 400; }
    .err { color: var(--danger); font-weight: 400; }
    .layouts { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 8px; max-height: 260px; overflow: auto; padding: 2px; }
    .layout {
      display: flex; flex-direction: column; gap: 4px; padding: 5px; text-align: left; font: inherit; font-weight: 400;
      background: #fff; border: 2px solid var(--border); border-radius: 8px; cursor: pointer; color: inherit;
    }
    .layout:hover { border-color: #b6c2cf; }
    .layout.selected { border-color: var(--primary); background: var(--primary-soft); }
    .layout img, .text-thumb, .auto-box { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; border-radius: 4px; display: block; }
    .text-thumb, .auto-box { display: grid; place-items: center; background: var(--bg); font-size: 11px; padding: 4px; text-align: center; overflow: hidden; }
    .auto-box { font-weight: 700; color: var(--primary); font-size: 14px; }
    .layout-name { font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .grow { flex: 1; }
    .danger { background: var(--danger); border-color: var(--danger); color: #fff; }
    .danger-outline { color: var(--danger); }
    @media (max-width: 760px) {
      .ed-body { grid-template-columns: 1fr; }
      .editor { width: 100vw; max-width: 100vw; max-height: 100vh; height: 100vh; margin: 0; border-radius: 0; }
    }
  `,
})
export class SlideEditor {
  private readonly api = inject(ApiService);
  private readonly dialog = viewChild.required<ElementRef<HTMLDialogElement>>('dialog');

  readonly slide = input.required<SlideContent>();
  readonly index = input.required<number>();
  readonly total = input.required<number>();
  readonly preview = input<string | null>(null);
  readonly samples = input<StyleSample[] | null>(null);
  readonly busy = input(false);

  readonly apply = output<SlideContent>();
  readonly remove = output<void>();
  readonly move = output<SlideMove>();
  readonly addAfter = output<void>();
  readonly close = output<void>();

  protected readonly title = signal('');
  protected readonly text = signal('');
  protected readonly notes = signal('');
  protected readonly imageId = signal<string | null>(null);
  protected readonly imageName = signal('');
  protected readonly sample = signal<number | null>(null);
  protected readonly uploading = signal(false);
  protected readonly imageError = signal<string | null>(null);
  protected readonly confirmDelete = signal(false);

  constructor() {
    // Load the slide into the form whenever a different slide (or a rebuilt version) arrives.
    effect(() => {
      const s = this.slide();
      this.title.set(s.title);
      this.text.set((s.bullets.length ? s.bullets : s.subtitle ? [s.subtitle] : []).join('\n'));
      this.notes.set(s.notes ?? '');
      this.imageId.set(s.image_id ?? null);
      this.imageName.set('');
      this.sample.set(s.sample ?? null);
      this.confirmDelete.set(false);
      this.imageError.set(null);
    });
    effect(() => {
      const d = this.dialog().nativeElement;
      if (!d.open) d.showModal();
    });
  }

  protected async pickImage(event: Event): Promise<void> {
    const inputEl = event.target as HTMLInputElement;
    const file = inputEl.files?.[0];
    inputEl.value = '';
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      this.imageError.set('Please choose an image file (PNG, JPG, GIF or WEBP).');
      return;
    }
    this.uploading.set(true);
    this.imageError.set(null);
    try {
      const img = await firstValueFrom(this.api.uploadImage(file));
      this.imageId.set(img.id);
      this.imageName.set(img.filename);
    } catch (err) {
      this.imageError.set(errorMessage(err));
    } finally {
      this.uploading.set(false);
    }
  }

  protected submit(): void {
    const s = this.slide();
    const bullets = this.text()
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean);
    const imageId = this.imageId();
    let kind = s.kind;
    if (imageId) kind = 'image';
    else if (kind === 'image') kind = 'content';
    const keepSubtitle = (s.kind === 'title' || s.kind === 'section') && !s.bullets.length && bullets.length <= 1;
    this.apply.emit({
      ...s,
      kind,
      title: this.title().trim(),
      subtitle: keepSubtitle ? (bullets[0] ?? '') : '',
      bullets: keepSubtitle ? [] : bullets,
      notes: this.notes().trim(),
      image_id: imageId,
      sample: this.sample(),
    });
  }
}
