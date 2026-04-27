import { Component } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    MatToolbarModule,
    MatButtonModule,
    MatIconModule,
  ],
  template: `
    <mat-toolbar color="primary">
      <mat-icon>insights</mat-icon>
      <span style="margin-left: 8px; font-weight: 500;">Live Stock</span>
      <span class="toolbar-spacer"></span>
      <a
        mat-button
        routerLink="/portfolio"
        routerLinkActive="active-link"
        [routerLinkActiveOptions]="{ exact: false }"
      >
        <mat-icon>account_balance_wallet</mat-icon>
        Portfolio
      </a>
      <a
        mat-button
        routerLink="/recommendations"
        routerLinkActive="active-link"
      >
        <mat-icon>recommend</mat-icon>
        Recommendations
      </a>
      <a
        mat-button
        routerLink="/discover"
        routerLinkActive="active-link"
      >
        <mat-icon>local_fire_department</mat-icon>
        Discover
      </a>
    </mat-toolbar>
    <router-outlet />
  `,
  styles: [
    `
      .active-link {
        background: rgba(255, 255, 255, 0.15);
      }
    `,
  ],
})
export class AppComponent {}
