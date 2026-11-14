import { Component, DestroyRef, ElementRef, afterRenderEffect, computed, effect, inject, input, output, signal, untracked, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ApiService, errorMessage } from '../core/api.service';
import { Flag, Generation, Run, RunEvent, RunSlide } from '../core/models';

interface AgentNode {
  key: string;
  name: string;
  role: string;
  icon: string;
}

const NODES: AgentNode[] = [
  { key: 'orchestrator', name: 'Orchestrator', role: 'Chooses the modes', icon: '🧭' },
  { key: 'guardrails', name: 'Guardrails', role: 'Removes personal data', icon: '🛡️' },
  { key: 'planner', name: 'Planner', role: 'Writes the slides', icon: '✍️' },
  { key: 'sen', name: 'SEN Adapter', role: 'Simplifies, adds symbols', icon: '🧩' },
  { key: 'reviewer', name: 'Reviewer', role: 'Checks facts and safety', icon: '🔎' },
  { key: 'teacher', name: 'You', role: 'Approve flagged slides', icon: '🧑‍🏫' },
  { key: 'builder', name: 'Builder', role: 'Pours into your style', icon: '🎨' },
];

interface Draft {
  page: number;
  title: string;
  bullets: string;
  /** Teacher changed something on this slide. */
  edited: boolean;
}

const KIND_LABEL: Record<string, string> = {
  personal_data: 'Personal data',
  reading_level: 'Reading level',
  density: 'Too dense',
  injection: 'AI instruction',
  accuracy: 'Accuracy',
  age_fit: 'Age fit',
  safeguarding: 'Safeguarding',
  inclusion: 'Inclusion',
};

