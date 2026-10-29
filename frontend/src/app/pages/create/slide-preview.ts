import { Component, computed, input } from '@angular/core';
import { Box, Layout, TextLook, TextRun } from '../../core/models';
import { EditSlide, Fit, arrange, fitText } from './deck';

/**
 * Live preview of one slide, drawn in the browser as the teacher types: the style's blank slide
 * as the background, with the text and picture laid out where the build will put them.
 * It's a close guide, not the real thing: Apply renders the actual slide.
 */
@Component({
  selector: 'app-slide-preview',
  template: `
    <div class="slide" [style.aspect-ratio]="size()[0] + ' / ' + size()[1]" [style.--pt]="pt()" [style.background]="background()">
      @if (layout()?.image; as src) {
        <img class="bg" [src]="src" alt="" />
      }
      @if (loading()) {
        <div class="shimmer" aria-hidden="true"></div>
      }
      @if (boxes(); as b) {
        @if (b.picture && slide().image) {
          <img class="pic" [src]="slide().image!.url" alt="" [style]="place(b.picture)" />
        }
        @if (b.title) {
          <div class="box" [class.guide]="guides()" [style]="place(b.title, fits().title)" [style.justify-content]="anchor(layout()!.title_look, 'middle')">
            @if (guides()) {
              <span class="guide-label">Title</span>
            } @else {
              <p [style.text-align]="align(layout()!.title_look)">
                @for (r of titleRuns(); track $index) {
                  <span [style]="runStyle(r, layout()!.title_look, fits().title)">{{ r.text }}</span>
                }
              </p>
            }
          </div>
        }
        @if (b.body) {
          <div class="box" [class.guide]="guides()" [style]="place(b.body, fits().body)" [style.justify-content]="anchor(layout()!.body_look, 'top')">
            @if (guides()) {
              <span class="guide-label">{{ cover() ? 'Subtitle' : 'Text' }}</span>
            } @else {
              @for (para of slide().body; track $index) {
                <p [class.bullet]="bullets()" [style.text-align]="align(layout()!.body_look)">
                  @for (r of para; track $index) {
                    <span [style]="runStyle(r, layout()!.body_look, fits().body)">{{ r.text }}</span>
                  }
                </p>
              }
            }
          </div>
        }
        @if (guides() && layout()?.picture; as picture) {
          <div class="box guide" [style]="place(picture)"><span class="guide-label">Picture</span></div>
        }
      }
    </div>
  `,
  styles: `
    :host { display: block; }
    .slide {
      position: relative; overflow: hidden; container-type: inline-size; border-radius: 8px;
      border: 1px solid var(--border); box-shadow: var(--shadow);
    }
    .bg { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
    .pic { position: absolute; object-fit: contain; }
    .box {
      position: absolute; display: flex; flex-direction: column;
      padding: calc(var(--pt) * 3.6) calc(var(--pt) * 7.2); line-height: 1.12;
    }
    p { margin: 0 0 0.25em; overflow-wrap: anywhere; white-space: pre-wrap; }
    p.bullet { padding-left: 1em; text-indent: -0.75em; }
    p.bullet::before { content: '•'; display: inline-block; width: 0.75em; text-indent: 0; }
    .guide { border: 1.5px dashed rgba(15, 118, 110, 0.75); background: rgba(224, 242, 240, 0.35); border-radius: 4px; justify-content: center !important; align-items: center; }
    .guide-label { font: 600 clamp(9px, 3cqw, 13px) system-ui, sans-serif; color: var(--primary-dark); background: rgba(255, 255, 255, 0.85); padding: 1px 6px; border-radius: 4px; }
    .shimmer {
      position: absolute; inset: 0;
      background: linear-gradient(100deg, transparent 30%, rgba(255, 255, 255, 0.45) 50%, transparent 70%);
      background-size: 250% 100%; animation: shimmer 1.3s linear infinite;
    }
    @keyframes shimmer { from { background-position: 120% 0; } to { background-position: -120% 0; } }
    @media (prefers-reduced-motion: reduce) { .shimmer { animation-duration: 4s; } }
  `,
})
export class SlidePreview {
  readonly slide = input.required<EditSlide>();
  readonly layout = input.required<Layout | null>();
  /** Slide size in inches. */
  readonly size = input<[number, number]>([13.33, 7.5]);
  readonly tone = input<'dark' | 'light' | 'image'>('light');
  /** Background used until the blank slide image has rendered. */
  readonly fallback = input('#ffffff');
  readonly cover = input(false);
  /** Outline the title/text/picture areas instead of drawing text (blank template view). */
  readonly guides = input(false);
  readonly loading = input(false);

