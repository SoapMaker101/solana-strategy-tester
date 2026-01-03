"""
Smoke test для scripts/compare_legacy_vs_replay.py.

Проверяет, что скрипт не падает и возвращает строку summary.
Тест не зависит от реальных прогонов - создает минимальные CSV/JSON файлы.
"""
import csv
import json
import sys
import importlib.util
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Загружаем модуль напрямую
scripts_path = Path(__file__).parent.parent.parent / "scripts" / "compare_legacy_vs_replay.py"
spec = importlib.util.spec_from_file_location("compare_legacy_vs_replay", scripts_path)
compare_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare_module)
compare_legacy_vs_replay = compare_module.compare_legacy_vs_replay


@pytest.fixture
def temp_dirs():
    """Создает временные директории для legacy и replay."""
    with tempfile.TemporaryDirectory() as tmpdir:
        legacy_dir = Path(tmpdir) / "legacy"
        replay_dir = Path(tmpdir) / "replay"
        legacy_dir.mkdir()
        replay_dir.mkdir()
        yield legacy_dir, replay_dir


def create_minimal_positions_csv(path: Path, prefix: str = ""):
    """Создает минимальный portfolio_positions.csv."""
    filename = f"{prefix}_portfolio_positions.csv" if prefix else "portfolio_positions.csv"
    filepath = path / filename
    
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            "strategy", "position_id", "signal_id", "contract_address",
            "entry_time", "exit_time", "status", "size", "pnl_sol",
            "pnl_pct_total", "realized_multiple", "reason", "fees_total_sol"
        ])
        writer.writeheader()
        
        # Минимальная позиция
        entry_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc).isoformat()
        exit_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc).isoformat()
        
        writer.writerow({
            "strategy": "test_strategy",
            "position_id": "pos_001",
            "signal_id": "sig_001",
            "contract_address": "0x123",
            "entry_time": entry_time,
            "exit_time": exit_time,
            "status": "closed",
            "size": "1.0",
            "pnl_sol": "0.1",
            "pnl_pct_total": "10.0",
            "realized_multiple": "1.1",
            "reason": "ladder_tp",
            "fees_total_sol": "0.01"
        })
    
    return filepath


def create_minimal_stats_json(path: Path, prefix: str = ""):
    """Создает минимальный portfolio_stats.json."""
    filename = f"{prefix}_portfolio_stats.json" if prefix else "portfolio_stats.json"
    filepath = path / filename
    
    stats = {
        "final_balance_sol": 10.1,
        "initial_balance_sol": 10.0,
        "total_return_pct": 1.0,
        "max_drawdown_pct": 5.0,
        "trades_executed": 1,
        "trades_skipped_by_risk": 0,
        "portfolio_reset_count": 0
    }
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2)
    
    return filepath


def create_minimal_events_csv(path: Path, prefix: str = ""):
    """Создает минимальный portfolio_events.csv."""
    filename = f"{prefix}_portfolio_events.csv" if prefix else "portfolio_events.csv"
    filepath = path / filename
    
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            "event_id", "timestamp", "event_type", "strategy", "signal_id",
            "contract_address", "position_id", "reason", "meta_json"
        ])
        writer.writeheader()
        
        entry_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc).isoformat()
        exit_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc).isoformat()
        
        # POSITION_OPENED
        writer.writerow({
            "event_id": "evt_001",
            "timestamp": entry_time,
            "event_type": "position_opened",
            "strategy": "test_strategy",
            "signal_id": "sig_001",
            "contract_address": "0x123",
            "position_id": "pos_001",
            "reason": "",
            "meta_json": "{}"
        })
        
        # POSITION_CLOSED
        writer.writerow({
            "event_id": "evt_002",
            "timestamp": exit_time,
            "event_type": "position_closed",
            "strategy": "test_strategy",
            "signal_id": "sig_001",
            "contract_address": "0x123",
            "position_id": "pos_001",
            "reason": "ladder_tp",
            "meta_json": "{}"
        })
    
    return filepath


