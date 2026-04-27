import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { AuthStatus, DiscoverResult, HoldingsResponse, Position, Recommendation, UploadResult } from './models';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api';

  health(): Observable<{ status: string; authenticated: boolean; error?: string }> {
    return this.http.get<{ status: string; authenticated: boolean; error?: string }>(
      `${this.base}/health`
    );
  }

  authStatus(): Observable<AuthStatus> {
    return this.http.get<AuthStatus>(`${this.base}/auth/status`);
  }

  logout(): Observable<unknown> {
    return this.http.post(`${this.base}/auth/logout`, {});
  }

  holdings(): Observable<HoldingsResponse> {
    return this.http.get<HoldingsResponse>(`${this.base}/holdings`);
  }

  uploadHoldings(file: File): Observable<UploadResult> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<UploadResult>(`${this.base}/holdings/upload`, form);
  }

  clearHoldings(): Observable<unknown> {
    return this.http.delete(`${this.base}/holdings`);
  }

  positions(): Observable<Position[]> {
    return this.http.get<Position[]>(`${this.base}/positions`);
  }

  recommendations(days = 365): Observable<Recommendation[]> {
    return this.http.get<Recommendation[]>(`${this.base}/recommendations`, {
      params: { days },
    });
  }

  analyze(symbol: string): Observable<Recommendation> {
    return this.http.get<Recommendation>(`${this.base}/analyze/${encodeURIComponent(symbol)}`);
  }

  discover(universe = 'NIFTY500', top = 20, refresh = false): Observable<DiscoverResult> {
    return this.http.get<DiscoverResult>(`${this.base}/discover`, {
      params: { universe, top, refresh: String(refresh) },
    });
  }

  universes(): Observable<{ groups: { label: string; indices: string[] }[] }> {
    return this.http.get<{ groups: { label: string; indices: string[] }[] }>(`${this.base}/universes`);
  }
}
