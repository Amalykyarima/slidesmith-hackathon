import { Component, ElementRef, afterNextRender, input, output, viewChild } from '@angular/core';
import { TextRun } from '../core/models';

/** Sizes are shown at half scale so a 44pt title fits the editor; the real size is kept in data-pt. */
const SCALE = 0.5;
const SIZES = [10, 12, 14, 16, 18, 20, 24, 28, 32, 36, 40, 44, 48, 54, 60, 72];
const COMMON_FONTS = ['Arial', 'Calibri', 'Century Gothic', 'Comic Sans MS', 'Georgia', 'Tahoma', 'Times New Roman', 'Trebuchet MS', 'Verdana'];

type Format = Omit<TextRun, 'text'>;

/**
 * Small rich-text editor for one slide text area. Each line is a paragraph (one bullet in the body).
 * Formatting uses the browser's editing commands; the DOM is read back into plain runs, so no HTML
 * from the browser ever reaches the server. Unset formatting means "as the template has it".
 */
@Component({
  selector: 'app-rich-text-editor',
  template: `
    <div class="toolbar" role="toolbar" [attr.aria-label]="label() + ' formatting'">
      <select class="tool" aria-label="Font" (change)="font($any($event.target))">
        <option value="">Font</option>
        @for (f of fontList(); track f) {
          <option [value]="f" [style.font-family]="f">{{ f }}</option>
        }
      </select>
      <select class="tool size" aria-label="Font size" (change)="size($any($event.target))">
        <option value="">Size</option>
        @for (s of sizes; track s) {
          <option [value]="s">{{ s }}</option>
        }
      </select>
      <button type="button" class="tool" aria-label="Bold" title="Bold (Ctrl+B)" (mousedown)="$event.preventDefault()" (click)="exec('bold')"><b>B</b></button>
      <button type="button" class="tool" aria-label="Italic" title="Italic (Ctrl+I)" (mousedown)="$event.preventDefault()" (click)="exec('italic')"><i>I</i></button>
      <button type="button" class="tool" aria-label="Underline" title="Underline (Ctrl+U)" (mousedown)="$event.preventDefault()" (click)="exec('underline')"><u>U</u></button>
      <label class="tool swatch" title="Text colour">
        <span aria-hidden="true" class="a" style="border-bottom-color: #c00000">A</span>
        <input type="color" value="#c00000" aria-label="Text colour" (change)="exec('foreColor', $any($event.target).value)" />
      </label>
      <label class="tool swatch" title="Highlight">
        <span aria-hidden="true" class="hl">ab</span>
        <input type="color" value="#ffff00" aria-label="Highlight colour" (change)="exec('hiliteColor', $any($event.target).value)" />
      </label>
      <button type="button" class="tool clear" title="Back to the template's style" (mousedown)="$event.preventDefault()" (click)="clear()">Clear</button>
    </div>
    <div
      #area
      class="area"
      [class.single]="singleLine()"
      contenteditable="true"
      role="textbox"
      [attr.aria-multiline]="!singleLine()"
      [attr.aria-label]="label()"
      [attr.data-placeholder]="placeholder()"
      (input)="emit()"
      (keydown)="onKey($event)"
      (paste)="onPaste($event)"
      (blur)="saveSelection()"
      (mouseup)="saveSelection()"
      (keyup)="saveSelection()"
    ></div>
  `,
  styles: `
    :host { display: block; border: 1px solid var(--border); border-radius: 8px; background: #fff; }
    :host(:focus-within) { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-soft); }
    .toolbar { display: flex; flex-wrap: wrap; gap: 4px; padding: 6px; border-bottom: 1px solid var(--border); background: var(--bg); border-radius: 8px 8px 0 0; }
    .tool {
      height: 28px; min-width: 28px; padding: 0 6px; border: 1px solid var(--border); border-radius: 6px;
      background: #fff; color: var(--ink); font: inherit; font-size: 13px; cursor: pointer;
      display: inline-flex; align-items: center; justify-content: center;
    }
    .tool:hover { border-color: var(--muted); }
    .tool:focus-visible { outline: 2px solid var(--primary); outline-offset: 1px; }
    select.tool { max-width: 130px; }
    select.size { max-width: 70px; }
    .swatch { position: relative; }
    .swatch input { position: absolute; inset: 0; opacity: 0; cursor: pointer; width: 100%; height: 100%; }
    .swatch .a { font-weight: 700; border-bottom: 3px solid; line-height: 1.1; }
    .swatch .hl { background: #ffff00; padding: 0 3px; border-radius: 2px; }
    .clear { color: var(--muted); }
    .area { min-height: 72px; padding: 10px 12px; outline: none; font-size: 15px; line-height: 1.45; white-space: pre-wrap; overflow-wrap: anywhere; }
    .area.single { min-height: 0; font-size: 18px; }
    .area:empty::before { content: attr(data-placeholder); color: var(--muted); font-weight: 400; }
  `,
})
export class RichTextEditor {
  /** Starting content: one array of runs per paragraph. Read once; edits flow out through `changed`. */
  readonly initial = input.required<TextRun[][]>();
  readonly fonts = input<string[]>([]);
  readonly singleLine = input(false);
  readonly label = input('Text');
  readonly placeholder = input('');
  readonly changed = output<TextRun[][]>();

