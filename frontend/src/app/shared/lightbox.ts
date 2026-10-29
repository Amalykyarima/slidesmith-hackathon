import { Component, ElementRef, afterNextRender, computed, input, linkedSignal, output, viewChild } from '@angular/core';

/**
 * Full-size viewer for slide images. Render it with `@if` when opening and drop it on `closed`.
 * A native modal <dialog>: focus stays inside, Esc closes, arrow keys step through the slides.
 */
@Component({
  selector: 'app-lightbox',
  template: `
    <dialog #dialog class="lightbox" aria-label="Slide preview" (close)="closed.emit()" (click)="closeOnBackdrop($event)">
      <figure>
        <img [src]="images()[index()]" [alt]="caption()" />
        <figcaption>
          <span>{{ caption() }}</span>
          @if (images().length > 1) {
            <span class="count">{{ index() + 1 }} / {{ images().length }}</span>
          }
        </figcaption>
      </figure>

      @if (images().length > 1) {
        <button type="button" class="nav prev" aria-label="Previous slide" [disabled]="index() === 0" (click)="step(-1)">‹</button>
        <button type="button" class="nav next" aria-label="Next slide" [disabled]="index() === images().length - 1" (click)="step(1)">›</button>
      }
      <button type="button" class="close" aria-label="Close preview" (click)="dialog.close()">✕</button>
    </dialog>
  `,
  styles: `
    .lightbox {
      border: none; padding: 48px 72px 24px; background: transparent; max-width: 100vw; max-height: 100vh;
      width: 100vw; height: 100vh; display: grid; place-items: center; color: #fff;
    }
    .lightbox::backdrop { background: rgba(10, 14, 20, 0.86); }
    figure { margin: 0; display: flex; flex-direction: column; align-items: center; gap: 10px; min-height: 0; }
    img {
      display: block; max-width: calc(100vw - 160px); max-height: calc(100vh - 120px); object-fit: contain;
      border-radius: 8px; background: #fff; box-shadow: 0 12px 40px rgba(0, 0, 0, 0.45);
    }
    figcaption { display: flex; gap: 14px; font-size: 14px; opacity: 0.9; }
    .count { opacity: 0.7; }
    button {
      position: fixed; border: none; border-radius: 999px; cursor: pointer; color: #fff;
      background: rgba(255, 255, 255, 0.14); display: grid; place-items: center;
    }
    button:hover:not(:disabled) { background: rgba(255, 255, 255, 0.28); }
    button:focus-visible { outline: 2px solid #fff; outline-offset: 2px; }
    button:disabled { opacity: 0.3; cursor: default; }
    .nav { top: 50%; transform: translateY(-50%); width: 48px; height: 48px; font-size: 30px; line-height: 1; }
    .prev { left: 16px; }
    .next { right: 16px; }
    .close { top: 14px; right: 16px; width: 40px; height: 40px; font-size: 18px; }
    @media (max-width: 640px) {
      .lightbox { padding: 56px 8px 16px; }
      img { max-width: calc(100vw - 16px); }
      .nav { top: auto; bottom: 16px; transform: none; }
    }
  `,
  host: { '(document:keydown)': 'onKey($event)' },
})
export class Lightbox {
  readonly images = input.required<string[]>();
  readonly captions = input<string[]>([]);
  readonly start = input(0);
  readonly closed = output<void>();

  protected readonly index = linkedSignal(() => Math.min(Math.max(this.start(), 0), this.images().length - 1));
  protected readonly caption = computed(() => this.captions()[this.index()] || `Slide ${this.index() + 1}`);
  private readonly dialog = viewChild.required<ElementRef<HTMLDialogElement>>('dialog');

  constructor() {
    afterNextRender(() => this.dialog().nativeElement.showModal());
  }

  protected step(delta: number): void {
    this.index.update((i) => Math.min(Math.max(i + delta, 0), this.images().length - 1));
  }

  protected onKey(event: KeyboardEvent): void {
    if (event.key === 'ArrowLeft') this.step(-1);
    else if (event.key === 'ArrowRight') this.step(1);
    else return;
    event.preventDefault();
  }

  /** Clicks on the dim area outside the slide land on the <dialog> itself. */
  protected closeOnBackdrop(event: MouseEvent): void {
    if (event.target === event.currentTarget) this.dialog().nativeElement.close();
  }
}
