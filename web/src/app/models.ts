export interface Holding {
  tradingsymbol: string;
  exchange: string;
  instrument_token: number;
  quantity: number;
  average_price: number;
  last_price: number;
  pnl: number;
  day_change_percentage: number;
  product: string;
}

export interface HoldingsResponse {
  source: 'kite' | 'csv' | 'none';
  uploaded_at: string | null;
  holdings: Holding[];
}

export interface AuthStatus {
  api_configured: boolean;
  authenticated: boolean;
  message: string;
}

export interface UploadResult {
  uploaded_at: string;
  count: number;
}

export interface Position {
  tradingsymbol: string;
  exchange: string;
  quantity: number;
  buy_price: number;
  sell_price: number;
  pnl: number;
  product: string;
  day_buy_quantity: number;
  day_sell_quantity: number;
}

export type RecommendationAction =
  | 'STRONG BUY'
  | 'BUY'
  | 'HOLD'
  | 'SELL'
  | 'STRONG SELL';

export interface NewsItem {
  headline: string;
  source: string;
  url: string;
  sentiment: 'positive' | 'negative' | 'neutral';
  score: number;
  published_at: string | null;
}

export interface TargetEntry {
  source: string;
  target: number;
  recommendation: string | null;
  as_of: string | null;
}

export interface ForecastBand {
  forecast: number | null;
  low: number | null;
  high: number | null;
  horizon_days: number;
  model_aic: number | null;
}

export interface MonteCarloBand {
  p5: number | null;
  p50: number | null;
  p95: number | null;
  horizon_days: number;
  sample_size: number | null;
}

export interface Recommendation {
  tradingsymbol: string;
  action: RecommendationAction;
  score: number;
  confidence: number;
  current_price: number;
  headline_reason: string;
  reasons: string[];
  technical_score: number;
  fundamental_score: number;
  news_score: number;
  news_items: NewsItem[];

  pe_ratio: number | null;
  debt_to_equity: number | null;
  roe: number | null;
  revenue_growth: number | null;
  market_cap: number | null;
  dividend_yield: number | null;
  fifty_two_week_high: number | null;
  fifty_two_week_low: number | null;

  atr: number | null;
  buy_upto: number | null;
  target_price_consensus: number | null;
  target_high: number | null;
  target_low: number | null;
  target_confidence: 'high' | 'medium' | 'low' | 'unknown';
  target_price_sources: TargetEntry[];
  stop_loss: number | null;

  analyst_count: number | null;
  analyst_recommendation: string | null;

  forecast_30d: ForecastBand | null;
  forecast_12m: MonteCarloBand | null;
  fundamental_sources: string[];
  risks: string[];
  business_summary: string | null;
  sector: string | null;
  industry: string | null;
  company_website: string | null;
  price_updated_at: string | null;
  price_source: string | null;
  promoter_holding: number | null;
  promoter_holding_change_qoq: number | null;
  promoter_holding_change_yoy: number | null;
  promoter_holding_history: number[];
  operating_margin_latest: number | null;
  operating_margin_history: number[];
  sales_cagr_5y: number | null;
  profit_cagr_5y: number | null;

  bulk_deals_30d: BulkDeal[];
  insider_trades_30d: InsiderTrade[];
  corporate_actions: CorporateAction[];
  recent_results: ResultRow[];
  upcoming_events: UpcomingEvent[];
  smart_money_sources: string[];

  one_year_return: number | null;
  three_year_return: number | null;
  five_year_return: number | null;
  annualized_volatility: number | null;
  max_drawdown_1y: number | null;
  sharpe_1y: number | null;
  beta_vs_nifty: number | null;

  theme_alignment: ThemeAlignment[];
}

export interface ThemeAlignment {
  theme: string;
  label: string;
  emoji: string;
  side: 'positive' | 'negative';
  article_count: number;
}

export interface MacroThemeStock {
  symbol: string;
  sector: string;
  name: string | null;
  in_portfolio: boolean;
}

export interface MacroThemeArticle {
  headline: string;
  source: string;
  url: string;
  published_at: string | null;
}

export interface MacroTheme {
  theme: string;
  label: string;
  emoji: string;
  source: 'rule_based' | 'gemini';
  score: number;
  article_count: number;
  matched_articles: MacroThemeArticle[];
  sectors_positive: string[];
  sectors_negative: string[];
  impacted_positive: MacroThemeStock[];
  impacted_negative: MacroThemeStock[];
  summary?: string;
  confidence?: string;
}

export interface MacroResult {
  themes: MacroTheme[];
  sources_used: string[];
  article_count: number;
  generated_at: string;
}

export interface BulkDeal {
  date: string;
  symbol: string;
  counterparty: string;
  side: string;
  qty: number;
  price: number;
  value: number;
  smart_money_tag: string | null;
  kind: string;
}

export interface InsiderTrade {
  date: string | null;
  person: string;
  person_role: string;
  side: string;
  qty: number | null;
  value: number | null;
}

export interface CorporateAction {
  subject: string;
  ex_date: string;
  purpose: string;
  record_date: string;
}

export interface ResultRow {
  period_to: string | null;
  period_from: string | null;
  revenue: number | null;
  net_profit: number | null;
  eps: number | null;
}

export interface UpcomingEvent {
  purpose: string;
  date: string;
  company: string | null;
}

export interface DiscoverShortlistItem {
  symbol: string;
  name: string | null;
  sector: string | null;
  industry: string | null;
  current_price: number;
  target_mean: number;
  upside_pct: number;
  rec_key: string;
  n_analysts: number;
  pos_in_range: number | null;
  hotness: number;
}

export interface SectorGroup {
  sector: string;
  count: number;
  picks: Recommendation[];
}

export interface DiscoverResult {
  scanned_at: string | null;
  universe: string;
  scanned_count: number;
  screened_count: number;
  picks: Recommendation[];
  sector_groups: SectorGroup[];
  shortlist: DiscoverShortlistItem[];
}
