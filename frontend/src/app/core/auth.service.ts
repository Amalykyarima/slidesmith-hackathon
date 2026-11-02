import { HttpClient, HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, firstValueFrom, throwError } from 'rxjs';

interface Session {
  auth_required: boolean;
  name: string | null;
}

/** Who is signed in. On a hosted SlideSmith teachers sign in with an access code. */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly session = signal<Session | null>(null);
  private loading: Promise<Session> | null = null;

  readonly name = computed(() => this.session()?.name ?? null);
  readonly authRequired = computed(() => this.session()?.auth_required ?? false);
  readonly signedIn = computed(() => !this.authRequired() || !!this.name());

  /** Fetches the session once (and again after sign-in or sign-out). */
  load(force = false): Promise<Session> {
    if (!force && this.session()) return Promise.resolve(this.session()!);
    if (!this.loading || force) {
      this.loading = firstValueFrom(this.http.get<Session>('/api/session'))
        .catch(() => ({ auth_required: false, name: null }))
        .then((s) => {
          this.session.set(s);
          this.loading = null;
          return s;
        });
    }
    return this.loading;
  }

  async login(code: string): Promise<void> {
    const res = await firstValueFrom(this.http.post<{ name: string | null }>('/api/login', { code }));
    this.session.set({ auth_required: true, name: res.name });
  }

  async logout(): Promise<void> {
    await firstValueFrom(this.http.post('/api/logout', {})).catch(() => undefined);
    this.session.set({ auth_required: true, name: null });
  }

  /** Called when the server says the sign-in has expired. */
  expire(): void {
    if (this.authRequired()) this.session.set({ auth_required: true, name: null });
  }
}

/** Pages need a sign-in when the server asks for one. */
export const authGuard: CanActivateFn = async (_route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const s = await auth.load();
  if (!s.auth_required || s.name) return true;
  return router.createUrlTree(['/login'], { queryParams: { next: state.url } });
};

/** A 401 from the API (sign-in expired) sends the teacher back to the sign-in page. */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  return next(req).pipe(
    catchError((err: unknown) => {
      if (err instanceof HttpErrorResponse && err.status === 401 && !req.url.endsWith('/api/login')) {
        auth.expire();
        void router.navigate(['/login'], { queryParams: { next: router.url } });
      }
      return throwError(() => err);
    }),
  );
};
