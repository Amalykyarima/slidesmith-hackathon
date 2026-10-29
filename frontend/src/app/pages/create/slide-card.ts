import { Component, computed, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ImagePosition, Layout, TextAlign, TextAnchor } from '../../core/models';
import { RichTextEditor } from '../../shared/rich-text-editor';
import { EditKind, EditSlide } from './deck';
import { SlidePreview } from './slide-preview';

const KINDS: { value: EditKind; label: string }[] = [
  { value: 'content', label: 'Content' },
  { value: 'section', label: 'Section break' },
  { value: 'title', label: 'Title' },
];
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

/** What the preview shows: the real rendered slide once applied, otherwise the live drawing. */
export interface BuiltState {
  /** Rendered image of the last build of this slide, if any. */
  image: string | null;
  /** The slide changed since it was last built. */
  stale: boolean;
  /** The last build of this slide is still rendering. */
  rendering: boolean;
}

/**
 * One slide of the deck: its text (formatted per word), picture, positions and notes on the left,
 * a live preview on the right. The cover uses the same card without a picture or slide type.
 */
@Component({
  selector: 'app-slide-card',
  imports: [FormsModule, RichTextEditor, SlidePreview],
  template: `
    @let s = slide();
    <article class="slide-card" [class.cover]="cover()">
      <header>
        @if (!cover()) {
          <span class="drag-handle" draggable="true" (dragstart)="dragStart.emit($event)" (dragend)="dragEnd.emit()" title="Drag to move" aria-hidden="true">⠿</span>
        }
        <strong class="label">{{ label() }}</strong>
        @if (!cover()) {
          <select class="kind" [attr.aria-label]="'Type of ' + label()" [ngModel]="s.kind" (ngModelChange)="changed.emit({ kind: $event })">
            @for (k of kinds; track k.value) {
              <option [value]="k.value">{{ k.label }}</option>
            }
          </select>
          <span class="grow"></span>
          <button type="button" class="btn btn-icon btn-xs" [disabled]="index() === 0" (click)="move.emit(-1)" [attr.aria-label]="'Move ' + label() + ' up'">↑</button>
          <button type="button" class="btn btn-icon btn-xs" [disabled]="index() === count() - 1" (click)="move.emit(1)" [attr.aria-label]="'Move ' + label() + ' down'">↓</button>
          <button type="button" class="btn btn-icon btn-xs" (click)="remove.emit()" [attr.aria-label]="'Delete ' + label()">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2m-9 0 1 14h8l1-14"/></svg>
          </button>
        } @else {
          <span class="grow"></span>
          <ng-content />
        }
      </header>

      <div class="cols">
        <div class="fields">
          <div class="field">
            <span class="field-label">Title</span>
            <app-rich-text-editor
              [value]="s.title.length ? [s.title] : []"
              [fonts]="fonts()"
              [singleLine]="true"
              [label]="'Title of ' + label()"
              [placeholder]="cover() ? 'e.g. Cells and Photosynthesis' : 'Slide title'"
              (changed)="changed.emit({ title: $event.flat() })"
            />
          </div>
          <div class="field">
            <span class="field-label">
              {{ textLabel() }}
              @if (!cover()) {
                <span class="hint">or rough notes for the AI</span>
              }
            </span>
            <app-rich-text-editor
              [value]="s.body"
              [fonts]="fonts()"
              [label]="textLabel() + ' of ' + label()"
              [placeholder]="cover() ? 'e.g. Year 9 Biology  |  Mr. Adams' : 'One bullet point per line'"
              (changed)="changed.emit({ body: $event })"
            />
          </div>

          @if (!cover()) {
            <div class="attach">
              <input #file type="file" accept="image/*" hidden (change)="pick($event)" />
              @if (s.image; as img) {
                <span class="attached">
                  <img [src]="img.url" alt="" />
                  <span class="small">{{ img.filename }}</span>
                  <button type="button" class="btn btn-icon btn-xs" aria-label="Remove picture" (click)="detach.emit()">✕</button>
                </span>
              } @else if (uploading()) {
                <span class="small muted"><span class="spinner"></span> Uploading…</span>
              } @else {
                <button type="button" class="btn btn-sm" (click)="file.click()">
                  <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>
                  Add picture
                </button>
              }
              @if (error(); as message) {
                <span class="small err">{{ message }}</span>
              }
            </div>
          }

          <div class="choices">
            @if (s.image) {
              <fieldset>
                <legend>Picture</legend>
                <div class="seg">
                  @for (o of imagePositions; track o.value) {
                    <button type="button" [class.on]="s.image_position === o.value" [attr.aria-pressed]="s.image_position === o.value" (click)="changed.emit({ image_position: o.value })">{{ o.label }}</button>
                  }
                </div>
                @if (s.image_position === 'large') {
                  <p class="muted small">The picture fills the slide; the text moves to the speaker notes.</p>
                }
              </fieldset>
            }
            <fieldset>
              <legend>Text across</legend>
              <div class="seg">
                @for (o of aligns; track o.value) {
                  <button type="button" [class.on]="s.text_align === o.value" [attr.aria-pressed]="s.text_align === o.value" (click)="changed.emit({ text_align: o.value })">{{ o.label }}</button>
                }
              </div>
            </fieldset>
            <fieldset>
              <legend>Text up/down</legend>
              <div class="seg">
                @for (o of anchors; track o.value) {
                  <button type="button" [class.on]="s.text_anchor === o.value" [attr.aria-pressed]="s.text_anchor === o.value" (click)="changed.emit({ text_anchor: o.value })">{{ o.label }}</button>
                }
              </div>
            </fieldset>
          </div>

          <details class="notes" [open]="!!s.notes">
            <summary>Speaker notes</summary>
            <textarea class="input" rows="2" maxlength="4000" [attr.aria-label]="'Speaker notes for ' + label()" [ngModel]="s.notes" (ngModelChange)="changed.emit({ notes: $event })"></textarea>
          </details>
        </div>

        <div class="preview">
          @let b = built();
          @if (b.image && !b.stale) {
            <button type="button" class="shot" (click)="enlarge.emit()" [attr.aria-label]="'View ' + label() + ' full size'">
              <img [src]="b.image" [alt]="label() + ' as built'" />
            </button>
            <span class="tag tag-ok">✓ Applied</span>
          } @else {
            <div class="live">
              <app-slide-preview
                [slide]="s"
                [layout]="layout()"
                [size]="size()"
                [tone]="tone()"
                [fallback]="fallback()"
                [cover]="cover()"
                [loading]="layoutLoading() || b.rendering"
              />
              @if (b.rendering) {
                <span class="rendering"><span class="spinner"></span> Rendering…</span>
              }
            </div>
            <span class="tag" [class.tag-warn]="b.image && b.stale">{{ b.image && b.stale ? 'Live preview · not applied yet' : 'Live preview' }}</span>
          }
        </div>
      </div>
    </article>
  `,
  styles: `
    :host { display: block; }
    .slide-card { padding: 14px; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow); }
    .slide-card.cover { border-style: dashed; }
    header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
    .label { font-size: 15px; white-space: nowrap; }
    .kind { padding: 4px 6px; font: inherit; font-size: 13px; border: 1px solid var(--border); border-radius: 6px; background: #fff; color: var(--ink); }
    .drag-handle { cursor: grab; font-size: 18px; line-height: 1; color: var(--muted); user-select: none; }
    .drag-handle:active { cursor: grabbing; }
    .btn-xs { width: 28px; height: 28px; padding: 0; font-size: 13px; }
    .grow { flex: 1; }
    .cols { display: grid; grid-template-columns: minmax(0, 1fr) minmax(260px, 42%); gap: 18px; align-items: start; }
    .fields { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
    .field { display: flex; flex-direction: column; gap: 4px; }
    .field-label { font-size: 13px; font-weight: 600; }
    .hint { font-weight: 400; color: var(--muted); }
    .attach { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
    .attached { display: inline-flex; align-items: center; gap: 8px; padding: 4px; background: #fff; border: 1px solid var(--border); border-radius: 8px; }
    .attached img { width: 44px; height: 32px; object-fit: cover; border-radius: 4px; }
    .attached .small { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .err { color: var(--danger); }
    .choices { display: flex; flex-wrap: wrap; gap: 14px; }
    fieldset { border: none; margin: 0; padding: 0; min-width: 0; }
    legend { font-size: 13px; font-weight: 600; margin-bottom: 4px; padding: 0; }
    .seg { display: inline-flex; flex-wrap: wrap; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; background: #fff; }
    .seg button { border: none; border-right: 1px solid var(--border); background: none; padding: 5px 10px; font: inherit; font-size: 13px; cursor: pointer; color: var(--ink); transition: background 0.15s; }
    .seg button:last-child { border-right: none; }
    .seg button.on { background: var(--primary); color: #fff; }
    .seg button:focus-visible { outline: 2px solid var(--primary); outline-offset: -2px; }
    .notes summary { cursor: pointer; font-size: 13px; font-weight: 600; margin-bottom: 6px; }
    .notes textarea { min-height: 60px; }
    .preview { position: sticky; top: 76px; display: flex; flex-direction: column; gap: 6px; }
    .live { position: relative; }
    .shot { display: block; width: 100%; padding: 0; border: none; background: none; cursor: zoom-in; border-radius: 8px; animation: fade-in 0.35s ease-out; }
    .shot img { width: 100%; display: block; border-radius: 8px; border: 1px solid var(--border); box-shadow: var(--shadow); }
    .shot:focus-visible { outline: 2px solid var(--primary); outline-offset: 3px; }
    .rendering {
      position: absolute; right: 8px; bottom: 8px; display: inline-flex; align-items: center; gap: 6px;
      padding: 3px 9px; font-size: 12px; font-weight: 600; background: rgba(255, 255, 255, 0.92); border-radius: 999px; box-shadow: var(--shadow);
    }
    .tag { align-self: flex-start; font-size: 12px; font-weight: 600; color: var(--muted); }
    .tag-ok { color: var(--primary-dark); }
    .tag-warn { color: var(--warn-ink); }
    @keyframes fade-in { from { opacity: 0; transform: scale(0.985); } to { opacity: 1; transform: none; } }
    @media (max-width: 760px) { .cols { grid-template-columns: 1fr; } .preview { position: static; order: -1; } }
  `,
})
export class SlideCard {
  readonly slide = input.required<EditSlide>();
  readonly label = input.required<string>();
  readonly cover = input(false);
  readonly index = input(0);
  readonly count = input(1);
  readonly fonts = input<string[]>([]);
  readonly layout = input<Layout | null>(null);
  readonly layoutLoading = input(false);
  readonly size = input<[number, number]>([13.33, 7.5]);
  readonly tone = input<'dark' | 'light' | 'image'>('light');
  readonly fallback = input('#ffffff');
  readonly built = input<BuiltState>({ image: null, stale: true, rendering: false });
  readonly uploading = input(false);
  readonly error = input<string | null>(null);

  readonly changed = output<Partial<EditSlide>>();
  readonly attach = output<File>();
  readonly detach = output<void>();
  readonly remove = output<void>();
  readonly move = output<number>();
  readonly dragStart = output<DragEvent>();
  readonly dragEnd = output<void>();
  readonly enlarge = output<void>();

  protected readonly kinds = KINDS;
  protected readonly imagePositions = IMAGE_POSITIONS;
  protected readonly aligns = ALIGNS;
  protected readonly anchors = ANCHORS;

  protected readonly textLabel = computed(() => (this.cover() || this.slide().kind !== 'content' ? 'Subtitle' : 'Bullet points'));

  protected pick(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (file) this.attach.emit(file);
  }
}
