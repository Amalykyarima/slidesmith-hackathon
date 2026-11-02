import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { errorMessage } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';

@Component({
  selector: 'app-login-page',
  imports: [FormsModule],
  template: `
    <section class="card login">
      <h1>Sign in</h1>
      <p class="muted">Enter the access code you were given to make slides in your own style.</p>
      @if (error(); as message) {
        <div class="alert alert-error" role="alert">{{ message }}</div>
      }
      <form (ngSubmit)="submit()">
        <label class="field">
          Access code
          <input
            class="input"
            name="code"
            [(ngModel)]="code"
            autocomplete="current-password"
            type="password"
            required
            autofocus
          />
        </label>
        <button class="btn btn-primary btn-lg" type="submit" [disabled]="busy() || !code().trim()">
          @if (busy()) {
            <span class="spinner"></span> Signing in…
          } @else {
            Sign in
          }
        </button>
      </form>
    </section>
  `,
  styles: `
    .login { max-width: 420px; margin: 48px auto; display: flex; flex-direction: column; gap: 14px; }
    .login h1 { margin: 0; }
    form { display: flex; flex-direction: column; gap: 14px; }
  `,
})
export class LoginPage {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  protected readonly code = signal('');
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
