import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { errorMessage } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';

@Component({
  selector: 'app-login-page',
  imports: [FormsModule],
  template: `
    <section class="card login" aria-labelledby="login-title">
      <span class="mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>
      </span>
      <h1 id="login-title">Sign in to SlideSmith</h1>
      <p class="muted intro">Use the access code you were given. Your styles and decks are private to you.</p>

      @if (error(); as message) {
        <div class="alert alert-error" role="alert">{{ message }}</div>
      }

      <form (ngSubmit)="submit()" novalidate>
        <label class="field" for="code">Access code</label>
        <div class="code-box">
          <input
            id="code"
            class="input"
            name="code"
            [(ngModel)]="code"
            [type]="showCode() ? 'text' : 'password'"
            autocomplete="current-password"
            autocapitalize="off"
            spellcheck="false"
            placeholder="e.g. maple-42"
            required
            autofocus
            [attr.aria-invalid]="!!error()"
          />
          <button
            type="button"
            class="reveal"
            (click)="showCode.set(!showCode())"
            [attr.aria-label]="showCode() ? 'Hide access code' : 'Show access code'"
            [attr.aria-pressed]="showCode()"
          >
            {{ showCode() ? 'Hide' : 'Show' }}
          </button>
        </div>

        <button class="btn btn-primary btn-lg submit" type="submit" [disabled]="busy() || !code().trim()">
          @if (busy()) {
            <span class="spinner"></span> Signing in…
          } @else {
            Sign in
          }
        </button>
      </form>

      <p class="small muted help">No code yet? Ask the person who set up SlideSmith for your school.</p>
    </section>
  `,
  styles: `
    :host { display: block; padding: 8vh 0 32px; }
    .login {
      max-width: 420px;
      margin: 0 auto;
      padding: 32px 28px 24px;
      display: flex;
      flex-direction: column;
    }
    .mark {
      display: inline-grid;
      place-items: center;
      width: 48px;
      height: 48px;
      border-radius: 12px;
      background: var(--primary);
      color: #fff;
      margin-bottom: 18px;
    }
    h1 { font-size: 24px; margin: 0 0 6px; }
    .intro { margin-bottom: 22px; }
    .alert { margin-bottom: 16px; }
    form { display: flex; flex-direction: column; }
    .field { font-weight: 600; font-size: 14px; margin-bottom: 6px; }
    .code-box { position: relative; margin-bottom: 18px; }
    .code-box .input { width: 100%; padding-right: 64px; font-size: 16px; }
    .reveal {
      position: absolute;
      right: 6px;
      top: 50%;
      transform: translateY(-50%);
      border: 0;
      background: transparent;
      color: var(--primary);
      font: inherit;
      font-size: 13px;
      font-weight: 600;
      padding: 6px 8px;
      border-radius: 6px;
      cursor: pointer;
    }
    .reveal:hover { background: var(--primary-soft); }
    .reveal:focus-visible { outline: 3px solid rgba(15, 118, 110, 0.35); }
    .submit { width: 100%; justify-content: center; }
    .help { margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--border); text-align: center; }
    @media (max-width: 480px) {
      :host { padding-top: 24px; }
      .login { padding: 24px 18px 18px; }
    }
  `,
})
export class LoginPage {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  protected readonly code = signal('');
  protected readonly showCode = signal(false);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected async submit(): Promise<void> {
    if (!this.code().trim() || this.busy()) return;
    this.busy.set(true);
    this.error.set(null);
    try {
      await this.auth.login(this.code().trim());
      const next = this.route.snapshot.queryParamMap.get('next');
      await this.router.navigateByUrl(next && next.startsWith('/') && !next.startsWith('/login') ? next : '/create');
    } catch (err) {
      this.error.set(errorMessage(err));
    } finally {
      this.busy.set(false);
    }
  }
}
