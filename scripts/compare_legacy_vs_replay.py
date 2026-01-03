#!/usr/bin/env python3
"""
Сравнение результатов legacy vs replay (Этап 2.5).

ЧТО ДЕЛАЕТ:
    Сравнивает результаты legacy PortfolioEngine и PortfolioReplay для одного и того же
    набора blueprints (strategy_trades.csv). Вычисляет метрики для обоих путей и выводит
    различия с объяснениями.

ЗАЧЕМ НУЖЕН:
    Понять и объяснить различия между legacy и replay путями.
    Не "свести результаты", а выявить причины различий (time_stop vs max_hold,
    forced closes, ordering и т.д.).

КОГДА ИСПОЛЬЗУЕТСЯ:
    ЭТАП 2.5 — "Compare legacy vs replay (контроль)" после завершения Этапа 2.
    Запускается после backtest run для обоих путей (legacy и replay).

ИСПОЛЬЗОВАНИЕ:
    python scripts/compare_legacy_vs_replay.py --legacy-dir output/reports/legacy --replay-dir output/reports/replay
    python scripts/compare_legacy_vs_replay.py --legacy-dir legacy --replay-dir replay --strategy my_strategy --out diff.md
"""
import argparse
import csv
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from collections import Counter, defaultdict


def parse_float(value: str) -> Optional[float]:
    """Безопасный парсинг float из CSV."""
    if not value or value == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def parse_datetime(value: str) -> Optional[datetime]:
    """Безопасный парсинг datetime из CSV."""
    if not value or value == "":
        return None
    try:
        # Пробуем разные форматы
        for fmt in ["%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"]:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        return None
    except (ValueError, TypeError):
        return None