def create_minimal_equity_csv(path: Path, prefix: str = ""):
    """Создает минимальный equity_curve.csv."""
    filename = f"{prefix}_equity_curve.csv" if prefix else "equity_curve.csv"
    filepath = path / filename
    
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "balance", "equity"])
        writer.writeheader()
        
        # Точки equity curve
        base_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        for i in range(5):
            timestamp = (base_time.replace(hour=10 + i)).isoformat()
            balance = 10.0 + (i * 0.02)  # Небольшой рост
            writer.writerow({
                "timestamp": timestamp,
                "balance": str(balance),
                "equity": str(balance)
            })
    
    return filepath


def test_compare_smoke_basic(temp_dirs):
    """Базовый smoke test: скрипт не падает и возвращает строку."""
    legacy_dir, replay_dir = temp_dirs
    
    # Создаем минимальные файлы
    create_minimal_positions_csv(legacy_dir)
    create_minimal_stats_json(legacy_dir)
    create_minimal_events_csv(legacy_dir)
    
    create_minimal_positions_csv(replay_dir)
    create_minimal_stats_json(replay_dir)
    create_minimal_events_csv(replay_dir)
    
    # Запускаем функцию сравнения
    result = compare_legacy_vs_replay(legacy_dir, replay_dir, verbose=False)
    
    # Проверяем, что результат - строка
    assert isinstance(result, str)
    assert len(result) > 0
    
    # Проверяем наличие ключевых секций в выводе
    assert "Legacy vs Replay — Summary Diff" in result
    assert "Core metrics:" in result
    assert "Sanity checks:" in result


def test_compare_smoke_with_equity(temp_dirs):
    """Smoke test с equity curve."""
    legacy_dir, replay_dir = temp_dirs
    
    # Создаем файлы с equity curve
    create_minimal_positions_csv(legacy_dir)
    create_minimal_stats_json(legacy_dir)
    create_minimal_events_csv(legacy_dir)
    create_minimal_equity_csv(legacy_dir)
    
    create_minimal_positions_csv(replay_dir)
    create_minimal_stats_json(replay_dir)
    create_minimal_events_csv(replay_dir)
    create_minimal_equity_csv(replay_dir)
    
    # Запускаем функцию сравнения
    result = compare_legacy_vs_replay(legacy_dir, replay_dir, verbose=False)
    
    # Проверяем результат
    assert isinstance(result, str)
    assert len(result) > 0
    assert "Legacy vs Replay — Summary Diff" in result


def test_compare_smoke_with_strategy_filter(temp_dirs):
    """Smoke test с фильтром по стратегии."""
    legacy_dir, replay_dir = temp_dirs
    
    # Создаем файлы с префиксом стратегии
    create_minimal_positions_csv(legacy_dir, prefix="test_strategy")
    create_minimal_stats_json(legacy_dir, prefix="test_strategy")
    
    create_minimal_positions_csv(replay_dir, prefix="test_strategy")
    create_minimal_stats_json(replay_dir, prefix="test_strategy")
    
    # Запускаем с фильтром
    result = compare_legacy_vs_replay(
        legacy_dir, replay_dir, strategy="test_strategy", verbose=False
    )
    
    # Проверяем результат
    assert isinstance(result, str)
    assert len(result) > 0


def test_compare_smoke_minimal_files_only(temp_dirs):
    """Smoke test только с positions и stats (без events и equity)."""
    legacy_dir, replay_dir = temp_dirs
    
    # Только минимально необходимые файлы
    create_minimal_positions_csv(legacy_dir)
    create_minimal_stats_json(legacy_dir)
    
    create_minimal_positions_csv(replay_dir)
    create_minimal_stats_json(replay_dir)
    
    # Запускаем функцию сравнения
    result = compare_legacy_vs_replay(legacy_dir, replay_dir, verbose=False)
    
    # Проверяем, что работает даже без events/equity
    assert isinstance(result, str)
    assert len(result) > 0
    assert "Legacy vs Replay — Summary Diff" in result


def test_compare_smoke_file_not_found(temp_dirs):
    """Проверка обработки ошибки: файлы не найдены."""
    legacy_dir, replay_dir = temp_dirs
    
    # Не создаем файлы - должно выбросить FileNotFoundError
    with pytest.raises(FileNotFoundError):
        compare_legacy_vs_replay(legacy_dir, replay_dir, verbose=False)

