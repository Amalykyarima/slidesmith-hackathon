import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { errorMessage } from '../../core/api.service';
import { Meta, PupilRow, SenService } from '../../core/sen';

/** Pupils with SEN, and the school documents the AI grounds its answers in. */
@Component({
  selector: 'app-pupils-page',
  imports: [FormsModule, RouterLink],
  template: `
    <div class="head">
      <div>
        <h1>Pupils</h1>
        <p class="lead">Adapt classwork for a pupil's needs, then log what you tried and review whether it worked. Every AI answer is a draft for staff to check.</p>
      </div>
      <div class="row">
        <a class="btn btn-primary" routerLink="/adapt">Adapt classwork</a>
        @if (!pupils().length) {
          <button type="button" class="btn" [disabled]="busy()" (click)="demo()">Load demo school</button>
        }
      </div>
    </div>

    @if (error(); as m) {
      <div class="alert alert-error" role="alert">{{ m }}</div>
    }

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
      @if (pupils().length) {
        <div class="table-wrap">
          <table>
            <thead><tr><th>Pupil</th><th>Area of need</th><th>Support in place</th><th>Records</th><th>Next review</th><th></th></tr></thead>
            <tbody>
              @for (p of pupils(); track p.id) {
                <tr (click)="open(p.id)" tabindex="0" (keydown.enter)="open(p.id)">
                  <td class="code"><strong>{{ p.code }}</strong><br /><span class="small muted">{{ p.year_group }}</span></td>
                  <td class="small">{{ p.need_area_label }}</td>
                  <td>@for (x of p.provision.slice(0, 3); track x) { <span class="pchip">{{ x }}</span> }@if (p.provision.length > 3) { <span class="small muted">+{{ p.provision.length - 3 }}</span> }</td>
                  <td class="small nowrap">{{ p.records }}@if (p.last_record) { <br /><span class="muted">last {{ p.last_record }}</span> }</td>
                  <td class="small nowrap">{{ p.next_review || "–" }}</td>
                  <td class="acts"><a class="btn btn-sm btn-primary" [routerLink]="['/learn', p.id]" (click)="$event.stopPropagation()">Open My day</a>
                    <a class="btn btn-sm" routerLink="/adapt" [queryParams]="{ pupil: p.id }" (click)="$event.stopPropagation()">Adapt work</a></td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      } @else {
        <p class="muted">No pupils yet. Add one, or load the demo school to explore.</p>
      }
    </section>

    <section class="card section">
      <h2>Your school's documents</h2>
      <p class="small muted">The AI grounds every answer in these and the SEND Code of Practice, and cites them. Upload your provision map, SEN policy or a pupil's targets.</p>
      @for (doc of docs(); track doc.id) {
        <div class="doc"><span>📄 {{ doc.name }} <span class="small muted">({{ doc.words }} words)</span></span>
          <button type="button" class="btn btn-sm" (click)="removeDoc(doc.id)">Remove</button></div>
      } @empty { <p class="small muted">None yet.</p> }
      <label class="btn btn-sm upload">Upload document (.docx, .pdf, .txt)<input type="file" accept=".docx,.pdf,.txt,.md" (change)="uploadDoc($event)" hidden /></label>
      @if (note(); as n) { <p class="small ok">{{ n }}</p> }
    </section>
  `,
  styles: `
    .head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; flex-wrap: wrap; }
    .between { justify-content: space-between; }
    .table-wrap { overflow-x: auto; margin-top: 10px; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th { text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); padding: 8px; border-bottom: 1px solid var(--border); }
    td { padding: 10px 8px; border-bottom: 1px solid var(--border); vertical-align: top; }
    td.code, td .btn, td.nowrap { white-space: nowrap; }
    .acts { display: flex; gap: 6px; }
    tbody tr { cursor: pointer; } tbody tr:hover { background: var(--primary-soft); }
    .pchip { display: inline-block; font-size: 11.5px; padding: 2px 7px; margin: 0 4px 4px 0; border-radius: 6px; background: #f1f5f9; }
    .doc { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px dashed var(--border); font-size: 14px; }
    .upload { margin-top: 10px; display: inline-flex; cursor: pointer; }
    .add { display: grid; grid-template-columns: 1fr 1fr 1.4fr auto; gap: 10px; align-items: end; margin: 12px 0; }
    .full { grid-column: 1 / -1; margin: 0; }
    .ok { color: #166534; }
    @media (max-width: 860px) { .add { grid-template-columns: 1fr; } }
  `,
})
export class SenDashboardPage {
  private readonly sen = inject(SenService);
  private readonly router = inject(Router);
  protected readonly pupils = signal<PupilRow[]>([]);
  protected readonly docs = signal<{ id: string; name: string; words: number }[]>([]);
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
      const [pupils, docs] = await Promise.all([firstValueFrom(this.sen.pupils()), firstValueFrom(this.sen.docs())]);
      this.pupils.set(pupils);
      this.docs.set(docs);
    } catch (err) {
      this.error.set(errorMessage(err));
    }
  }

  protected open(id: string): void {
    void this.router.navigate(['/pupils', id]);
  }

  protected async demo(): Promise<void> {
    this.busy.set(true);
    try {
      await firstValueFrom(this.sen.demo());
      await this.load();
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

  protected async uploadDoc(e: Event): Promise<void> {
    const input = e.target as HTMLInputElement;
    const f = input.files?.[0];
    input.value = '';
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
}
