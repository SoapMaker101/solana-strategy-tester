from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List
import os
import requests
import pandas as pd

from ..domain.models import Candle

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
    def __init__(self, cache_dir: str = "data/candles/cached", timeframe: str = "1m", max_cache_age_days: int = 2):
        self.cache_dir = Path(cache_dir)
        self.timeframe = timeframe
        self.max_cache_age_days = max_cache_age_days

    def _get_cache_path(self, contract_address: str) -> Path:
        return self.cache_dir / f"{contract_address}_{self.timeframe}.csv"

    def _is_cache_fresh(self, path: Path) -> bool:
        if not path.exists():
            return False
        try:
            df = pd.read_csv(path)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            last_ts = df["timestamp"].max()
            age = datetime.now(timezone.utc) - last_ts
            return age <= timedelta(days=self.max_cache_age_days)
        except Exception:
            return False

    def _load_from_cache(self, path: Path) -> Optional[List[Candle]]:
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

    def _save_to_cache(self, path: Path, candles: List[Candle]):
        try:
            os.makedirs(path.parent, exist_ok=True)
            df = pd.DataFrame([{
                "timestamp": c.timestamp.isoformat(),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            } for c in candles])
            df.to_csv(path, index=False)
            print(f"📅 Saved {len(candles)} candles to cache: {path}")
        except Exception as e:
            print(f"⚠️ Failed to save cache: {e}")

    def load_prices(self, contract_address: str, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> List[Candle]:
        cache_path = self._get_cache_path(contract_address)
        candles: List[Candle] = []
        now_ts = int(datetime.now(timezone.utc).timestamp())

        try:
            headers = {"User-Agent": "Mozilla/5.0 GeckoLoader"}
            tf_map = {"1m": ("minute", None), "15m": ("minute", "15")}
            tf_endpoint, aggregate = tf_map[self.timeframe]

            pools_url = f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{contract_address}/pools"
            r = requests.get(pools_url, headers=headers)
            r.raise_for_status()
            pool_id = r.json()["data"][0]["attributes"]["address"]

            before_ts = now_ts
            seen = set()

            while True:
                query = f"limit=1000&before_timestamp={before_ts}"
                if aggregate:
                    query += f"&aggregate={aggregate}"

                ohlcv_url = f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool_id}/ohlcv/{tf_endpoint}?{query}"
                print(f"⬅️ Fetching: {ohlcv_url}")
                res = requests.get(ohlcv_url, headers=headers)
                res.raise_for_status()

                candles_raw = res.json()["data"]["attributes"].get("ohlcv_list", [])
                if not candles_raw:
                    break

                batch = [
                    Candle(
                        timestamp=datetime.utcfromtimestamp(row[0]).replace(tzinfo=timezone.utc),
                        open=float(row[1]),
                        close=float(row[2]),
                        high=float(row[3]),
                        low=float(row[4]),
                        volume=float(row[5]),
                    )
                    for row in candles_raw
                    if row[0] not in seen
                ]
                seen.update(row[0] for row in candles_raw)

                candles.extend(batch)

                if start_time and batch[-1].timestamp <= start_time:
                    break

                before_ts = int(batch[-1].timestamp.timestamp())

            candles.sort(key=lambda c: c.timestamp)
            print(f"📦 Total candles fetched: {len(candles)}")
            self._save_to_cache(cache_path, candles)

        except Exception as e:
            print(f"❌ Error loading candles for {contract_address}: {e}")

        return [
            c for c in candles
            if (start_time is None or c.timestamp >= start_time) and
               (end_time is None or c.timestamp <= end_time)
        ]