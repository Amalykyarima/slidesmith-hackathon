import { Component, ElementRef, afterNextRender, input, viewChild } from '@angular/core';

/**
 * Full-page loader. Render it with `@if` while work runs: it opens as a modal <dialog>, so the
 * page behind it can't be clicked or typed into, and Esc doesn't dismiss it. A deck of slides
 * builds itself in the middle of the screen.
 */
@Component({
  selector: 'app-busy-overlay',
  template: `
    <dialog #dialog class="busy" aria-live="polite" [attr.aria-label]="message()" (cancel)="$event.preventDefault()">
      <div class="stage" aria-hidden="true">
        <div class="deck">
          <span class="sheet s3"></span>
          <span class="sheet s2"></span>
          <span class="sheet s1">
            <i class="bar title"></i>
            <i class="bar l1"></i>
            <i class="bar l2"></i>
            <i class="bar l3"></i>
            <i class="spark"></i>
          </span>
        </div>
      </div>
      <p class="message">{{ message() }}</p>
      @if (detail(); as d) {
        <p class="detail">{{ d }}</p>
      }
      <div class="track" aria-hidden="true"><span></span></div>
    </dialog>
  `,
  styles: `
    .busy {
      border: none; padding: 0; margin: 0; width: 100vw; height: 100vh; max-width: 100vw; max-height: 100vh;
      background: transparent; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px;
      color: var(--ink);
    }
    .busy::backdrop { background: rgba(244, 246, 248, 0.82); backdrop-filter: blur(5px); }
    .stage { width: 220px; height: 150px; display: grid; place-items: center; }
    .deck { position: relative; width: 168px; height: 95px; }
    .sheet {
      position: absolute; inset: 0; border-radius: 10px; background: #fff; border: 1px solid var(--border);
      box-shadow: 0 10px 30px rgba(16, 24, 40, 0.14);
    }
    .s3 { animation: fan3 2.4s ease-in-out infinite; background: var(--primary-soft); }
    .s2 { animation: fan2 2.4s ease-in-out infinite; }
    .s1 { overflow: hidden; animation: lift 2.4s ease-in-out infinite; }
    .bar { position: absolute; left: 14px; height: 7px; border-radius: 4px; background: var(--primary); transform-origin: left; }
    .title { top: 14px; width: 58%; height: 10px; animation: write 2.4s ease-in-out infinite; }
    .l1 { top: 36px; width: 72%; opacity: 0.45; animation: write 2.4s 0.25s ease-in-out infinite both; }
    .l2 { top: 51px; width: 64%; opacity: 0.45; animation: write 2.4s 0.45s ease-in-out infinite both; }
    .l3 { top: 66px; width: 46%; opacity: 0.45; animation: write 2.4s 0.65s ease-in-out infinite both; }
    .spark {
      position: absolute; inset: 0;
      background: linear-gradient(110deg, transparent 35%, rgba(255, 255, 255, 0.9) 50%, transparent 65%);
      background-size: 250% 100%; animation: sweep 2.4s linear infinite;
    }
    .message { margin: 0; font-size: 18px; font-weight: 700; letter-spacing: -0.01em; text-align: center; }
    .detail { margin: -6px 0 0; font-size: 14px; color: var(--muted); text-align: center; max-width: 340px; }
    .track { width: 200px; height: 4px; border-radius: 4px; background: var(--border); overflow: hidden; position: relative; }
    .track span { position: absolute; top: 0; bottom: 0; width: 40%; border-radius: 4px; background: var(--primary); animation: run 1.2s ease-in-out infinite; }
    @keyframes write { 0% { transform: scaleX(0); } 35%, 85% { transform: scaleX(1); } 100% { transform: scaleX(0); } }
    @keyframes lift { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-6px); } }
    @keyframes fan2 { 0%, 100% { transform: rotate(0) translate(0, 0); } 50% { transform: rotate(-6deg) translate(-10px, 4px); } }
    @keyframes fan3 { 0%, 100% { transform: rotate(0) translate(0, 0); } 50% { transform: rotate(7deg) translate(12px, 6px); } }
    @keyframes sweep { from { background-position: 130% 0; } to { background-position: -130% 0; } }
    @keyframes run { from { left: -40%; } to { left: 100%; } }
    @media (prefers-reduced-motion: reduce) {
      .s1, .s2, .s3, .bar, .spark, .track span { animation-duration: 6s; }
    }
  `,
})
export class BusyOverlay {
  readonly message = input.required<string>();
  readonly detail = input<string | null>(null);
  private readonly dialog = viewChild.required<ElementRef<HTMLDialogElement>>('dialog');

  constructor() {
    afterNextRender(() => {
      const el = this.dialog().nativeElement;
      if (!el.open) el.showModal();
    });
  }
}