/** Live view of the agent team, and the teacher's review when the Reviewer escalates. */
@Component({
  selector: 'app-agent-run',
  imports: [FormsModule],
  template: `
    @let r = run();
    <section class="card section agents" aria-live="polite">
      <div class="agents-head">
        <div>
          <h2>{{ heading(r?.status) }}</h2>
          <p class="muted small">Each agent has one job. Anything worrying comes to you before the deck is built.</p>
        </div>
        @if (r) {
          <span class="status" [class]="'status s-' + r.status">{{ statusLabel(r.status) }}</span>
        }
      </div>

      <ol class="rail">
        @for (n of nodes(); track n.key) {
          @let st = nodeState(n.key);
          <li class="node" [class]="'node st-' + st">
            <span class="node-icon" aria-hidden="true">{{ n.icon }}</span>
            <span class="node-name">{{ n.name }}</span>
            <span class="node-role">{{ n.role }}</span>
          </li>
        }
      </ol>

      @if (r?.modes?.length) {
        <div class="modes-chips">
          @for (m of r!.modes; track m) {
            <span class="chip">{{ m }}</span>
          }
        </div>
      }

      <ul class="feed" #feedEl>
        @for (e of feed(); track e.n) {
          <li [class]="'ev ev-' + e.status">
            <span class="ev-time">{{ since(e) }}</span>
            <span class="ev-agent">{{ e.name }}</span>
            <span class="ev-msg">{{ e.message }}</span>
          </li>
        }
      </ul>

      @if (r?.status === 'failed') {
        <div class="alert alert-error" role="alert">{{ r?.error || 'The run failed.' }}</div>
      }

      <!-- ================= Human-in-the-loop review ================= -->
      @if (r?.status === 'needs_review') {
        <div class="review">
          <h3>Your review: {{ flaggedPages().length }} {{ flaggedPages().length === 1 ? 'slide needs' : 'slides need' }} a look</h3>
          <p class="muted small">
            Edit the text, or tick “Fine as it is” for each point. Personal data can't be waved through: remove it.
            Nothing is built until you approve.
          </p>

          @for (d of drafts(); track d.page) {
            @let flags = flagsFor(d.page);
            @if (flags.length) {
              <article class="rslide" [class.has-block]="hasBlock(d.page)">
                <header>
                  <span class="badge">Page {{ d.page }}</span>
                  @for (f of flags; track $index) {
                    <span class="sev" [class]="'sev sev-' + f.severity">{{ kindLabel(f.kind) }}</span>
                  }
                </header>
                <ul class="flag-list">
                  @for (f of flags; track $index) {
                    <li>
                      <strong>{{ f.source === 'reviewer' ? 'Reviewer' : 'Guardrail' }}:</strong> {{ f.message }}
                      @if (f.suggestion) {
                        <span class="muted"> Suggestion: {{ f.suggestion }}</span>
                      }
                      @if (f.severity === 'check') {
                        <label class="accept">
                          <input type="checkbox" [checked]="accepted().has(flagIndex(f))" (change)="toggleAccept(flagIndex(f))" />
                          Fine as it is
                        </label>
                      }
                    </li>
                  }
                </ul>
                <label class="field">
                  Title
                  <input class="input" [ngModel]="d.title" (ngModelChange)="edit(d.page, { title: $event })" />
                </label>
                <label class="field">
                  Bullets <span class="hint">(one per line)</span>
                  <textarea class="input" rows="4" [ngModel]="d.bullets" (ngModelChange)="edit(d.page, { bullets: $event })"></textarea>
                </label>
                @if (original(d.page); as orig) {
                  <p class="small muted sen-note">
                    🧩 The SEN Adapter simplified this slide.
                    <button type="button" class="link" (click)="edit(d.page, { bullets: orig.join('\\n') })">Use the original wording</button>
                  </p>
                }
              </article>
            }
          }

          @if (otherPages().length) {
            <p class="small muted">Slides {{ otherPages().join(', ') }} passed every check.</p>
          }

          @if (approveError(); as m) {
            <div class="alert alert-error" role="alert">{{ m }}</div>
          }
          <div class="row">
            <button type="button" class="btn btn-primary btn-lg" [disabled]="!readyToApprove() || approving()" (click)="approve()">
              @if (approving()) {
                <span class="spinner"></span> Building…
              } @else {
                Approve and build the deck
              }
            </button>
            @if (!readyToApprove()) {
              <span class="muted small">{{ remaining() }} point(s) still to deal with.</span>
            }
          </div>
        </div>
      }
    </section>
  `,
  styles: `
    .agents { border-top: 4px solid var(--primary); }
    .agents-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 16px; }
    .status { padding: 5px 12px; border-radius: 999px; font-size: 13px; font-weight: 700; white-space: nowrap; }
    .s-running { background: #e0f2fe; color: #075985; }
    .s-needs_review { background: #fef3c7; color: #92400e; }
    .s-built { background: #dcfce7; color: #166534; }
    .s-failed { background: #fee2e2; color: #991b1b; }

    .rail { list-style: none; margin: 0 0 14px; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(118px, 1fr)); gap: 8px; }
    .node { position: relative; display: flex; flex-direction: column; gap: 2px; padding: 10px; border-radius: 10px;
      border: 1.5px solid var(--border); background: var(--bg); opacity: 0.55; transition: all 0.25s; }
    .node-icon { font-size: 20px; line-height: 1; }
    .node-name { font-weight: 700; font-size: 13px; }
    .node-role { font-size: 11.5px; color: var(--muted); line-height: 1.3; }
    .st-working { opacity: 1; border-color: #0284c7; background: #f0f9ff; animation: pulse 1.2s ease-in-out infinite; }
    .st-done { opacity: 1; border-color: #16a34a; background: #f0fdf4; }
    .st-done::after { content: '✓'; position: absolute; top: 6px; right: 9px; color: #16a34a; font-weight: 800; }
    .st-warn { opacity: 1; border-color: #d97706; background: #fffbeb; }
    .st-warn::after { content: '!'; position: absolute; top: 6px; right: 10px; color: #d97706; font-weight: 800; }
    .st-waiting { opacity: 1; border-color: #7c3aed; background: #f5f3ff; animation: pulse 1.6s ease-in-out infinite; }
    .st-skipped { opacity: 0.35; border-style: dashed; }
    .st-error { opacity: 1; border-color: var(--danger); background: #fef2f2; }
    @keyframes pulse { 50% { box-shadow: 0 0 0 4px rgba(2, 132, 199, 0.15); } }

    .modes-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
    .chip { font-size: 12px; padding: 3px 10px; border-radius: 999px; background: var(--primary-soft); color: var(--primary-dark); font-weight: 600; }

    .feed { list-style: none; margin: 0; padding: 10px 12px; max-height: 220px; overflow: auto; background: #0f172a; color: #e2e8f0;
      border-radius: 10px; font: 12.5px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace; }
    .ev { display: grid; grid-template-columns: 44px 108px 1fr; gap: 8px; }
    .ev-time { color: #64748b; }
    .ev-agent { color: #7dd3fc; font-weight: 700; }
    .ev-warn .ev-msg { color: #fcd34d; }
    .ev-error .ev-msg { color: #fca5a5; }
    .ev-waiting .ev-msg { color: #c4b5fd; }
    .ev-status { opacity: 0.6; }

    .review { margin-top: 20px; padding-top: 16px; border-top: 1px dashed var(--border); display: flex; flex-direction: column; gap: 14px; }
    .rslide { border: 1px solid var(--border); border-left: 4px solid #d97706; border-radius: 10px; padding: 14px; display: flex; flex-direction: column; gap: 10px; }
    .rslide.has-block { border-left-color: var(--danger); }
    .rslide header { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
    .sev { font-size: 11.5px; font-weight: 700; padding: 2px 8px; border-radius: 6px; }
    .sev-block { background: #fee2e2; color: #991b1b; }
    .sev-check { background: #fef3c7; color: #92400e; }
    .sev-info { background: #e2e8f0; color: #334155; }
    .flag-list { margin: 0; padding-left: 18px; font-size: 14px; display: flex; flex-direction: column; gap: 6px; }
    .accept { display: inline-flex; gap: 6px; align-items: center; margin-left: 8px; font-weight: 600; font-size: 13px; color: var(--primary-dark); }
    .sen-note { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .link { background: none; border: 0; padding: 0; color: var(--primary-dark); font: inherit; text-decoration: underline; cursor: pointer; }
    @media (max-width: 640px) { .ev { grid-template-columns: 38px 1fr; } .ev-msg { grid-column: 1 / -1; } }
  `,
})
export class AgentRun {
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly runId = input.required<string>();
  /** The deck is built (directly, or after the teacher approved). */
  readonly built = output<{ run: Run; generation: Generation | null }>();

