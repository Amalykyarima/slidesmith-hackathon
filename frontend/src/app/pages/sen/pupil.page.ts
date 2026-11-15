import { Component, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { errorMessage } from '../../core/api.service';
import { ApdrRecord, DraftDoc, PupilDetail, RecordRow, SenService, mdToHtml } from '../../core/sen';
import { SourcesList } from '../../shared/sources-list';

interface EditRec {
  id: string;
  assess: string;
  outcomes: string;
  provision: string;
  who: string;
  frequency: string;
  do: string;
  criteria: string;
  pupil_voice: string;
  parent_contact: string;
  review_date: string;
  approved_by: string;
}

const lines = (s: string) => s.split('\n').map((x) => x.trim()).filter(Boolean);

/** One pupil: profile, assess-plan-do-review cycle, and drafts for staff to sign. */
@Component({
  selector: 'app-pupil-page',
  imports: [FormsModule, RouterLink, SourcesList],
  template: `
    <p class="small"><a routerLink="/sen">← SEN overview</a></p>
    @if (error(); as m) {
      <div class="alert alert-error" role="alert">{{ m }}</div>
    }
    @if (p(); as p) {
      <div class="head">
        <div>
          <h1>{{ p.code }} <span class="muted thin">{{ p.year_group }}</span></h1>
          <p class="tags">
            <span class="chip">{{ p.status }}</span>
            <span class="chip alt">{{ p.need_area_label }}</span>
            @if (p.next_review) { <span class="chip" [class.bad]="overdue()">Next review {{ p.next_review }}</span> }
            @if (p.attendance; as a) { <span class="chip" [class.bad]="a.flag === 'persistent'" [class.warn]="a.flag === 'watch'">Attendance {{ a.pct }}%</span> }
          </p>
        </div>
        <a class="btn" routerLink="/adapt" [queryParams]="{ pupil: p.id }">Adapt classwork for {{ p.code }}</a>
      </div>

      <div class="grid">
        <section class="card section">
          <h2>About {{ p.code }}</h2>
          <dl>
            <dt>Needs</dt><dd>{{ p.summary || '–' }}</dd>
            <dt>Strengths</dt><dd>{{ p.strengths || '–' }}</dd>
            <dt>Provision in place</dt>
            <dd>@for (x of p.provision; track x) { <span class="pchip">{{ x }}</span> } @empty { – }</dd>
          </dl>
          @if (p.attendance?.flag !== 'ok' && p.attendance) {
            <p class="small pastoral">Pastoral flag: attendance is {{ p.attendance.pct }}%{{ p.attendance.recent_pct !== null ? ', ' + p.attendance.recent_pct + '% in recent weeks' : '' }}. Worth a conversation with the family and the attendance lead.</p>
          }
        </section>

        <section class="card section log">
          <h2>Log support</h2>
          <p class="small muted">A few lines on what you tried and what happened. The AI turns it into an assess-plan-do-review record for you to check and approve.</p>
          <textarea class="input" rows="5" [ngModel]="note()" (ngModelChange)="note.set($event)" maxlength="4000" placeholder="e.g. Tried a Now/Next board in maths. Finished 3 of 4 tasks on Tues and Thurs…"></textarea>
          <div class="row">
            <button type="button" class="btn btn-primary" [disabled]="busy() || note().trim().length < 10" (click)="log()">
              @if (busy() === 'log') { <span class="spinner"></span> Writing the record… } @else { Turn into a record }
            </button>
            @if (p.code === 'Y4-AB') { <button type="button" class="btn btn-sm" (click)="example()">Use an example note</button> }
          </div>
        </section>
      </div>

      @if (edit(); as e) {
        <section class="card section draft">
          <div class="banner">Draft record: check, edit and approve. It counts as evidence only once a member of staff approves it.</div>
          <div class="apdr">
            <div class="step"><span class="letter a">A</span><label class="field">Assess<textarea class="input" rows="7" [(ngModel)]="e.assess"></textarea></label></div>
            <div class="step"><span class="letter p">P</span>
              <div class="stack">
                <label class="field">Outcomes <span class="hint">(one per line)</span><textarea class="input" rows="6" [(ngModel)]="e.outcomes"></textarea></label>
                <label class="field">Provision <span class="hint">(one per line)</span><textarea class="input" rows="4" [(ngModel)]="e.provision"></textarea></label>
                <div class="two"><label class="field">Who<input class="input" [(ngModel)]="e.who" /></label><label class="field">How often<input class="input" [(ngModel)]="e.frequency" /></label></div>
              </div>
            </div>
            <div class="step"><span class="letter d">D</span><label class="field">Do<textarea class="input" rows="6" [(ngModel)]="e.do"></textarea></label></div>
            <div class="step"><span class="letter r">R</span>
              <div class="stack">
                <label class="field">Success criteria <span class="hint">(one per line)</span><textarea class="input" rows="4" [(ngModel)]="e.criteria"></textarea></label>
                <label class="field">Review date<input class="input" type="date" [(ngModel)]="e.review_date" /></label>
              </div>
            </div>
          </div>
          <div class="two">
            <label class="field">Pupil voice<input class="input" [(ngModel)]="e.pupil_voice" /></label>
            <label class="field">Parent contact<input class="input" [(ngModel)]="e.parent_contact" /></label>
          </div>
          @if (pending()?.record?.missing?.length) {
            <p class="small missing"><strong>Still missing:</strong> {{ pending()!.record.missing.join('; ') }}</p>
          }
          <app-sources [sources]="pending()?.sources ?? []" />
          <div class="row sign">
            <input class="input" [(ngModel)]="e.approved_by" placeholder="Your name and role, e.g. Ms Patel (SENCO)" />
            <button type="button" class="btn btn-primary" [disabled]="!e.approved_by.trim() || busy()" (click)="approve()">Approve record</button>
          </div>
        </section>
      }

      <section class="card section">
        <h2>Drafts for staff to sign</h2>
        <p class="small muted">Built from {{ p.code }}'s approved records, profile and your provision map. The AI never writes an EHC plan: the local authority does. These are drafts for a human to edit and sign.</p>
        <div class="row">
          <button type="button" class="btn" [disabled]="busy()" (click)="draft('support_plan')">SEN support plan</button>
          <button type="button" class="btn" [disabled]="busy()" (click)="draft('parent_update')">Update for parents</button>
          <button type="button" class="btn" [disabled]="busy()" (click)="draft('ehcp_contribution')">EHC needs assessment contribution</button>
          @if (busy() === 'draft') { <span class="small muted"><span class="spinner"></span> Drafting (up to a minute)…</span> }
        </div>
        @for (dr of p.drafts; track dr.id) {
          <article class="doc" [class.signed]="dr.status === 'signed'">
            <header>
              <strong>{{ dr.kind_label }}</strong>
              @if (dr.status === 'signed') { <span class="chip ok">Signed by {{ dr.signed_by }} · {{ dr.signed_at?.slice(0, 10) }}</span> }
              @else { <span class="chip warn">Draft: needs staff sign-off</span> }
              <span class="small muted">{{ dr.created_at.slice(0, 16) }}</span>
            </header>
            @if (editing() === dr.id) {
              <textarea class="input mono" rows="16" [ngModel]="body()" (ngModelChange)="body.set($event)"></textarea>
            } @else {
              <div class="md" [innerHTML]="html(dr.body)"></div>
            }
            @if (dr.status === 'draft') {
              @if (dr.checks.length) {
                <details class="checks" open><summary>Check before signing ({{ dr.checks.length }})</summary>
                  <ul>@for (c of dr.checks; track $index) { <li>{{ c }}</li> }</ul></details>
              }
              <app-sources [sources]="dr.sources" />
              <div class="row sign">
                @if (editing() === dr.id) {
                  <button type="button" class="btn btn-sm" (click)="saveEdit(dr)">Save edits</button>
                } @else {
                  <button type="button" class="btn btn-sm" (click)="startEdit(dr)">Edit</button>
                }
                <input class="input" [ngModel]="signer()" (ngModelChange)="signer.set($event)" placeholder="Your name and role" />
                <button type="button" class="btn btn-primary btn-sm" [disabled]="!signer().trim()" (click)="sign(dr)">Sign</button>
              </div>
            }
          </article>
        }
      </section>

      <section class="card section">
        <h2>Assess-plan-do-review history</h2>
        @for (r of p.records; track r.id) {
          <div class="hist" [class.draft-row]="r.status === 'draft'">
            <div class="when">{{ r.created_at.slice(0, 10) }}<br />
              @if (r.status === 'approved') { <span class="chip ok">Approved</span><br /><span class="small muted">{{ r.approved_by }}</span> }
              @else { <span class="chip warn">Draft</span> }</div>
            <div class="small">
              <p><strong>A</strong> {{ r.record.assess }}</p>
              <p><strong>P</strong> {{ r.record.plan.outcomes.join(' · ') }}</p>
              <p><strong>D</strong> {{ r.record.do }}</p>
              <p><strong>R</strong> {{ r.record.review.success_criteria.join(' · ') }} @if (r.review_date) { <em>(review {{ r.review_date }})</em> }</p>
            </div>
          </div>
        } @empty { <p class="muted small">No records yet. Log some support above.</p> }
      </section>
    }
  `,
  styles: `
    .head { display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; align-items: flex-start; }
    .thin { font-weight: 400; font-size: 0.7em; }
    .tags { display: flex; flex-wrap: wrap; gap: 6px; }
    .chip { font-size: 12px; padding: 3px 10px; border-radius: 999px; background: #e0f2fe; color: #075985; font-weight: 600; }
    .chip.alt { background: #f1f5f9; color: #334155; } .chip.bad { background: #fee2e2; color: #991b1b; }
    .chip.warn { background: #fef3c7; color: #92400e; } .chip.ok { background: #dcfce7; color: #166534; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
    dl { display: grid; grid-template-columns: 130px 1fr; gap: 8px 12px; font-size: 14px; margin: 0; }
    dt { color: var(--muted); font-weight: 600; } dd { margin: 0; }
    .pchip { display: inline-block; font-size: 12px; padding: 2px 8px; margin: 0 4px 4px 0; border-radius: 6px; background: #f1f5f9; }
    .pastoral { margin-top: 12px; padding: 10px; border-radius: 8px; background: #fffbeb; color: #92400e; }
    .log textarea { margin: 8px 0; }
    .draft { border-top: 4px solid #7c3aed; display: flex; flex-direction: column; gap: 14px; }
    .banner { background: #f5f3ff; color: #5b21b6; font-weight: 600; font-size: 14px; padding: 10px 14px; border-radius: 8px; }
    .apdr { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    .step { display: grid; grid-template-columns: 34px 1fr; gap: 10px; align-items: start; }
    .letter { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 8px; color: #fff; font-weight: 800; margin-top: 20px; }
    .a { background: #0284c7; } .p { background: #7c3aed; } .d { background: #16a34a; } .r { background: #d97706; }
    .two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .missing { background: #fffbeb; padding: 8px 12px; border-radius: 8px; margin: 0; }
    .sign { flex-wrap: nowrap; } .sign .input { max-width: 340px; }
    .doc { border: 1px solid var(--border); border-left: 4px solid #d97706; border-radius: 10px; padding: 14px; margin-top: 14px; display: flex; flex-direction: column; gap: 10px; }
    .doc.signed { border-left-color: #16a34a; }
    .doc header { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    .md { font-size: 14.5px; line-height: 1.6; } .md :is(h4) { margin: 12px 0 4px; } .md p { margin: 4px 0; }
    .md mark { background: #fef08a; }
    .mono { font: 13px/1.5 ui-monospace, Menlo, monospace; }
    .checks { background: #fffbeb; border-radius: 8px; padding: 8px 12px; font-size: 13.5px; } .checks summary { font-weight: 700; cursor: pointer; }
    .hist { display: grid; grid-template-columns: 120px 1fr; gap: 14px; padding: 12px 0; border-bottom: 1px dashed var(--border); }
    .hist p { margin: 2px 0; } .when { font-size: 13px; font-weight: 600; }
    @media (max-width: 860px) { .grid, .apdr, .two { grid-template-columns: 1fr; } .sign { flex-wrap: wrap; } }
  `,
})
export class PupilPage {
  private readonly sen = inject(SenService);
  readonly id = input.required<string>();
  protected readonly p = signal<PupilDetail | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly busy = signal<'' | 'log' | 'draft' | 'approve'>('');
  protected readonly edit = signal<EditRec | null>(null);
  protected readonly pending = signal<RecordRow | null>(null);
  protected readonly editing = signal<string | null>(null);
  protected readonly note = signal('');
  protected readonly body = signal('');
  protected readonly signer = signal('');

  ngOnInit(): void {
    void this.load();
  }

  private async load(): Promise<void> {
    try {
      const p = await firstValueFrom(this.sen.pupil(this.id()));
      this.p.set(p);
      const draft = p.records.find((r) => r.status === 'draft');
      if (draft && !this.edit()) this.startRecord(draft);
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  protected overdue(): boolean {
    const nr = this.p()?.next_review;
    return !!nr && nr < new Date().toISOString().slice(0, 10);
  }

  protected html(md: string): string {
    return mdToHtml(md);
  }

  protected async example(): Promise<void> {
    this.note.set((await firstValueFrom(this.sen.demoNote())).note);
  }

  protected async log(): Promise<void> {
    this.busy.set('log');
    this.error.set(null);
    try {
      const r = await firstValueFrom(this.sen.logSupport(this.id(), this.note().trim()));
      this.note.set('');
      this.startRecord(r);
      await this.load();
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.busy.set('');
    }
  }

  private startRecord(r: RecordRow): void {
    const rec = r.record;
    this.pending.set(r);
    this.edit.set({
      id: r.id,
      assess: rec.assess,
      outcomes: (rec.plan?.outcomes ?? []).join('\n'),
      provision: (rec.plan?.provision ?? []).join('\n'),
      who: rec.plan?.who ?? '',
      frequency: rec.plan?.frequency ?? '',
      do: rec.do,
      criteria: (rec.review?.success_criteria ?? []).join('\n'),
      pupil_voice: rec.pupil_voice,
      parent_contact: rec.parent_contact,
      review_date: r.review_date ?? '',
      approved_by: '',
    });
  }

  protected async approve(): Promise<void> {
    const e = this.edit();
    const r = this.pending();
    if (!e || !r) return;
    const record: ApdrRecord = {
      ...r.record,
      assess: e.assess,
      plan: { ...r.record.plan, outcomes: lines(e.outcomes), provision: lines(e.provision), who: e.who, frequency: e.frequency },
      do: e.do,
      review: { success_criteria: lines(e.criteria) },
      pupil_voice: e.pupil_voice,
      parent_contact: e.parent_contact,
    };
    this.busy.set('approve');
    try {
      await firstValueFrom(this.sen.approveRecord(e.id, record, e.approved_by.trim(), e.review_date || null));
      this.edit.set(null);
      this.pending.set(null);
      await this.load();
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.busy.set('');
    }
  }

  protected async draft(kind: DraftDoc['kind']): Promise<void> {
    this.busy.set('draft');
    this.error.set(null);
    try {
      await firstValueFrom(this.sen.draft(this.id(), kind));
      await this.load();
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.busy.set('');
    }
  }

  protected startEdit(d: DraftDoc): void {
    this.body.set(d.body);
    this.editing.set(d.id);
  }

  protected async saveEdit(d: DraftDoc): Promise<void> {
    try {
      await firstValueFrom(this.sen.editDraft(d.id, this.body()));
      this.editing.set(null);
      await this.load();
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  protected async sign(d: DraftDoc): Promise<void> {
    this.error.set(null);
    try {
      await firstValueFrom(this.sen.signDraft(d.id, this.editing() === d.id ? this.body() : d.body, this.signer().trim()));
      this.editing.set(null);
      await this.load();
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }
}
