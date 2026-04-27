import { CommonModule, DecimalPipe } from '@angular/common';
import {
  Component,
  Inject,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import {
  MAT_DIALOG_DATA,
  MatDialog,
  MatDialogModule,
  MatDialogRef,
} from '@angular/material/dialog';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { forkJoin } from 'rxjs';

import { ApiService } from '../api.service';
import {
  AuthStatus,
  Holding,
  Recommendation,
  RecommendationAction,
} from '../models';

interface Row extends Holding {
  rec?: Recommendation;
}

// Shared rendering helpers used by both the inline accordion body and the
// "Research any stock" dialog.
function actionClass(action: RecommendationAction): string {
  return 'action-' + action.toLowerCase().replace(' ', '-');
}

function pct(value: number | null, base: number): number {
  if (value === null || base === 0) return 0;
  return ((value - base) / base) * 100;
}

function formatCrore(v: number): string {
  if (v >= 1e7) {
    const cr = v / 1e7;
    if (cr >= 1e5) return (cr / 1e5).toFixed(2) + ' L Cr';
    return cr.toFixed(0) + ' Cr';
  }
  return v.toLocaleString('en-IN');
}

function trendArrow(history: number[]): string {
  if (history.length < 2) return '';
  const latest = history[history.length - 1];
  const five = history[Math.max(0, history.length - 5)];
  const delta = latest - five;
  if (delta >= 1) return `↑ +${delta.toFixed(0)}pp`;
  if (delta <= -1) return `↓ ${delta.toFixed(0)}pp`;
  return `→ flat`;
}

const ANALYSIS_TEMPLATE = `
  <p>
    <strong>Blended score:</strong> {{ r.score >= 0 ? '+' : '' }}{{ r.score | number:'1.3-3' }}
    &nbsp;·&nbsp; <strong>Confidence:</strong> {{ r.confidence | number:'1.0-1' }}%
  </p>
  <p class="muted" style="margin-top:-8px;">
    Tech {{ r.technical_score >= 0 ? '+' : '' }}{{ r.technical_score | number:'1.3-3' }}
    · Fund {{ r.fundamental_score >= 0 ? '+' : '' }}{{ r.fundamental_score | number:'1.3-3' }}
    · News {{ r.news_score >= 0 ? '+' : '' }}{{ r.news_score | number:'1.3-3' }}
    · sources: {{ r.fundamental_sources.join(', ') || 'none' }}
  </p>

  <h3 style="margin-top:24px; margin-bottom:8px;">Trade plan</h3>
  <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:12px;">
    <div style="padding:12px; border:1px solid #e0e0e0; border-radius:6px;">
      <div class="muted" style="font-size:11px; text-transform:uppercase; letter-spacing:0.4px;">Buy upto</div>
      <div style="font-size:22px; font-weight:500;" *ngIf="r.buy_upto !== null; else dashEntry">
        ₹ {{ r.buy_upto | number:'1.2-2' }}
        <span class="muted" style="font-size:12px; margin-left:4px;">
          ({{ pct(r.buy_upto, r.current_price) >= 0 ? '+' : '' }}{{ pct(r.buy_upto, r.current_price) | number:'1.1-1' }}%)
        </span>
      </div>
      <ng-template #dashEntry><span class="muted">—</span></ng-template>
      <div class="muted" style="font-size:11px; margin-top:4px;">Don't pay above this — 8% margin to consensus, max 5% over LTP.</div>
    </div>
    <div style="padding:12px; border:1px solid #e0e0e0; border-radius:6px;">
      <div class="muted" style="font-size:11px; text-transform:uppercase; letter-spacing:0.4px;">12m target (hold upto)</div>
      <div style="font-size:22px; font-weight:500;" *ngIf="r.target_price_consensus !== null; else dashEntry2">
        ₹ {{ r.target_price_consensus | number:'1.2-2' }}
        <span class="pos" style="font-size:12px; margin-left:4px;" *ngIf="r.target_price_consensus > r.current_price">
          +{{ pct(r.target_price_consensus, r.current_price) | number:'1.1-1' }}%
        </span>
      </div>
      <ng-template #dashEntry2><span class="muted">—</span></ng-template>
      <div class="muted" style="font-size:11px; margin-top:4px;">
        Consensus across {{ r.target_price_sources.length }} source(s). Confidence: {{ r.target_confidence }}.
      </div>
    </div>
    <div style="padding:12px; border:1px solid #e0e0e0; border-radius:6px;">
      <div class="muted" style="font-size:11px; text-transform:uppercase; letter-spacing:0.4px;">Stop loss</div>
      <div style="font-size:22px; font-weight:500;" *ngIf="r.stop_loss !== null; else dashEntry3">
        ₹ {{ r.stop_loss | number:'1.2-2' }}
        <span class="neg" style="font-size:12px; margin-left:4px;" *ngIf="r.stop_loss < r.current_price">
          {{ pct(r.stop_loss, r.current_price) | number:'1.1-1' }}%
        </span>
      </div>
      <ng-template #dashEntry3><span class="muted">—</span></ng-template>
      <div class="muted" style="font-size:11px; margin-top:4px;">2× ATR below LTP, never deeper than 5% above 52-week-low.</div>
    </div>
  </div>

  <ng-container *ngIf="r.target_price_sources.length > 0">
    <h3 style="margin-top:24px; margin-bottom:8px;">Price targets by source</h3>
    <table style="width:100%; border-collapse:collapse;">
      <tr *ngFor="let t of r.target_price_sources" style="border-bottom:1px solid #f0f0f0;">
        <td style="padding:6px 8px; font-weight:500;">{{ t.source }}</td>
        <td style="padding:6px 8px;" class="right">₹ {{ t.target | number:'1.2-2' }}</td>
        <td style="padding:6px 8px;" class="right">
          <span [class.pos]="t.target > r.current_price" [class.neg]="t.target < r.current_price">
            {{ pct(t.target, r.current_price) >= 0 ? '+' : '' }}{{ pct(t.target, r.current_price) | number:'1.1-1' }}%
          </span>
        </td>
        <td style="padding:6px 8px;" class="muted">{{ t.recommendation || '' }}</td>
      </tr>
    </table>
  </ng-container>

  <ng-container *ngIf="r.analyst_count">
    <h3 style="margin-top:24px; margin-bottom:8px;">Analyst consensus</h3>
    <p style="margin:4px 0;">
      <strong>{{ (r.analyst_recommendation || '').replace('_', ' ').toUpperCase() }}</strong>
      from <strong>{{ r.analyst_count }}</strong> analysts.
      Range: ₹ {{ r.target_low | number:'1.0-0' }} – ₹ {{ r.target_high | number:'1.0-0' }}.
    </p>
  </ng-container>

  <ng-container *ngIf="hasFundamentals(r)">
    <h3 style="margin-top:24px; margin-bottom:8px;">Fundamentals</h3>
    <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:8px;">
      <div *ngIf="r.pe_ratio !== null" style="padding:8px; background:#fafafa; border-radius:4px;">
        <div class="muted" style="font-size:11px;">P/E</div>
        <div style="font-size:18px; font-weight:500;">{{ r.pe_ratio | number:'1.1-1' }}</div>
      </div>
      <div *ngIf="r.roe !== null" style="padding:8px; background:#fafafa; border-radius:4px;">
        <div class="muted" style="font-size:11px;">ROE</div>
        <div style="font-size:18px; font-weight:500;">{{ r.roe | number:'1.1-1' }}%</div>
      </div>
      <div *ngIf="r.debt_to_equity !== null" style="padding:8px; background:#fafafa; border-radius:4px;">
        <div class="muted" style="font-size:11px;">D/E</div>
        <div style="font-size:18px; font-weight:500;">{{ r.debt_to_equity | number:'1.2-2' }}</div>
      </div>
      <div *ngIf="r.dividend_yield !== null" style="padding:8px; background:#fafafa; border-radius:4px;">
        <div class="muted" style="font-size:11px;">Div Yield</div>
        <div style="font-size:18px; font-weight:500;">{{ r.dividend_yield | number:'1.2-2' }}%</div>
      </div>
      <div *ngIf="r.market_cap !== null" style="padding:8px; background:#fafafa; border-radius:4px;">
        <div class="muted" style="font-size:11px;">Market cap</div>
        <div style="font-size:18px; font-weight:500;">₹ {{ formatCrore(r.market_cap) }}</div>
      </div>
      <div *ngIf="r.fifty_two_week_high !== null && r.fifty_two_week_low !== null" style="padding:8px; background:#fafafa; border-radius:4px;">
        <div class="muted" style="font-size:11px;">52-week range</div>
        <div style="font-size:14px; font-weight:500;">
          ₹ {{ r.fifty_two_week_low | number:'1.0-0' }} – ₹ {{ r.fifty_two_week_high | number:'1.0-0' }}
        </div>
      </div>
      <div *ngIf="r.promoter_holding !== null" style="padding:8px; background:#fafafa; border-radius:4px;">
        <div class="muted" style="font-size:11px;">Promoter holding</div>
        <div style="font-size:18px; font-weight:500;">
          {{ r.promoter_holding | number:'1.1-1' }}%
          <span *ngIf="r.promoter_holding_change_qoq !== null"
                style="font-size:11px;"
                [class.pos]="r.promoter_holding_change_qoq > 0"
                [class.neg]="r.promoter_holding_change_qoq < 0">
            ({{ r.promoter_holding_change_qoq >= 0 ? '+' : ''
            }}{{ r.promoter_holding_change_qoq | number:'1.2-2' }} pp QoQ)
          </span>
        </div>
      </div>
      <div *ngIf="r.operating_margin_latest !== null" style="padding:8px; background:#fafafa; border-radius:4px;">
        <div class="muted" style="font-size:11px;">Operating margin</div>
        <div style="font-size:18px; font-weight:500;">
          {{ r.operating_margin_latest | number:'1.0-0' }}%
          <span *ngIf="r.operating_margin_history.length >= 5" class="muted" style="font-size:11px;">
            · {{ trendArrow(r.operating_margin_history) }} vs 5y
          </span>
        </div>
      </div>
      <div *ngIf="r.sales_cagr_5y !== null" style="padding:8px; background:#fafafa; border-radius:4px;">
        <div class="muted" style="font-size:11px;">Sales 5y CAGR</div>
        <div style="font-size:18px; font-weight:500;">{{ r.sales_cagr_5y | number:'1.0-0' }}%</div>
      </div>
      <div *ngIf="r.profit_cagr_5y !== null" style="padding:8px; background:#fafafa; border-radius:4px;">
        <div class="muted" style="font-size:11px;">Profit 5y CAGR</div>
        <div style="font-size:18px; font-weight:500;">{{ r.profit_cagr_5y | number:'1.0-0' }}%</div>
      </div>
    </div>
  </ng-container>

  <h3 style="margin-top:24px; margin-bottom:8px;">Why to buy / hold</h3>
  <ul class="reasons-list">
    <li *ngFor="let reason of r.reasons">{{ reason }}</li>
    <li *ngIf="r.reasons.length === 0" class="muted">No specific bullish signal.</li>
  </ul>

  <ng-container *ngIf="r.risks?.length">
    <h3 style="margin-top:24px; margin-bottom:8px;">Why to sell / what could go wrong</h3>
    <div style="background:#ffebee; border-left:3px solid #c62828; padding:8px 12px; margin-bottom:8px; font-size:12px;">
      <strong>Honest risks for this position:</strong>
    </div>
    <ul class="reasons-list">
      <li *ngFor="let risk of r.risks">{{ risk }}</li>
    </ul>
  </ng-container>

  <ng-container *ngIf="r.theme_alignment?.length">
    <h3 style="margin-top:24px; margin-bottom:8px;">Macro themes affecting this stock</h3>
    <div style="display:flex; flex-wrap:wrap; gap:6px;">
      <span *ngFor="let ta of r.theme_alignment"
            class="action-chip"
            [style.background]="ta.side === 'positive' ? '#2e7d32' : '#c62828'">
        {{ ta.emoji }} {{ ta.label }} · {{ ta.side === 'positive' ? 'tailwind' : 'headwind' }}
      </span>
    </div>
  </ng-container>

  <ng-container *ngIf="r.bulk_deals_30d?.length || r.insider_trades_30d?.length">
    <h3 style="margin-top:24px; margin-bottom:8px;">Institutional activity (30d)</h3>
    <p class="muted" style="font-size:11px; margin-top:0;">
      Source: NSE bulk + block deals (single trades &gt;0.5% of equity) + BSE insider disclosures.
      "Smart money" tag = recognized FII/MF/insurer name.
    </p>
    <table style="width:100%; border-collapse:collapse;" *ngIf="r.bulk_deals_30d?.length">
      <thead>
        <tr style="background:#fafafa;">
          <th style="padding:6px 8px; text-align:left;">Date</th>
          <th style="padding:6px 8px; text-align:left;">Counterparty</th>
          <th style="padding:6px 8px; text-align:center;">Side</th>
          <th style="padding:6px 8px; text-align:right;">Qty</th>
          <th style="padding:6px 8px; text-align:right;">Value</th>
        </tr>
      </thead>
      <tr *ngFor="let d of r.bulk_deals_30d.slice(0, 10)" style="border-bottom:1px solid #f0f0f0;">
        <td style="padding:6px 8px; font-size:12px;">{{ d.date }}</td>
        <td style="padding:6px 8px;">
          {{ d.counterparty }}
          <span *ngIf="d.smart_money_tag" class="action-chip" style="background:#1565c0; font-size:10px; margin-left:6px;">{{ d.smart_money_tag }}</span>
        </td>
        <td style="padding:6px 8px; text-align:center;" [class.pos]="d.side === 'BUY'" [class.neg]="d.side === 'SELL'">{{ d.side }}</td>
        <td style="padding:6px 8px; text-align:right;">{{ d.qty | number }}</td>
        <td style="padding:6px 8px; text-align:right;">₹{{ d.value / 1e7 | number:'1.2-2' }} Cr</td>
      </tr>
    </table>
    <table style="width:100%; border-collapse:collapse; margin-top:8px;" *ngIf="r.insider_trades_30d?.length">
      <thead>
        <tr style="background:#fff3e0;">
          <th style="padding:6px 8px; text-align:left;" colspan="5">Insider trades</th>
        </tr>
      </thead>
      <tr *ngFor="let t of r.insider_trades_30d.slice(0, 5)" style="border-bottom:1px solid #f0f0f0;">
        <td style="padding:6px 8px; font-size:12px;">{{ t.date }}</td>
        <td style="padding:6px 8px;">{{ t.person }} <span class="muted">({{ t.person_role }})</span></td>
        <td style="padding:6px 8px; text-align:center;" [class.pos]="t.side?.toUpperCase()?.startsWith('BUY')" [class.neg]="t.side?.toUpperCase()?.startsWith('SELL')">{{ t.side }}</td>
        <td style="padding:6px 8px; text-align:right;">{{ t.qty | number }}</td>
        <td style="padding:6px 8px; text-align:right;" *ngIf="t.value">₹{{ t.value / 1e5 | number:'1.0-0' }} L</td>
      </tr>
    </table>
  </ng-container>

  <ng-container *ngIf="r.upcoming_events?.length || r.corporate_actions?.length">
    <h3 style="margin-top:24px; margin-bottom:8px;">Events</h3>
    <div *ngIf="r.upcoming_events?.length" style="margin-bottom:8px;">
      <strong>Upcoming:</strong>
      <ul class="reasons-list" style="margin-top:4px;">
        <li *ngFor="let e of r.upcoming_events.slice(0, 5)">{{ e.purpose }} — {{ e.date }}</li>
      </ul>
    </div>
    <div *ngIf="r.corporate_actions?.length">
      <strong>Recent corporate actions:</strong>
      <ul class="reasons-list" style="margin-top:4px;">
        <li *ngFor="let ca of r.corporate_actions.slice(0, 5)">{{ ca.subject }} (ex {{ ca.ex_date }})</li>
      </ul>
    </div>
  </ng-container>

  <ng-container *ngIf="hasHistorical(r)">
    <h3 style="margin-top:24px; margin-bottom:8px;">Historical performance</h3>
    <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap:8px;">
      <div *ngIf="r.one_year_return !== null" style="padding:8px; background:#fafafa; border-radius:4px;">
        <div class="muted" style="font-size:11px;">1Y return</div>
        <div style="font-size:18px; font-weight:500;" [class.pos]="r.one_year_return >= 0" [class.neg]="r.one_year_return < 0">
          {{ r.one_year_return >= 0 ? '+' : '' }}{{ r.one_year_return | number:'1.1-1' }}%
        </div>
      </div>
      <div *ngIf="r.three_year_return !== null" style="padding:8px; background:#fafafa; border-radius:4px;">
        <div class="muted" style="font-size:11px;">3Y CAGR</div>
        <div style="font-size:18px; font-weight:500;" [class.pos]="r.three_year_return >= 0" [class.neg]="r.three_year_return < 0">
          {{ r.three_year_return >= 0 ? '+' : '' }}{{ r.three_year_return | number:'1.1-1' }}%
        </div>
      </div>
      <div *ngIf="r.five_year_return !== null" style="padding:8px; background:#fafafa; border-radius:4px;">
        <div class="muted" style="font-size:11px;">5Y CAGR</div>
        <div style="font-size:18px; font-weight:500;" [class.pos]="r.five_year_return >= 0" [class.neg]="r.five_year_return < 0">
          {{ r.five_year_return >= 0 ? '+' : '' }}{{ r.five_year_return | number:'1.1-1' }}%
        </div>
      </div>
      <div *ngIf="r.annualized_volatility !== null" style="padding:8px; background:#fafafa; border-radius:4px;">
        <div class="muted" style="font-size:11px;">Ann. volatility</div>
        <div style="font-size:18px; font-weight:500;">{{ r.annualized_volatility | number:'1.1-1' }}%</div>
      </div>
      <div *ngIf="r.max_drawdown_1y !== null" style="padding:8px; background:#fafafa; border-radius:4px;">
        <div class="muted" style="font-size:11px;">Max 1Y drawdown</div>
        <div style="font-size:18px; font-weight:500;" class="neg">{{ r.max_drawdown_1y | number:'1.1-1' }}%</div>
      </div>
      <div *ngIf="r.sharpe_1y !== null" style="padding:8px; background:#fafafa; border-radius:4px;">
        <div class="muted" style="font-size:11px;">Sharpe (1Y)</div>
        <div style="font-size:18px; font-weight:500;" [class.pos]="r.sharpe_1y >= 1" [class.neg]="r.sharpe_1y < 0">
          {{ r.sharpe_1y | number:'1.2-2' }}
        </div>
      </div>
      <div *ngIf="r.beta_vs_nifty !== null" style="padding:8px; background:#fafafa; border-radius:4px;">
        <div class="muted" style="font-size:11px;">Beta vs NIFTY</div>
        <div style="font-size:18px; font-weight:500;">{{ r.beta_vs_nifty | number:'1.2-2' }}</div>
      </div>
    </div>
  </ng-container>

  <ng-container *ngIf="r.business_summary || r.sector">
    <h3 style="margin-top:24px; margin-bottom:8px;">About {{ r.tradingsymbol }}</h3>
    <div class="muted" style="font-size:12px; margin-bottom:6px;">
      <span *ngIf="r.sector">{{ r.sector }}</span>
      <span *ngIf="r.industry"> · {{ r.industry }}</span>
      <span *ngIf="r.company_website">
        ·
        <a [href]="r.company_website" target="_blank" rel="noopener">{{ r.company_website }}</a>
      </span>
    </div>
    <p style="margin:0; font-size:14px;">{{ r.business_summary }}</p>
  </ng-container>

  <h3 style="margin-top:24px; margin-bottom:8px;">News</h3>
  <ul class="reasons-list" *ngIf="r.news_items.length > 0; else noNews">
    <li *ngFor="let n of r.news_items">
      <a [href]="n.url" target="_blank" rel="noopener">[{{ n.source }}] {{ n.headline }}</a>
      <span class="muted" style="margin-left:6px;" *ngIf="n.sentiment !== 'neutral'">
        · {{ n.sentiment }}
      </span>
    </li>
  </ul>
  <ng-template #noNews>
    <p class="muted">No news headlines found for this symbol.</p>
  </ng-template>

  <h3 style="margin-top:24px; margin-bottom:8px;">Historical-pattern forecasts</h3>
  <div style="background:#fff8e1; border-left:3px solid #f9a825; padding:8px 12px; margin-bottom:12px; font-size:12px;">
    <strong>Heads up:</strong> these are statistical projections from past prices, not predictions.
    12-month bands are deliberately wide because long-horizon forecasts are unreliable.
    Use as scenarios, not numbers to act on.
  </div>
  <div *ngIf="r.forecast_30d as f30">
    <strong>Next 30 days (ARIMA):</strong>
    ₹ {{ f30.forecast | number:'1.2-2' }}
    <span class="muted">(80% CI: ₹ {{ f30.low | number:'1.2-2' }} – ₹ {{ f30.high | number:'1.2-2' }})</span>
  </div>
  <div *ngIf="r.forecast_12m as f12" style="margin-top:6px;">
    <strong>Next 12 months (Monte Carlo):</strong>
    ₹ {{ f12.p50 | number:'1.0-0' }} median
    <span class="muted">(90% range: ₹ {{ f12.p5 | number:'1.0-0' }} – ₹ {{ f12.p95 | number:'1.0-0' }})</span>
  </div>
  <div *ngIf="!r.forecast_30d && !r.forecast_12m" class="muted">Insufficient history for forecast.</div>
`;

@Component({
  selector: 'app-stock-detail-dialog',
  standalone: true,
  imports: [CommonModule, DecimalPipe, MatDialogModule, MatButtonModule, MatIconModule],
  template: `
    <h2 mat-dialog-title>
      {{ data.row.tradingsymbol }}
      <span *ngIf="data.row.rec as r" class="action-chip" [class]="actionClass(r.action)" style="margin-left: 12px;">
        {{ r.action }}
      </span>
      <span *ngIf="data.row.rec as r" class="muted" style="margin-left:8px; font-size:14px;">
        ₹ {{ r.current_price | number:'1.2-2' }}
      </span>
    </h2>
    <mat-dialog-content>
      <ng-container *ngIf="data.row.rec as r">
        ${ANALYSIS_TEMPLATE}
      </ng-container>
      <p *ngIf="!data.row.rec" class="muted">No recommendation available.</p>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Close</button>
    </mat-dialog-actions>
  `,
})
export class StockDetailDialogComponent {
  constructor(
    public dialogRef: MatDialogRef<StockDetailDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: { row: Row }
  ) {}

  readonly actionClass = actionClass;
  readonly pct = pct;
  readonly formatCrore = formatCrore;
  readonly trendArrow = trendArrow;

  hasFundamentals(r: Recommendation): boolean {
    return (
      r.pe_ratio !== null ||
      r.roe !== null ||
      r.debt_to_equity !== null ||
      r.dividend_yield !== null ||
      r.market_cap !== null ||
      r.promoter_holding !== null ||
      r.operating_margin_latest !== null ||
      r.sales_cagr_5y !== null ||
      r.profit_cagr_5y !== null
    );
  }

  hasHistorical(r: Recommendation): boolean {
    return (
      r.one_year_return !== null ||
      r.three_year_return !== null ||
      r.five_year_return !== null ||
      r.annualized_volatility !== null ||
      r.sharpe_1y !== null ||
      r.beta_vs_nifty !== null
    );
  }
}

@Component({
  selector: 'app-portfolio',
  standalone: true,
  imports: [
    CommonModule,
    DecimalPipe,
    MatProgressBarModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatSnackBarModule,
    MatChipsModule,
    MatTooltipModule,
    MatDialogModule,
    MatExpansionModule,
  ],
  template: `
    <div class="page">
      <div style="display:flex; align-items:center; gap:12px; margin-bottom:16px; flex-wrap:wrap;">
        <h1 class="page-title">Portfolio</h1>

        <span *ngIf="source() === 'kite'"
              class="action-chip"
              style="background:#1565c0;">
          <mat-icon style="font-size:14px; height:14px; width:14px; vertical-align:middle;">cloud_done</mat-icon>
          Live · Zerodha
        </span>

        <span class="toolbar-spacer"></span>

        <input
          #searchInput
          type="text"
          placeholder="Research any stock (e.g. INFY)"
          (keydown.enter)="researchSymbol(searchInput.value); searchInput.value = ''"
          [disabled]="researching()"
          style="padding:6px 10px; border:1px solid #ccc; border-radius:4px; width:240px;"
        />
        <button mat-stroked-button color="primary" (click)="reload()" [disabled]="loading()">
          <mat-icon>refresh</mat-icon> Refresh
        </button>
        <button mat-stroked-button *ngIf="auth()?.authenticated" (click)="logout()">
          <mat-icon>logout</mat-icon> Disconnect
        </button>
      </div>

      <mat-progress-bar *ngIf="loading()" mode="indeterminate"></mat-progress-bar>
      <p *ngIf="loading()" class="muted" style="margin-top:8px;">
        Crunching technical signals + Indian financial news for each holding…
      </p>

      <div class="error-banner" *ngIf="error() as err">
        <strong>Error.</strong> {{ err }}
      </div>

      <ng-container *ngIf="!loading() && !error()">
        <!-- Empty / not-connected state -->
        <mat-card *ngIf="rows().length === 0">
          <mat-card-content style="padding: 24px;">
            <h2 style="margin-top:0;">Connect your Zerodha account</h2>
            <ng-container *ngIf="auth() as a">
              <p class="muted" style="margin-top:0;">
                Status: <strong>{{ a.message }}</strong>
              </p>
              <p *ngIf="a.api_configured && !a.authenticated">
                Run this in a terminal to log in (one tap per Zerodha trading day):
              </p>
              <pre *ngIf="a.api_configured && !a.authenticated"
                   style="background:#eee; padding:12px; border-radius:4px;"><code>uv run stock-app auth --manual</code></pre>
              <p *ngIf="!a.api_configured" class="muted">
                Add <code>KITE_API_KEY</code> and <code>KITE_API_SECRET</code> to <code>.env</code> (see README) and restart the API.
              </p>
            </ng-container>
          </mat-card-content>
        </mat-card>

        <ng-container *ngIf="rows().length > 0">
          <div class="summary-cards">
            <mat-card class="summary-card">
              <mat-card-content>
                <div class="label">Holdings</div>
                <div class="value">{{ rows().length }}</div>
              </mat-card-content>
            </mat-card>
            <mat-card class="summary-card">
              <mat-card-content>
                <div class="label">Total P&amp;L</div>
                <div class="value" [class.pos]="totalPnl() >= 0" [class.neg]="totalPnl() < 0">
                  {{ totalPnl() >= 0 ? '+' : '' }}₹ {{ totalPnl() | number:'1.0-0' }}
                  <span class="muted" style="font-size:14px; margin-left:8px;">
                    ({{ pnlPercent() | number:'1.2-2' }}%)
                  </span>
                </div>
              </mat-card-content>
            </mat-card>
            <mat-card class="summary-card">
              <mat-card-content>
                <div class="label">Buy signals</div>
                <div class="value pos">{{ buyCount() }}</div>
              </mat-card-content>
            </mat-card>
            <mat-card class="summary-card">
              <mat-card-content>
                <div class="label">Hold</div>
                <div class="value">{{ holdCount() }}</div>
              </mat-card-content>
            </mat-card>
            <mat-card class="summary-card">
              <mat-card-content>
                <div class="label">Sell signals</div>
                <div class="value neg">{{ sellCount() }}</div>
              </mat-card-content>
            </mat-card>
          </div>

          <p class="muted" style="margin: 0 0 8px 0;">
            Click any holding to expand the full analysis (why to buy, why to sell, target price).
            Sorted: <strong>Strong Buy → Buy → Hold → Sell → Strong Sell</strong>.
          </p>

          <mat-accordion>
            <mat-expansion-panel *ngFor="let h of rows(); trackBy: trackBySymbol">
              <mat-expansion-panel-header style="height:auto; padding:8px 16px;">
                <mat-panel-title style="flex: 0 1 38%; align-items:center; gap:10px;">
                  <span *ngIf="h.rec as r" class="action-chip" [class]="actionClass(r.action)">
                    {{ r.action }}
                  </span>
                  <span *ngIf="!h.rec" class="muted">—</span>
                  <strong>{{ h.tradingsymbol }}</strong>
                  <span class="muted" style="font-size:12px;">{{ h.quantity }} qty</span>
                </mat-panel-title>
                <mat-panel-description style="flex-wrap:wrap; gap:14px;">
                  <span>LTP: <strong>₹{{ h.last_price | number:'1.2-2' }}</strong></span>
                  <span [class.pos]="h.day_change_percentage >= 0" [class.neg]="h.day_change_percentage < 0">
                    {{ h.day_change_percentage >= 0 ? '+' : '' }}{{ h.day_change_percentage | number:'1.2-2' }}%
                  </span>
                  <span [class.pos]="h.pnl >= 0" [class.neg]="h.pnl < 0">
                    P&amp;L {{ h.pnl >= 0 ? '+' : '' }}₹{{ h.pnl | number:'1.0-0' }}
                  </span>
                  <span *ngIf="h.rec?.target_price_consensus as tp" class="muted">
                    target ₹{{ tp | number:'1.0-0' }}
                    <span class="pos" *ngIf="tp > h.last_price">
                      (+{{ targetUpsidePct(h.rec!) | number:'1.0-0' }}%)
                    </span>
                  </span>
                </mat-panel-description>
              </mat-expansion-panel-header>

              <ng-container *ngIf="h.rec as r">
                ${ANALYSIS_TEMPLATE}
              </ng-container>
              <p *ngIf="!h.rec" class="muted">Analysis unavailable for this stock.</p>
            </mat-expansion-panel>
          </mat-accordion>
        </ng-container>
      </ng-container>
    </div>
  `,
})
export class PortfolioComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly snack = inject(MatSnackBar);
  private readonly dialog = inject(MatDialog);

  readonly loading = signal(false);
  readonly researching = signal(false);
  readonly error = signal<string | null>(null);
  readonly rows = signal<Row[]>([]);
  readonly source = signal<'kite' | 'csv' | 'none'>('none');
  readonly auth = signal<AuthStatus | null>(null);

  readonly invested = computed(() =>
    this.rows().reduce((s, h) => s + h.average_price * h.quantity, 0)
  );
  readonly current = computed(() =>
    this.rows().reduce((s, h) => s + h.last_price * h.quantity, 0)
  );
  readonly totalPnl = computed(() => this.rows().reduce((s, h) => s + h.pnl, 0));
  readonly pnlPercent = computed(() => {
    const inv = this.invested();
    return inv > 0 ? (this.totalPnl() / inv) * 100 : 0;
  });
  readonly buyCount = computed(() =>
    this.rows().filter((r) => r.rec?.action === 'BUY' || r.rec?.action === 'STRONG BUY').length
  );
  readonly holdCount = computed(() => this.rows().filter((r) => r.rec?.action === 'HOLD').length);
  readonly sellCount = computed(() =>
    this.rows().filter((r) => r.rec?.action === 'SELL' || r.rec?.action === 'STRONG SELL').length
  );

  readonly actionClass = actionClass;
  readonly pct = pct;
  readonly formatCrore = formatCrore;
  readonly trendArrow = trendArrow;

  ngOnInit(): void {
    this.reload();
  }

  reload(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.authStatus().subscribe({
      next: (a) => this.auth.set(a),
      error: () => this.auth.set(null),
    });
    forkJoin({
      holdings: this.api.holdings(),
      recommendations: this.api.recommendations(),
    }).subscribe({
      next: ({ holdings, recommendations }) => {
        this.source.set(holdings.source);
        const recBySymbol = new Map(recommendations.map((r) => [r.tradingsymbol, r]));
        const merged = holdings.holdings.map((h) => ({
          ...h,
          rec: recBySymbol.get(h.tradingsymbol),
        }));
        const order: Record<string, number> = {
          'STRONG BUY': 0, BUY: 1, HOLD: 2, SELL: 3, 'STRONG SELL': 4,
        };
        merged.sort((a, b) => {
          const oa = a.rec ? order[a.rec.action] ?? 2 : 99;
          const ob = b.rec ? order[b.rec.action] ?? 2 : 99;
          if (oa !== ob) return oa - ob;
          // Within same action, higher target upside first
          const ua = a.rec?.target_price_consensus
            ? a.rec.target_price_consensus / Math.max(a.last_price, 1)
            : 0;
          const ub = b.rec?.target_price_consensus
            ? b.rec.target_price_consensus / Math.max(b.last_price, 1)
            : 0;
          return ub - ua;
        });
        this.rows.set(merged);
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(err?.error?.detail ?? err?.message ?? 'Unknown error');
        this.loading.set(false);
      },
    });
  }

  logout(): void {
    this.api.logout().subscribe(() => {
      this.snack.open('Disconnected from Zerodha', 'Dismiss', { duration: 3000 });
      this.reload();
    });
  }

  researchSymbol(symbol: string): void {
    const sym = symbol.trim().toUpperCase();
    if (!sym) return;
    this.researching.set(true);
    this.snack.open(`Researching ${sym} (~30s for first run)…`, undefined, { duration: 3000 });
    this.api.analyze(sym).subscribe({
      next: (rec) => {
        const row: Row = {
          tradingsymbol: sym,
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
        this.dialog.open(StockDetailDialogComponent, {
          data: { row },
          width: '720px',
          maxWidth: '95vw',
        });
        this.researching.set(false);
      },
      error: (err) => {
        const msg = err?.error?.detail ?? err?.message ?? 'Research failed';
        this.snack.open(`Could not research ${sym}: ${msg}`, 'Dismiss', { duration: 6000 });
        this.researching.set(false);
      },
    });
  }

  hasFundamentals(r: Recommendation): boolean {
    return (
      r.pe_ratio !== null ||
      r.roe !== null ||
      r.debt_to_equity !== null ||
      r.dividend_yield !== null ||
      r.market_cap !== null ||
      r.promoter_holding !== null ||
      r.operating_margin_latest !== null ||
      r.sales_cagr_5y !== null ||
      r.profit_cagr_5y !== null
    );
  }

  hasHistorical(r: Recommendation): boolean {
    return (
      r.one_year_return !== null ||
      r.three_year_return !== null ||
      r.five_year_return !== null ||
      r.annualized_volatility !== null ||
      r.sharpe_1y !== null ||
      r.beta_vs_nifty !== null
    );
  }

  targetUpsidePct(r: Recommendation): number {
    if (r.target_price_consensus === null || r.current_price === 0) return 0;
    return ((r.target_price_consensus - r.current_price) / r.current_price) * 100;
  }

  trackBySymbol(_: number, row: Row): string {
    return row.tradingsymbol;
  }
}