  protected readonly run = signal<Run | null>(null);
  private readonly events = signal<RunEvent[]>([]);
  protected readonly drafts = signal<Draft[]>([]);
  protected readonly accepted = signal<Set<number>>(new Set());
  protected readonly approving = signal(false);
  protected readonly approveError = signal<string | null>(null);
  private source: EventSource | null = null;
  private pollTimer?: ReturnType<typeof setTimeout>;
  private startedAt = 0;
  private announced = false;
  private readonly feedEl = viewChild<ElementRef<HTMLElement>>('feedEl');

  protected readonly feed = computed(() => this.events().filter((e) => e.status !== 'status'));

  protected readonly nodes = computed(() => {
    const r = this.run();
    // The SEN Adapter only shows when the orchestrator switched it on.
    return NODES.filter((n) => n.key !== 'sen' || r?.sen !== false);
  });

  protected readonly flaggedPages = computed(() => [...new Set((this.run()?.flags ?? []).filter((f) => f.severity !== 'info').map((f) => f.page))]);
  protected readonly otherPages = computed(() => {
    const flagged = new Set((this.run()?.flags ?? []).map((f) => f.page));
    return (this.run()?.slides ?? []).map((s) => s.page).filter((p) => !flagged.has(p));
  });

  /** Points still open: "check" flags not accepted on slides the teacher didn't edit, plus every "block". */
  protected readonly remaining = computed(() => {
    const flags = this.run()?.flags ?? [];
    const edited = new Set(this.drafts().filter((d) => d.edited).map((d) => d.page));
    return flags.filter((f, i) =>
      f.severity === 'block' ? !edited.has(f.page) : f.severity === 'check' && !edited.has(f.page) && !this.accepted().has(i),
    ).length;
  });
  protected readonly readyToApprove = computed(() => this.remaining() === 0);