  protected readonly boxes = computed(() => {
    const layout = this.layout();
    if (!layout) return null;
    // The blank template shows every area; a real slide drops what it doesn't use.
    if (this.guides()) return { title: layout.title, body: layout.body, picture: null, titleRoom: null, bodyRoom: null };
    return arrange(layout, this.slide(), this.size());
  });
  /** Text size and grown height per box, as the build will work them out. */
  protected readonly fits = computed(() => {
    const b = this.boxes();
    const layout = this.layout();
    const size = this.size();
    const fit = (paragraphs: TextRun[][], box: Box | null, room: number | null, look: TextLook | null, isTitle: boolean): Fit | null =>
      box && look ? fitText(paragraphs, box, room, look.size, isTitle, size) : null;
    return {
      title: b && layout ? fit([this.titleRuns()], b.title, b.titleRoom, layout.title_look, true) : null,
      body: b && layout ? fit(this.slide().body, b.body, b.bodyRoom, layout.body_look, false) : null,
    };
  });
  protected readonly titleRuns = computed(() => this.slide().title.filter((r) => r.text));
  protected readonly bullets = computed(() => !this.cover() && this.slide().kind === 'content' && !!this.layout()?.body_look?.bullets);
  /** One point, in container units: font sizes scale with the preview's width. */
  protected readonly pt = computed(() => `calc(100cqw / ${72 * this.size()[0]})`);
  protected readonly background = computed(() => (this.layout()?.image ? '#fff' : this.fallback()));

  protected place([l, t, w, h]: Box, fit: Fit | null = null): Record<string, string> {
    const height = fit ? fit.height : h;
    return { left: `${l * 100}%`, top: `${t * 100}%`, width: `${w * 100}%`, height: `${height * 100}%` };
  }

  protected align(look: TextLook | null): string {
    const chosen = this.slide().text_align;
    return chosen !== 'auto' ? chosen : (look?.align ?? 'left');
  }

  protected anchor(look: TextLook | null, fallback: 'top' | 'middle'): string {
    const chosen = this.slide().text_anchor;
    const value = chosen !== 'auto' ? chosen : (look?.anchor ?? fallback);
    return value === 'middle' ? 'center' : value === 'bottom' ? 'flex-end' : 'flex-start';
  }

  protected runStyle(r: TextRun, look: TextLook | null, fit: Fit | null): Record<string, string> {
    const ink = this.tone() === 'dark' ? '#ffffff' : '#1b2430';
    const bold = r.bold ?? look?.bold;
    const italic = r.italic ?? look?.italic;
    const style: Record<string, string> = {
      'font-size': `calc(var(--pt) * ${r.size ?? fit?.pt ?? look?.size ?? 20})`,
      color: r.color ?? look?.color ?? ink,
      'font-family': `${JSON.stringify(r.font ?? look?.font ?? 'Calibri')}, system-ui, sans-serif`,
      'font-weight': bold ? '700' : '400',
      'font-style': italic ? 'italic' : 'normal',
    };
    if (r.underline) style['text-decoration'] = 'underline';
    if (r.highlight) style['background-color'] = r.highlight;
    return style;
  }
}
