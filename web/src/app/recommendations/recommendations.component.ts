import { CommonModule, DecimalPipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { MatCardModule } from '@angular/material/card';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatTooltipModule } from '@angular/material/tooltip';

import { ApiService } from '../api.service';
import { Recommendation, RecommendationAction } from '../models';

@Component({
  selector: 'app-recommendations',
  standalone: true,
  imports: [
    CommonModule,
    DecimalPipe,
    MatCardModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    MatExpansionModule,
    MatTooltipModule,
  ],
  template: `
    <div class="page">
      <div style="display:flex; align-items:center; gap:12px; margin-bottom:16px;">
        <h1 class="page-title">Recommendations</h1>
        <span class="toolbar-spacer"></span>
        <button mat-stroked-button color="primary" (click)="reload()" [disabled]="loading()">
          <mat-icon>refresh</mat-icon> Re-analyze
        </button>
      </div>

      <p class="muted" style="margin-top:-8px;">
        Technical + fundamental + news scoring across all your holdings. May take a minute on first run.
      </p>

      <mat-progress-bar *ngIf="loading()" mode="indeterminate"></mat-progress-bar>

      <div class="error-banner" *ngIf="error() as err">
        <strong>Failed to load recommendations.</strong> {{ err }}
      </div>

      <ng-container *ngIf="!loading() && !error()">
        <div class="summary-cards">
          <mat-card class="summary-card" *ngFor="let bucket of buckets()">
            <mat-card-content>
              <div class="label">{{ bucket.label }}</div>
              <div class="value">{{ bucket.count }}</div>
            </mat-card-content>
          </mat-card>
        </div>

        <mat-card *ngIf="recs().length > 0">
          <table mat-table [dataSource]="recs()" style="width:100%">
            <ng-container matColumnDef="symbol">
              <th mat-header-cell *matHeaderCellDef>Symbol</th>
              <td mat-cell *matCellDef="let r"><strong>{{ r.tradingsymbol }}</strong></td>
            </ng-container>

            <ng-container matColumnDef="price">
              <th mat-header-cell *matHeaderCellDef class="right">Price</th>
              <td mat-cell *matCellDef="let r" class="right">
                {{ r.current_price | number:'1.2-2' }}
              </td>
            </ng-container>

            <ng-container matColumnDef="action">
              <th mat-header-cell *matHeaderCellDef class="center">Action</th>
              <td mat-cell *matCellDef="let r" class="center">
                <span class="action-chip" [class]="actionClass(r.action)">{{ r.action }}</span>
              </td>
            </ng-container>

            <ng-container matColumnDef="score">
              <th mat-header-cell *matHeaderCellDef class="right">Score</th>
              <td mat-cell *matCellDef="let r" class="right">
                <span class="score-bar" matTooltip="Range -1.0 to +1.0">
                  <span [style.background]="r.score >= 0 ? '#2e7d32' : '#c62828'"
                        [style.width.%]="scoreWidth(r.score)"
                        [style.left.%]="scoreLeft(r.score)"></span>
                </span>
                <span [class.pos]="r.score >= 0" [class.neg]="r.score < 0">
                  {{ r.score >= 0 ? '+' : '' }}{{ r.score | number:'1.3-3' }}
                </span>
              </td>
            </ng-container>

            <ng-container matColumnDef="confidence">
              <th mat-header-cell *matHeaderCellDef class="right">Confidence</th>
              <td mat-cell *matCellDef="let r" class="right">
                {{ r.confidence | number:'1.0-1' }}%
              </td>
            </ng-container>

            <ng-container matColumnDef="tech">
              <th mat-header-cell *matHeaderCellDef class="right">Tech</th>
              <td mat-cell *matCellDef="let r" class="right" [class.pos]="r.technical_score >= 0" [class.neg]="r.technical_score < 0">
                {{ r.technical_score >= 0 ? '+' : '' }}{{ r.technical_score | number:'1.3-3' }}
              </td>
            </ng-container>

            <ng-container matColumnDef="fund">
              <th mat-header-cell *matHeaderCellDef class="right">Fund</th>
              <td mat-cell *matCellDef="let r" class="right" [class.pos]="r.fundamental_score > 0" [class.neg]="r.fundamental_score < 0">
                {{ r.fundamental_score >= 0 ? '+' : '' }}{{ r.fundamental_score | number:'1.3-3' }}
              </td>
            </ng-container>

            <ng-container matColumnDef="news">
              <th mat-header-cell *matHeaderCellDef class="right">News</th>
              <td mat-cell *matCellDef="let r" class="right" [class.pos]="r.news_score > 0" [class.neg]="r.news_score < 0">
                {{ r.news_score >= 0 ? '+' : '' }}{{ r.news_score | number:'1.3-3' }}
              </td>
            </ng-container>

            <tr mat-header-row *matHeaderRowDef="cols"></tr>
            <tr mat-row *matRowDef="let row; columns: cols"></tr>
          </table>
        </mat-card>

        <h2 style="margin-top:32px; font-weight:500;">Reasons</h2>
        <mat-accordion multi>
          <mat-expansion-panel *ngFor="let r of recs()">
            <mat-expansion-panel-header>
              <mat-panel-title>
                <strong>{{ r.tradingsymbol }}</strong>
                <span class="action-chip" [class]="actionClass(r.action)" style="margin-left:12px;">
                  {{ r.action }}
                </span>
              </mat-panel-title>
              <mat-panel-description>
                <span class="muted">
                  Score {{ r.score >= 0 ? '+' : '' }}{{ r.score | number:'1.3-3' }} · Confidence {{ r.confidence | number:'1.0-1' }}%
                </span>
              </mat-panel-description>
            </mat-expansion-panel-header>
            <ul class="reasons-list" *ngIf="r.reasons.length > 0; else noReasons">
              <li *ngFor="let reason of r.reasons">{{ reason }}</li>
            </ul>
            <ng-template #noReasons>
              <p class="muted">No specific signals.</p>
            </ng-template>

            <div *ngIf="r.news_items?.length" style="margin-top:16px;">
              <h4 style="margin:0 0 6px 0;">News</h4>
              <ul class="reasons-list">
                <li *ngFor="let n of r.news_items">
                  <a [href]="n.url" target="_blank" rel="noopener">[{{ n.source }}] {{ n.headline }}</a>
                  <span class="muted" *ngIf="n.sentiment !== 'neutral'" style="margin-left:6px;">
                    · {{ n.sentiment }}
                  </span>
                </li>
              </ul>
            </div>
          </mat-expansion-panel>
        </mat-accordion>

        <mat-card *ngIf="recs().length === 0">
          <mat-card-content>
            <p class="muted">No holdings to analyze.</p>
          </mat-card-content>
        </mat-card>
      </ng-container>
    </div>
  `,
})
export class RecommendationsComponent implements OnInit {
  private readonly api = inject(ApiService);

  readonly cols = ['symbol', 'price', 'action', 'score', 'confidence', 'tech', 'fund', 'news'];

  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly recs = signal<Recommendation[]>([]);

  readonly buckets = computed(() => {
    const order: RecommendationAction[] = [
      'STRONG BUY',
      'BUY',
      'HOLD',
      'SELL',
      'STRONG SELL',
    ];
    return order.map((label) => ({
      label,
      count: this.recs().filter((r) => r.action === label).length,
    }));
  });

  ngOnInit(): void {
    this.reload();
  }

  reload(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.recommendations().subscribe({
      next: (data) => {
        this.recs.set(data);
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(err?.error?.detail ?? err?.message ?? 'Unknown error');
        this.loading.set(false);
      },
    });
  }

  actionClass(action: RecommendationAction): string {
    return (
      'action-' +
      action.toLowerCase().replace(' ', '-')
    );
  }

  scoreWidth(score: number): number {
    return Math.min(Math.abs(score), 1) * 50;
  }

  scoreLeft(score: number): number {
    return score >= 0 ? 50 : 50 - this.scoreWidth(score);
  }
}
