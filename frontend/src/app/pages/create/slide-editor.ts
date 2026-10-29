import { Component, inject, input, linkedSignal, output, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ApiService, errorMessage } from '../../core/api.service';
import { Generation, ImagePosition, SlideContent, TextAlign, TextAnchor, TextRun } from '../../core/models';
import { RichTextEditor } from '../../shared/rich-text-editor';

const IMAGE_POSITIONS: { value: ImagePosition; label: string }[] = [
  { value: 'auto', label: 'Template' },
  { value: 'left', label: 'Left' },
  { value: 'right', label: 'Right' },
  { value: 'top', label: 'Top' },
  { value: 'large', label: 'Large' },
  { value: 'none', label: 'Hidden' },
];
const ALIGNS: { value: TextAlign; label: string }[] = [
  { value: 'auto', label: 'Template' },
  { value: 'left', label: 'Left' },
  { value: 'center', label: 'Centre' },
  { value: 'right', label: 'Right' },
];
const ANCHORS: { value: TextAnchor; label: string }[] = [
  { value: 'auto', label: 'Template' },
  { value: 'top', label: 'Top' },
  { value: 'middle', label: 'Middle' },
  { value: 'bottom', label: 'Bottom' },
];

/**
 * Edit generated slides (formatted text, picture and text position, notes) and build them
 * again in the same style. Rebuilding never calls the AI, so the teacher's edits are kept as-is.
 */
@Component({
  selector: 'app-slide-editor',
  imports: [FormsModule, RichTextEditor],
  template: `
    <div class="editor-head">
      <div>
        <h3>Edit slides</h3>
        <p class="muted small">
          Select words to change their font, size, colour or highlight. Each line in the body is one bullet point.
          Then rebuild: the AI isn't used again, so your changes stay exactly as you made them.
        </p>
      </div>
    </div>

    @for (s of edits(); track s.page; let i = $index) {
      <article class="slide-edit">
        <header>
          <strong>{{ s.page === 0 ? 'Cover' : 'Slide ' + s.page }}</strong>
          <span class="badge">{{ s.kind }}</span>
        </header>
        <div class="cols">
          <div class="thumb">
            @if (generation().previews[i]; as src) {
              <img [src]="src" [alt]="'Current ' + (s.page === 0 ? 'cover' : 'slide ' + s.page)" loading="lazy" />
            } @else {
              <span class="muted small">No preview yet</span>
            }
          </div>

          <div class="fields">
            <div class="field">
              <span class="field-label">Title</span>
              <app-rich-text-editor
                [initial]="titleOf(s)"
                [fonts]="fonts()"
                [singleLine]="true"
                [label]="'Title of ' + (s.page === 0 ? 'the cover' : 'slide ' + s.page)"
                placeholder="Slide title"
                (changed)="setTitle(i, $event)"
              />
            </div>
            <div class="field">
              <span class="field-label">{{ s.kind === 'title' || s.kind === 'section' ? 'Subtitle' : 'Bullet points' }}</span>
              <app-rich-text-editor
                [initial]="bodyOf(s)"
                [fonts]="fonts()"
                [label]="'Body of ' + (s.page === 0 ? 'the cover' : 'slide ' + s.page)"
                placeholder="One bullet point per line"
                (changed)="patch(i, { body_runs: $event })"
              />
            </div>

            <div class="choices">
              @if (generation().image_pages.includes(s.page)) {
                <fieldset>
                  <legend>Picture</legend>
                  <div class="seg">
                    @for (o of imagePositions; track o.value) {
                      <button type="button" [class.on]="(s.image_position ?? 'auto') === o.value" [attr.aria-pressed]="(s.image_position ?? 'auto') === o.value" (click)="patch(i, { image_position: o.value })">{{ o.label }}</button>
                    }
                  </div>
                  @if (s.image_position === 'large') {
                    <p class="muted small">The picture fills the slide; bullet points move to the speaker notes.</p>
                  }
                </fieldset>
              }
              <fieldset>
                <legend>Text across</legend>
                <div class="seg">
                  @for (o of aligns; track o.value) {
                    <button type="button" [class.on]="(s.text_align ?? 'auto') === o.value" [attr.aria-pressed]="(s.text_align ?? 'auto') === o.value" (click)="patch(i, { text_align: o.value })">{{ o.label }}</button>
                  }
                </div>
              </fieldset>
              <fieldset>
                <legend>Text up/down</legend>
                <div class="seg">
                  @for (o of anchors; track o.value) {
                    <button type="button" [class.on]="(s.text_anchor ?? 'auto') === o.value" [attr.aria-pressed]="(s.text_anchor ?? 'auto') === o.value" (click)="patch(i, { text_anchor: o.value })">{{ o.label }}</button>
                  }
                </div>
              </fieldset>
            </div>

            <label class="field">
              <span class="field-label">Speaker notes</span>
              <textarea class="input" rows="2" maxlength="4000" [ngModel]="s.notes" (ngModelChange)="patch(i, { notes: $event })"></textarea>
            </label>
          </div>
        </div>
      </article>
    }

    @if (error(); as message) {
      <div class="alert alert-error" role="alert">{{ message }}</div>
    }
    <div class="actions">
      <button type="button" class="btn btn-primary" [disabled]="rebuilding() || !dirty()" (click)="rebuild()">
        @if (rebuilding()) {
          <span class="spinner"></span> Rebuilding…
        } @else {
          Rebuild slides
        }
      </button>
      @if (!dirty()) {
        <span class="muted small">Make a change to rebuild.</span>
      }
    </div>
  `,
  styles: `
    :host { display: block; margin-top: 20px; padding-top: 18px; border-top: 1px solid var(--border); }
    .editor-head { margin-bottom: 12px; }
    .slide-edit { padding: 14px; margin-bottom: 14px; background: var(--bg); border-radius: 10px; }
    header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
    .cols { display: grid; grid-template-columns: minmax(160px, 260px) 1fr; gap: 16px; align-items: start; }
    .thumb img { width: 100%; display: block; border-radius: 6px; border: 1px solid var(--border); }
    .fields { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
    .field { display: flex; flex-direction: column; gap: 4px; }
    .field-label { font-size: 13px; font-weight: 600; }
    .choices { display: flex; flex-wrap: wrap; gap: 14px; }
    fieldset { border: none; margin: 0; padding: 0; min-width: 0; }
    legend { font-size: 13px; font-weight: 600; margin-bottom: 4px; padding: 0; }
    .seg { display: inline-flex; flex-wrap: wrap; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; background: #fff; }
    .seg button { border: none; border-right: 1px solid var(--border); background: none; padding: 5px 10px; font: inherit; font-size: 13px; cursor: pointer; color: var(--ink); }
    .seg button:last-child { border-right: none; }
    .seg button.on { background: var(--primary); color: #fff; }
    .seg button:focus-visible { outline: 2px solid var(--primary); outline-offset: -2px; }
    .actions { display: flex; align-items: center; gap: 12px; margin-top: 6px; }
    @media (max-width: 720px) { .cols { grid-template-columns: 1fr; } .thumb { max-width: 320px; } }
  `,
})
export class SlideEditor {
  private readonly api = inject(ApiService);

