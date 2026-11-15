import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { errorMessage } from '../../core/api.service';
import { Dashboard, Meta, SenService } from '../../core/sen';

/** SENCO view: who's on the register, which reviews are due, provision in use, attendance flags. */
@Component({
  selector: 'app-sen-dashboard',
  imports: [FormsModule, RouterLink],
  template: `
    <div class="head">
      <div>
        <h1>SEN overview</h1>
        <p class="lead">Every pupil on SEN support, what's in place for them, and what needs doing next. Drafts are always for staff to check and sign.</p>
      </div>
      <div class="row">
        <a class="btn btn-primary" routerLink="/adapt">Adapt classwork</a>
        @if (!d()?.pupils?.length) {
          <button type="button" class="btn" [disabled]="busy()" (click)="demo()">Load demo school</button>
        }
      </div>
    </div>

    @if (error(); as m) {
      <div class="alert alert-error" role="alert">{{ m }}</div>
    }

    @if (d(); as d) {
      <div class="tiles">
        <div class="tile"><span class="n">{{ d.counts.pupils }}</span><span>pupils on the register</span></div>
        <div class="tile" [class.bad]="d.counts.overdue"><span class="n">{{ d.counts.overdue }}</span><span>reviews overdue</span></div>
        <div class="tile" [class.warn]="d.counts.soon"><span class="n">{{ d.counts.soon }}</span><span>reviews in the next 2 weeks</span></div>
        <div class="tile" [class.warn]="d.counts.attendance_flags"><span class="n">{{ d.counts.attendance_flags }}</span><span>attendance flags</span></div>
        <div class="tile" [class.todo]="d.counts.unapproved + d.counts.unsigned"><span class="n">{{ d.counts.unapproved + d.counts.unsigned }}</span><span>drafts waiting for a human</span></div>
      </div>

      <section class="card section">
        <div class="row between">
          <h2>Pupils</h2>
          <button type="button" class="btn btn-sm" (click)="adding.set(!adding())">{{ adding() ? 'Cancel' : '+ Add pupil' }}</button>
        </div>
        @if (adding()) {
          <div class="add">
            <label class="field">Code or initials <input class="input" [(ngModel)]="newCode" placeholder="e.g. Y4-AB" maxlength="16" /></label>
            <label class="field">Year <input class="input" [(ngModel)]="newYear" placeholder="Year 4" /></label>
            <label class="field">Main need
              <select class="input" [(ngModel)]="newNeed">
                @for (n of meta()?.needs ?? []; track n.key) { <option [value]="n.key">{{ n.label }}</option> }
              </select>
            </label>
            <button type="button" class="btn btn-primary" (click)="add()">Add</button>
            <p class="small muted full">No names: use initials or your school's code. Names, emails and phone numbers are refused.</p>
          </div>
        }
        @if (d.pupils.length) {
          <div class="table-wrap">
            <table>
              <thead>
                <tr><th>Pupil</th><th>Status</th><th>Area of need</th><th>Provision</th><th>Next review</th><th>Attendance</th><th>Records</th></tr>
              </thead>
              <tbody>
                @for (p of d.pupils; track p.id) {
                  <tr (click)="open(p.id)" tabindex="0" (keydown.enter)="open(p.id)">
                    <td><strong>{{ p.code }}</strong><br /><span class="small muted">{{ p.year_group }}</span></td>
                    <td><span class="chip" [class.ehcp]="p.status === 'EHC plan'">{{ p.status }}</span></td>
                    <td class="small">{{ p.need_area_label }}</td>
                    <td class="prov">@for (x of p.provision.slice(0, 3); track x) { <span class="pchip">{{ x }}</span> }@if (p.provision.length > 3) { <span class="small muted">+{{ p.provision.length - 3 }}</span> }</td>
                    <td>
                      @switch (p.review_state) {
                        @case ('overdue') { <span class="badge bad">Overdue · {{ p.next_review }}</span> }
                        @case ('soon') { <span class="badge warn">Due {{ p.next_review }}</span> }
                        @case ('ok') { <span class="small">{{ p.next_review }}</span> }
                        @default { <span class="small muted">Not set</span> }
                      }
                    </td>
                    <td>
                      @if (p.attendance; as a) {
                        <span class="badge" [class.bad]="a.flag === 'persistent'" [class.warn]="a.flag === 'watch'">{{ a.pct }}%</span>
                        @if (a.recent_pct !== null && a.recent_pct < a.pct - 3) { <span class="small muted"> ↓ {{ a.recent_pct }}% lately</span> }
                      } @else { <span class="small muted">–</span> }
                    </td>
                    <td class="small">{{ p.records }}@if (p.unapproved) { <span class="badge todo">{{ p.unapproved }} to approve</span> }</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
          <p class="small muted">Attendance: red is persistent absence (below 90%), amber is below 95% or dropping. It's a prompt to talk, not a judgement.</p>
        } @else {
          <p class="muted">No pupils yet. Add one, or load the demo school to explore.</p>
        }
      </section>

      <div class="two">
        <section class="card section">
          <h2>Provision in use</h2>
          @for (x of d.provision; track x.name) {
            <div class="bar"><span>{{ x.name }}</span><span class="track"><span [style.width.%]="(x.pupils / maxProv()) * 100"></span></span><strong>{{ x.pupils }}</strong></div>
          } @empty { <p class="muted small">Nothing recorded yet.</p> }
          <h3 class="mt">By area of need</h3>
          @for (a of areaList(); track a[0]) {
            <div class="bar"><span>{{ a[0] }}</span><span class="track"><span [style.width.%]="(a[1] / d.counts.pupils) * 100"></span></span><strong>{{ a[1] }}</strong></div>
          }
        </section>

        <section class="card section">
          <h2>Your school's documents</h2>
          <p class="small muted">The AI grounds every answer in these and the SEND Code of Practice, and cites them. Upload your provision map, SEN policy or a plan's outcomes.</p>
          @for (doc of d.docs; track doc.id) {
            <div class="doc"><span>📄 {{ doc.name }} <span class="small muted">({{ doc.words }} words)</span></span>
              <button type="button" class="btn btn-sm" (click)="removeDoc(doc.id)">Remove</button></div>
          } @empty { <p class="small muted">None yet.</p> }
          <label class="btn btn-sm upload">Upload document (.docx, .pdf, .txt)<input type="file" accept=".docx,.pdf,.txt,.md" (change)="uploadDoc($event)" hidden /></label>
          <h3 class="mt">Attendance</h3>
          <p class="small muted">CSV with columns <code>code, attendance, recent</code> (percentages), exported from your MIS.</p>
          <label class="btn btn-sm upload">Upload attendance CSV<input type="file" accept=".csv" (change)="uploadAttendance($event)" hidden /></label>
          @if (note(); as n) { <p class="small ok">{{ n }}</p> }
        </section>
      </div>
    }
  `,
  styles: `
    .head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; flex-wrap: wrap; }
    .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin: 8px 0 18px; }
    .tile { background: #fff; border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; display: flex; flex-direction: column; gap: 2px; font-size: 13.5px; color: var(--muted); }
    .tile .n { font-size: 30px; font-weight: 800; color: var(--text); line-height: 1.1; }
    .tile.bad { border-color: #fca5a5; background: #fef2f2; } .tile.bad .n { color: #b91c1c; }
    .tile.warn { border-color: #fcd34d; background: #fffbeb; } .tile.warn .n { color: #b45309; }
    .tile.todo { border-color: #c4b5fd; background: #f5f3ff; } .tile.todo .n { color: #6d28d9; }
    .between { justify-content: space-between; }
    .table-wrap { overflow-x: auto; margin-top: 10px; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th { text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); padding: 8px; border-bottom: 1px solid var(--border); }
    td:first-child { white-space: nowrap; }
    td { padding: 10px 8px; border-bottom: 1px solid var(--border); vertical-align: top; }
    tbody tr { cursor: pointer; } tbody tr:hover { background: var(--primary-soft); }
    .chip { font-size: 12px; padding: 3px 9px; border-radius: 999px; background: #e0f2fe; color: #075985; font-weight: 600; white-space: nowrap; }
    .chip.ehcp { background: #ede9fe; color: #5b21b6; }
    .pchip { display: inline-block; font-size: 11.5px; padding: 2px 7px; margin: 0 4px 4px 0; border-radius: 6px; background: #f1f5f9; }
    .badge { font-size: 12px; font-weight: 700; padding: 3px 8px; border-radius: 6px; background: #dcfce7; color: #166534; white-space: nowrap; }
    .badge.bad { background: #fee2e2; color: #991b1b; } .badge.warn { background: #fef3c7; color: #92400e; } .badge.todo { background: #ede9fe; color: #5b21b6; margin-left: 6px; }
    .two { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
    .bar { display: grid; grid-template-columns: 1.4fr 1fr 24px; gap: 10px; align-items: center; font-size: 13.5px; margin: 6px 0; }
    .track { height: 8px; background: #f1f5f9; border-radius: 4px; overflow: hidden; } .track span { display: block; height: 100%; background: var(--primary); }
    .mt { margin-top: 18px; }
    .doc { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px dashed var(--border); font-size: 14px; }
    .upload { margin-top: 10px; display: inline-flex; cursor: pointer; }
    .add { display: grid; grid-template-columns: 1fr 1fr 1.4fr auto; gap: 10px; align-items: end; margin: 12px 0; }
    .full { grid-column: 1 / -1; margin: 0; }
    .ok { color: #166534; }
    @media (max-width: 860px) { .two, .add { grid-template-columns: 1fr; } }
  `,
})
export class SenDashboardPage {
  private readonly sen = inject(SenService);
  private readonly router = inject(Router);
  protected readonly d = signal<Dashboard | null>(null);
  protected readonly meta = signal<Meta | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly note = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected readonly adding = signal(false);
  protected newCode = '';
  protected newYear = '';
  protected newNeed = 'autism';

