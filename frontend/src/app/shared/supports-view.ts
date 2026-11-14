import { Component, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../core/api.service';
import { Symbol, Supports } from '../core/models';

type Tint = 'white' | 'cream' | 'blue' | 'green';
type Part = 'nownext' | 'timetable' | 'steps' | 'words';

/** Where a symbol lives, so the picker can swap it. */
interface Target {
  part: 'schedule' | 'key_words' | 'steps';
  i: number;
  j?: number;
}

/** Printable visual supports for SEN: Now/Next, visual timetable, task steps, key words. */
@Component({
  selector: 'app-supports-view',
  imports: [FormsModule],
  template: `
    @let s = data();
    @if (s) {
      <div class="toolbar no-print">
        <div class="parts" role="group" aria-label="What to show">
          @for (p of partList; track p.key) {
            <label class="part"><input type="checkbox" [checked]="shown().has(p.key)" (change)="toggle(p.key)" /> {{ p.label }}</label>
          }
        </div>
        <div class="row">
          <span class="small muted">Background</span>
          @for (t of tints; track t) {
            <button type="button" class="tint" [class]="'tint t-' + t" [class.on]="tint() === t" (click)="tint.set(t)" [attr.aria-label]="t + ' background'"></button>
          }
          <label class="part"><input type="checkbox" [checked]="large()" (change)="large.set(!large())" /> Large text</label>
          <button type="button" class="btn btn-primary btn-sm" (click)="print()">Print / save PDF</button>
        </div>
      </div>
      <p class="small muted no-print">Click any word to change it, or a symbol to swap it.</p>

      <div class="sheet" [class]="'sheet t-' + tint()" [class.large]="large()">
        @if (shown().has('nownext') && s.schedule.length) {
          <section class="block">
            <h3>Now and Next</h3>
            <div class="nownext">
              @for (k of [nowIndex(), nowIndex() + 1]; track $index; let first = $first) {
                @if (s.schedule[k]; as c) {
                  <div class="nn-card" [class.now]="first">
                    <span class="nn-tag">{{ first ? 'Now' : 'Next' }}</span>
                    <button type="button" class="sym" (click)="pick({ part: 'schedule', i: k })">
                      @if (c.picto_url) { <img [src]="c.picto_url" [alt]="c.picto_name || c.label" /> } @else { <span class="nosym">?</span> }
                    </button>
                    <span class="nn-label" contenteditable="true" (blur)="setText('schedule', k, $event)">{{ c.label }}</span>
                  </div>
                }
              }
            </div>
            <div class="row no-print nn-ctrl">
              <button type="button" class="btn btn-sm" [disabled]="nowIndex() === 0" (click)="nowIndex.set(nowIndex() - 1)">← Back</button>
              <button type="button" class="btn btn-sm" [disabled]="nowIndex() >= s.schedule.length - 2" (click)="nowIndex.set(nowIndex() + 1)">Finished: move on →</button>
            </div>
          </section>
        }

        @if (shown().has('timetable') && s.schedule.length) {
          <section class="block">
            <h3>{{ s.title || 'Today' }}: my timetable</h3>
            <ol class="timetable">
              @for (c of s.schedule; track $index; let i = $index) {
                <li [class.done]="i < nowIndex()">
                  <button type="button" class="sym" (click)="pick({ part: 'schedule', i })">
                    @if (c.picto_url) { <img [src]="c.picto_url" [alt]="c.picto_name || c.label" /> } @else { <span class="nosym">?</span> }
                  </button>
                  <span contenteditable="true" (blur)="setText('schedule', i, $event)">{{ c.label }}</span>
                </li>
              }
            </ol>
          </section>
        }

        @if (shown().has('steps')) {
          @for (t of s.task_steps; track $index; let i = $index) {
            <section class="block">
              <h3>{{ t.task || 'My task' }}: step by step</h3>
              <ol class="steps">
                @for (st of t.steps; track $index; let j = $index) {
                  <li>
                    <span class="num">{{ j + 1 }}</span>
                    <button type="button" class="sym" (click)="pick({ part: 'steps', i, j })">
                      @if (st.picto_url) { <img [src]="st.picto_url" [alt]="st.picto_name || st.text" /> } @else { <span class="nosym">?</span> }
                    </button>
                    <span contenteditable="true" (blur)="setStep(i, j, $event)">{{ st.text }}</span>
                    <span class="tick" aria-hidden="true"></span>
                  </li>
                }
              </ol>
            </section>
          }
        }

        @if (shown().has('words') && s.key_words.length) {
          <section class="block">
            <h3>Key words</h3>
            <div class="words">
              @for (k of s.key_words; track $index; let i = $index) {
                <div class="word">
                  <button type="button" class="sym" (click)="pick({ part: 'key_words', i })">
                    @if (k.picto_url) { <img [src]="k.picto_url" [alt]="k.picto_name || k.word" /> } @else { <span class="nosym">?</span> }
                  </button>
                  <strong contenteditable="true" (blur)="setWord(i, 'word', $event)">{{ k.word }}</strong>
                  <span contenteditable="true" (blur)="setWord(i, 'meaning', $event)">{{ k.meaning }}</span>
                </div>
              }
            </div>
          </section>
        }
        <p class="credit">{{ s.credit }}</p>
      </div>

      @if (picking(); as tgt) {
        <div class="picker no-print" role="dialog" aria-label="Choose a symbol">
          <div class="picker-box card">
            <div class="row">
              <input class="input" [ngModel]="query()" (ngModelChange)="search($event)" placeholder="Search symbols, e.g. listen, volcano" autofocus />
              <button type="button" class="btn btn-sm" (click)="picking.set(null)">Close</button>
            </div>
            <div class="picker-grid">
              @for (p of results(); track p.id) {
                <button type="button" class="picker-item" (click)="choose(tgt, p)" [title]="p.name">
                  <img [src]="p.url" [alt]="p.name" />
                  <span>{{ p.name }}</span>
                </button>
              } @empty {
                <p class="muted small">Type a word to find a symbol.</p>
              }
            </div>
          </div>
        </div>
      }
    }
  `,
  styles: `
    .toolbar { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 10px; margin-bottom: 8px; }
    .parts { display: flex; flex-wrap: wrap; gap: 12px; }
    .part { display: inline-flex; gap: 6px; align-items: center; font-size: 14px; font-weight: 600; }
    .tint { width: 22px; height: 22px; border-radius: 50%; border: 1.5px solid var(--border); cursor: pointer; }
    .tint.on { outline: 3px solid var(--primary); outline-offset: 1px; }
    .t-white { background: #ffffff; } .t-cream { background: #fdf6e3; } .t-blue { background: #e6f0fa; } .t-green { background: #e9f5ea; }

    .sheet { border-radius: 14px; padding: 22px; display: flex; flex-direction: column; gap: 26px; margin-top: 10px; border: 1px solid var(--border);
      font-family: 'Arial', 'Helvetica', sans-serif; letter-spacing: 0.02em; word-spacing: 0.08em; color: #1f2937; }
    .sheet.large { font-size: 125%; }
    .block h3 { font-size: 1.25em; margin-bottom: 12px; }
    .sym { border: 0; background: none; padding: 0; cursor: pointer; display: grid; place-items: center; }
    .sym img { width: 100%; height: 100%; object-fit: contain; }
    .nosym { display: grid; place-items: center; width: 100%; height: 100%; border: 2px dashed #cbd5e1; border-radius: 10px; color: #94a3b8; font-size: 1.6em; }
    [contenteditable] { outline: none; border-radius: 4px; }
    [contenteditable]:focus { background: #fff; box-shadow: 0 0 0 2px var(--primary); }

    .nownext { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
    .nn-card { position: relative; display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 34px 16px 18px;
      border: 4px solid #94a3b8; border-radius: 18px; background: #fff; }
    .nn-card.now { border-color: #16a34a; }
    .nn-tag { position: absolute; top: -2px; left: -2px; padding: 4px 16px; border-radius: 14px 0 14px 0; background: #94a3b8; color: #fff; font-weight: 800; font-size: 1.1em; }
    .nn-card.now .nn-tag { background: #16a34a; }
    .nn-card .sym { width: 140px; height: 140px; }
    .nn-label { font-size: 1.5em; font-weight: 800; text-align: center; }
    .nn-ctrl { margin-top: 10px; }

    .timetable { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 10px; }
    .timetable li { display: flex; flex-direction: column; align-items: center; gap: 6px; width: 118px; padding: 10px; background: #fff;
      border: 2.5px solid #cbd5e1; border-radius: 14px; font-weight: 700; text-align: center; }
    .timetable li.done { opacity: 0.4; text-decoration: line-through; }
    .timetable .sym { width: 72px; height: 72px; }

    .steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
    .steps li { display: grid; grid-template-columns: 40px 64px 1fr 34px; gap: 12px; align-items: center; padding: 10px 14px; background: #fff;
      border: 2.5px solid #cbd5e1; border-radius: 14px; font-size: 1.15em; font-weight: 600; }
    .num { display: grid; place-items: center; width: 36px; height: 36px; border-radius: 50%; background: var(--primary); color: #fff; font-weight: 800; }
    .steps .sym { width: 60px; height: 60px; }
    .tick { width: 30px; height: 30px; border: 3px solid #94a3b8; border-radius: 8px; }

    .words { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; }
    .word { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 14px; text-align: center; background: #fff;
      border: 2.5px solid #cbd5e1; border-radius: 14px; }
    .word .sym { width: 84px; height: 84px; }
    .word strong { font-size: 1.25em; }
    .credit { font-size: 11px; color: #64748b; }

    .picker { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; background: rgba(15, 23, 42, 0.45); padding: 16px; }
    .picker-box { width: min(640px, 100%); max-height: 80vh; overflow: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
    .picker-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(92px, 1fr)); gap: 8px; }
    .picker-item { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 8px; border: 1px solid var(--border); border-radius: 10px;
      background: #fff; cursor: pointer; font-size: 11px; }
    .picker-item img { width: 56px; height: 56px; }
    .picker-item:hover { border-color: var(--primary); }

    @media (max-width: 640px) { .nownext { grid-template-columns: 1fr; } .steps li { grid-template-columns: 32px 48px 1fr; } .tick { display: none; } }
    @media print {
      .no-print { display: none !important; }
      .sheet { border: 0; padding: 0; }
      .block { break-inside: avoid; }
    }
  `,
})
export class SupportsView {
  private readonly api = inject(ApiService);
  readonly supports = input<Supports | null>(null);

  protected readonly data = signal<Supports | null>(null);
  protected readonly nowIndex = signal(0);
  protected readonly tint = signal<Tint>('cream');
  protected readonly large = signal(false);
  protected readonly tints: Tint[] = ['white', 'cream', 'blue', 'green'];
  protected readonly partList: { key: Part; label: string }[] = [
    { key: 'nownext', label: 'Now / Next' },
    { key: 'timetable', label: 'Timetable' },
    { key: 'steps', label: 'Task steps' },
    { key: 'words', label: 'Key words' },
  ];
  protected readonly shown = signal<Set<Part>>(new Set(['nownext', 'timetable', 'steps', 'words']));
  protected readonly picking = signal<Target | null>(null);
  protected readonly query = signal('');
  protected readonly results = signal<{ id: string; name: string; url: string }[]>([]);
  private searchTimer?: ReturnType<typeof setTimeout>;

  protected readonly empty = computed(() => {
    const s = this.data();
    return !s || (!s.schedule.length && !s.key_words.length && !s.task_steps.length);
  });

  constructor() {
    effect(() => {
      const s = this.supports();
      untracked(() => {
        this.data.set(s ? structuredClone(s) : null);
        this.nowIndex.set(0);
      });
    });
  }

  protected toggle(p: Part): void {
    this.shown.update((set) => {
      const next = new Set(set);
      if (next.has(p)) next.delete(p);
      else next.add(p);
      return next;
    });
  }

  protected print(): void {
    window.print();
  }

  private text(e: Event): string {
    return ((e.target as HTMLElement).innerText || '').replace(/\s+/g, ' ').trim();
  }

  protected setText(part: 'schedule', i: number, e: Event): void {
    const label = this.text(e);
    this.data.update((s) => (s ? { ...s, schedule: s.schedule.map((c, k) => (k === i ? { ...c, label } : c)) } : s));
  }

  protected setStep(i: number, j: number, e: Event): void {
    const text = this.text(e);
    this.data.update((s) =>
      s ? { ...s, task_steps: s.task_steps.map((t, k) => (k === i ? { ...t, steps: t.steps.map((st, m) => (m === j ? { ...st, text } : st)) } : t)) } : s,
    );
  }

  protected setWord(i: number, key: 'word' | 'meaning', e: Event): void {
    const value = this.text(e);
    this.data.update((s) => (s ? { ...s, key_words: s.key_words.map((k, m) => (m === i ? { ...k, [key]: value } : k)) } : s));
  }

  protected pick(t: Target): void {
    const s = this.data();
    if (!s) return;
    const current =
      t.part === 'schedule' ? s.schedule[t.i]?.label : t.part === 'key_words' ? s.key_words[t.i]?.word : s.task_steps[t.i]?.steps[t.j ?? 0]?.text;
    this.picking.set(t);
    this.search((current || '').split(/\s+/).slice(0, 2).join(' '));
  }

  protected search(q: string): void {
    this.query.set(q);
    clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(async () => {
      if (!q.trim()) return this.results.set([]);
      try {
        this.results.set(await firstValueFrom(this.api.searchPictos(q)));
      } catch {
        this.results.set([]);
      }
    }, 200);
  }

  protected choose(t: Target, p: { id: string; name: string; url: string }): void {
    const sym: Partial<Symbol> = { picto_id: p.id, picto_url: p.url, picto_name: p.name };
    this.data.update((s) => {
      if (!s) return s;
      if (t.part === 'schedule') return { ...s, schedule: s.schedule.map((c, k) => (k === t.i ? { ...c, ...sym } : c)) };
      if (t.part === 'key_words') return { ...s, key_words: s.key_words.map((c, k) => (k === t.i ? { ...c, ...sym } : c)) };
      return {
        ...s,
        task_steps: s.task_steps.map((tk, k) => (k === t.i ? { ...tk, steps: tk.steps.map((st, m) => (m === t.j ? { ...st, ...sym } : st)) } : tk)),
      };
    });
    this.picking.set(null);
  }
}
