import { Component, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { errorMessage } from '../core/api.service';
import { HelpRequest, Period, SenService } from '../core/sen';

interface Row {
  time: string;
  subject: string;
  learn: string;
  video_url: string;
  video_title: string;
  breakdown: Period['breakdown'];
}

const blank = (): Row => ({ time: '', subject: '', learn: '', video_url: '', video_title: '', breakdown: null });

/** Teacher sets a pupil's lessons for today; the AI makes each one a visual, step-by-step breakdown. */
@Component({
  selector: 'app-day-editor',
  imports: [FormsModule, RouterLink],
  template: `
    <section class="card section day">
      <div class="row between">
        <div>
          <h2>Today's lessons for {{ code() }}</h2>
          <p class="small muted">Type what they'll learn and the tasks for each period, or upload the period's slides. The AI turns each one into steps with symbols, which their avatar talks them through. Videos: only links you add here are ever shown.</p>
        </div>
        <a class="btn btn-primary" [routerLink]="['/learn', pupilId()]" target="_blank">Open {{ code() }}'s day ↗</a>
      </div>

      @if (error(); as m) { <div class="alert alert-error" role="alert">{{ m }}</div> }

      @for (r of rows(); track $index; let i = $index) {
        <div class="period">
          <div class="ph">
            <span class="badge">Period {{ i + 1 }}</span>
            <input class="input t" [(ngModel)]="r.time" placeholder="9:00" />
            <input class="input s" [(ngModel)]="r.subject" placeholder="Subject, e.g. Maths" />
            <button type="button" class="btn btn-sm" (click)="remove(i)" aria-label="Remove period">✕</button>
          </div>
          <textarea class="input" rows="4" [(ngModel)]="r.learn" placeholder="What they'll learn, then one task per line&#10;Equivalent fractions&#10;Shade half of each shape&#10;Match the fractions that are the same"></textarea>
          <div class="ph">
            <label class="btn btn-sm">Upload slides / worksheet<input type="file" accept=".pptx,.docx,.pdf,.txt" (change)="upload($event, i)" hidden /></label>
            <input class="input" [(ngModel)]="r.video_url" placeholder="Optional video link (https://…)" />
            <input class="input" [(ngModel)]="r.video_title" placeholder="Video title" />
          </div>
          @if (r.breakdown; as b) {
            <div class="preview">
              @for (t of b.task_steps; track $index) {
                @for (s of t.steps; track $index) {
                  <span class="step">@if (s.picto_url) { <img [src]="s.picto_url" alt="" /> } {{ s.text }}</span>
                }
              }
            </div>
          }
        </div>
      }
      <div class="row">
        <button type="button" class="btn btn-sm" (click)="add()">+ Add period</button>
        <button type="button" class="btn btn-primary" [disabled]="saving()" (click)="save()">
          @if (saving()) { <span class="spinner"></span> Making visual steps… } @else { Save and make visual steps }
        </button>
        @if (saved()) { <span class="small ok">Saved. {{ code() }} can start their day.</span> }
      </div>

      <h3 class="mt">Help requests from {{ code() }}</h3>
      <button type="button" class="btn btn-sm" (click)="loadHelp()">Refresh</button>
      @for (h of help(); track h.id) {
        <div class="help" [class.sg]="h.kind === 'safeguarding'" [class.seen]="h.seen">
          <span><strong>{{ h.kind === 'safeguarding' ? '⚠️ Safeguarding' : '🙋 Help' }}</strong>{{ h.period ? ' · period ' + h.period : '' }} · {{ h.created_at.slice(11, 16) }}</span>
          <span>{{ h.message }}</span>
          @if (!h.seen) { <button type="button" class="btn btn-sm" (click)="seen(h.id)">On my way</button> }
        </div>
      } @empty { <p class="small muted">None yet.</p> }
    </section>
  `,
  styles: `
    .day { display: flex; flex-direction: column; gap: 12px; border-top: 4px solid #16a34a; }
    .between { justify-content: space-between; align-items: flex-start; flex-wrap: nowrap; gap: 14px; }
    .period { border: 1px solid var(--border); border-radius: 12px; padding: 12px; display: flex; flex-direction: column; gap: 8px; background: #fff; }
    .ph { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .ph .t { width: 90px; } .ph .s { flex: 1; min-width: 160px; } .ph .input { flex: 1; min-width: 160px; }
    .preview { display: flex; flex-wrap: wrap; gap: 6px; }
    .step { display: inline-flex; gap: 6px; align-items: center; font-size: 13px; padding: 4px 10px; border-radius: 999px; background: #f0fdf4; border: 1px solid #bbf7d0; }
    .step img { width: 20px; height: 20px; }
    .ok { color: #166534; } .mt { margin-top: 10px; }
    .help { display: grid; grid-template-columns: 1fr 2fr auto; gap: 10px; align-items: center; padding: 8px 10px; border-radius: 8px; background: #fffbeb; font-size: 14px; }
    .help.sg { background: #fee2e2; } .help.seen { opacity: 0.5; }
    @media (max-width: 760px) { .between { flex-wrap: wrap; } .help { grid-template-columns: 1fr; } }
  `,
})
export class DayEditor {
  private readonly sen = inject(SenService);
  readonly pupilId = input.required<string>();
  readonly code = input<string>('');
  protected readonly rows = signal<Row[]>([blank()]);
  protected readonly help = signal<HelpRequest[]>([]);
  protected readonly saving = signal(false);
  protected readonly saved = signal(false);
  protected readonly error = signal<string | null>(null);

  async ngOnInit(): Promise<void> {
    try {
      const d = await firstValueFrom(this.sen.day(this.pupilId()));
      if (d.periods.length) this.rows.set(d.periods.map((p) => ({ ...p })));
    } catch (err) {
      this.error.set(errorMessage(err));
    }
    void this.loadHelp();
  }

  protected add(): void {
    this.rows.update((r) => [...r, blank()]);
  }

  protected remove(i: number): void {
    this.rows.update((r) => r.filter((_, k) => k !== i));
  }

  protected async upload(e: Event, i: number): Promise<void> {
    const input = e.target as HTMLInputElement;
    const f = input.files?.[0];
    input.value = '';
    if (!f) return;
    try {
      const text = (await firstValueFrom(this.sen.extract(f))).text.slice(0, 2500);
      this.rows.update((r) => r.map((x, k) => (k === i ? { ...x, learn: text, subject: x.subject || f.name.replace(/\.\w+$/, '') } : x)));
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  protected async save(): Promise<void> {
    this.saving.set(true);
    this.saved.set(false);
    this.error.set(null);
    try {
      const d = await firstValueFrom(this.sen.saveDay(this.pupilId(), this.rows().filter((r) => r.subject.trim() || r.learn.trim())));
      this.rows.set(d.periods.length ? d.periods.map((p) => ({ ...p })) : [blank()]);
      this.saved.set(true);
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.saving.set(false);
    }
  }

  protected async loadHelp(): Promise<void> {
    try {
      this.help.set((await firstValueFrom(this.sen.help())).filter((h) => h.pupil_id === this.pupilId()));
    } catch {
      /* ignore */
    }
  }

  protected async seen(id: string): Promise<void> {
    await firstValueFrom(this.sen.helpSeen(id));
    await this.loadHelp();
  }
}
