import { Routes } from '@angular/router';
import { authGuard } from './core/auth.service';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'styles' },
  {
    path: 'login',
    title: 'Sign in · SlideSmith',
    loadComponent: () => import('./pages/login/login.page').then((m) => m.LoginPage),
  },
  {
    path: 'styles',
    title: 'Styles · SlideSmith',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/styles/styles.page').then((m) => m.StylesPage),
  },
  {
    path: 'create',
    title: 'Create slides · SlideSmith',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/create/create.page').then((m) => m.CreatePage),
  },
  {
    path: 'supports',
    title: 'Visual supports · SlideSmith',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/supports/supports.page').then((m) => m.SupportsPage),
  },
  {
    path: 'live',
    title: 'Live avatar · SlideSmith',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/live/live.page').then((m) => m.LivePage),
  },
  { path: '**', redirectTo: 'styles' },
];