  readonly generation = input.required<Generation>();
  readonly fonts = input<string[]>([]);
  readonly rebuilt = output<Generation>();

  protected readonly imagePositions = IMAGE_POSITIONS;
  protected readonly aligns = ALIGNS;
  protected readonly anchors = ANCHORS;

  /**
   * Working copy of the slides. It starts again only when a different deck arrives (a rebuild),
   * not when the same deck is re-fetched while its previews render.
   */
  protected readonly edits = linkedSignal<string, SlideContent[]>({
    source: () => this.generation().id,
    computation: () => structuredClone(untracked(this.generation).slides),
  });
  protected readonly dirty = linkedSignal<string, boolean>({ source: () => this.generation().id, computation: () => false });
  protected readonly rebuilding = signal(false);
  protected readonly error = signal<string | null>(null);

  protected titleOf(s: SlideContent): TextRun[][] {
    return [s.title_runs?.length ? s.title_runs : [{ text: s.title }]];
  }

  protected bodyOf(s: SlideContent): TextRun[][] {
    if (s.body_runs) return s.body_runs;
    if (s.bullets.length) return s.bullets.map((b) => [{ text: b }]);
    return s.subtitle ? [[{ text: s.subtitle }]] : [];
  }

  protected setTitle(index: number, paragraphs: TextRun[][]): void {
    const runs = paragraphs.flat();
    this.patch(index, { title_runs: runs, title: runs.map((r) => r.text).join('').trim() });
  }

  protected patch(index: number, changes: Partial<SlideContent>): void {
    this.edits.update((slides) => slides.map((s, i) => (i === index ? { ...s, ...changes } : s)));
    this.dirty.set(true);
  }

  protected async rebuild(): Promise<void> {
    this.error.set(null);
    this.rebuilding.set(true);
    try {
      this.rebuilt.emit(await firstValueFrom(this.api.rebuild(this.generation().id, this.edits())));
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.rebuilding.set(false);
    }
  }
}
