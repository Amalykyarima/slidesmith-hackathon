import { Component, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { catchError, of } from 'rxjs';
import { ApiService } from './core/api.service';
import { AuthService } from './core/auth.service';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  private readonly api = inject(ApiService);
  /** undefined = loading, null = backend unreachable */
  protected readonly health = toSignal(this.api.health().pipe(catchError(() => of(null))));
  protected readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  constructor() {
    void this.auth.load();
  }

  protected async signOut(): Promise<void> {
    await this.auth.logout();
    await this.router.navigate(['/login']);
  }
}
