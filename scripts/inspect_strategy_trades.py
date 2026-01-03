#!/usr/bin/env python3
"""
Санитарная проверка StrategyTradeBlueprint (Этап 1.5).

ЧТО ДЕЛАЕТ:
    Читает strategy_trades.csv и выводит сводную статистику по blueprints стратегий.
    Анализирует распределение по причинам выхода, количество partial exits,
    realized multiple и максимальные достигнутые уровни.

ЗАЧЕМ НУЖЕН:
    Визуально и количественно понять, что именно делают стратегии.
    Проверить повторяемость и адекватность blueprints перед переходом к Этапу 2 (PortfolioReplay).
    Зафиксировать примеры трейдов как эталон для последующего сравнения.

КОГДА ИСПОЛЬЗУЕТСЯ:
    ЭТАП 1.5 — "Санитарная проверка" после завершения Этапа 1.
    Запускается после backtest run для анализа сгенерированного strategy_trades.csv.

ИСПОЛЬЗОВАНИЕ:
    python scripts/inspect_strategy_trades.py
    python scripts/inspect_strategy_trades.py path/to/strategy_trades.csv
"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

# Путь к strategy_trades.csv (можно переопределить через argv)
DEFAULT_CSV_PATH = "output/reports/strategy_trades.csv"


def parse_float(value):
    """Безопасный парсинг float из CSV."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def parse_json_field(value):
    """Безопасный парсинг JSON поля (может быть пустым)."""
    if not value or value == "":
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def count_partial_exits(partial_exits_json_str):
    """Подсчитывает количество partial exits из JSON строки."""
    if not partial_exits_json_str or partial_exits_json_str == "":
        return 0
    parsed = parse_json_field(partial_exits_json_str)
    if parsed is None:
        return 0
    if isinstance(parsed, list):
        return len(parsed)
    return 0


def has_final_exit(final_exit_json_str):
    """Проверяет наличие final_exit (не пустой JSON)."""
    if not final_exit_json_str or final_exit_json_str == "":
        return False
    parsed = parse_json_field(final_exit_json_str)
    return parsed is not None


def main():
    # Определяем путь к CSV (аргумент командной строки или дефолт)
    if len(sys.argv) > 1:
        csv_path = Path(sys.argv[1])
    else:
        csv_path = Path(DEFAULT_CSV_PATH)
    
    # Проверяем существование файла
    if not csv_path.exists():
        print(f"ERROR: File not found: {csv_path}", file=sys.stderr)
        print(f"Usage: python {sys.argv[0]} [path/to/strategy_trades.csv]", file=sys.stderr)
        sys.exit(1)
    
    # Читаем CSV
    blueprints = []
    try:
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            blueprints = list(reader)
    except Exception as e:
        print(f"ERROR: Failed to read CSV: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Проверяем пустой файл
    if not blueprints:
        print("=" * 35)
        print("Strategy Trades Inspection")
        print("=" * 35)
        print(f"\nFile: {csv_path}")
        print("\n⚠️  File is empty (no blueprints)")
        print("\n" + "=" * 35)
        return
    
    # Собираем статистику
    total_blueprints = len(blueprints)
    blueprints_with_final_exit = 0
    reasons = []
    partial_exits_counts = []
    realized_multiples = []
    max_xn_reached_values = []
    
    for row in blueprints:
        # Проверяем final_exit
        final_exit_json_str = row.get("final_exit_json", "")
        if has_final_exit(final_exit_json_str):
            blueprints_with_final_exit += 1
        
        # Собираем reason
        reason = row.get("reason", "unknown")
        if reason:
            reasons.append(reason)
        
        # Подсчитываем partial_exits
        partial_exits_json_str = row.get("partial_exits_json", "")
        count = count_partial_exits(partial_exits_json_str)
        partial_exits_counts.append(count)
        
        # Собираем realized_multiple
        realized_multiple = parse_float(row.get("realized_multiple"))
        if realized_multiple is not None:
            realized_multiples.append(realized_multiple)
        
        # Собираем max_xn_reached
        max_xn = parse_float(row.get("max_xn_reached"))
        if max_xn is not None:
            max_xn_reached_values.append(max_xn)
    
    # Вычисляем статистику
    reason_distribution = Counter(reasons)
    
    avg_partial_exits = 0.0
    if partial_exits_counts:
        avg_partial_exits = sum(partial_exits_counts) / len(partial_exits_counts)
    
    min_realized_multiple = None
    max_realized_multiple = None
    if realized_multiples:
        min_realized_multiple = min(realized_multiples)
        max_realized_multiple = max(realized_multiples)
    
    # Топ-3 max_xn_reached
    top_max_xn = sorted(max_xn_reached_values, reverse=True)[:3] if max_xn_reached_values else []
    
    # Выводим статистику (диагностический вывод, красота важнее компактности)
    print("=" * 35)
    print("Strategy Trades Inspection")
    print("=" * 35)
    
    print(f"\nTotal blueprints: {total_blueprints}")
    
    blueprints_without_final_exit = total_blueprints - blueprints_with_final_exit
    print(f"With final exit: {blueprints_with_final_exit}")
    print(f"Without final exit: {blueprints_without_final_exit}")
    
    print(f"\nReasons distribution:")
    if reason_distribution:
        for reason, count in reason_distribution.most_common():
            print(f"- {reason}: {count}")
    else:
        print("- (no data)")
    
    print(f"\nPartial exits:")
    if partial_exits_counts:
        print(f"- avg: {avg_partial_exits:.1f}")
        print(f"- min: {min(partial_exits_counts)}")
        print(f"- max: {max(partial_exits_counts)}")
    else:
        print("- (no data)")
    
    print(f"\nRealized multiple:")
    if min_realized_multiple is not None and max_realized_multiple is not None:
        print(f"- min: {min_realized_multiple:.2f}")
        print(f"- max: {max_realized_multiple:.2f}")
    else:
        print("- (no data)")
    
    print(f"\nTop max_xn_reached:")
    if top_max_xn:
        for xn in top_max_xn:
            print(f"- {xn:.1f}")
    else:
        print("- (no data)")
    
    print("\n" + "=" * 35)


if __name__ == "__main__":
    main()