  protected readonly sizes = SIZES;
  private readonly area = viewChild.required<ElementRef<HTMLDivElement>>('area');
  private range: Range | null = null;

  constructor() {
    afterNextRender(() => (this.area().nativeElement.innerHTML = toHtml(this.initial())));
  }

  protected fontList(): string[] {
    return [...new Set([...this.fonts(), ...COMMON_FONTS])];
  }

  protected saveSelection(): void {
    const sel = window.getSelection();
    if (sel?.rangeCount && this.area().nativeElement.contains(sel.anchorNode)) this.range = sel.getRangeAt(0).cloneRange();
  }

  /** Puts the caret/selection back after a toolbar control took focus. */
  private restoreSelection(): boolean {
    const el = this.area().nativeElement;
    el.focus();
    if (!this.range) return false;
    const sel = window.getSelection();
    sel?.removeAllRanges();
    sel?.addRange(this.range);
    return !this.range.collapsed;
  }

  protected exec(command: string, value?: string): void {
    this.restoreSelection();
    document.execCommand('styleWithCSS', false, 'true');
    document.execCommand(command, false, value);
    this.emit();
  }

  protected font(select: HTMLSelectElement): void {
    if (select.value) this.exec('fontName', select.value);
    select.value = '';
  }

  protected size(select: HTMLSelectElement): void {
    const pt = Number(select.value);
    select.value = '';
    if (!pt || !this.restoreSelection()) return;
    // The browser only knows sizes 1-7: mark the selection with 7, then swap in the real size.
    document.execCommand('styleWithCSS', false, 'true');
    document.execCommand('fontSize', false, '7');
    const root = this.area().nativeElement;
    root.querySelectorAll<HTMLElement>('font[size="7"], span[style*="xxx-large"], span[style*="-webkit-xxx-large"]').forEach((el) => {
      el.removeAttribute('size');
      el.style.fontSize = `${pt * SCALE}pt`;
      el.dataset['pt'] = String(pt);
    });
    this.emit();
  }

  protected clear(): void {
    this.exec('removeFormat');
  }

  protected onKey(event: KeyboardEvent): void {
    if (event.key === 'Enter' && this.singleLine()) event.preventDefault();
  }

  /** Paste as plain text, so formatting copied from elsewhere doesn't sneak in. */
  protected onPaste(event: ClipboardEvent): void {
    event.preventDefault();
    let text = event.clipboardData?.getData('text/plain') ?? '';
    if (this.singleLine()) text = text.replace(/\s*\n\s*/g, ' ');
    document.execCommand('insertText', false, text);
  }

  protected emit(): void {
    this.changed.emit(fromDom(this.area().nativeElement));
  }
}

