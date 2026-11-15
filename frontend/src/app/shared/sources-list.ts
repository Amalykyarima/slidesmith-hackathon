import { Component, input } from '@angular/core';
import { Source } from '../core/sen';

/** The passages an AI answer cited: the Code of Practice [C..] and the school's own documents [S..]. */
@Component({
  selector: 'app-sources',
  template: `
    @if (sources().length) {
      <details class="sources">
        <summary>Grounded in {{ sources().length }} source{{ sources().length === 1 ? '' : 's' }}: {{ summary() }}</summary>
        @for (s of sources(); track s.id) {
          <div class="src">
            <span class="sid" [class.school]="s.id.startsWith('S')">{{ s.id }}</span>
            <div>
              <strong>{{ s.source }}</strong> · {{ s.title }}
              <p>{{ s.text }}</p>
            </div>
          </div>
        }
      </details>
    } @else {
      <p class="small muted">No sources cited.</p>
    }
  `,
  styles: `
    .sources { border: 1px solid var(--border); border-radius: 10px; padding: 10px 14px; background: #f8fafc; font-size: 13.5px; }
    summary { cursor: pointer; font-weight: 600; color: var(--primary-dark); }
    .src { display: grid; grid-template-columns: 36px 1fr; gap: 10px; margin-top: 10px; }
    .src p { margin: 4px 0 0; color: var(--muted); }
    .sid { display: inline-grid; place-items: center; height: 24px; border-radius: 6px; background: #e0e7ff; color: #3730a3; font-weight: 700; font-size: 12px; }
    .sid.school { background: #dcfce7; color: #166534; }
  `,
})
export class SourcesList {
  readonly sources = input<Source[]>([]);
  protected summary(): string {
    const school = this.sources().filter((s) => s.id.startsWith('S')).length;
    const cop = this.sources().length - school;
    return [school ? `${school} from your school's documents` : '', cop ? `${cop} from the SEND Code of Practice` : '']
      .filter(Boolean)
      .join(', ');
  }
}
