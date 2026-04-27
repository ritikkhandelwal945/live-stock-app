import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'portfolio' },
  {
    path: 'portfolio',
    loadComponent: () =>
      import('./portfolio/portfolio.component').then((m) => m.PortfolioComponent),
  },
  {
    path: 'recommendations',
    loadComponent: () =>
      import('./recommendations/recommendations.component').then(
        (m) => m.RecommendationsComponent
      ),
  },
  {
    path: 'discover',
    loadComponent: () =>
      import('./discover/discover.component').then((m) => m.DiscoverComponent),
  },
  {
    path: 'macro',
    loadComponent: () =>
      import('./macro/macro.component').then((m) => m.MacroComponent),
  },
  { path: '**', redirectTo: 'portfolio' },
];
