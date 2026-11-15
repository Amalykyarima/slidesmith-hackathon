import { Component, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { errorMessage } from '../../core/api.service';
import { Supports } from '../../core/models';
import { Adaptation, Meta, Pupil, SenService } from '../../core/sen';
import { SourcesList } from '../../shared/sources-list';
import { SupportsView } from '../../shared/supports-view';

const EXAMPLE = `Year 4 Maths: Fractions
LO: To recognise and write equivalent fractions.
1. Shade 1/2 of each shape. Then shade 2/4 of the next shape. What do you notice?
2. Complete: 1/3 = ?/6 = 3/?
3. Challenge: Explain in a sentence why 4/8 is the same as 1/2.
Work quietly on your own for 20 minutes.`;

/** Upload a lesson or worksheet; get it adapted for a specific need, grounded in the school's provision. */
@Component({
  selector: 'app-adapt-page',
  imports: [FormsModule, SourcesList, SupportsView],
  template: `
    <div class="no-print">
      <h1>Adapt classwork</h1>
      <p class="lead">Upload or paste a lesson or worksheet, choose the pupil or the need, and get an adapted version that keeps the same objective, aligned to your school's provision. Always check it before use.</p>
      @if (error(); as m) { <div class="alert alert-error" role="alert">{{ m }}</div> }

      <section class="card section stack">
        <div class="three">
          <label class="field">For a pupil
            <select class="input" [ngModel]="pupilId()" (ngModelChange)="pickPupil($event)">
              <option value="">No specific pupil</option>
              @for (p of pupils(); track p.id) { <option [value]="p.id">{{ p.code }} · {{ p.year_group }}</option> }
            </select>
          </label>
          <label class="field">Phase
            <select class="input" [ngModel]="phase()" (ngModelChange)="phase.set($event)">
              <option value="primary">Primary</option><option value="secondary">Secondary</option><option value="university">FE / university</option>
            </select>
          </label>
        </div>
        <div class="field">Adapt for
          <div class="needs">
            @for (n of meta()?.needs ?? []; track n.key) {
              <label class="need" [class.on]="needs().has(n.key)"><input type="checkbox" [checked]="needs().has(n.key)" (change)="toggle(n.key)" /> {{ n.label }}</label>
            }
          </div>
        </div>
        <label class="field">The lesson or worksheet
          <textarea class="input" rows="8" [ngModel]="work()" (ngModelChange)="work.set($event)" maxlength="12000" placeholder="Paste the text, or upload a file below"></textarea>
        </label>
        <div class="row">
          <label class="btn btn-sm">Upload .pptx, .docx, .pdf<input type="file" accept=".pptx,.docx,.pdf,.txt,.md" (change)="upload($event)" hidden /></label>
          <button type="button" class="btn btn-sm" (click)="work.set(example)">Use an example worksheet</button>
          <span class="small muted">Names and contact details are removed before anything reaches the AI.</span>
        </div>
        <div class="row">
          <button type="button" class="btn btn-primary btn-lg" [disabled]="busy() || work().trim().length < 20 || (!needs().size && !pupilId())" (click)="adapt()">
            @if (busy() === 'adapt') { <span class="spinner"></span> Adapting… } @else { Adapt it }
          </button>
        </div>
      </section>
    </div>

    @if (a(); as a) {
      <section class="card section">
        <div class="row between no-print">
          <span class="chip warn">Draft: check before use</span>
          <div class="row">
            <button type="button" class="btn btn-sm" [disabled]="busy()" (click)="makeSupports(a)">
              @if (busy() === 'supports') { <span class="spinner"></span> } Make visual supports
            </button>
            <button type="button" class="btn btn-primary btn-sm" (click)="print()">Print</button>
          </div>
        </div>
        <article class="sheet">
          <h2>{{ a.title }}</h2>
          <p class="obj"><strong>I am learning to:</strong> {{ a.objective }}</p>
          <h3>What to do</h3>
          <ol class="steps">@for (i of a.instructions; track $index) { <li>{{ stripNum(i) }}</li> }</ol>
          @for (t of a.tasks; track $index; let k = $index) {
            <div class="task">
              <h3>Task {{ k + 1 }}</h3>
              <p>{{ t.task }}</p>
              <p class="scaffold"><strong>Help:</strong> {{ t.scaffold }}</p>
              <ol class="mini">@for (s of t.steps; track $index) { <li>{{ s }}</li> }</ol>
              <div class="answer"></div>
            </div>
          }
          @if (a.word_bank.length) {
            <h3>Word bank</h3>
            <div class="words">@for (w of a.word_bank; track w.word) { <div><strong>{{ w.word }}</strong>: {{ w.meaning }}</div> }</div>
          }
        </article>
        <div class="no-print why">
          <h3>Why these changes</h3>
          <ul>@for (s of a.strategies; track $index) { <li><strong>{{ s.strategy }}</strong>: {{ s.why }}</li> }</ul>
          @if (a.check.length) {
            <details class="checks" open><summary>Check before use ({{ a.check.length }})</summary><ul>@for (c of a.check; track $index) { <li>{{ c }}</li> }</ul></details>
          }
          <app-sources [sources]="a.sources" />
        </div>
      </section>
    }

    @if (supports(); as s) {
      <section class="card section">
        <h2 class="no-print">Visual supports</h2>
        <app-supports-view [supports]="s" />
      </section>
    }
  `,
  styles: `
    .three { display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 12px; }
    .needs { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
    .need { display: inline-flex; gap: 6px; align-items: center; padding: 6px 12px; border: 1.5px solid var(--border); border-radius: 999px; font-size: 13.5px; cursor: pointer; font-weight: 500; }
    .need.on { border-color: var(--primary); background: var(--primary-soft); font-weight: 700; }
    .need input { margin: 0; }
    .between { justify-content: space-between; }
    .chip.warn { font-size: 12.5px; padding: 4px 10px; border-radius: 999px; background: #fef3c7; color: #92400e; font-weight: 700; }
    .sheet { margin-top: 14px; padding: 24px; border: 1px solid var(--border); border-radius: 12px; background: #fdf6e3;
      font-family: Arial, Helvetica, sans-serif; font-size: 17px; line-height: 1.6; letter-spacing: 0.02em; }
    .sheet h2 { font-size: 24px; } .sheet h3 { font-size: 19px; margin: 18px 0 6px; }
    .obj { background: #fff; border-radius: 8px; padding: 10px 14px; }
    .steps li { margin: 4px 0; }
    .task { background: #fff; border: 2px solid #cbd5e1; border-radius: 12px; padding: 12px 16px; margin: 12px 0; }
    .scaffold { background: #eef6ff; border-radius: 8px; padding: 8px 12px; }
    .mini { font-size: 15.5px; }
    .answer { height: 70px; border-bottom: 2px dashed #94a3b8; margin-top: 6px; }
    .words { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; }
    .words div { background: #fff; border-radius: 8px; padding: 8px 12px; }
    .why { margin-top: 16px; display: flex; flex-direction: column; gap: 10px; font-size: 14px; }
    .checks { background: #fffbeb; border-radius: 8px; padding: 8px 12px; } .checks summary { font-weight: 700; cursor: pointer; }
    @media (max-width: 760px) { .three { grid-template-columns: 1fr; } }
    @media print { .sheet { border: 0; background: #fff; } .card { border: 0; box-shadow: none; } }
  `,
})
export class AdaptPage {
  private readonly sen = inject(SenService);
  /** ?pupil= from the pupil page */
  readonly pupil = input<string>('');
  protected readonly meta = signal<Meta | null>(null);
  protected readonly pupils = signal<Pupil[]>([]);
  protected readonly a = signal<Adaptation | null>(null);
  protected readonly supports = signal<Supports | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly busy = signal<'' | 'adapt' | 'supports'>('');
  protected readonly example = EXAMPLE;
  protected readonly pupilId = signal('');
  protected readonly phase = signal('primary');
  protected readonly needs = signal(new Set<string>());
  protected readonly work = signal('');

  async ngOnInit(): Promise<void> {
    try {
      const [meta, pupils] = await Promise.all([firstValueFrom(this.sen.meta()), firstValueFrom(this.sen.pupils())]);
      this.meta.set(meta);
      this.pupils.set(pupils);
      if (this.pupil()) {
        this.pickPupil(this.pupil());
      }
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  protected pickPupil(id: string): void {
    this.pupilId.set(id);
    const p = this.pupils().find((x) => x.id === id);
    if (!p) return;
    this.needs.set(new Set(p.needs));
    this.phase.set(p.phase);
  }

  protected toggle(k: string): void {
    const next = new Set(this.needs());
    if (next.has(k)) next.delete(k);
    else next.add(k);
    this.needs.set(next);
  }

  protected stripNum(s: string): string {
    return s.replace(/^\s*\d+[.)]\s*/, '');
  }

  protected async upload(e: Event): Promise<void> {
    const input = e.target as HTMLInputElement;
    const f = input.files?.[0];
    input.value = '';
    if (!f) return;
    try {
      this.work.set((await firstValueFrom(this.sen.extract(f))).text);
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  protected async adapt(): Promise<void> {
    this.busy.set('adapt');
    this.error.set(null);
    this.supports.set(null);
    try {
      this.a.set(await firstValueFrom(this.sen.adapt({ work: this.work(), needs: [...this.needs()], pupil_id: this.pupilId() || undefined, phase: this.phase() })));
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.busy.set('');
    }
  }

  protected async makeSupports(a: Adaptation): Promise<void> {
    this.busy.set('supports');
    try {
      const details = [...a.instructions.map((i) => this.stripNum(i)), ...a.word_bank.map((w) => `Key word: ${w.word} - ${w.meaning}`)].join('\n');
      this.supports.set(await firstValueFrom(this.sen.supports(a.title, details, this.phase())));
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.busy.set('');
    }
  }

  protected print(): void {
    window.print();
  }
}
