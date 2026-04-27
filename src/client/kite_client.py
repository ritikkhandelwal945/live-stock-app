import time
from datetime import date, timedelta

import pandas as pd
from kiteconnect import KiteConnect

from src.auth.kite_auth import get_authenticated_kite
from src.client.models import Holding, Position, StockQuote
from src.data.http import patch_session


def _patch_session(kite: KiteConnect) -> None:
    patch_session(kite.reqsession)


class KiteClient:
    def __init__(self, kite: KiteConnect | None = None):
        self._kite = kite or get_authenticated_kite()
        _patch_session(self._kite)
        self._instruments_cache: pd.DataFrame | None = None
        self._last_historical_call: float = 0

    @property
    def kite(self) -> KiteConnect:
        return self._kite

    def get_holdings(self) -> list[Holding]:
        raw = self._kite.holdings()
        holdings = []
        for h in raw:
            holdings.append(Holding(
                tradingsymbol=h["tradingsymbol"],
                exchange=h.get("exchange", "NSE"),
                instrument_token=h.get("instrument_token", 0),
                quantity=h.get("quantity", 0),
                average_price=h.get("average_price", 0.0),
                last_price=h.get("last_price", 0.0),
                pnl=h.get("pnl", 0.0),
                day_change_percentage=h.get("day_change_percentage", 0.0),
                product=h.get("product", ""),
            ))
        return holdings

    def get_positions(self) -> list[Position]:
        raw = self._kite.positions()
        positions = []
        for p in raw.get("net", []):
            positions.append(Position(
                tradingsymbol=p["tradingsymbol"],
                exchange=p.get("exchange", "NSE"),
                quantity=p.get("quantity", 0),
                buy_price=p.get("buy_price", 0.0),
                sell_price=p.get("sell_price", 0.0),
                pnl=p.get("pnl", 0.0),
                product=p.get("product", ""),
                day_buy_quantity=p.get("day_buy_quantity", 0),
                day_sell_quantity=p.get("day_sell_quantity", 0),
            ))
        return positions

    def get_orders(self) -> list[dict]:
        return self._kite.orders()

    def get_instruments(self, exchange: str = "NSE") -> pd.DataFrame:
        if self._instruments_cache is None:
            raw = self._kite.instruments(exchange)
            self._instruments_cache = pd.DataFrame(raw)
        return self._instruments_cache

    def symbol_to_token(self, symbol: str, exchange: str = "NSE") -> int:
        instruments = self.get_instruments(exchange)
        match = instruments[instruments["tradingsymbol"] == symbol]
        if match.empty:
            raise ValueError(f"Instrument not found: {symbol} on {exchange}")
        return int(match.iloc[0]["instrument_token"])

    def get_quote(self, symbols: list[str], exchange: str = "NSE") -> dict[str, StockQuote]:
        keys = [f"{exchange}:{s}" for s in symbols]
        raw = self._kite.quote(keys)
        quotes = {}
        for key, data in raw.items():
            symbol = key.split(":")[1]
            ohlc = data.get("ohlc", {})
            quotes[symbol] = StockQuote(
                tradingsymbol=symbol,
                last_price=data.get("last_price", 0.0),
                open=ohlc.get("open", 0.0),
                high=ohlc.get("high", 0.0),
                low=ohlc.get("low", 0.0),
                close=ohlc.get("close", 0.0),
                volume=data.get("volume", 0),
                lower_circuit_limit=data.get("lower_circuit_limit", 0.0),
                upper_circuit_limit=data.get("upper_circuit_limit", 0.0),
                net_change=data.get("net_change", 0.0),
            )
        return quotes

    def get_historical_data(
        self,
        symbol: str,
        days: int = 365,
        interval: str = "day",
        exchange: str = "NSE",
    ) -> pd.DataFrame:
        # Rate limit: max 3 requests/second
        elapsed = time.time() - self._last_historical_call
        if elapsed < 0.35:
            time.sleep(0.35 - elapsed)

        token = self.symbol_to_token(symbol, exchange)
        to_date = date.today()
        from_date = to_date - timedelta(days=days)

        raw = self._kite.historical_data(
            instrument_token=token,
            from_date=from_date,
            to_date=to_date,
            interval=interval,
        )
        self._last_historical_call = time.time()

        df = pd.DataFrame(raw)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
        return df