def read_portfolio_positions_csv(csv_path: Path) -> List[Dict[str, Any]]:
    """
    Читает portfolio_positions.csv файл.
    
    Returns:
        Список словарей с позициями
    """
    if not csv_path.exists():
        return []
    
    positions = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Преобразуем типы (CSV содержит: position_id, signal_id, contract_address,
            # entry_time, entry_price, exit_time, exit_price, size_sol, pnl_pct, pnl_sol,
            # status, reason и другие поля)
            position = {
                "position_id": row.get("position_id", ""),
                "signal_id": row.get("signal_id", ""),
                "contract_address": row.get("contract_address", ""),
                "entry_time": parse_datetime(row.get("entry_time", "")),
                "exit_time": parse_datetime(row.get("exit_time", "")),
                "entry_price": parse_float(row.get("entry_price", "")),
                "exit_price": parse_float(row.get("exit_price", "")),
                "size_sol": parse_float(row.get("size_sol", "")),
                "pnl_pct": parse_float(row.get("pnl_pct", "")),
                "pnl_sol": parse_float(row.get("pnl_sol", "")),
                "status": row.get("status", ""),
                "reason": row.get("reason", ""),
                # Сохраняем все поля для verbose режима
                "_raw": row,
            }
            positions.append(position)
    
    return positions


def read_portfolio_stats_json(json_path: Path) -> Optional[Dict[str, Any]]:
    """
    Читает portfolio_stats.json файл.
    
    Returns:
        Словарь со статистикой или None
    """
    if not json_path.exists():
        return None
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def read_portfolio_events_csv(csv_path: Path) -> List[Dict[str, Any]]:
    """
    Читает portfolio_events.csv файл.
    
    Returns:
        Список словарей с событиями
    """
    if not csv_path.exists():
        return []
    
    events = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                event = {
                    "event_type": row.get("event_type", ""),
                    "strategy": row.get("strategy", ""),
                    "signal_id": row.get("signal_id", ""),
                    "position_id": row.get("position_id", ""),
                    "timestamp": parse_datetime(row.get("timestamp", "")),
                    "reason": row.get("reason", ""),
                }
                events.append(event)
    except (IOError, csv.Error):
        return []
    
    return events


def read_equity_curve_csv(csv_path: Path) -> List[Dict[str, Any]]:
    """
    Читает equity_curve.csv файл.
    
    Returns:
        Список словарей с точками equity curve
    """
    if not csv_path.exists():
        return []
    
    equity_points = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                point = {
                    "timestamp": parse_datetime(row.get("timestamp", "")),
                    "balance": parse_float(row.get("balance", "")),
                    "equity": parse_float(row.get("equity", "")),
                }
                if point["balance"] is not None or point["equity"] is not None:
                    equity_points.append(point)
    except (IOError, csv.Error):
        return []
    
    return equity_points


def find_portfolio_files(directory: Path, strategy_name: Optional[str] = None) -> Dict[str, Path]:
    """
    Находит portfolio CSV и JSON файлы в директории (robust glob).
    
    Ищет файлы как без префикса стратегии (portfolio_*.csv), так и с префиксом (*_portfolio_*.csv).
    Приоритет: файлы без префикса (если есть) > файлы с префиксом.
    
    Args:
        directory: Директория для поиска
        strategy_name: Опциональный фильтр по имени стратегии (для файлов с префиксом)
        
    Returns:
        Словарь: {
            "positions_csv": Path или None,
            "stats_json": Path или None,
            "events_csv": Path или None,
            "equity_csv": Path или None,
        }
    """
    if not directory.exists():
        return {"positions_csv": None, "stats_json": None, "events_csv": None, "equity_csv": None}
    
    files = {"positions_csv": None, "stats_json": None, "events_csv": None, "equity_csv": None}
    
    # Ищем portfolio_positions CSV
    # Сначала пробуем без префикса (основной файл для сравнения)
    positions_csv = directory / "portfolio_positions.csv"
    if positions_csv.exists():
        files["positions_csv"] = positions_csv
    else:
        # Если нет без префикса, ищем с префиксом
        if strategy_name:
            pattern = f"{strategy_name}_portfolio_positions.csv"
            candidate = directory / pattern
            if candidate.exists():
                files["positions_csv"] = candidate
        else:
            # Ищем любой файл с паттерном *_portfolio_positions.csv
            for csv_file in directory.glob("*_portfolio_positions.csv"):
                files["positions_csv"] = csv_file
                break
    
    # Ищем portfolio_stats JSON
    # Сначала без префикса (если есть такой формат)
    stats_json = directory / "portfolio_stats.json"
    if stats_json.exists():
        files["stats_json"] = stats_json
    else:
        # Ищем с префиксом стратегии
        if strategy_name:
            pattern = f"{strategy_name}_portfolio_stats.json"
            candidate = directory / pattern
            if candidate.exists():
                files["stats_json"] = candidate
        else:
            # Ищем любой файл с паттерном *_portfolio_stats.json
            for json_file in directory.glob("*_portfolio_stats.json"):
                files["stats_json"] = json_file
                break
    
    # Ищем portfolio_events CSV (обычно без префикса)
    events_csv = directory / "portfolio_events.csv"
    if events_csv.exists():
        files["events_csv"] = events_csv
    else:
        # Fallback: ищем с префиксом
        if strategy_name:
            pattern = f"{strategy_name}_portfolio_events.csv"
            candidate = directory / pattern
            if candidate.exists():
                files["events_csv"] = candidate
        else:
            for events_file in directory.glob("*_portfolio_events.csv"):
                files["events_csv"] = events_file
                break
    
    # Ищем equity_curve CSV (обычно с префиксом стратегии)
    # Но сначала пробуем без префикса
    equity_csv = directory / "equity_curve.csv"
    if equity_csv.exists():
        files["equity_csv"] = equity_csv
    else:
        if strategy_name:
            pattern = f"{strategy_name}_equity_curve.csv"
            candidate = directory / pattern
            if candidate.exists():
                files["equity_csv"] = candidate
        else:
            # Ищем любой файл с паттерном *_equity_curve.csv
            for equity_file in directory.glob("*_equity_curve.csv"):
                files["equity_csv"] = equity_file
                break
    
    return files


def analyze_close_reasons(
    positions: List[Dict[str, Any]],
    events: List[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Анализирует распределение причин закрытия позиций.
    
    Returns:
        Словарь с анализом:
        - reasons_counter: Counter причин закрытия
        - reasons_list: список всех причин
    """
    if events is None:
        events = []
    
    # Собираем reasons из events (source of truth)
    reasons = []
    if events:
        for event in events:
            if event.get("event_type", "").lower() == "position_closed":
                reason = event.get("reason", "unknown")
                if reason:
                    reasons.append(reason)
    else:
        # Fallback на positions
        for pos in positions:
            if pos.get("status") == "closed":
                reason = pos.get("reason", "unknown")
                if reason:
                    reasons.append(reason)
    
    reasons_counter = Counter(reasons)
    
    return {
        "reasons_counter": reasons_counter,
        "reasons_list": reasons,
    }


def compare_close_reasons(
    legacy_reasons: Dict[str, Any],
    replay_reasons: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Сравнивает распределение причин закрытия между legacy и replay.
    
    Returns:
        Словарь с результатами сравнения
    """
    legacy_counter = legacy_reasons.get("reasons_counter", Counter())
    replay_counter = replay_reasons.get("reasons_counter", Counter())
    
    legacy_reasons_set = set(legacy_counter.keys())
    replay_reasons_set = set(replay_counter.keys())
    
    return {
        "legacy_counter": legacy_counter,
        "replay_counter": replay_counter,
        "only_in_legacy": list(legacy_reasons_set - replay_reasons_set),
        "only_in_replay": list(replay_reasons_set - legacy_reasons_set),
        "common_reasons": list(legacy_reasons_set & replay_reasons_set),
        "top_legacy": legacy_counter.most_common(5),
        "top_replay": replay_counter.most_common(5),
    }


def calculate_metrics(
    positions: List[Dict[str, Any]],
    stats: Optional[Dict[str, Any]],
    events: List[Dict[str, Any]] = None,
    equity_curve: List[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Вычисляет метрики из positions, stats, events и equity_curve.
    
    Args:
        positions: Список позиций из portfolio_positions.csv
        stats: Статистика из portfolio_stats.json
        events: Список событий из portfolio_events.csv (опционально)
        equity_curve: Список точек equity curve (опционально)
    
    Returns:
        Словарь с метриками
    """
    if events is None:
        events = []
    if equity_curve is None:
        equity_curve = []
    
    metrics = {
        "count_positions_total": len(positions),
        "count_positions_opened": 0,
        "count_positions_closed": 0,
        "count_unique_position_ids": 0,
        "total_pnl_sol": 0.0,
        "number_of_resets": 0,
        "max_drawdown_pct": 0.0,
        "final_balance_sol": 0.0,
        "trades_executed": 0,
        "trades_skipped_by_risk": 0,
    }
    
    # 1) Count positions:
    # - количество POSITION_OPENED (из events если есть, иначе из positions)
    # - количество POSITION_CLOSED (из events если есть, иначе из positions)
    # - количество уникальных position_id
    
    if events:
        # Используем events как source of truth
        # event_type может быть в разном регистре, поэтому используем lower()
        opened_count = sum(1 for e in events if e.get("event_type", "").lower() == "position_opened")
        closed_count = sum(1 for e in events if e.get("event_type", "").lower() == "position_closed")
        unique_position_ids = len(set(e.get("position_id") for e in events if e.get("position_id")))
        
        metrics["count_positions_opened"] = opened_count
        metrics["count_positions_closed"] = closed_count
        metrics["count_unique_position_ids"] = unique_position_ids
    else:
        # Fallback на positions
        opened_count = len([p for p in positions if p.get("entry_time") is not None])
        closed_count = len([p for p in positions if p.get("status") == "closed"])
        unique_position_ids = len(set(p.get("position_id") for p in positions if p.get("position_id")))
        
        metrics["count_positions_opened"] = opened_count
        metrics["count_positions_closed"] = closed_count
        metrics["count_unique_position_ids"] = unique_position_ids
    
    # 2) Total pnl_sol:
    # - из positions (source of truth)
    # - fallback на stats если positions не содержат pnl
    
    total_pnl = 0.0
    has_pnl_in_positions = False
    for pos in positions:
        pnl_sol = pos.get("pnl_sol")
        if pnl_sol is not None:
            total_pnl += pnl_sol
            has_pnl_in_positions = True
    
    if has_pnl_in_positions:
        metrics["total_pnl_sol"] = total_pnl
    elif stats:
        # Fallback: если pnl нет в positions, пытаемся вычислить из баланса
        # Это best-effort: final_balance может включать не все транзакции
        # Но для сравнения это достаточно
        final_balance = stats.get("final_balance_sol", 0.0)
        # Если есть initial_balance в stats - используем его
        initial_balance = stats.get("initial_balance_sol", 0.0)
        if initial_balance > 0:
            metrics["total_pnl_sol"] = final_balance - initial_balance
        else:
            # Если initial_balance нет, используем только final_balance как индикатор
            # (но это не точный total_pnl)
            metrics["total_pnl_sol"] = final_balance
    
    # 3) Number of resets:
    # - count(PORTFOLIO_RESET_TRIGGERED) из events (source of truth)
    # - fallback на stats
    
    if events:
        # event_type может быть в разном регистре
        reset_count = sum(1 for e in events if e.get("event_type", "").lower() == "portfolio_reset_triggered")
        metrics["number_of_resets"] = reset_count
    elif stats:
        metrics["number_of_resets"] = stats.get("portfolio_reset_count", 0)
    
    # 4) Max drawdown:
    # - по equity curve если есть (source of truth)
    # - иначе по cumulative pnl (best-effort)
    # - fallback на stats
    
    if equity_curve:
        # Вычисляем max drawdown из equity curve
        balances = []
        for point in equity_curve:
            balance = point.get("balance")
            if balance is None:
                balance = point.get("equity")
            if balance is not None:
                balances.append(balance)
        
        if balances:
            peak = balances[0]
            max_dd = 0.0
            for balance in balances:
                if balance > peak:
                    peak = balance
                dd = (peak - balance) / peak * 100.0 if peak > 0 else 0.0
                if dd > max_dd:
                    max_dd = dd
            metrics["max_drawdown_pct"] = max_dd
    elif stats:
        # Fallback на stats
        metrics["max_drawdown_pct"] = stats.get("max_drawdown_pct", 0.0)
    
    # Извлекаем остальные метрики из stats (если доступны)
    if stats:
        metrics["final_balance_sol"] = stats.get("final_balance_sol", 0.0)
        metrics["trades_executed"] = stats.get("trades_executed", 0)
        metrics["trades_skipped_by_risk"] = stats.get("trades_skipped_by_risk", 0)
    
    return metrics


def compare_close_reasons(
    legacy_reasons: Dict[str, Any],
    replay_reasons: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Сравнивает распределение причин закрытия между legacy и replay.
    
    Returns:
        Словарь с результатами сравнения
    """
    legacy_counter = legacy_reasons.get("reasons_counter", Counter())
    replay_counter = replay_reasons.get("reasons_counter", Counter())
    
    legacy_reasons_set = set(legacy_counter.keys())
    replay_reasons_set = set(replay_counter.keys())
    
    return {
        "legacy_counter": legacy_counter,
        "replay_counter": replay_counter,
        "only_in_legacy": list(legacy_reasons_set - replay_reasons_set),
        "only_in_replay": list(replay_reasons_set - legacy_reasons_set),
        "common_reasons": list(legacy_reasons_set & replay_reasons_set),
        "top_legacy": legacy_counter.most_common(5),
        "top_replay": replay_counter.most_common(5),
    }


def check_monotonic_timestamps(events: List[Dict[str, Any]], label: str) -> List[str]:
    """
    Проверяет monotonic timestamps в событиях.
    
    Args:
        events: Список событий
        label: Метка для warning (например, "LEGACY" или "REPLAY")
    
    Returns:
        Список warning сообщений (пустой если нет нарушений)
    """
    warnings = []
    
    if not events:
        return warnings
    
    # Сортируем события по timestamp
    sorted_events = sorted(events, key=lambda e: e.get("timestamp") or datetime.min)
    
    # Проверяем монотонность
    violations = []
    for i in range(len(sorted_events) - 1):
        current_ts = sorted_events[i].get("timestamp")
        next_ts = sorted_events[i + 1].get("timestamp")
        
        if current_ts is None or next_ts is None:
            continue
        
        if current_ts > next_ts:
            violations.append({
                "index": i,
                "current": current_ts,
                "next": next_ts,
                "current_event": sorted_events[i],
                "next_event": sorted_events[i + 1],
            })
    
    if violations:
        warnings.append(
            f"[WARNING] {label}: Found {len(violations)} timestamp violations (events not sorted)"
        )
        # Показываем первые 3 нарушения
        for i, v in enumerate(violations[:3], 1):
            warnings.append(
                f"  Violation {i}: event at {v['current']} > next event at {v['next']} "
                f"(types: {v['current_event'].get('event_type')} > {v['next_event'].get('event_type')})"
            )
        if len(violations) > 3:
            warnings.append(f"  ... and {len(violations) - 3} more violations")
    
    return warnings


def check_reset_chain_correctness(events: List[Dict[str, Any]], label: str) -> List[str]:
    """
    Проверяет reset chain correctness.
    
    Правило: если есть PORTFOLIO_RESET_TRIGGERED, то перед ним должны быть
    POSITION_CLOSED для всех открытых позиций.
    
    Args:
        events: Список событий (должен быть отсортирован по timestamp)
        label: Метка для warning
    
    Returns:
        Список warning сообщений
    """
    warnings = []
    
    if not events:
        return warnings
    
    # Сортируем события по timestamp
    sorted_events = sorted(events, key=lambda e: e.get("timestamp") or datetime.min)
    
    # Находим все reset события
    reset_events = [
        (i, e) for i, e in enumerate(sorted_events)
        if e.get("event_type", "").lower() == "portfolio_reset_triggered"
    ]
    
    for reset_idx, reset_event in reset_events:
        reset_time = reset_event.get("timestamp")
        if reset_time is None:
            continue
        
        # Собираем все открытые позиции до reset
        opened_positions = set()
        closed_positions = set()
        
        # Проходим события до reset
        for i in range(reset_idx):
            event = sorted_events[i]
            event_type = event.get("event_type", "").lower()
            position_id = event.get("position_id")
            
            if event_type == "position_opened" and position_id:
                opened_positions.add(position_id)
            elif event_type == "position_closed" and position_id:
                closed_positions.add(position_id)
                # Убираем из opened, если была закрыта
                opened_positions.discard(position_id)
        
        # Проверяем, что все открытые позиции закрыты до или в момент reset
        not_closed_before_reset = opened_positions - closed_positions
        
        if not_closed_before_reset:
            # Проверяем, закрыты ли они в момент reset (в том же timestamp)
            # или сразу после reset
            closed_at_reset = set()
            for i in range(reset_idx, len(sorted_events)):
                event = sorted_events[i]
                event_ts = event.get("timestamp")
                
                # Проверяем события с тем же timestamp что и reset
                # (позиции могут закрываться одновременно с reset)
                if event_ts != reset_time:
                    break
                
                if event.get("event_type", "").lower() == "position_closed":
                    closed_at_reset.add(event.get("position_id"))
            
            still_open = not_closed_before_reset - closed_at_reset
            
            if still_open:
                warnings.append(
                    f"[WARNING] {label}: Reset chain violation at {reset_time}: "
                    f"{len(still_open)} positions not closed before/at reset"
                )
                # Показываем первые 3 позиции
                for pos_id in list(still_open)[:3]:
                    warnings.append(f"  Position {pos_id} not closed")
                if len(still_open) > 3:
                    warnings.append(f"  ... and {len(still_open) - 3} more positions")
    
    return warnings


def check_positions_events_consistency(
    positions: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
    label: str,
) -> List[str]:
    """
    Проверяет positions-events consistency.
    
    Правила:
    - Для каждого position_id: если есть POSITION_OPENED, должен быть хотя бы 1 event
    - Если есть POSITION_CLOSED — должен быть POSITION_OPENED
    
    Args:
        positions: Список позиций
        events: Список событий
        label: Метка для warning
    
    Returns:
        Список warning сообщений
    """
    warnings = []
    
    if not events:
        return warnings
    
    # Собираем position_ids из позиций
    position_ids_from_positions = set(p.get("position_id") for p in positions if p.get("position_id"))
    
    # Собираем события по position_id
    events_by_position = defaultdict(list)
    for event in events:
        position_id = event.get("position_id")
        if position_id:
            events_by_position[position_id].append(event)
    
    # Проверка 1: Если есть POSITION_OPENED, должен быть хотя бы 1 event для этого position_id
    opened_positions = set()
    for event in events:
        if event.get("event_type") == "position_opened":
            position_id = event.get("position_id")
            if position_id:
                opened_positions.add(position_id)
                # Проверяем, что есть хотя бы 1 event (уже есть, т.к. это событие открытия)
                pass
    
    # Проверка 2: Если есть POSITION_CLOSED — должен быть POSITION_OPENED
    closed_positions = set()
    for event in events:
        if event.get("event_type") == "position_closed":
            position_id = event.get("position_id")
            if position_id:
                closed_positions.add(position_id)
    
    # Находим закрытые позиции без открытия
    closed_without_opened = closed_positions - opened_positions
    
    if closed_without_opened:
        warnings.append(
            f"[WARNING] {label}: Found {len(closed_without_opened)} positions closed without POSITION_OPENED"
        )
        for pos_id in list(closed_without_opened)[:3]:
            warnings.append(f"  Position {pos_id} has POSITION_CLOSED but no POSITION_OPENED")
        if len(closed_without_opened) > 3:
            warnings.append(f"  ... and {len(closed_without_opened) - 3} more positions")
    
    # Проверка 3: Позиции без событий (опционально, может быть нормально для открытых позиций)
    # Но если позиция закрыта и нет событий - это проблема
    for pos in positions:
        position_id = pos.get("position_id")
        if not position_id:
            continue
        
        if pos.get("status") == "closed" and position_id not in events_by_position:
            warnings.append(
                f"[WARNING] {label}: Position {position_id} is closed but has no events"
            )
    
    return warnings


def format_diff(key: str, legacy_value: Any, replay_value: Any) -> str:
    """
    Форматирует разницу для одной метрики.
    """
    if isinstance(legacy_value, float) and isinstance(replay_value, float):
        diff = replay_value - legacy_value
        diff_pct = (diff / legacy_value * 100) if legacy_value != 0 else 0.0
        return f"{key:30s} | Legacy: {legacy_value:12.4f} | Replay: {replay_value:12.4f} | Diff: {diff:12.4f} ({diff_pct:+.2f}%)"
    elif isinstance(legacy_value, int) and isinstance(replay_value, int):
        diff = replay_value - legacy_value
        return f"{key:30s} | Legacy: {legacy_value:12d} | Replay: {replay_value:12d} | Diff: {diff:12d}"
    else:
        return f"{key:30s} | Legacy: {str(legacy_value):20s} | Replay: {str(replay_value):20s}"


def analyze_strategy_trades_csv(csv_path: Path) -> Optional[Dict[str, Any]]:
    """
    Анализирует strategy_trades.csv и подсчитывает метрики по blueprints.
    
    Args:
        csv_path: Путь к strategy_trades.csv
        
    Returns:
        Словарь с метриками или None, если файл не найден/ошибка
    """
    if not csv_path.exists():
        return None
    
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            blueprints = list(reader)
    except Exception:
        return None
    
    total_blueprints = len(blueprints)
    with_final_exit = 0
    without_final_exit = 0
    
    for row in blueprints:
        final_exit_json = row.get("final_exit_json", "")
        # Проверяем, что final_exit_json не пустой (не "" и не пустая строка после strip)
        if final_exit_json and final_exit_json.strip():
            with_final_exit += 1
        else:
            without_final_exit += 1
    
    return {
        "total": total_blueprints,
        "with_final_exit": with_final_exit,
        "without_final_exit": without_final_exit,
    }


def print_summary_diff(
    legacy_metrics: Dict[str, Any],
    replay_metrics: Dict[str, Any],
    legacy_dir: Path,
    replay_dir: Path,
    reasons_comparison: Optional[Dict[str, Any]] = None,
    verbose: bool = False,
    sanity_warnings: List[str] = None,
    blueprints_stats: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Выводит summary diff в читаемом формате.
    
    Returns:
        Строка с отформатированным diff (для сохранения в файл)
    """
    output_lines = []
    
    output_lines.append("=" * 40)
    output_lines.append("Legacy vs Replay — Summary Diff")
    output_lines.append("=" * 40)
    output_lines.append("")
    
    # Paths
    output_lines.append("Paths:")
    output_lines.append(f"- legacy: {legacy_dir}")
    output_lines.append(f"- replay: {replay_dir}")
    output_lines.append("")
    
    # Core metrics (компактный формат)
    output_lines.append("Core metrics:")
    
    def format_metric(name: str, legacy_val: Any, replay_val: Any, unit: str = "") -> str:
        """Форматирует одну метрику в компактном виде."""
        diff = replay_val - legacy_val
        if isinstance(legacy_val, float) and isinstance(replay_val, float):
            if unit == "%":
                return f"- {name}: legacy {legacy_val:.2f}{unit} | replay {replay_val:.2f}{unit} | diff {diff:+.2f}{unit}"
            else:
                return f"- {name}: legacy {legacy_val:.4f}{unit} | replay {replay_val:.4f}{unit} | diff {diff:+.4f}{unit}"
        else:
            return f"- {name}: legacy {legacy_val} | replay {replay_val} | diff {diff:+d}"
    
    output_lines.append(format_metric("positions_opened", legacy_metrics["count_positions_opened"], replay_metrics["count_positions_opened"]))
    output_lines.append(format_metric("positions_closed", legacy_metrics["count_positions_closed"], replay_metrics["count_positions_closed"]))
    output_lines.append(format_metric("unique_positions", legacy_metrics["count_unique_position_ids"], replay_metrics["count_unique_position_ids"]))
    output_lines.append(format_metric("total_pnl_sol", legacy_metrics["total_pnl_sol"], replay_metrics["total_pnl_sol"], " SOL"))
    output_lines.append(format_metric("resets", legacy_metrics["number_of_resets"], replay_metrics["number_of_resets"]))
    output_lines.append(format_metric("max_drawdown", legacy_metrics["max_drawdown_pct"], replay_metrics["max_drawdown_pct"], "%"))
    output_lines.append("")
    
    # Blueprints статистика (если указан --strategy-trades)
    if blueprints_stats:
        output_lines.append("Blueprints:")
        output_lines.append(f"- total: {blueprints_stats['total']}")
        output_lines.append(f"- with final_exit: {blueprints_stats['with_final_exit']}")
        output_lines.append(f"- without final_exit: {blueprints_stats['without_final_exit']}")
        output_lines.append("")
    
    # Close reasons (упрощенный формат)
    if reasons_comparison:
        output_lines.append("Close reasons (top):")
        
        # Top reasons в legacy
        if reasons_comparison["top_legacy"]:
            output_lines.append("Legacy:")
            for reason, count in reasons_comparison["top_legacy"][:5]:
                output_lines.append(f"  - {reason}: {count}")
        
        # Top reasons в replay
        if reasons_comparison["top_replay"]:
            output_lines.append("Replay:")
            for reason, count in reasons_comparison["top_replay"][:5]:
                output_lines.append(f"  - {reason}: {count}")
        
        output_lines.append("")
        
        # Only in legacy/replay
        if reasons_comparison["only_in_legacy"]:
            output_lines.append("Only in legacy:")
            for reason in sorted(reasons_comparison["only_in_legacy"]):
                count = reasons_comparison["legacy_counter"].get(reason, 0)
                output_lines.append(f"  - {reason}: {count}")
            output_lines.append("")
        
        if reasons_comparison["only_in_replay"]:
            output_lines.append("Only in replay:")
            for reason in sorted(reasons_comparison["only_in_replay"]):
                count = reasons_comparison["replay_counter"].get(reason, 0)
                output_lines.append(f"  - {reason}: {count}")
            output_lines.append("")
    
    
    # Sanity checks (компактный формат)
    output_lines.append("Sanity checks:")
    if sanity_warnings is None:
        sanity_warnings = []
    
    # Определяем статус каждой проверки
    monotonic_ok = True
    reset_chain_ok = True
    positions_events_ok = True
    
    for warning in sanity_warnings:
        if "timestamp violations" in warning.lower():
            monotonic_ok = False
        if "reset chain violation" in warning.lower():
            reset_chain_ok = False
        if "positions closed without" in warning.lower() or "has no events" in warning.lower():
            positions_events_ok = False
    
    output_lines.append(f"- monotonic timestamps: {'OK' if monotonic_ok else 'WARN'}")
    output_lines.append(f"- reset chain: {'OK' if reset_chain_ok else 'WARN'}")
    output_lines.append(f"- positions/events: {'OK' if positions_events_ok else 'WARN'}")
    output_lines.append("")
    
    # Explanations hint (короткий список)
    output_lines.append("Explanations hint:")
    explanations_hint = []
    
    # Проверяем ключевые различия
    if legacy_metrics["count_positions_opened"] != replay_metrics["count_positions_opened"]:
        explanations_hint.append("Different capacity blocking")
    
    if legacy_metrics["count_positions_closed"] != replay_metrics["count_positions_closed"]:
        explanations_hint.append("Different close triggers (time_stop vs max_hold_minutes)")
    
    if abs(legacy_metrics["total_pnl_sol"] - replay_metrics["total_pnl_sol"]) > 0.01:
        explanations_hint.append("Different exit timing affects PnL")
    
    if legacy_metrics["number_of_resets"] != replay_metrics["number_of_resets"]:
        explanations_hint.append("Different equity curves → different reset timing")
    
    if reasons_comparison:
        legacy_time_stop = reasons_comparison["legacy_counter"].get("time_stop", 0)
        replay_max_hold = reasons_comparison["replay_counter"].get("max_hold_minutes", 0)
        if legacy_time_stop > 0 or replay_max_hold > 0:
            explanations_hint.append(f"Legacy: time_stop ({legacy_time_stop}), Replay: max_hold ({replay_max_hold})")
    
    if not explanations_hint:
        explanations_hint.append("Metrics are similar, differences are minimal")
    
    for hint in explanations_hint:
        output_lines.append(f"- {hint}")
    output_lines.append("")
    
    # Verbose информация (если запрошено)
    if verbose and sanity_warnings:
        output_lines.append("--- Detailed sanity warnings ---")
        for warning in sanity_warnings:
            output_lines.append(warning)
        output_lines.append("")
    
    output_lines.append("=" * 40)
    
    return "\n".join(output_lines)


def compare_legacy_vs_replay(
    legacy_dir: Path,
    replay_dir: Path,
    strategy: Optional[str] = None,
    verbose: bool = False,
    strategy_trades_path: Optional[Path] = None,
) -> str:
    """
    Основная логика сравнения legacy vs replay.
    
    Args:
        legacy_dir: Директория с legacy отчетами
        replay_dir: Директория с replay отчетами
        strategy: Опциональный фильтр по имени стратегии
        verbose: Выводить детальную информацию
        strategy_trades_path: Опциональный путь к strategy_trades.csv для анализа blueprints
    
    Returns:
        Строка с summary diff
    
    Raises:
        FileNotFoundError: Если не найдены необходимые файлы
    """
    # Находим файлы
    legacy_files = find_portfolio_files(legacy_dir, strategy)
    replay_files = find_portfolio_files(replay_dir, strategy)
    
    # Проверяем наличие файлов
    if not legacy_files["positions_csv"]:
        error_msg = f"Не найдены legacy portfolio файлы в {legacy_dir}"
        if strategy:
            error_msg += f" (искали: {strategy}_portfolio_positions.csv)"
        raise FileNotFoundError(error_msg)
    
    if not replay_files["positions_csv"]:
        error_msg = f"Не найдены replay portfolio файлы в {replay_dir}"
        if strategy:
            error_msg += f" (искали: {strategy}_portfolio_positions.csv)"
        raise FileNotFoundError(error_msg)
    
    if verbose:
        print(f"[INFO] Legacy positions: {legacy_files['positions_csv']}")
        print(f"[INFO] Legacy stats: {legacy_files['stats_json']}")
        print(f"[INFO] Legacy events: {legacy_files['events_csv']}")
        print(f"[INFO] Legacy equity: {legacy_files['equity_csv']}")
        print(f"[INFO] Replay positions: {replay_files['positions_csv']}")
        print(f"[INFO] Replay stats: {replay_files['stats_json']}")
        print(f"[INFO] Replay events: {replay_files['events_csv']}")
        print(f"[INFO] Replay equity: {replay_files['equity_csv']}")
        print()
    
    # Читаем данные
    legacy_positions = read_portfolio_positions_csv(legacy_files["positions_csv"])
    replay_positions = read_portfolio_positions_csv(replay_files["positions_csv"])
    
    legacy_stats = read_portfolio_stats_json(legacy_files["stats_json"]) if legacy_files["stats_json"] else None
    replay_stats = read_portfolio_stats_json(replay_files["stats_json"]) if replay_files["stats_json"] else None
    
    legacy_events = read_portfolio_events_csv(legacy_files["events_csv"]) if legacy_files["events_csv"] else []
    replay_events = read_portfolio_events_csv(replay_files["events_csv"]) if replay_files["events_csv"] else []
    
    legacy_equity = read_equity_curve_csv(legacy_files["equity_csv"]) if legacy_files["equity_csv"] else []
    replay_equity = read_equity_curve_csv(replay_files["equity_csv"]) if replay_files["equity_csv"] else []
    
    # Вычисляем метрики
    legacy_metrics = calculate_metrics(legacy_positions, legacy_stats, legacy_events, legacy_equity)
    replay_metrics = calculate_metrics(replay_positions, replay_stats, replay_events, replay_equity)
    
    # Анализируем причины закрытия
    legacy_reasons = analyze_close_reasons(legacy_positions, legacy_events)
    replay_reasons = analyze_close_reasons(replay_positions, replay_events)
    reasons_comparison = compare_close_reasons(legacy_reasons, replay_reasons)
    
    # Sanity checks (read-only диагностика)
    sanity_warnings = []
    
    # 1) Monotonic timestamps
    if legacy_events:
        legacy_ts_warnings = check_monotonic_timestamps(legacy_events, "LEGACY")
        sanity_warnings.extend(legacy_ts_warnings)
    if replay_events:
        replay_ts_warnings = check_monotonic_timestamps(replay_events, "REPLAY")
        sanity_warnings.extend(replay_ts_warnings)
    
    # 2) Reset chain correctness
    if legacy_events:
        legacy_reset_warnings = check_reset_chain_correctness(legacy_events, "LEGACY")
        sanity_warnings.extend(legacy_reset_warnings)
    if replay_events:
        replay_reset_warnings = check_reset_chain_correctness(replay_events, "REPLAY")
        sanity_warnings.extend(replay_reset_warnings)
    
    # 3) Positions-events consistency
    if legacy_positions or legacy_events:
        legacy_consistency_warnings = check_positions_events_consistency(
            legacy_positions, legacy_events, "LEGACY"
        )
        sanity_warnings.extend(legacy_consistency_warnings)
    if replay_positions or replay_events:
        replay_consistency_warnings = check_positions_events_consistency(
            replay_positions, replay_events, "REPLAY"
        )
        sanity_warnings.extend(replay_consistency_warnings)
    
    # Анализируем strategy_trades.csv (если указан путь)
    blueprints_stats = None
    if strategy_trades_path:
        blueprints_stats = analyze_strategy_trades_csv(strategy_trades_path)
    
    # Выводим summary diff
    diff_output = print_summary_diff(
        legacy_metrics, replay_metrics, legacy_dir, replay_dir,
        reasons_comparison, verbose, sanity_warnings, blueprints_stats
    )
    
    return diff_output


def main():
    parser = argparse.ArgumentParser(
        description="Сравнение результатов legacy vs replay (Этап 2.5)"
    )
    parser.add_argument(
        "--legacy-dir",
        type=Path,
        required=True,
        help="Директория с legacy отчетами (содержит portfolio_*.csv)"
    )
    parser.add_argument(
        "--replay-dir",
        type=Path,
        required=True,
        help="Директория с replay отчетами (содержит portfolio_*.csv)"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Путь для сохранения summary diff (optional, поддерживает .md и .txt)"
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default=None,
        help="Опциональный фильтр по имени стратегии"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Вывести детальную информацию"
    )
    parser.add_argument(
        "--strategy-trades",
        type=Path,
        default=None,
        help="Путь к strategy_trades.csv для анализа blueprints (опционально)"
    )
    
    args = parser.parse_args()
    
    try:
        diff_output = compare_legacy_vs_replay(
            args.legacy_dir, args.replay_dir, args.strategy, args.verbose, args.strategy_trades
        )
        print(diff_output)
        
        # Сохраняем в файл, если указан
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with open(args.out, 'w', encoding='utf-8') as f:
                f.write(diff_output)
            print(f"\n[INFO] Summary diff сохранен в {args.out}")
        
        return 0
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        return 1
    except Exception as e:
        print(f"[ERROR] Неожиданная ошибка: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())

