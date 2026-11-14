import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ApiService, errorMessage } from '../../core/api.service';
import { LevelKey, Supports } from '../../core/models';
import { SupportsView } from '../../shared/supports-view';

const EXAMPLES: { label: string; topic: string; details: string; level: LevelKey }[] = [
  {
    label: 'Volcano model (Year 3 science)',
    topic: 'Making a volcano model',
    level: 'primary',
    details: 'Read the instruction card\nCut out the volcano shape\nGlue it onto the paper plate\nColour the lava red and orange\nShow your teacher\nTidy your table',
  },
  {
    label: 'Morning routine (any class)',
    topic: 'Morning in class',
    level: 'primary',
    details: 'Hang up your coat\nSit on the carpet for register\nPhonics\nBreak time\nMaths\nLunch',
  },
  {
    label: 'Fractions practice (Year 7)',
    topic: 'Equivalent fractions',
    level: 'secondary',
    details: 'Starter: 3 quick recall questions\nWatch the teacher model one example\nWork with your partner on questions 1-4\nCheck your answers with the answer card\nExit ticket',
  },
  {
    label: 'Lab practical (university)',
    topic: 'Titration practical',
    level: 'university',
    details: 'Put on goggles and lab coat\nRinse the burette with the acid\nFill the burette to 0.00 cm3\nAdd 3 drops of indicator to the flask\nTitrate until the colour just changes\nRecord the reading and repeat',
  },
];

/** For TAs and teachers who need visual supports now: Now/Next, timetable, steps and key words. */
@Component({
  selector: 'app-supports-page',
  imports: [FormsModule, SupportsView],
  template: `
    <div class="no-print">
      <h1>Visual supports</h1>
      <p class="lead">
        Describe a lesson, activity or part of the day. In seconds you get a Now/Next board, a visual timetable, step-by-step task cards
        and key-word cards with symbols, ready to print for pupils who need them.
      </p>

      @if (error(); as m) {
        <div class="alert alert-error" role="alert">{{ m }}</div>
      }

      <section class="card section">
        <div class="examples">
          <span class="small muted">Try:</span>
          @for (e of examples; track e.label) {
            <button type="button" class="btn btn-sm" (click)="useExample(e)">{{ e.label }}</button>
          }
        </div>
        <div class="stack">
          <div class="two">
            <label class="field">
              What is it?
              <input class="input" [(ngModel)]="topic" maxlength="200" placeholder="e.g. Making a volcano model" />
            </label>
            <label class="field">
              Who is it for?
              <select class="input" [(ngModel)]="level">
                <option value="primary">Primary</option>
                <option value="secondary">Secondary</option>
                <option value="university">University / FE</option>
              </select>
            </label>
          </div>
          <label class="field">
            What happens, step by step? <span class="hint">(one line each, rough notes are fine)</span>
            <textarea class="input" rows="6" [(ngModel)]="details" maxlength="3000"
              placeholder="Read the card&#10;Cut out the shape&#10;Glue it on the plate"></textarea>
          </label>
          <p class="small muted">Names, emails and phone numbers are removed before anything reaches the AI.</p>
          <div class="row">
            <button type="button" class="btn btn-primary btn-lg" [disabled]="busy() || (!topic().trim() && !details().trim())" (click)="make()">
              @if (busy()) {
                <span class="spinner"></span> Making cards…
              } @else {
                Make visual supports
              }
            </button>
          </div>
        </div>
      </section>
    </div>

    @if (result(); as s) {
      <section class="card section">
        <app-supports-view [supports]="s" />
      </section>
    }
  `,
  styles: `
    .examples { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 16px; }
    .two { display: grid; grid-template-columns: 2fr 1fr; gap: 14px; }
    @media (max-width: 640px) { .two { grid-template-columns: 1fr; } }
    @media print { .card { border: 0; box-shadow: none; } .section { padding: 0; } }
  `,
})
export class SupportsPage {
  private readonly api = inject(ApiService);
  protected readonly examples = EXAMPLES;
  protected readonly topic = signal('');
  protected readonly details = signal('');
  protected readonly level = signal<LevelKey>('primary');
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly result = signal<Supports | null>(null);

  protected useExample(e: (typeof EXAMPLES)[number]): void {
    this.topic.set(e.topic);
    this.details.set(e.details);
    this.level.set(e.level);
  }

  protected async make(): Promise<void> {
    this.busy.set(true);
    this.error.set(null);
    try {
      this.result.set(await firstValueFrom(this.api.supports(this.topic().trim(), this.details().trim(), this.level())));
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.busy.set(false);
    }
  }
}