  constructor() {
    effect(() => {
      const id = this.runId();
      untracked(() => this.connect(id));
    });
    this.destroyRef.onDestroy(() => this.disconnect());
    // Keep the newest agent message in view.
    afterRenderEffect(() => {
      this.feed();
      const el = this.feedEl()?.nativeElement;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }

  private async connect(id: string): Promise<void> {
    this.disconnect();
    this.announced = false;
    this.startedAt = Date.now() / 1000;
    try {
      const run = await firstValueFrom(this.api.getRun(id));
      this.apply(run);
      if (run.status !== 'running') return;
    } catch {
      /* the stream below still works */
    }
    if (typeof EventSource === 'undefined') return this.poll(id);
    const es = new EventSource(`/api/runs/${id}/events?after=${this.events().length}`, { withCredentials: true });
    this.source = es;
    es.addEventListener('agent', (msg) => {
      const ev = JSON.parse((msg as MessageEvent).data) as RunEvent;
      this.events.update((list) => (list.some((e) => e.n === ev.n) ? list : [...list, ev]));
    });
    es.addEventListener('end', () => {
      this.disconnect();
      void this.refresh(id);
    });
    es.onerror = () => {
      // Proxies sometimes cut long streams: fall back to polling.
      this.disconnect();
      this.poll(id);
    };
  }

  private poll(id: string): void {
    this.pollTimer = setTimeout(async () => {
      const run = await this.refresh(id);
      if (run?.status === 'running') this.poll(id);
    }, 900);
  }

  private async refresh(id: string): Promise<Run | null> {
    try {
      const run = await firstValueFrom(this.api.getRun(id));
      this.apply(run);
      return run;
    } catch {
      return null;
    }
  }

  private apply(run: Run): void {
    this.run.set(run);
    this.events.set(run.events);
    if (run.events.length) this.startedAt = Math.min(this.startedAt, run.events[0].t);
    if (run.status === 'needs_review' && !this.drafts().length) {
      this.drafts.set(run.slides.map((s) => ({ page: s.page, title: s.title, bullets: s.bullets.join('\n'), edited: false })));
    }
    if (run.status === 'built' && !this.announced) {
      this.announced = true;
      this.built.emit({ run, generation: null });
    }
  }

  private disconnect(): void {
    this.source?.close();
    this.source = null;
    clearTimeout(this.pollTimer);
  }

  protected nodeState(key: string): string {
    const r = this.run();
    const mine = this.events().filter((e) => e.agent === key && e.status !== 'status');
    if (key === 'teacher') {
      if (mine.length) return 'done';
      return r?.status === 'needs_review' ? 'waiting' : r?.status === 'built' ? 'skipped' : 'idle';
    }
    if (!mine.length) return r?.status === 'built' || r?.status === 'failed' ? 'skipped' : 'idle';
    const last = mine[mine.length - 1].status;
    return last === 'working' && r?.status !== 'running' && r?.status !== 'needs_review' ? 'done' : last;
  }

  protected since(e: RunEvent): string {
    return `${Math.max(0, e.t - this.startedAt).toFixed(1)}s`;
  }

  protected heading(s: string | undefined): string {
    return s === 'needs_review' ? 'Your AI team needs you' : s === 'built' ? 'Your AI team finished' : s === 'failed' ? 'Your AI team hit a problem' : 'Your AI team is working';
  }

  protected statusLabel(s: string): string {
    return { running: 'Working…', needs_review: 'Waiting for you', built: 'Deck built', failed: 'Failed' }[s] ?? s;
  }

  protected kindLabel(k: string): string {
    return KIND_LABEL[k] ?? k;
  }

  protected flagsFor(page: number): Flag[] {
    return (this.run()?.flags ?? []).filter((f) => f.page === page);
  }

  protected flagIndex(f: Flag): number {
    return (this.run()?.flags ?? []).indexOf(f);
  }

  protected hasBlock(page: number): boolean {
    return this.flagsFor(page).some((f) => f.severity === 'block');
  }

  protected original(page: number): string[] | null {
    return this.run()?.original?.[String(page)] ?? null;
  }

  protected toggleAccept(i: number): void {
    this.accepted.update((set) => {
      const next = new Set(set);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }

  protected edit(page: number, changes: Partial<Draft>): void {
    this.drafts.update((list) => list.map((d) => (d.page === page ? { ...d, ...changes, edited: true } : d)));
  }

  protected async approve(): Promise<void> {
    const r = this.run();
    if (!r || !this.readyToApprove()) return;
    this.approving.set(true);
    this.approveError.set(null);
    const slides: Partial<RunSlide>[] = this.drafts()
      .filter((d) => d.edited)
      .map((d) => ({ page: d.page, title: d.title.trim(), bullets: d.bullets.split('\n').map((b) => b.trim()).filter(Boolean) }));
    try {
      const out = await firstValueFrom(this.api.approveRun(r.id, slides, [...this.accepted()]));
      this.run.set(out.run);
      this.events.set(out.run.events);
      this.announced = true;
      this.built.emit({ run: out.run, generation: out.generation });
    } catch (err) {
      this.approveError.set(errorMessage(err));
    } finally {
      this.approving.set(false);
    }
  }
}
