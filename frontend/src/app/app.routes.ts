import { Routes } from '@angular/router';
import { authGuard } from './core/auth.service';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'live' },
  {
    path: 'sen',
    title: 'Pupils · SlideSmith',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/sen/dashboard.page').then((m) => m.SenDashboardPage),
  },
  {
    path: 'pupils/:id',
    title: 'Pupil · SlideSmith',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/sen/pupil.page').then((m) => m.PupilPage),
  },
  {
    path: 'learn/:id',
    title: 'My day · SlideSmith',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/learn/learn.page').then((m) => m.LearnPage),
  },
  {
    path: 'adapt',
    title: 'Adapt classwork · SlideSmith',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/sen/adapt.page').then((m) => m.AdaptPage),
  },
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
    title: 'SEN assistant · SlideSmith',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/live/live.page').then((m) => m.LivePage),
  },
  { path: '**', redirectTo: 'sen' },
];