// ----------------------------------------------------------------------------- runs <-> DOM

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function toHtml(paragraphs: TextRun[][]): string {
  return paragraphs
    .map((runs) => {
      const inner = runs
        .map((r) => {
          const css: string[] = [];
          if (r.bold != null) css.push(`font-weight:${r.bold ? 700 : 400}`);
          if (r.italic != null) css.push(`font-style:${r.italic ? 'italic' : 'normal'}`);
          if (r.underline != null) css.push(`text-decoration:${r.underline ? 'underline' : 'none'}`);
          if (r.size) css.push(`font-size:${r.size * SCALE}pt`);
          if (r.font) css.push(`font-family:${escapeHtml(JSON.stringify(r.font))}`);
          if (r.color) css.push(`color:#${r.color.replace('#', '')}`);
          if (r.highlight) css.push(`background-color:#${r.highlight.replace('#', '')}`);
          const pt = r.size ? ` data-pt="${r.size}"` : '';
          return css.length ? `<span style="${css.join(';')}"${pt}>${escapeHtml(r.text)}</span>` : escapeHtml(r.text);
        })
        .join('');
      return `<div>${inner || '<br>'}</div>`;
    })
    .join('');
}

function toHex(color: string): string | null {
  if (!color || color === 'transparent') return null;
  if (color.startsWith('#')) return color.length === 4 ? '#' + [...color.slice(1)].map((c) => c + c).join('') : color;
  const m = color.match(/rgba?\(([^)]+)\)/);
  if (!m) return null;
  const [r, g, b, a] = m[1].split(',').map((v) => parseFloat(v));
  if (a === 0) return null;
  return '#' + [r, g, b].map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
}

function formatOf(el: HTMLElement, base: Format): Format {
  const f: Format = { ...base };
  const tag = el.tagName;
  if (tag === 'B' || tag === 'STRONG') f.bold = true;
  if (tag === 'I' || tag === 'EM') f.italic = true;
  if (tag === 'U') f.underline = true;
  if (tag === 'FONT') {
    const face = el.getAttribute('face');
    const color = toHex(el.getAttribute('color') ?? '');
    if (face) f.font = face;
    if (color) f.color = color;
  }
  const s = el.style;
  if (s.fontWeight) f.bold = s.fontWeight === 'bold' || s.fontWeight === 'bolder' || Number(s.fontWeight) >= 600;
  if (s.fontStyle) f.italic = s.fontStyle === 'italic' || s.fontStyle === 'oblique';
  const deco = s.textDecorationLine || s.textDecoration;
  if (deco) f.underline = deco.includes('underline');
  const color = toHex(s.color);
  if (color) f.color = color;
  const highlight = toHex(s.backgroundColor);
  if (highlight) f.highlight = highlight;
  if (s.fontFamily) f.font = s.fontFamily.split(',')[0].replace(/["']/g, '').trim();
  if (s.fontSize && el.dataset['pt']) f.size = Number(el.dataset['pt']);
  return f;
}

const BLOCKS = new Set(['DIV', 'P', 'LI', 'UL', 'OL']);

function sameFormat(a: Format, b: Format): boolean {
  const keys: (keyof Format)[] = ['bold', 'italic', 'underline', 'size', 'font', 'color', 'highlight'];
  return keys.every((k) => (a[k] ?? null) === (b[k] ?? null));
}

function fromDom(root: HTMLElement): TextRun[][] {
  const paragraphs: TextRun[][] = [[]];
  const current = () => paragraphs[paragraphs.length - 1];
  const breakLine = () => {
    if (current().length) paragraphs.push([]);
  };
  const walk = (node: Node, fmt: Format) => {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = (node.textContent ?? '').replace(/ /g, ' ');
      if (!text) return;
      const runs = current();
      const last = runs[runs.length - 1];
      if (last && sameFormat(last, fmt)) last.text += text;
      else runs.push({ ...clean(fmt), text });
      return;
    }
    if (!(node instanceof HTMLElement)) return;
    if (node.tagName === 'BR') {
      paragraphs.push([]);
      return;
    }
    const block = BLOCKS.has(node.tagName);
    if (block) breakLine();
    const f = formatOf(node, fmt);
    node.childNodes.forEach((child) => walk(child, f));
    if (block) breakLine();
  };
  root.childNodes.forEach((child) => walk(child, {}));
  return paragraphs.filter((runs) => runs.some((r) => r.text.trim()));
}

/** Drops unset keys so the JSON stays small and "unset" means "template". */
function clean(fmt: Format): Format {
  return Object.fromEntries(Object.entries(fmt).filter(([, v]) => v !== undefined && v !== null)) as Format;
}
