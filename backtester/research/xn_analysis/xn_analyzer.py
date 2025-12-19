# backtester/research/xn_analysis/xn_analyzer.py
# XN analyzer - analyzes XN potential of signals based on HIGH prices

from __future__ import annotations

import warnings
from datetime import datetime, timedelta
from typing import Optional, Dict, cast
import pandas as pd

from ...domain.models import Signal
from .xn_models import XNAnalysisConfig, XNSignalResult


class XNAnalyzer:
    """
    Analyzer for XN potential of signals.
    
    For each signal, determines what XN multipliers were achieved
    within a given holding period based on HIGH prices.
    
    This module does NOT depend on PortfolioEngine or Strategy.
    It works directly with signals and candles DataFrame.
    """
    
    @staticmethod
    def analyze_signal(
        signal: Signal,
        candles_df: pd.DataFrame,
        config: XNAnalysisConfig,
    ) -> Optional[XNSignalResult]:
        """
        Analyze XN potential for a single signal.
        
        :param signal: Signal to analyze
        :param candles_df: DataFrame with candles (columns: timestamp, open, high, low, close, volume)
        :param config: XN analysis configuration
        :return: XNSignalResult with analysis results, or None if signal should be skipped
        """
        try:
            # Validate input DataFrame
            required_columns = ["timestamp", "high"]
            missing_columns = [col for col in required_columns if col not in candles_df.columns]
            if missing_columns:
                warnings.warn(
                    f"[XN] Signal {signal.id}: Missing columns in candles_df: {missing_columns}. Skipping.",
                    UserWarning
                )
                return None
            
            # Convert timestamp to datetime if needed
            if not pd.api.types.is_datetime64_any_dtype(candles_df["timestamp"]):
                candles_df = candles_df.copy()
                candles_df["timestamp"] = pd.to_datetime(candles_df["timestamp"], utc=True)
            
            # Sort by timestamp for consistency
            candles_df = candles_df.sort_values("timestamp").reset_index(drop=True)
            
            # Find first candle AFTER signal timestamp
            signal_time = signal.timestamp
            if isinstance(signal_time, pd.Timestamp):
                signal_time = signal_time.to_pydatetime()
            
            # Filter candles after signal timestamp
            after_signal = candles_df[candles_df["timestamp"] > signal_time]
            
            if after_signal.empty:
                warnings.warn(
                    f"[XN] Signal {signal.id}: No candles found after signal timestamp {signal_time}. Skipping.",
                    UserWarning
                )
                return None
            
            # Get entry_price from close of first candle after signal
            first_candle = after_signal.iloc[0]
            entry_price = float(first_candle["close"])
            
            if entry_price <= 0:
                warnings.warn(
                    f"[XN] Signal {signal.id}: Invalid entry_price {entry_price}. Skipping.",
                    UserWarning
                )
                return None
            
            # entry_time is the timestamp of the first candle after signal
            entry_time = first_candle["timestamp"]
            if isinstance(entry_time, pd.Timestamp):
                entry_time = entry_time.to_pydatetime()
            
            # Calculate holding period end
            holding_end = entry_time + timedelta(days=config.holding_days)
            
            # Filter candles in holding period (from entry_time to holding_end)
            # Use >= entry_time to include entry candle
            relevant_candles = candles_df[
                (candles_df["timestamp"] >= entry_time) &
                (candles_df["timestamp"] <= holding_end)
            ].copy()
            
            if relevant_candles.empty:
                warnings.warn(
                    f"[XN] Signal {signal.id}: No candles in holding period. Skipping.",
                    UserWarning
                )
                return None
            
            # Find maximum high price in the holding period
            max_price = float(relevant_candles["high"].max())
            
            # Calculate maximum XN achieved
            max_xn = max_price / entry_price if entry_price > 0 else 0.0
            
            # Calculate time_to_xn for each XN level
            time_to_xn: Dict[float, Optional[int]] = {}
            
            for xn_level in config.xn_levels:
                target_price = entry_price * xn_level
                
                # Find first candle where HIGH >= target_price
                reached_candles = cast(pd.DataFrame, relevant_candles[relevant_candles["high"] >= target_price])
                
                if reached_candles.empty:
                    # XN level not reached
                    time_to_xn[xn_level] = None
                else:
                    # First candle that reached the XN level
                    first_reached = reached_candles.iloc[0]
                    reached_time = first_reached["timestamp"]
                    if isinstance(reached_time, pd.Timestamp):
                        reached_time = reached_time.to_pydatetime()
                    
                    # Calculate minutes from entry_time to reached_time
                    time_delta = reached_time - entry_time
                    minutes = int(time_delta.total_seconds() / 60)
                    
                    if minutes < 0:
                        # Should not happen if data is correct, but handle gracefully
                        minutes = 0
                    
                    time_to_xn[xn_level] = minutes
            
            return XNSignalResult(
                signal_id=signal.id,
                contract_address=signal.contract_address,
                entry_time=entry_time,
                entry_price=entry_price,
                max_price=max_price,
                max_xn=max_xn,
                time_to_xn=time_to_xn,
            )
        
        except Exception as e:
            warnings.warn(
                f"[XN] Signal {signal.id}: Analysis error: {str(e)}. Skipping.",
                UserWarning
            )
            return None





