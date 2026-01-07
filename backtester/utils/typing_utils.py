from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence, TypeVar, cast
import pandas as pd

T = TypeVar("T")


def is_nonempty_df(df: Optional[pd.DataFrame]) -> bool:
    """Check if DataFrame is not None and not empty."""
    return df is not None and not df.empty


def is_nonempty_series(s: Optional[pd.Series]) -> bool:
    """Check if Series is not None and not empty."""
    return s is not None and not s.empty


def ensure_df(obj: Any) -> pd.DataFrame:
    """Runtime guard + typing narrowing for DataFrame."""
    if isinstance(obj, pd.DataFrame):
        return obj
    raise TypeError(f"Expected DataFrame, got {type(obj)!r}")


def ensure_series(obj: Any) -> pd.Series:
    """Runtime guard + typing narrowing for Series."""
    if isinstance(obj, pd.Series):
        return obj
    raise TypeError(f"Expected Series, got {type(obj)!r}")


def safe_float(x: Any, *, default: float = 0.0) -> float:
    """Safely convert value to float, handling None and invalid values."""
    if x is None:
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def isin_values(values: Iterable[str]) -> Sequence[str]:
    """Convert iterable to list for pandas isin() - pandas typing complains about set[str]."""
    return list(values)


def as_utc_datetime(value: Any) -> Optional[pd.Timestamp]:
    """
    Normalize value to pd.Timestamp for type safety.
    Does NOT change timezone/value if already Timestamp.
    Returns None if value is None, NaT, or invalid.
    """
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        # Check if it's NaT
        if pd.isna(value):
            return None
        return value
    try:
        ts = pd.Timestamp(value)
        # Check if conversion resulted in NaT
        # Явная проверка: pd.Timestamp() всегда возвращает pd.Timestamp (не NDFrame),
        # но basedpyright может не знать это, поэтому проверяем тип перед pd.isna()
        if isinstance(ts, pd.Timestamp):
            # pd.isna() на pd.Timestamp всегда возвращает bool
            if pd.isna(ts):
                return None
            return ts
        # Если не pd.Timestamp (не должно быть в runtime) - возвращаем None
        return None
    except Exception:
        return None

