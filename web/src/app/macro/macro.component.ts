import { CommonModule, DatePipe, DecimalPipe } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';

import { ApiService } from '../api.service';
import { MacroResult, MacroTheme } from '../models';
import { StockDetailDialogComponent } from '../portfolio/portfolio.component';

@Component({
  selector: 'app-macro',
  standalone: true,
  imports: [
    CommonModule,
    DatePipe,
    DecimalPipe,
    MatButtonModule,
    MatCardModule,
    MatChipsModule,
    MatDialogModule,
    MatIconModule,
    MatProgressBarModule,
    MatTooltipModule,
  ],
  template: `
    <div class="page">
      <div style="display:flex; align-items:center; gap:12px; margin-bottom:8px; flex-wrap:wrap;">
        <h1 class="page-title">Macro Themes</h1>
        <span *ngIf="result() as r" class="muted">
          · {{ r.article_count }} articles scanned ·
          {{ r.themes.length }} active themes
          <span *ngIf="r.sources_used.includes('gemini')" class="action-chip"
                style="background:#7c4dff; margin-left:6px;">via Gemini</span>
          <span *ngIf="r.generated_at"> · {{ r.generated_at | date: 'short' }}</span>
        </span>
        <span class="toolbar-spacer"></span>
        <button mat-stroked-button color="primary" (click)="run(false)" [disabled]="loading()">
          <mat-icon>refresh</mat-icon> Reload
        </button>
        <button mat-stroked-button (click)="run(true)" [disabled]="loading()" matTooltip="Bypass cache">
          <mat-icon>cached</mat-icon> Force re-scan
        </button>
      </div>

      <p class="muted" style="margin-top:0;">
        Active macro themes detected from {{ result()?.article_count || 0 }} recent Indian financial-news headlines
        (ET / CNBC TV18 / MoneyControl / Mint / Business Standard).
        Sectors are mapped to NSE stock-universe to surface impacted holdings + watchlist.
        <em>Honest framing: this is rule-based theme matching, not predictive signal.</em>
      </p>

      <mat-progress-bar *ngIf="loading()" mode="indeterminate"></mat-progress-bar>

      <div class="error-banner" *ngIf="error() as err">
        <strong>Error.</strong> {{ err }}
      </div>

      <ng-container *ngIf="!loading() && result() as r">
        <mat-card *ngIf="r.themes.length === 0" style="margin-top:12px;">
          <mat-card-content>
            <p class="muted">No active macro themes (≥3 articles needed per theme).
              Try Force re-scan, or wait — themes activate as headlines accumulate.</p>
          </mat-card-content>
        </mat-card>

        <div *ngFor="let t of r.themes" style="margin-top:18px;">
          <mat-card>
            <mat-card-content>
              <div style="display:flex; align-items:baseline; gap:10px; flex-wrap:wrap;">
                <span style="font-size:24px;">{{ t.emoji }}</span>
                <h2 style="margin:0;">{{ t.label }}</h2>
                <span class="action-chip"
                      [style.background]="t.source === 'gemini' ? '#7c4dff' : '#1565c0'">
                  {{ t.source === 'gemini' ? 'Gemini' : 'rule-based' }}
                </span>
                <span class="muted">{{ t.article_count }} articles · score {{ t.score | number:'1.2-2' }}</span>
              </div>
              <p *ngIf="t.summary" style="margin:8px 0 0 0;">{{ t.summary }}</p>

              <div *ngIf="t.matched_articles.length > 0" style="margin-top:12px;">
                <h4 style="margin:0 0 4px 0;">Headlines</h4>
                <ul class="reasons-list">
                  <li *ngFor="let a of t.matched_articles">
                    <a [href]="a.url" target="_blank" rel="noopener">[{{ a.source }}] {{ a.headline }}</a>
                  </li>
                </ul>
              </div>

              <div style="display:grid; grid-template-columns: 1fr 1fr; gap:16px; margin-top:14px;">
                <div *ngIf="t.impacted_positive.length > 0">
                  <h4 style="margin:0 0 6px 0; color:#2e7d32;">↑ Beneficiaries ({{ t.impacted_positive.length }})</h4>
                  <div class="muted" style="font-size:11px; margin-bottom:4px;">
                    Sectors: {{ t.sectors_positive.join(', ') }}
                  </div>
                  <div style="display:flex; flex-wrap:wrap; gap:4px;">
                    <span *ngFor="let s of t.impacted_positive"
                          (click)="research(s.symbol)"
                          style="cursor:pointer; padding:4px 8px; border-radius:4px; font-size:13px;"
                          [style.background]="s.in_portfolio ? '#c8e6c9' : '#f5f5f5'"
                          [matTooltip]="s.sector + (s.in_portfolio ? ' · in your portfolio' : '')">
                      {{ s.symbol }}
                      <mat-icon *ngIf="s.in_portfolio" style="font-size:11px; height:11px; width:11px; vertical-align:middle;">star</mat-icon>
                    </span>
                  </div>
                </div>
                <div *ngIf="t.impacted_negative.length > 0">
                  <h4 style="margin:0 0 6px 0; color:#c62828;">↓ At risk ({{ t.impacted_negative.length }})</h4>
                  <div class="muted" style="font-size:11px; margin-bottom:4px;">
                    Sectors: {{ t.sectors_negative.join(', ') }}
                  </div>
                  <div style="display:flex; flex-wrap:wrap; gap:4px;">
                    <span *ngFor="let s of t.impacted_negative"
                          (click)="research(s.symbol)"
                          style="cursor:pointer; padding:4px 8px; border-radius:4px; font-size:13px;"
                          [style.background]="s.in_portfolio ? '#ffcdd2' : '#f5f5f5'"
                          [matTooltip]="s.sector + (s.in_portfolio ? ' · in your portfolio' : '')">
                      {{ s.symbol }}
                      <mat-icon *ngIf="s.in_portfolio" style="font-size:11px; height:11px; width:11px; vertical-align:middle;">warning</mat-icon>
                    </span>
                  </div>
                </div>
              </div>
            </mat-card-content>
          </mat-card>
        </div>
      </ng-container>
    </div>
  `,
})
export class MacroComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly dialog = inject(MatDialog);

  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly result = signal<MacroResult | null>(null);

  ngOnInit(): void {
    this.run(false);
  }

  run(refresh: boolean): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.macro(refresh).subscribe({
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

  research(symbol: string): void {
    this.api.analyze(symbol).subscribe({
      next: (rec) => {
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
      },
      error: (err) => this.error.set(err?.error?.detail ?? 'Could not research ' + symbol),
    });
  }
}
