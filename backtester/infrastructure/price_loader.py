# backtester/infrastructure/price_loader.py
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List
import os
import requests
import pandas as pd

from ..domain.models import Candle  # ← ВАЖНО!

class PriceLoader(ABC):
    @abstractmethod
    def load_prices(
        self,
        contract_address: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Candle]:
        raise NotImplementedError


class CsvPriceLoader(PriceLoader):
    def __init__(self, candles_dir: str, timeframe: str = "1m"):
        self.candles_dir = Path(candles_dir)
        self.timeframe = timeframe

    def _build_path(self, contract_address: str) -> Path:
        filename = f"{contract_address}_{self.timeframe}.csv"
        return self.candles_dir / filename

    def load_prices(self, contract_address: str, start_time=None, end_time=None) -> List[Candle]:
        path = self._build_path(contract_address)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {path}")
        df = pd.read_csv(path)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp")

        if start_time is not None:
            df = df[df["timestamp"] >= start_time]
        if end_time is not None:
            df = df[df["timestamp"] <= end_time]

        return [
            Candle(
                timestamp=row.timestamp.to_pydatetime(),
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
            ) for row in df.itertuples(index=False)
        ]


class GeckoTerminalPriceLoader(PriceLoader):
    def __init__(self, cache_dir: str = "data/candles/cached", timeframe: str = "1m"):
        self.cache_dir = Path(cache_dir)
        self.timeframe = timeframe

    def _get_cache_path(self, contract_address: str) -> Path:
        return self.cache_dir / f"{contract_address}_{self.timeframe}.csv"

    def _load_from_cache(self, contract_address: str) -> Optional[List[Candle]]:
        path = self._get_cache_path(contract_address)
        if not path.exists():
            return None
        try:
            df = pd.read_csv(path)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            return [
                Candle(
                    timestamp=row.timestamp.to_pydatetime(),
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    volume=row.volume,
                ) for row in df.itertuples(index=False)
            ]
        except Exception as e:
            print(f"⚠️ Failed to load cache from {path}: {e}")
            return None

    def _save_to_cache(self, contract_address: str, candles: List[Candle]):
        path = self._get_cache_path(contract_address)
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            df = pd.DataFrame([{
                "timestamp": c.timestamp.isoformat(),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            } for c in candles])
            df.to_csv(path, index=False)
            print(f"📥 Saved {len(candles)} candles to cache: {path}")
        except Exception as e:
            print(f"⚠️ Failed to save cache: {e}")

    def _fetch_from_api(self, contract_address: str) -> List[Candle]:
        headers = {"User-Agent": "Mozilla/5.0 GeckoLoader"}
        try:
            pools_url = f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{contract_address}/pools"
            print(f"🔍 GET {pools_url}")
            r = requests.get(pools_url, headers=headers)
            r.raise_for_status()
            pool_id = r.json()["data"][0]["attributes"]["address"]

            tf_map = {"1m": "minute", "15m": "minute?aggregate=15"}
            endpoint = tf_map[self.timeframe]
            ohlcv_url = f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool_id}/ohlcv/{endpoint}?limit=1000"
            print(f"📊 GET {ohlcv_url}")
            res = requests.get(ohlcv_url, headers=headers)
            res.raise_for_status()

            candles_raw = res.json()["data"]["attributes"]["ohlcv_list"]
            return [
                Candle(
                    timestamp=datetime.utcfromtimestamp(row[0]).replace(tzinfo=timezone.utc),
                    open=float(row[1]),
                    close=float(row[2]),
                    high=float(row[3]),
                    low=float(row[4]),
                    volume=float(row[5]),
                ) for row in candles_raw
            ]

        except Exception as e:
            print(f"❌ Error fetching candles from API for {contract_address}: {e}")
            return []

    def load_prices(self, contract_address: str, start_time=None, end_time=None) -> List[Candle]:
        candles = self._load_from_cache(contract_address)
        if candles:
            print(f"✅ Loaded {len(candles)} candles from cache for {contract_address}")
        else:
            candles = self._fetch_from_api(contract_address)
            if candles:
                self._save_to_cache(contract_address, candles)
            else:
                print(f"⚠️ No candles fetched from API and no cache available for {contract_address}")
                return []

        return [
            c for c in candles
            if (start_time is None or c.timestamp >= start_time) and
               (end_time is None or c.timestamp <= end_time)
        ]
