import { CommonModule, DecimalPipe } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatTabsModule } from '@angular/material/tabs';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { FormsModule } from '@angular/forms';

import { ApiService } from '../api.service';
import {
  DiscoverResult,
  Recommendation,
  RecommendationAction,
} from '../models';
import {
  StockDetailDialogComponent,
} from '../portfolio/portfolio.component';

interface UniverseGroup {
  label: string;
  indices: string[];
}

@Component({
  selector: 'app-discover',
  standalone: true,
  imports: [
    CommonModule,
    DecimalPipe,
    FormsModule,
    MatTableModule,
    MatProgressBarModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatDialogModule,
    MatTooltipModule,
    MatTabsModule,
    MatFormFieldModule,
    MatSelectModule,
  ],
  template: `
    <div class="page">
      <div style="display:flex; align-items:center; gap:12px; margin-bottom:8px; flex-wrap:wrap;">
        <h1 class="page-title">Discover hot stocks</h1>
        <span class="muted" *ngIf="result() as r">
          · scanned {{ r.scanned_count }} stocks · {{ r.screened_count }} passed pre-filter
          <span *ngIf="r.scanned_at"> · {{ r.scanned_at }}</span>
        </span>
        <span class="toolbar-spacer"></span>

        <mat-form-field appearance="outline" subscriptSizing="dynamic" style="width:280px;">
          <mat-label>Universe</mat-label>
          <mat-select [(ngModel)]="universe" (selectionChange)="run(false)">
            <mat-optgroup *ngFor="let g of universeGroups()" [label]="g.label">
              <mat-option *ngFor="let i of g.indices" [value]="i">
                {{ formatIndex(i) }}
              </mat-option>
            </mat-optgroup>
          </mat-select>
        </mat-form-field>

        <button mat-stroked-button color="primary" (click)="run(false)" [disabled]="loading()">
          <mat-icon>local_fire_department</mat-icon> {{ result() ? 'Refresh from cache' : 'Run scan' }}
        </button>
        <button mat-stroked-button (click)="run(true)" [disabled]="loading()" matTooltip="Bypass cache (slow)">
          <mat-icon>refresh</mat-icon> Force re-scan
        </button>
      </div>

      <p class="muted" style="margin-top:0;">
        Scans the chosen universe for stocks with strong-buy analyst consensus + meaningful upside, then deep-analyzes the top {{ topN }}
        with the same multi-source pipeline as your portfolio (yfinance + Screener + news + ARIMA + Monte Carlo).
        Sectoral indices are small (10-20 stocks) and finish in &lt;1 minute. Broad indices like NIFTY 500 take 3–8 min cold.
      </p>

      <mat-progress-bar *ngIf="loading()" mode="indeterminate"></mat-progress-bar>
      <p *ngIf="loading()" class="muted" style="margin-top:8px;">
        Stage 1: pre-filtering candidates… Stage 2: deep-analyzing top picks…
      </p>

      <div class="error-banner" *ngIf="error() as err">
        <strong>Error.</strong> {{ err }}
      </div>

      <ng-container *ngIf="!loading() && result() as r">
        <h2 style="margin-top:24px; margin-bottom:8px;">
          Top {{ r.picks.length }} picks · {{ formatIndex(r.universe) }}
        </h2>

        <mat-tab-group>
          <mat-tab label="All sectors">
            <ng-container *ngTemplateOutlet="picksTable; context: { picks: r.picks }"></ng-container>
          </mat-tab>
          <mat-tab *ngFor="let g of r.sector_groups" [label]="g.sector + ' (' + g.count + ')'">
            <ng-container *ngTemplateOutlet="picksTable; context: { picks: g.picks }"></ng-container>
          </mat-tab>
        </mat-tab-group>

        <ng-template #picksTable let-picks="picks">
          <mat-card *ngIf="picks.length > 0; else emptyTab" style="margin-top:8px;">
            <table mat-table [dataSource]="picks" style="width:100%;">
              <ng-container matColumnDef="symbol">
                <th mat-header-cell *matHeaderCellDef>Symbol</th>
                <td mat-cell *matCellDef="let p">
                  <strong>{{ p.tradingsymbol }}</strong>
                  <div class="muted" style="font-size:11px;">{{ p.industry || p.sector || '' }}</div>
                </td>
              </ng-container>
              <ng-container matColumnDef="action">
                <th mat-header-cell *matHeaderCellDef class="center">Action</th>
                <td mat-cell *matCellDef="let p" class="center">
                  <span class="action-chip" [class]="actionClass(p.action)">{{ p.action }}</span>
                </td>
              </ng-container>
              <ng-container matColumnDef="price">
                <th mat-header-cell *matHeaderCellDef class="right">Price</th>
                <td mat-cell *matCellDef="let p" class="right">₹ {{ p.current_price | number:'1.2-2' }}</td>
              </ng-container>
              <ng-container matColumnDef="buy_upto">
                <th mat-header-cell *matHeaderCellDef class="right">Buy upto</th>
                <td mat-cell *matCellDef="let p" class="right">
                  {{ p.buy_upto !== null ? '₹ ' + (p.buy_upto | number:'1.0-0') : '—' }}
                </td>
              </ng-container>
              <ng-container matColumnDef="target">
                <th mat-header-cell *matHeaderCellDef class="right">12m Target</th>
                <td mat-cell *matCellDef="let p" class="right">
                  <ng-container *ngIf="p.target_price_consensus">
                    ₹ {{ p.target_price_consensus | number:'1.0-0' }}
                    <span class="pos" style="font-size:11px;">+{{ upside(p) | number:'1.1-1' }}%</span>
                  </ng-container>
                </td>
              </ng-container>
              <ng-container matColumnDef="stop">
                <th mat-header-cell *matHeaderCellDef class="right">Stop</th>
                <td mat-cell *matCellDef="let p" class="right">
                  {{ p.stop_loss !== null ? '₹ ' + (p.stop_loss | number:'1.0-0') : '—' }}
                </td>
              </ng-container>
              <ng-container matColumnDef="analysts">
                <th mat-header-cell *matHeaderCellDef class="right">Analysts</th>
                <td mat-cell *matCellDef="let p" class="right">
                  {{ p.analyst_count }} <span class="muted" style="font-size:11px;">({{ p.analyst_recommendation }})</span>
                </td>
              </ng-container>
              <ng-container matColumnDef="why">
                <th mat-header-cell *matHeaderCellDef>Why</th>
                <td mat-cell *matCellDef="let p" style="max-width:340px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"
                    [matTooltip]="p.headline_reason">
                  {{ p.headline_reason }}
                </td>
              </ng-container>
              <tr mat-header-row *matHeaderRowDef="cols"></tr>
              <tr mat-row *matRowDef="let row; columns: cols"
                  style="cursor:pointer"
                  (click)="openDetail(row)"></tr>
            </table>
          </mat-card>
          <ng-template #emptyTab>
            <p class="muted" style="margin-top:16px;">No picks for this sector.</p>
          </ng-template>
        </ng-template>

        <h2 style="margin-top:32px; margin-bottom:8px;">Pre-filter shortlist ({{ r.shortlist.length }})</h2>
        <p class="muted" style="margin-top:0;">All stocks in the universe that passed the cheap analyst-consensus screen, ranked by hotness. Top {{ topN }} above are deep-analyzed.</p>
        <mat-card *ngIf="r.shortlist.length > 0">
          <table mat-table [dataSource]="r.shortlist" style="width:100%;">
            <ng-container matColumnDef="symbol">
              <th mat-header-cell *matHeaderCellDef>Symbol</th>
              <td mat-cell *matCellDef="let s">
                <strong>{{ s.symbol }}</strong>
                <div class="muted" style="font-size:11px;">{{ s.name }}</div>
              </td>
            </ng-container>
            <ng-container matColumnDef="rec">
              <th mat-header-cell *matHeaderCellDef class="center">Consensus</th>
              <td mat-cell *matCellDef="let s" class="center">
                <span class="action-chip" [class]="recClass(s.rec_key)">{{ recLabel(s.rec_key) }}</span>
              </td>
            </ng-container>
            <ng-container matColumnDef="price">
              <th mat-header-cell *matHeaderCellDef class="right">Price</th>
              <td mat-cell *matCellDef="let s" class="right">₹ {{ s.current_price | number:'1.2-2' }}</td>
            </ng-container>
            <ng-container matColumnDef="target">
              <th mat-header-cell *matHeaderCellDef class="right">Target</th>
              <td mat-cell *matCellDef="let s" class="right">₹ {{ s.target_mean | number:'1.0-0' }}</td>
            </ng-container>
            <ng-container matColumnDef="upside">
              <th mat-header-cell *matHeaderCellDef class="right">Upside</th>
              <td mat-cell *matCellDef="let s" class="right pos">+{{ s.upside_pct | number:'1.1-1' }}%</td>
            </ng-container>
            <ng-container matColumnDef="analysts">
              <th mat-header-cell *matHeaderCellDef class="right">Analysts</th>
              <td mat-cell *matCellDef="let s" class="right">{{ s.n_analysts }}</td>
            </ng-container>
            <ng-container matColumnDef="sector">
              <th mat-header-cell *matHeaderCellDef>Sector</th>
              <td mat-cell *matCellDef="let s">{{ s.sector || s.industry }}</td>
            </ng-container>
            <ng-container matColumnDef="research">
              <th mat-header-cell *matHeaderCellDef class="center"></th>
              <td mat-cell *matCellDef="let s" class="center">
                <button mat-icon-button (click)="$event.stopPropagation(); deepResearch(s.symbol)" matTooltip="Deep-research this stock">
                  <mat-icon>search</mat-icon>
                </button>
              </td>
            </ng-container>

            <tr mat-header-row *matHeaderRowDef="shortCols"></tr>
            <tr mat-row *matRowDef="let row; columns: shortCols"></tr>
          </table>
        </mat-card>
      </ng-container>
    </div>
  `,
})
export class DiscoverComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly dialog = inject(MatDialog);

  readonly topN = 30;
  readonly cols = ['symbol', 'action', 'price', 'buy_upto', 'target', 'stop', 'analysts', 'why'];
  readonly shortCols = ['symbol', 'rec', 'price', 'target', 'upside', 'analysts', 'sector', 'research'];

  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly result = signal<DiscoverResult | null>(null);
  readonly universeGroups = signal<UniverseGroup[]>([]);

  universe = 'NIFTY500';

  ngOnInit(): void {
    this.api.universes().subscribe({
      next: (u) => this.universeGroups.set(u.groups || []),
      error: () => {},
    });
    this.run(false);
  }

  run(refresh: boolean): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.discover(this.universe, this.topN, refresh).subscribe({
      next: (r) => {
        this.result.set(r);
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(err?.error?.detail ?? err?.message ?? 'Scan failed');
        this.loading.set(false);
      },
    });
  }

  openDetail(rec: Recommendation): void {
    const row = {
      tradingsymbol: rec.tradingsymbol,
      exchange: 'NSE',
      instrument_token: 0,
      quantity: 0,
      average_price: 0,
      last_price: rec.current_price,
      pnl: 0,
      day_change_percentage: 0,
      product: '',
      rec,
    };
    this.dialog.open(StockDetailDialogComponent, { data: { row }, width: '720px', maxWidth: '95vw' });
  }

  deepResearch(symbol: string): void {
    this.api.analyze(symbol).subscribe({
      next: (rec) => this.openDetail(rec),
      error: (err) => this.error.set(err?.error?.detail ?? 'Could not research ' + symbol),
    });
  }

  upside(p: Recommendation): number {
    if (!p.target_price_consensus || !p.current_price) return 0;
    return ((p.target_price_consensus - p.current_price) / p.current_price) * 100;
  }

  actionClass(action: RecommendationAction): string {
    return 'action-' + action.toLowerCase().replace(' ', '-');
  }

  recClass(rec: string): string {
    if (rec === 'strong_buy') return 'action-strong-buy';
    if (rec === 'buy') return 'action-buy';
    if (rec === 'hold') return 'action-hold';
    return 'action-sell';
  }

  recLabel(rec: string): string {
    return (rec || '').replace('_', ' ').toUpperCase();
  }

  formatIndex(i: string): string {
    return i.replace(/_/g, ' ').replace('NIFTY', 'NIFTY ');
  }
}
