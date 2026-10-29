import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'create' },
  {
    path: 'styles',
    title: 'Styles · SlideSmith',
    loadComponent: () => import('./pages/styles/styles.page').then((m) => m.StylesPage),
  },
  {
    path: 'create',
    title: 'Create slides · SlideSmith',
    loadComponent: () => import('./pages/create/create.page').then((m) => m.CreatePage),
  },
  { path: '**', redirectTo: 'styles' },
];