  constructor() {
    void this.load();
    firstValueFrom(this.sen.meta()).then((m) => this.meta.set(m), () => undefined);
  }

  private async load(): Promise<void> {
    try {
      this.d.set(await firstValueFrom(this.sen.dashboard()));
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  protected maxProv(): number {
    return Math.max(1, ...(this.d()?.provision ?? []).map((x) => x.pupils));
  }

  protected areaList(): [string, number][] {
    return Object.entries(this.d()?.by_area ?? {});
  }

  protected open(id: string): void {
    void this.router.navigate(['/pupils', id]);
  }

  protected async demo(): Promise<void> {
    this.busy.set(true);
    try {
      this.d.set(await firstValueFrom(this.sen.demo()));
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.busy.set(false);
    }
  }

  protected async add(): Promise<void> {
    this.error.set(null);
    try {
      const p = await firstValueFrom(this.sen.createPupil({ code: this.newCode.trim(), year_group: this.newYear.trim(), needs: [this.newNeed] }));
      this.adding.set(false);
      this.newCode = '';
      this.open(p.id);
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  private file(e: Event): File | null {
    const input = e.target as HTMLInputElement;
    const f = input.files?.[0] ?? null;
    input.value = '';
    return f;
  }

  protected async uploadDoc(e: Event): Promise<void> {
    const f = this.file(e);
    if (!f) return;
    try {
      await firstValueFrom(this.sen.uploadDoc(f));
      this.note.set(`Added ${f.name}. Answers will now cite it.`);
      await this.load();
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  protected async removeDoc(id: string): Promise<void> {
    await firstValueFrom(this.sen.deleteDoc(id));
    await this.load();
  }

  protected async uploadAttendance(e: Event): Promise<void> {
    const f = this.file(e);
    if (!f) return;
    try {
      const r = await firstValueFrom(this.sen.uploadAttendance(f));
      this.note.set(`Attendance updated for ${r.rows} pupil(s).`);
      await this.load();
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }
}
