# backtester/infrastructure/reporter.py

from __future__ import annotations

from typing import List, Dict, Any, Optional
import json
import csv
import statistics
from pathlib import Path
from datetime import datetime
from collections import Counter

import numpy as np
from .xlsx_writer import save_xlsx
from .reporting.report_pack import build_report_pack_xlsx
from ..domain.strategy_trade_blueprint import StrategyTradeBlueprint


class Reporter:
    def __init__(self, output_dir: str = "output/reports"):
        """
        Инициализирует репортер, который сохраняет результаты бэктеста в различные форматы.

        :param output_dir: Папка, куда будут сохраняться отчеты.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.charts_dir = self.output_dir.parent / "charts"
        self.charts_dir.mkdir(parents=True, exist_ok=True)

    def calculate_metrics(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Вычисляет все метрики для списка результатов.

        :param results: Список словарей с результатами по сигналам.
        :return: Словарь с метриками.
        """
        if not results:
            return {
                "total_trades": 0,
                "winrate": 0.0,
                "total_pnl": 0.0,
                "avg_pnl": 0.0,
                "median_pnl": 0.0,
            }

        # Фильтруем только сделки с входом (исключаем no_entry и error)
        trades = [
            r for r in results
            if r["result"].entry_time is not None and r["result"].reason not in ("no_entry", "error")
        ]

        if not trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "winrate": 0.0,
                "total_pnl": 0.0,
                "avg_pnl": 0.0,
                "median_pnl": 0.0,
                "best_trade": 0.0,
                "worst_trade": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown": 0.0,
                "profit_factor": 0.0,
                "avg_trade_duration_hours": 0.0,
                "exit_reasons": {},
                "source_distribution": {},
                "narrative_distribution": {},
            }

        pnls = [r["result"].pnl for r in trades]
        winning_pnls = [p for p in pnls if p > 0]
        losing_pnls = [p for p in pnls if p < 0]

        # Базовые метрики
        total_trades = len(trades)
        winning_trades = len(winning_pnls)
        losing_trades = len(losing_pnls)
        winrate = winning_trades / total_trades if total_trades > 0 else 0.0
        total_pnl = sum(pnls)
        avg_pnl = statistics.mean(pnls) if pnls else 0.0
        median_pnl = statistics.median(pnls) if pnls else 0.0
        best_trade = max(pnls) if pnls else 0.0
        worst_trade = min(pnls) if pnls else 0.0

        # Sharpe ratio (годовая, предполагая 252 торговых дня)
        if len(pnls) > 1:
            returns_std = statistics.stdev(pnls) if len(pnls) > 1 else 0.0
            sharpe_ratio = (avg_pnl / returns_std * np.sqrt(252)) if returns_std > 0 else 0.0
        else:
            sharpe_ratio = 0.0

        # Max drawdown (кумулятивный)
        cumulative_pnl = np.cumsum(pnls)
        running_max = np.maximum.accumulate(cumulative_pnl)
        drawdowns = cumulative_pnl - running_max
        max_drawdown = min(drawdowns) if len(drawdowns) > 0 else 0.0

        # Profit factor
        total_profit = sum(winning_pnls) if winning_pnls else 0.0
        total_loss = abs(sum(losing_pnls)) if losing_pnls else 0.0
        profit_factor = total_profit / total_loss if total_loss > 0 else (float('inf') if total_profit > 0 else 0.0)

        # Средняя длительность сделки
        durations = []
        for r in trades:
            if r["result"].entry_time and r["result"].exit_time:
                duration = (r["result"].exit_time - r["result"].entry_time).total_seconds() / 3600
                durations.append(duration)
        avg_trade_duration_hours = statistics.mean(durations) if durations else 0.0

        # Распределение по причинам выхода
        exit_reasons = Counter(r["result"].reason for r in trades)

        # Распределение по источникам сигналов
        source_distribution = Counter(r.get("source", "unknown") for r in results if r.get("source"))

        # Распределение по narrative
        narrative_distribution = Counter(r.get("narrative", "unknown") for r in results if r.get("narrative"))

        return {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "winrate": winrate,
            "total_pnl": total_pnl,
            "avg_pnl": avg_pnl,
            "median_pnl": median_pnl,
            "best_trade": best_trade,
            "worst_trade": worst_trade,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown": max_drawdown,
            "profit_factor": profit_factor,
            "avg_trade_duration_hours": avg_trade_duration_hours,
            "exit_reasons": dict(exit_reasons),
            "source_distribution": dict(source_distribution),
            "narrative_distribution": dict(narrative_distribution),
        }

    def generate_summary_report(self, strategy_name: str, metrics: Dict[str, Any]) -> str:
        """
        Генерирует текстовый отчет с метриками.

        :param strategy_name: Название стратегии.
        :param metrics: Словарь с метриками.
        :return: Текст отчета.
        """
        lines = [
            f"=== Backtest Report: {strategy_name} ===",
            "",
            "⚠️  NOTE: This is STRATEGY-LEVEL report (individual trades).",
            "    Total PnL is the sum of percentages, NOT portfolio return.",
            "    For REAL portfolio return, see Portfolio-level reports.",
            "",
            "Basic Metrics:",
            f"  Total Trades: {metrics['total_trades']}",
            f"  Winning Trades: {metrics['winning_trades']}",
            f"  Losing Trades: {metrics['losing_trades']}",
            f"  Winrate: {metrics['winrate']:.2%}",
            f"  Total PnL (sum of %): {metrics['total_pnl']:.2%} ⚠️ Not portfolio return!",
            f"  Average PnL: {metrics['avg_pnl']:.2%}",
            f"  Median PnL: {metrics['median_pnl']:.2%}",
            f"  Best Trade: {metrics['best_trade']:.2%}",
            f"  Worst Trade: {metrics['worst_trade']:.2%}",
            "",
            "Advanced Metrics:",
            f"  Sharpe Ratio: {metrics['sharpe_ratio']:.2f}",
            f"  Max Drawdown: {metrics['max_drawdown']:.2%}",
            f"  Profit Factor: {metrics['profit_factor']:.2f}",
            f"  Avg Trade Duration: {metrics['avg_trade_duration_hours']:.2f} hours",
            "",
            "Exit Reasons:",
        ]
        
        for reason, count in metrics['exit_reasons'].items():
            lines.append(f"  {reason}: {count}")
        
        lines.extend([
            "",
            "Signal Source Distribution:",
        ])
        
        for source, count in metrics['source_distribution'].items():
            lines.append(f"  {source}: {count}")
        
        lines.extend([
            "",
            "Narrative Distribution:",
        ])
        
        for narrative, count in metrics['narrative_distribution'].items():
            lines.append(f"  {narrative}: {count}")
        
        return "\n".join(lines)

    def save_results(self, strategy_name: str, results: List[Dict[str, Any]]) -> None:
        """
        Сохраняет результаты бэктеста по конкретной стратегии в отдельный JSON-файл.

        :param strategy_name: Название стратегии (используется в имени файла).
        :param results: Список словарей с результатами по сигналам.
        """
        out_path = self.output_dir / f"{strategy_name}.json"
        
        # Сериализуем результаты для JSON
        json_results = []
        for row in results:
            r = row["result"]
            json_results.append({
                "signal_id": row["signal_id"],
                "contract_address": row["contract_address"],
                "timestamp": row["timestamp"].isoformat() if isinstance(row["timestamp"], datetime) else str(row["timestamp"]),
                "entry_time": r.entry_time.isoformat() if r.entry_time else None,
                "entry_price": r.entry_price,
                "exit_time": r.exit_time.isoformat() if r.exit_time else None,
                "exit_price": r.exit_price,
                "pnl": r.pnl,
                "reason": r.reason,
                "meta": r.meta,
            })
        
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(json_results, f, ensure_ascii=False, indent=2)

    def save_csv_report(self, strategy_name: str, results: List[Dict[str, Any]]) -> None:
        """
        Сохраняет результаты в CSV формат.

        :param strategy_name: Название стратегии.
        :param results: Список словарей с результатами по сигналам.
        """
        import pandas as pd
        
        csv_data = []
        for row in results:
            r = row["result"]
            csv_data.append({
                "signal_id": row["signal_id"],
                "contract_address": row["contract_address"],
                "timestamp": row["timestamp"],
                "entry_time": r.entry_time,
                "entry_price": r.entry_price,
                "exit_time": r.exit_time,
                "exit_price": r.exit_price,
                "pnl": r.pnl,
                "pnl_pct": r.pnl * 100,
                "reason": r.reason,
            })
        
        df = pd.DataFrame(csv_data)
        csv_path = self.output_dir / f"{strategy_name}.csv"
        df.to_csv(csv_path, index=False)
        print(f"[report] Saved CSV report to {csv_path}")

    def save_trades_table(self, strategy_name: str, results: List[Dict[str, Any]]) -> None:
        """
        Сохраняет CSV таблицу сделок output/reports/{strategy_name}_trades.csv.
        
        Включает только сделки где result.entry_time != None и result.reason not in ("no_entry", "error").
        Расплющивает meta: скаляры (int/float/str/bool) как есть, dict/list сериализует в JSON-строку.
        Даже если сделок 0 — файл всё равно создается (с заголовками).
        
        :param strategy_name: Название стратегии (используется в имени файла).
        :param results: Список словарей с результатами по сигналам.
        """
        import pandas as pd
        
        # Фильтруем только сделки с входом (исключаем no_entry и error)
        trades = [
            row for row in results
            if row["result"].entry_time is not None 
            and row["result"].reason not in ("no_entry", "error")
        ]
        
        if not trades:
            # Создаём пустой DataFrame с базовыми колонками
            csv_path = self.output_dir / f"{strategy_name}_trades.csv"
            pd.DataFrame([], columns=[  # type: ignore[arg-type]
                "signal_id", "contract_address", "signal_timestamp",
                "entry_time", "exit_time", "entry_price", "exit_price",
                "pnl_pct", "reason", "source", "narrative"
            ]).to_csv(csv_path, index=False)
            print(f"📄 Saved trades table to {csv_path}")
            return
        
        # Создаём список строк для CSV
        csv_rows = []
        for row in trades:
            r = row["result"]
            
            # Базовые поля
            csv_row = {
                "signal_id": row["signal_id"],
                "contract_address": row["contract_address"],
                "signal_timestamp": row["timestamp"],
                "entry_time": r.entry_time,
                "exit_time": r.exit_time,
                "entry_price": r.entry_price,
                "exit_price": r.exit_price,
                "pnl_pct": r.pnl * 100,  # Конвертируем в проценты
                "reason": r.reason,
                "source": row.get("source"),
                "narrative": row.get("narrative"),
            }
            
            # Расплющиваем meta
            if r.meta:
                for key, value in r.meta.items():
                    # Если значение - словарь или список, преобразуем в JSON string
                    if isinstance(value, (dict, list)):
                        csv_row[f"meta_{key}"] = json.dumps(value, ensure_ascii=False)
                    else:
                        # Скалярные значения (int/float/str/bool) добавляем как есть
                        csv_row[f"meta_{key}"] = value
            
            csv_rows.append(csv_row)
        
        # Создаём DataFrame и сохраняем
        df = pd.DataFrame(csv_rows)
        csv_path = self.output_dir / f"{strategy_name}_trades.csv"
        df.to_csv(csv_path, index=False)
        print(f"📄 Saved trades table to {csv_path}")

    def generate_html_report(self, strategy_name: str, metrics: Dict[str, Any], results: List[Dict[str, Any]]) -> None:
        """
        Генерирует HTML отчет с метриками и графиками.

        :param strategy_name: Название стратегии.
        :param metrics: Словарь с метриками.
        :param results: Список результатов для детализации.
        """
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Backtest Report: {strategy_name}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        h2 {{ color: #666; margin-top: 30px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        .metric {{ margin: 10px 0; }}
        .positive {{ color: green; }}
        .negative {{ color: red; }}
    </style>
</head>
<body>
    <h1>Backtest Report: {strategy_name}</h1>
    
    <div style="background-color: #fff3cd; border: 1px solid #ffc107; padding: 10px; margin: 20px 0; border-radius: 5px;">
        <strong>⚠️ Important:</strong> This is a <strong>STRATEGY-LEVEL</strong> report showing individual trades.
        <br><strong>Total PnL</strong> is the <strong>sum of percentages</strong>, NOT the real portfolio return.
        <br>For <strong>real portfolio return</strong> with position sizing, fees, and dynamic balance, see <strong>Portfolio-level reports</strong>.
    </div>
    
    <h2>Basic Metrics</h2>
    <table>
        <tr><th>Metric</th><th>Value</th></tr>
        <tr><td>Total Trades</td><td>{metrics['total_trades']}</td></tr>
        <tr><td>Winning Trades</td><td>{metrics['winning_trades']}</td></tr>
        <tr><td>Losing Trades</td><td>{metrics['losing_trades']}</td></tr>
        <tr><td>Winrate</td><td>{metrics['winrate']:.2%}</td></tr>
        <tr><td>Total PnL (sum of %) ⚠️</td><td class="{'positive' if metrics['total_pnl'] >= 0 else 'negative'}">{metrics['total_pnl']:.2%}</td></tr>
        <tr><td>Average PnL</td><td class="{'positive' if metrics['avg_pnl'] >= 0 else 'negative'}">{metrics['avg_pnl']:.2%}</td></tr>
        <tr><td>Median PnL</td><td class="{'positive' if metrics['median_pnl'] >= 0 else 'negative'}">{metrics['median_pnl']:.2%}</td></tr>
        <tr><td>Best Trade</td><td class="positive">{metrics['best_trade']:.2%}</td></tr>
        <tr><td>Worst Trade</td><td class="negative">{metrics['worst_trade']:.2%}</td></tr>
    </table>
    
    <h2>Advanced Metrics</h2>
    <table>
        <tr><th>Metric</th><th>Value</th></tr>
        <tr><td>Sharpe Ratio</td><td>{metrics['sharpe_ratio']:.2f}</td></tr>
        <tr><td>Max Drawdown</td><td class="negative">{metrics['max_drawdown']:.2%}</td></tr>
        <tr><td>Profit Factor</td><td>{metrics['profit_factor']:.2f}</td></tr>
        <tr><td>Avg Trade Duration</td><td>{metrics['avg_trade_duration_hours']:.2f} hours</td></tr>
    </table>
    
    <h2>Exit Reasons</h2>
    <table>
        <tr><th>Reason</th><th>Count</th></tr>
"""
        
        for reason, count in metrics['exit_reasons'].items():
            html_content += f"        <tr><td>{reason}</td><td>{count}</td></tr>\n"
        
        html_content += """    </table>
    
    <h2>Signal Source Distribution</h2>
    <table>
        <tr><th>Source</th><th>Count</th></tr>
"""
        
        for source, count in metrics['source_distribution'].items():
            html_content += f"        <tr><td>{source}</td><td>{count}</td></tr>\n"
        
        html_content += """    </table>
    
    <p><small>Report generated at: """ + datetime.now().isoformat() + """</small></p>
</body>
</html>
"""
        
        html_path = self.output_dir / f"{strategy_name}.html"
        with html_path.open("w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"[report] Saved HTML report to {html_path}")

    def plot_equity_curve(self, results: List[Dict[str, Any]], strategy_name: str) -> Optional[Path]:
        """
        Строит график equity curve (кумулятивный PnL по времени).

        :param results: Список результатов.
        :param strategy_name: Название стратегии.
        :return: Путь к сохраненному файлу графика.
        """
        try:
            import matplotlib.pyplot as plt
            
            # Фильтруем только сделки с входом
            trades = [
                r for r in results
                if r["result"].entry_time is not None and r["result"].reason not in ("no_entry", "error")
            ]
            
            if not trades:
                return None
            
            # Сортируем по времени входа
            trades_sorted = sorted(trades, key=lambda x: x["result"].entry_time or datetime.min)
            
            # Вычисляем кумулятивный PnL
            pnls = [r["result"].pnl for r in trades_sorted]
            cumulative_pnl = np.cumsum(pnls)
            
            # Временные метки для оси X
            timestamps = [r["result"].entry_time for r in trades_sorted]
            
            plt.figure(figsize=(12, 6))
            plt.plot(timestamps, cumulative_pnl * 100, linewidth=2)
            plt.title(f"Equity Curve: {strategy_name}")
            plt.xlabel("Time")
            plt.ylabel("Cumulative PnL (%)")
            plt.grid(True, alpha=0.3)
            plt.axhline(y=0, color='r', linestyle='--', alpha=0.5)
            
            output_path = self.charts_dir / f"{strategy_name}_equity_curve.png"
            plt.savefig(output_path, dpi=150, bbox_inches='tight')
            plt.close()
            
            return output_path
        except ImportError:
            print("[WARNING] matplotlib not available, skipping equity curve plot")
            return None
        except Exception as e:
            print(f"[WARNING] Failed to plot equity curve: {e}")
            return None

    def plot_pnl_distribution(self, results: List[Dict[str, Any]], strategy_name: str) -> Optional[Path]:
        """
        Строит гистограмму распределения PnL.

        :param results: Список результатов.
        :param strategy_name: Название стратегии.
        :return: Путь к сохраненному файлу графика.
        """
        try:
            import matplotlib.pyplot as plt
            
            trades = [
                r for r in results
                if r["result"].entry_time is not None and r["result"].reason not in ("no_entry", "error")
            ]
            
            if not trades:
                return None
            
            pnls = [r["result"].pnl * 100 for r in trades]
            
            plt.figure(figsize=(10, 6))
            plt.hist(pnls, bins=30, edgecolor='black', alpha=0.7)
            plt.axvline(x=0, color='r', linestyle='--', alpha=0.5)
            plt.title(f"PnL Distribution: {strategy_name}")
            plt.xlabel("PnL (%)")
            plt.ylabel("Frequency")
            plt.grid(True, alpha=0.3)
            
            output_path = self.charts_dir / f"{strategy_name}_pnl_distribution.png"
            plt.savefig(output_path, dpi=150, bbox_inches='tight')
            plt.close()
            
            return output_path
        except ImportError:
            return None
        except Exception as e:
            print(f"[WARNING] Failed to plot PnL distribution: {e}")
            return None

    def plot_exit_reasons(self, metrics: Dict[str, Any], strategy_name: str) -> Optional[Path]:
        """
        Строит pie chart распределения по причинам выхода.

        :param metrics: Словарь с метриками.
        :param strategy_name: Название стратегии.
        :return: Путь к сохраненному файлу графика.
        """
        try:
            import matplotlib.pyplot as plt
            
            if not metrics.get('exit_reasons'):
                return None
            
            reasons = list(metrics['exit_reasons'].keys())
            counts = list(metrics['exit_reasons'].values())
            
            plt.figure(figsize=(8, 8))
            plt.pie(counts, labels=reasons, autopct='%1.1f%%', startangle=90)
            plt.title(f"Exit Reasons Distribution: {strategy_name}")
            
            output_path = self.charts_dir / f"{strategy_name}_exit_reasons.png"
            plt.savefig(output_path, dpi=150, bbox_inches='tight')
            plt.close()
            
            return output_path
        except ImportError:
            return None
        except Exception as e:
            print(f"[WARNING] Failed to plot exit reasons: {e}")
            return None

    def plot_trades_timeline(self, results: List[Dict[str, Any]], strategy_name: str) -> Optional[Path]:
        """
        Строит scatter plot временной динамики сделок (entry/exit).

        :param results: Список результатов.
        :param strategy_name: Название стратегии.
        :return: Путь к сохраненному файлу графика.
        """
        try:
            import matplotlib.pyplot as plt
            
            trades = [
                r for r in results
                if r["result"].entry_time is not None and r["result"].exit_time is not None
                and r["result"].reason not in ("no_entry", "error")
            ]
            
            if not trades:
                return None
            
            entry_times = [r["result"].entry_time for r in trades]
            exit_times = [r["result"].exit_time for r in trades]
            pnls = [r["result"].pnl * 100 for r in trades]
            
            # Цвета в зависимости от PnL
            colors = ['green' if p >= 0 else 'red' for p in pnls]
            
            plt.figure(figsize=(14, 6))
            plt.scatter(entry_times, pnls, c=colors, alpha=0.6, s=50, label='Entry')
            plt.scatter(exit_times, pnls, c=colors, alpha=0.6, s=50, marker='x', label='Exit')
            
            # Соединяем entry и exit для каждой сделки
            for i in range(len(trades)):
                plt.plot([entry_times[i], exit_times[i]], [pnls[i], pnls[i]], 
                        'k-', alpha=0.2, linewidth=0.5)
            
            plt.axhline(y=0, color='black', linestyle='-', alpha=0.3)
            plt.title(f"Trades Timeline: {strategy_name}")
            plt.xlabel("Time")
            plt.ylabel("PnL (%)")
            plt.legend()
            plt.grid(True, alpha=0.3)
            plt.xticks(rotation=45)
            
            output_path = self.charts_dir / f"{strategy_name}_trades_timeline.png"
            plt.savefig(output_path, dpi=150, bbox_inches='tight')
            plt.close()
            
            return output_path
        except ImportError:
            return None
        except Exception as e:
            print(f"[WARNING] Failed to plot trades timeline: {e}")
            return None

    def generate_full_report(self, strategy_name: str, results: List[Dict[str, Any]]) -> None:
        """
        Генерирует полный отчет со всеми метриками, графиками и форматами.

        :param strategy_name: Название стратегии.
        :param results: Список результатов.
        """
        # Вычисляем метрики
        metrics = self.calculate_metrics(results)
        
        # Сохраняем JSON
        self.save_results(strategy_name, results)
        
        # Сохраняем CSV
        self.save_csv_report(strategy_name, results)
        
        # Генерируем HTML отчет
        self.generate_html_report(strategy_name, metrics, results)
        
        # Строим графики
        self.plot_equity_curve(results, strategy_name)
        self.plot_pnl_distribution(results, strategy_name)
        self.plot_exit_reasons(metrics, strategy_name)
        self.plot_trades_timeline(results, strategy_name)
        
        # Выводим текстовый отчет
        summary = self.generate_summary_report(strategy_name, metrics)
        print(f"\n{summary}\n")

    def save_portfolio_results(self, strategy_name: str, portfolio_result) -> None:
        """
        Сохраняет портфельные результаты в JSON и CSV форматы.

        :param strategy_name: Название стратегии.
        :param portfolio_result: PortfolioResult объект.
        """
        from ..domain.portfolio import PortfolioResult
        
        if not isinstance(portfolio_result, PortfolioResult):
            return
        
        # Сохраняем equity curve в CSV
        import pandas as pd
        # Фильтруем записи с валидными timestamp
        valid_equity = [
            point for point in portfolio_result.equity_curve
            if point.get("timestamp") is not None
        ]
        if valid_equity:
            equity_df = pd.DataFrame(valid_equity)
            equity_path = self.output_dir / f"{strategy_name}_equity_curve.csv"
            equity_df.to_csv(equity_path, index=False)
            print(f"[chart] Saved equity curve to {equity_path}")
        
        # Сохраняем позиции в CSV
        positions_data = []
        for pos in portfolio_result.positions:
            positions_data.append({
                "position_id": pos.position_id,
                "signal_id": pos.signal_id,
                "contract_address": pos.contract_address,
                "entry_time": pos.entry_time.isoformat() if pos.entry_time else None,
                "entry_price": pos.entry_price,
                "exit_time": pos.exit_time.isoformat() if pos.exit_time else None,
                "exit_price": pos.exit_price,
                "size_sol": pos.meta.get("original_size", pos.size) if pos.meta else pos.size,
                "pnl_pct": pos.pnl_pct,
                "pnl_sol": pos.meta.get("pnl_sol", 0.0) if pos.meta else 0.0,
                "raw_pnl_pct": pos.meta.get("raw_pnl_pct", 0.0) if pos.meta else 0.0,
                "fee_pct": pos.meta.get("fee_pct", 0.0) if pos.meta else 0.0,
                "status": pos.status,
                "reason": pos.meta.get("close_reason") if pos.meta else None,
            })
        
        if positions_data:
            positions_df = pd.DataFrame(positions_data)
            positions_path = self.output_dir / f"{strategy_name}_portfolio_positions.csv"
            positions_df.to_csv(positions_path, index=False)
            print(f"💼 Saved portfolio positions to {positions_path}")
        
        # Сохраняем статистику в JSON
        stats_data = {
            "final_balance_sol": portfolio_result.stats.final_balance_sol,
            "total_return_pct": portfolio_result.stats.total_return_pct,
            "max_drawdown_pct": portfolio_result.stats.max_drawdown_pct,
            "trades_executed": portfolio_result.stats.trades_executed,
            "trades_skipped_by_risk": portfolio_result.stats.trades_skipped_by_risk,
        }
        
        stats_path = self.output_dir / f"{strategy_name}_portfolio_stats.json"
        with stats_path.open("w", encoding="utf-8") as f:
            json.dump(stats_data, f, indent=2, ensure_ascii=False)
        print(f"[report] Saved portfolio stats to {stats_path}")
        
        # Строим график equity curve портфеля
        self.plot_portfolio_equity_curve(strategy_name, portfolio_result)

    def save_portfolio_results_xlsx(self, strategy_name: str, portfolio_result) -> None:
        """
        Сохраняет портфельные результаты в XLSX формат с несколькими листами.
        
        Листы:
        - positions: таблица позиций
        - equity_curve: кривая equity
        - stats: статистика портфеля
        
        :param strategy_name: Название стратегии.
        :param portfolio_result: PortfolioResult объект.
        """
        from ..domain.portfolio import PortfolioResult
        
        if not isinstance(portfolio_result, PortfolioResult):
            return
        
        import pandas as pd
        
        # Подготавливаем данные для листов
        sheets = {}
        
        # Лист 1: Positions
        positions_data = []
        for pos in portfolio_result.positions:
            positions_data.append({
                "position_id": pos.position_id,
                "signal_id": pos.signal_id,
                "contract_address": pos.contract_address,
                "entry_time": pos.entry_time.isoformat() if pos.entry_time else None,
                "entry_price": pos.entry_price,
                "exit_time": pos.exit_time.isoformat() if pos.exit_time else None,
                "exit_price": pos.exit_price,
                "size_sol": pos.meta.get("original_size", pos.size) if pos.meta else pos.size,
                "pnl_pct": pos.pnl_pct,
                "pnl_sol": pos.meta.get("pnl_sol", 0.0) if pos.meta else 0.0,
                "raw_pnl_pct": pos.meta.get("raw_pnl_pct", 0.0) if pos.meta else 0.0,
                "fee_pct": pos.meta.get("fee_pct", 0.0) if pos.meta else 0.0,
                "status": pos.status,
                "reason": pos.meta.get("close_reason") if pos.meta else None,
            })
        
        if positions_data:
            sheets["positions"] = pd.DataFrame(positions_data)
        else:
            # Пустой DataFrame с правильными колонками
            sheets["positions"] = pd.DataFrame(
                [], columns=pd.Index([
                    "position_id", "signal_id", "contract_address", "entry_time", "entry_price",
                    "exit_time", "exit_price", "size_sol", "pnl_pct", "pnl_sol",
                    "raw_pnl_pct", "fee_pct", "status", "reason"
                ])
            )
        
        # Лист 2: Equity Curve
        valid_equity = [
            point for point in portfolio_result.equity_curve
            if point.get("timestamp") is not None
        ]
        if valid_equity:
            sheets["equity_curve"] = pd.DataFrame(valid_equity)
        else:
            sheets["equity_curve"] = pd.DataFrame([], columns=pd.Index(["timestamp", "balance"]))  # type: ignore[call-overload]
        
        # Лист 3: Stats
        stats_data = {
            "final_balance_sol": [portfolio_result.stats.final_balance_sol],
            "total_return_pct": [portfolio_result.stats.total_return_pct],
            "max_drawdown_pct": [portfolio_result.stats.max_drawdown_pct],
            "trades_executed": [portfolio_result.stats.trades_executed],
            "trades_skipped_by_risk": [portfolio_result.stats.trades_skipped_by_risk],
            "trades_skipped_by_reset": [getattr(portfolio_result.stats, 'trades_skipped_by_reset', 0)],
            "portfolio_reset_count": [getattr(portfolio_result.stats, 'portfolio_reset_count', 0)],
            "portfolio_reset_profit_count": [getattr(portfolio_result.stats, 'portfolio_reset_profit_count', 0)],
            "portfolio_reset_capacity_count": [getattr(portfolio_result.stats, 'portfolio_reset_capacity_count', 0)],
        }
        sheets["stats"] = pd.DataFrame(stats_data)
        
        # Сохраняем XLSX
        xlsx_path = self.output_dir / f"{strategy_name}_portfolio_report.xlsx"
        save_xlsx(xlsx_path, sheets)

    def plot_portfolio_equity_curve(self, strategy_name: str, portfolio_result) -> Optional[Path]:
        """
        Строит график equity curve портфеля.

        :param strategy_name: Название стратегии.
        :param portfolio_result: PortfolioResult объект.
        :return: Путь к сохраненному файлу графика.
        """
        try:
            import matplotlib.pyplot as plt
            
            if not portfolio_result.equity_curve:
                return None
            
            timestamps = [point["timestamp"] for point in portfolio_result.equity_curve if point.get("timestamp")]
            balances = [point["balance"] for point in portfolio_result.equity_curve if point.get("timestamp")]
            
            if not timestamps:
                return None
            
            plt.figure(figsize=(14, 6))
            plt.plot(timestamps, balances, linewidth=2, label="Portfolio Balance")
            plt.axhline(y=portfolio_result.stats.final_balance_sol, color='r', linestyle='--', alpha=0.5, label=f"Final: {portfolio_result.stats.final_balance_sol:.4f} SOL")
            plt.title(f"Portfolio Equity Curve: {strategy_name}")
            plt.xlabel("Time")
            plt.ylabel("Balance (SOL)")
            plt.grid(True, alpha=0.3)
            plt.legend()
            plt.xticks(rotation=45)
            
            output_path = self.charts_dir / f"{strategy_name}_portfolio_equity.png"
            plt.savefig(output_path, dpi=150, bbox_inches='tight')
            plt.close()
            
            print(f"[chart] Saved portfolio equity curve chart to {output_path}")
            return output_path
        except ImportError:
            print("[WARNING] matplotlib not available, skipping portfolio equity curve plot")
            return None
        except Exception as e:
            print(f"[WARNING] Failed to plot portfolio equity curve: {e}")
            return None

    def compute_max_xn_reached(self, pos) -> Optional[float]:
        """
        Вычисляет максимальный достигнутый XN для позиции.
        
        Приоритет источников (по убыванию доверия):
        1. Runner truth: Position.meta["levels_hit"] - dict вида {"2.0": "...", "7.0": "...", ...}
        2. Fallback: ratio цен (raw_entry_price/raw_exit_price или exec_entry_price/exec_exit_price)
        
        Args:
            pos: Position объект
            
        Returns:
            Optional[float]: максимальный XN или None если данных нет
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Приоритет 1: levels_hit из meta (Runner truth)
        if pos.meta and "levels_hit" in pos.meta:
            levels_hit_raw = pos.meta["levels_hit"]
            if levels_hit_raw and isinstance(levels_hit_raw, dict):
                try:
                    # Парсим ключи как float
                    levels = []
                    for k_str in levels_hit_raw.keys():
                        try:
                            levels.append(float(k_str))
                        except (ValueError, TypeError):
                            # Пропускаем невалидные ключи
                            continue
                    
                    if levels:
                        max_xn = max(levels)
                        return max_xn
                    else:
                        logger.warning(
                            "[report] Invalid levels_hit keys for %s: %s (no valid float keys)",
                            pos.signal_id,
                            list(levels_hit_raw.keys())
                        )
                except Exception as e:
                    logger.warning(
                        "[report] Error parsing levels_hit for %s: %s",
                        pos.signal_id,
                        str(e)
                    )
        
        # Fallback: ratio цен
        # Сначала пробуем raw цены
        raw_entry_price = pos.meta.get("raw_entry_price", pos.entry_price) if pos.meta else pos.entry_price
        raw_exit_price = pos.meta.get("raw_exit_price", pos.exit_price) if pos.meta else pos.exit_price
        
        if raw_entry_price and raw_exit_price and raw_entry_price > 0:
            return raw_exit_price / raw_entry_price
        
        # Если raw цены недоступны, пробуем exec цены
        exec_entry_price = pos.meta.get("exec_entry_price", pos.entry_price) if pos.meta else pos.entry_price
        exec_exit_price = pos.meta.get("exec_exit_price", pos.exit_price) if pos.meta else pos.exit_price
        
        if exec_entry_price and exec_exit_price and exec_entry_price > 0:
            return exec_exit_price / exec_entry_price
        
        # Нет данных
        return None

    def save_portfolio_positions_table(self, portfolio_results: Dict[str, Any]) -> None:
        """
        Сохраняет positions-level таблицу для всех стратегий в CSV.
        
        Это таблица исполненных портфельных позиций (positions-level), где каждая строка = 1 Position
        (агрегат по signal_id+strategy+contract). Используется Stage A для анализа устойчивости стратегий.
        
        Обязательные колонки:
        - strategy: название стратегии
        - position_id: uuid4 hex
        - signal_id: идентификатор сигнала
        - contract_address: адрес контракта
        - entry_time: время входа (ISO)
        - exit_time: время выхода (ISO)
        - status: статус (должен быть "closed")
        - size: размер позиции в SOL
        - pnl_sol: портфельный PnL в SOL (обязательно!)
        - pnl_pct_total: PnL в процентах (percent)
        - realized_multiple: суммарный multiple из ladder fills
        - reason: каноническая причина закрытия
        - fees_total_sol: суммарные комиссии
        - exec_entry_price: исполненная цена входа (с slippage)
        - exec_exit_price: исполненная цена выхода (с slippage)
        - raw_entry_price: сырая цена входа (без slippage, для диагностики)
        - raw_exit_price: сырая цена выхода (без slippage)
        - closed_by_reset: закрыта ли позиция по reset (bool)
        - triggered_portfolio_reset: триггернула ли portfolio-level reset (bool)
        - reset_reason: причина reset (profit_reset/capacity_prune/manual_close/none)
        - hold_minutes: длительность удержания позиции в минутах
        - max_xn_reached: максимальный XN достигнутый (из levels_hit или fallback на цены)
        - hit_x2: достигнут ли XN >= 2.0 (bool)
        - hit_x5: достигнут ли XN >= 5.0 (bool)
        
        Запрещено: дублировать строки одной позиции из-за partial close.
        Positions-level = агрегат.
        
        :param portfolio_results: Словарь {strategy_name: PortfolioResult}
        """
        import pandas as pd
        from ..domain.portfolio import PortfolioResult
        
        trades_rows = []
        
        for strategy_name, portfolio_result in portfolio_results.items():
            if not isinstance(portfolio_result, PortfolioResult):
                continue
            
            for pos in portfolio_result.positions:
                # Включаем только закрытые позиции с валидными временами
                if pos.status != "closed" or not pos.entry_time or not pos.exit_time:
                    continue
                
                # Получаем pnl_sol из meta (должен быть обязательно для закрытых позиций)
                pnl_sol = pos.meta.get("pnl_sol") if pos.meta else None
                if pnl_sol is None:
                    # Fallback: вычисляем если отсутствует
                    # Но лучше гарантировать что reporter всегда пишет pnl_sol
                    if pos.pnl_pct is not None:
                        pnl_sol = pos.size * pos.pnl_pct
                    else:
                        pnl_sol = 0.0
                
                # Получаем исполненные цены из meta
                exec_entry_price = pos.meta.get("exec_entry_price", pos.entry_price) if pos.meta else pos.entry_price
                exec_exit_price = pos.meta.get("exec_exit_price", pos.exit_price) if pos.meta else pos.exit_price
                
                # Получаем сырые цены
                raw_entry_price = pos.meta.get("raw_entry_price", pos.entry_price) if pos.meta else pos.entry_price
                raw_exit_price = pos.meta.get("raw_exit_price", pos.exit_price) if pos.meta else pos.exit_price
                
                # Считаем комиссии
                network_fee_sol = pos.meta.get("network_fee_sol", 0.0) if pos.meta else 0.0
                # Полные комиссии включают network_fee при входе и выходе, плюс swap/lp fees
                # Для простоты берем из meta если есть, иначе оцениваем
                fees_total_sol = pos.meta.get("fees_total_sol")
                if fees_total_sol is None:
                    # Fallback: оцениваем через размер позиции и комиссии
                    # Это приблизительно, но лучше чем ничего
                    fees_total_sol = network_fee_sol * 2  # вход + выход
                
                # Флаги reset
                closed_by_reset = pos.meta.get("closed_by_reset", False) if pos.meta else False
                triggered_portfolio_reset = pos.meta.get("triggered_portfolio_reset", False) if pos.meta else False
                reset_reason = pos.meta.get("reset_reason", "none") if pos.meta else "none"
                close_reason = pos.meta.get("close_reason", reset_reason) if pos.meta else reset_reason
                
                # Вычисляем hold_minutes
                hold_minutes = None
                if pos.entry_time and pos.exit_time:
                    hold_delta = pos.exit_time - pos.entry_time
                    hold_minutes = int(hold_delta.total_seconds() / 60)
                
                # Вычисляем max_xn_reached (максимальный XN достигнутый)
                # Приоритет: levels_hit из meta (Runner truth), fallback на цены
                max_xn_reached = self.compute_max_xn_reached(pos)
                
                # Вычисляем hit flags
                hit_x2 = max_xn_reached is not None and max_xn_reached >= 2.0
                hit_x5 = max_xn_reached is not None and max_xn_reached >= 5.0
                
                # Вычисляем realized PnL метрики для Runner с частичными закрытиями
                # TAIL_XN_THRESHOLD = 4.0 (tail threshold для Runner)
                TAIL_XN_THRESHOLD = 4.0
                
                # realized_total_pnl_sol: суммарный realized PnL из partial_exits
                # Если partial_exits есть, суммируем все exit["pnl_sol"]
                # Иначе используем pnl_sol из meta (fallback)
                realized_total_pnl_sol = 0.0
                realized_tail_pnl_sol = 0.0
                
                if pos.meta and "partial_exits" in pos.meta:
                    partial_exits = pos.meta.get("partial_exits", [])
                    if partial_exits:
                        # Считаем realized_total_pnl_sol как сумму всех partial_exits
                        realized_total_pnl_sol = sum(exit.get("pnl_sol", 0.0) for exit in partial_exits)
                        # Считаем realized_tail_pnl_sol как сумму exit["pnl_sol"] для exit["xn"] >= 4.0
                        realized_tail_pnl_sol = sum(
                            exit.get("pnl_sol", 0.0) 
                            for exit in partial_exits 
                            if exit.get("xn", 0.0) >= TAIL_XN_THRESHOLD
                        )
                    else:
                        # partial_exits пустой список - используем fallback
                        realized_total_pnl_sol = pnl_sol
                        if max_xn_reached is not None and max_xn_reached >= TAIL_XN_THRESHOLD:
                            realized_tail_pnl_sol = pnl_sol
                        else:
                            realized_tail_pnl_sol = 0.0
                else:
                    # partial_exits отсутствует - fallback
                    realized_total_pnl_sol = pnl_sol
                    if max_xn_reached is not None and max_xn_reached >= TAIL_XN_THRESHOLD:
                        realized_tail_pnl_sol = pnl_sol
                    else:
                        realized_tail_pnl_sol = 0.0
                
                fractions_exited = pos.meta.get("fractions_exited", {}) if pos.meta else {}
                realized_multiple = pos.meta.get("realized_multiple")
                if realized_multiple is None:
                    realized_multiple = sum(
                        float(xn) * float(frac) for xn, frac in fractions_exited.items()
                    ) if fractions_exited else 1.0
                pnl_pct_total = (float(realized_multiple) - 1.0) * 100.0

                # Порядок колонок согласно ТЗ v2.0.1
                trade_row = {
                    # Идентификаторы
                    "position_id": pos.position_id,
                    "strategy": strategy_name,
                    "signal_id": pos.signal_id,
                    "contract_address": pos.contract_address,
                    # Время и статус
                    "entry_time": pos.entry_time.isoformat() if pos.entry_time else None,
                    "exit_time": pos.exit_time.isoformat() if pos.exit_time else None,
                    "status": pos.status,
                    # Размер и PnL
                    "size": pos.meta.get("original_size", pos.size) if pos.meta else pos.size,
                    "pnl_sol": pnl_sol,
                    "pnl_pct_total": pnl_pct_total,
                    "realized_multiple": realized_multiple,
                    # Причина закрытия
                    "reason": close_reason,
                    # Комиссии
                    "fees_total_sol": fees_total_sol,
                    # Execution цены
                    "exec_entry_price": exec_entry_price,
                    "exec_exit_price": exec_exit_price,
                    # Raw цены
                    "raw_entry_price": raw_entry_price,
                    "raw_exit_price": raw_exit_price,
                    # Reset флаги
                    "closed_by_reset": closed_by_reset,
                    "triggered_portfolio_reset": triggered_portfolio_reset,
                    "reset_reason": reset_reason,
                    # Время удержания
                    "hold_minutes": hold_minutes,
                    # Runner ladder метрики
                    "max_xn_reached": max_xn_reached,
                    "hit_x2": hit_x2,
                    "hit_x5": hit_x5,
                    # Realized PnL метрики
                    "realized_total_pnl_sol": realized_total_pnl_sol,
                    "realized_tail_pnl_sol": realized_tail_pnl_sol,
                }
                
                trades_rows.append(trade_row)
        
        # Создаем DataFrame
        if trades_rows:
            df = pd.DataFrame(trades_rows)
            # Убеждаемся, что порядок колонок соответствует ТЗ v2.0.1
            expected_columns = [
                "position_id", "strategy", "signal_id", "contract_address",
                "entry_time", "exit_time", "status",
                "size", "pnl_sol", "pnl_pct_total", "realized_multiple",
                "reason", "fees_total_sol",
                "exec_entry_price", "exec_exit_price",
                "raw_entry_price", "raw_exit_price",
                "closed_by_reset", "triggered_portfolio_reset", "reset_reason",
                "hold_minutes",
                "max_xn_reached", "hit_x2", "hit_x5",
                "realized_total_pnl_sol", "realized_tail_pnl_sol",
            ]
            # Добавляем отсутствующие колонки как NaN
            for col in expected_columns:
                if col not in df.columns:
                    df[col] = None
            # Переупорядочиваем колонки согласно ТЗ
            df = df[expected_columns]
            # Сортируем по entry_time для консистентности
            df["entry_time_dt"] = pd.to_datetime(df["entry_time"], utc=True)
            df = df.sort_values(by="entry_time_dt")
            df = df.drop("entry_time_dt", axis=1)
        else:
            # Создаем пустой DataFrame с правильными колонками (порядок согласно ТЗ v2.0.1)
            df = pd.DataFrame([], columns=[  # type: ignore[arg-type]
                # Идентификаторы
                "position_id", "strategy", "signal_id", "contract_address",
                # Время и статус
                "entry_time", "exit_time", "status",
                # Размер и PnL
                "size", "pnl_sol", "pnl_pct_total", "realized_multiple",
                # Причина закрытия
                "reason",
                # Комиссии
                "fees_total_sol",
                # Execution цены
                "exec_entry_price", "exec_exit_price",
                # Raw цены
                "raw_entry_price", "raw_exit_price",
                # Reset флаги
                "closed_by_reset", "triggered_portfolio_reset", "reset_reason",
                # Время удержания
                "hold_minutes",
                # Runner ladder метрики
                "max_xn_reached", "hit_x2", "hit_x5",
                # Realized PnL метрики
                "realized_total_pnl_sol", "realized_tail_pnl_sol",
            ])
        
        # Удаляем дубликаты по position_id - positions-level агрегат
        # (если есть данные)
        if not df.empty:
            df = df.drop_duplicates(subset=["position_id"], keep="first")
        
        # Сохраняем
        positions_path = self.output_dir / "portfolio_positions.csv"
        df.to_csv(positions_path, index=False)
        print(f"📊 Saved portfolio positions table to {positions_path} ({len(df)} executed positions)")
    
    def save_portfolio_events_table(self, portfolio_results: Dict[str, Any]) -> None:
        """
        Сохраняет events-level таблицу для всех стратегий в CSV (v2.0).
        
        Это таблица событий портфеля (events-level), где каждая запись = PortfolioEvent.
        Используется для отладки и анализа capacity pressure, prune, reset триггеров.
        
        Колонки:
        - timestamp: время события (ISO)
        - event_type: тип события (POSITION_OPENED, POSITION_PARTIAL_EXIT, POSITION_CLOSED, PORTFOLIO_RESET_TRIGGERED)
        - strategy: название стратегии
        - signal_id: идентификатор сигнала
        - contract_address: адрес контракта
        - position_id: идентификатор позиции
        - event_id: идентификатор события
        - reason: каноническая причина (для закрытий/reset)
        - meta_json: JSON строка с дополнительными метаданными
        
        :param portfolio_results: Словарь {strategy_name: PortfolioResult}
        """
        import pandas as pd
        from ..domain.portfolio import PortfolioResult
        from ..domain.portfolio_events import PortfolioEvent
        
        events_rows = []
        
        for strategy_name, portfolio_result in portfolio_results.items():
            if not isinstance(portfolio_result, PortfolioResult):
                continue
            
            # Получаем события из stats
            if not hasattr(portfolio_result.stats, 'portfolio_events') or not portfolio_result.stats.portfolio_events:
                continue
            
            for event in portfolio_result.stats.portfolio_events:
                if not isinstance(event, PortfolioEvent):
                    continue
                
                # Используем position_id из поля события (не из meta)
                position_id = event.position_id
                
                # Сериализуем meta в JSON
                meta_json = json.dumps(event.meta, ensure_ascii=False) if event.meta else "{}"
                
                # Порядок колонок согласно ТЗ v2.0.1
                event_row = {
                    "timestamp": event.timestamp.isoformat(),
                    "event_type": event.event_type.value,
                    "strategy": event.strategy,
                    "signal_id": event.signal_id,
                    "contract_address": event.contract_address,
                    "position_id": event.position_id,
                    "event_id": event.event_id,
                    "reason": event.reason,
                    "meta_json": meta_json,
                }
                
                events_rows.append(event_row)
        
        # Ожидаемый порядок колонок (согласно тестам)
        expected_columns = [
            "timestamp", "event_type", "strategy", "signal_id",
            "contract_address", "position_id", "event_id", "reason", "meta_json",
        ]
        
        # Создаем DataFrame
        if events_rows:
            df = pd.DataFrame(events_rows)
            # Добавляем отсутствующие колонки как None
            for col in expected_columns:
                if col not in df.columns:
                    df[col] = None
            # Переупорядочиваем колонки согласно ожидаемому порядку
            df = df.reindex(columns=expected_columns)
            # Сортируем по timestamp для консистентности
            df["timestamp_dt"] = pd.to_datetime(df["timestamp"], utc=True)
            df = df.sort_values("timestamp_dt")
            df = df.drop("timestamp_dt", axis=1)
        else:
            # Создаем пустой DataFrame с правильными колонками
            df = pd.DataFrame(columns=expected_columns)  # type: ignore[arg-type]
        
        # Сохраняем
        events_path = self.output_dir / "portfolio_events.csv"
        try:
            df.to_csv(events_path, index=False, encoding='utf-8')
            print(f"📋 Saved portfolio events table to {events_path} ({len(df)} events)")
        except Exception as e:
            # Fail-safe: если не удалось сохранить, выводим warning и продолжаем
            import warnings
            warnings.warn(f"Failed to save portfolio_events.csv: {e}. Continuing without events export.")
            print(f"[WARNING] Failed to save portfolio_events.csv: {e}. Continuing...")
    
    def save_portfolio_trades_table(self, portfolio_results: Dict[str, Any]) -> None:
        """
        Обратная совместимость: вызывает save_portfolio_positions_table.
        """
        self.save_portfolio_positions_table(portfolio_results)
    
    def save_portfolio_executions_table(self, portfolio_results: Dict[str, Any]) -> None:
        """
        Сохраняет executions-level таблицу для всех стратегий в CSV.
        
        Это таблица событий исполнения (executions-level), где каждая запись = fill/partial_close/force_close event.
        Используется для дебага и анализа исполнения.
        
        Колонки:
        - position_id: идентификатор позиции
        - signal_id: идентификатор сигнала
        - strategy: название стратегии
        - event_time: время события (ISO)
        - event_type: тип события (POSITION_OPENED/POSITION_PARTIAL_EXIT/POSITION_CLOSED)
        - event_id: ссылка на PortfolioEvent (если есть)
        - qty_delta: изменение количества (если есть)
        - raw_price: сырая цена (без slippage)
        - exec_price: исполненная цена (с slippage)
        - fees_sol: комиссии для этого события
        - pnl_sol_delta: изменение PnL для этого события
        - reason: каноническая причина (если применимо)
        - xn: target multiple (для ladder exits)
        - fraction: доля выхода (для ladder exits)
        
        :param portfolio_results: Словарь {strategy_name: PortfolioResult}
        """
        import pandas as pd
        from ..domain.portfolio import PortfolioResult
        
        executions_rows = []
        
        for strategy_name, portfolio_result in portfolio_results.items():
            if not isinstance(portfolio_result, PortfolioResult):
                continue
            
            for pos in portfolio_result.positions:
                if not pos.entry_time:
                    continue
                
                # Entry event
                exec_entry_price = pos.meta.get("exec_entry_price", pos.entry_price) if pos.meta else pos.entry_price
                raw_entry_price = pos.meta.get("raw_entry_price", pos.entry_price) if pos.meta else pos.entry_price
                network_fee_entry = pos.meta.get("network_fee_sol", 0.0) if pos.meta else 0.0
                # Для entry fees обычно только network fee (swap/lp применяются при выходе)
                fees_entry = network_fee_entry
                
                executions_rows.append({
                    "position_id": pos.position_id,
                    "signal_id": pos.signal_id,
                    "strategy": strategy_name,
                    "event_time": pos.entry_time.isoformat(),
                    "event_type": "entry",
                    "event_id": pos.meta.get("open_event_id") if pos.meta else None,
                    "qty_delta": pos.size,
                    "raw_price": raw_entry_price,
                    "exec_price": exec_entry_price,
                    "fees_sol": fees_entry,
                    "pnl_sol_delta": 0.0,
                    "reason": None,
                    "xn": None,
                    "fraction": None,
                })
                
                # Partial exits (для Runner стратегий)
                if pos.meta and "partial_exits" in pos.meta:
                    partial_exits = pos.meta.get("partial_exits", [])
                    for partial in partial_exits:
                        if isinstance(partial, dict):
                            hit_time_str = partial.get("hit_time", "")
                            try:
                                if isinstance(hit_time_str, str):
                                    hit_time = datetime.fromisoformat(hit_time_str.replace("Z", "+00:00"))
                                else:
                                    hit_time = hit_time_str
                            except (ValueError, AttributeError):
                                continue
                            
                            exit_size = partial.get("exit_size", 0.0)
                            exit_price = partial.get("exit_price", 0.0)
                            pnl_sol = partial.get("pnl_sol", 0.0)
                            fees_partial = partial.get("fees_sol", 0.0) + partial.get("network_fee_sol", 0.0)
                            
                            # Вычисляем raw_price из exit_price (обратная операция slippage)
                            # Это приблизительно, но для дебага достаточно
                            raw_exit_price = exit_price / (1.0 - 0.03) if exit_price > 0 else 0.0  # Примерный slippage
                            
                            # Вычисляем fraction безопасно (избегаем деления на ноль)
                            denom = pos.meta.get("original_size", None) if pos.meta else None
                            if denom is None or denom <= 0:
                                fraction = None
                            else:
                                fraction = exit_size / denom
                            
                            executions_rows.append({
                                "position_id": pos.position_id,
                                "signal_id": pos.signal_id,
                                "strategy": strategy_name,
                                "event_time": hit_time.isoformat() if isinstance(hit_time, datetime) else str(hit_time),
                                "event_type": "partial_exit",
                                "event_id": partial.get("event_id"),
                                "qty_delta": -exit_size,
                                "raw_price": raw_exit_price,
                                "exec_price": exit_price,
                                "fees_sol": fees_partial,
                                "pnl_sol_delta": pnl_sol,
                                "reason": "forced_close" if partial.get("is_remainder") else "ladder_tp",
                                "xn": partial.get("xn"),
                                "fraction": fraction,
                            })
                
                # Final exit или force close
                if pos.exit_time and pos.status == "closed":
                    exec_exit_price = pos.meta.get("exec_exit_price", pos.exit_price) if pos.meta else pos.exit_price
                    raw_exit_price = pos.meta.get("raw_exit_price", pos.exit_price) if pos.meta else pos.exit_price
                    pnl_sol = pos.meta.get("pnl_sol", 0.0) if pos.meta else 0.0
                    fees_total = pos.meta.get("fees_total_sol", 0.0) if pos.meta else 0.0
                    closed_by_reset = pos.meta.get("closed_by_reset", False) if pos.meta else False
                    reset_reason = pos.meta.get("reset_reason", None) if pos.meta else None
                    
                    executions_rows.append({
                        "position_id": pos.position_id,
                        "signal_id": pos.signal_id,
                        "strategy": strategy_name,
                        "event_time": pos.exit_time.isoformat(),
                        "event_type": "final_exit",
                        "event_id": pos.meta.get("close_event_id") if pos.meta else None,
                        "qty_delta": -pos.size,
                        "raw_price": raw_exit_price,
                        "exec_price": exec_exit_price,
                        "fees_sol": fees_total,
                        "pnl_sol_delta": pnl_sol,
                        "reason": reset_reason if closed_by_reset else pos.meta.get("close_reason") if pos.meta else None,
                        "xn": None,
                        "fraction": None,
                    })
        
        # Создаем DataFrame
        if executions_rows:
            df = pd.DataFrame(executions_rows)
            # Сортируем по event_time для консистентности
            df["event_time_dt"] = pd.to_datetime(df["event_time"], utc=True)
            df = df.sort_values("event_time_dt")
            df = df.drop("event_time_dt", axis=1)
        else:
            # Создаем пустой DataFrame с правильными колонками (position_id должен быть первым согласно ТЗ v2.0.1)
            df = pd.DataFrame([], columns=[  # type: ignore[arg-type]
                "position_id", "signal_id", "strategy", "event_time", "event_type", "event_id",
                "qty_delta", "raw_price", "exec_price", "fees_sol", "pnl_sol_delta",
                "reason", "xn", "fraction",
            ])
        
        # Сохраняем
        executions_path = self.output_dir / "portfolio_executions.csv"
        df.to_csv(executions_path, index=False)
        print(f"🔧 Saved portfolio executions table to {executions_path} ({len(df)} execution events)")
    
    def save_portfolio_policy_summary(self, portfolio_results: Dict[str, Any]) -> None:
        """
        Сохраняет сводный отчет по политике reset/prune (hardening v1.7.1).
        
        Генерирует portfolio_policy_summary.csv с агрегированной статистикой по:
        - profit reset событиям
        - capacity reset (close-all) событиям
        - capacity prune событиям
        
        Args:
            portfolio_results: Dict[str, PortfolioResult] - результаты портфельной симуляции
        """
        from ..domain.portfolio import PortfolioResult
        
        summary_rows = []
        
        for strategy_name, p_result in portfolio_results.items():
            if not isinstance(p_result, PortfolioResult):
                continue
            
            stats = p_result.stats
            
            # Собираем данные о prune событиях из stats
            prune_events = getattr(stats, 'capacity_prune_events', [])
            
            # Агрегируем prune статистику
            if prune_events:
                all_pruned_hold_days = []
                all_pruned_current_pnl_pct = []
                for event in prune_events:
                    all_pruned_hold_days.extend(event.get("pruned_hold_days", []))
                    all_pruned_current_pnl_pct.extend(event.get("pruned_current_pnl_pct", []))
                
                avg_pruned_positions_per_event = np.mean([e.get("pruned_count", 0) for e in prune_events]) if prune_events else 0.0
                median_pruned_hold_days = np.median(all_pruned_hold_days) if all_pruned_hold_days else None
                median_pruned_current_pnl_pct = np.median(all_pruned_current_pnl_pct) if all_pruned_current_pnl_pct else None
            else:
                avg_pruned_positions_per_event = 0.0
                median_pruned_hold_days = None
                median_pruned_current_pnl_pct = None
            
            # Считаем долю prune позиций от всех закрытых
            total_closed = len([p for p in p_result.positions if p.status == "closed"])
            pruned_closed = len([
                p for p in p_result.positions
                if p.meta and p.meta.get("capacity_prune", False)
            ])
            pruned_positions_share_of_all_closed = (
                pruned_closed / total_closed if total_closed > 0 else 0.0
            )
            
            row = {
                "strategy": strategy_name,
                "portfolio_reset_profit_count": stats.portfolio_reset_profit_count,
                "portfolio_reset_capacity_count": stats.portfolio_reset_capacity_count,
                "portfolio_capacity_prune_count": getattr(stats, 'portfolio_capacity_prune_count', 0),
                "avg_pruned_positions_per_event": avg_pruned_positions_per_event,
                "median_pruned_hold_days": median_pruned_hold_days,
                "median_pruned_current_pnl_pct": median_pruned_current_pnl_pct,
                "pruned_positions_share_of_all_closed": pruned_positions_share_of_all_closed,
            }
            
            summary_rows.append(row)
        
        # Определяем путь к файлу
        summary_path = self.output_dir / "portfolio_policy_summary.csv"
        
        # Определяем колонки (используем из первого элемента или фиксированный список)
        if summary_rows:
            # Берем ключи из первого элемента
            fieldnames = list(summary_rows[0].keys())
        else:
            # Фиксированный список колонок для пустого файла
            fieldnames = [
                "strategy",
                "portfolio_reset_profit_count",
                "portfolio_reset_capacity_count",
                "portfolio_capacity_prune_count",
                "avg_pruned_positions_per_event",
                "median_pruned_hold_days",
                "median_pruned_current_pnl_pct",
                "pruned_positions_share_of_all_closed",
            ]
        
        # Записываем CSV с использованием стандартной библиотеки
        with open(summary_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(summary_rows)
        
        if summary_rows:
            print(f"📊 Saved portfolio policy summary to {summary_path}")
        else:
            print(f"📊 Saved empty portfolio policy summary to {summary_path}")
    
    def save_report_pack_xlsx(
        self,
        portfolio_results: Optional[Dict[str, Any]] = None,
        runner_stats: Optional[Dict[str, Any]] = None,
        include_skipped_attempts: bool = True,
        config: Optional[Dict[str, Any]] = None,
    ) -> Optional[Path]:
        """
        Создает единый XLSX-отчёт (report_pack.xlsx) со всеми ключевыми таблицами (v1.10).
        
        Args:
            portfolio_results: Словарь {strategy_name: PortfolioResult} для summary метрик
            runner_stats: Статистика Runner для summary (signals_processed, etc.)
            include_skipped_attempts: Флаг для summary
            config: Конфигурация из global_config.reporting (опционально)
        
        Returns:
            Path к созданному файлу или None если не удалось создать
        """
        # Конфиг по умолчанию
        default_config = {
            "export_xlsx": True,
            "xlsx_filename": "report_pack.xlsx",
            "xlsx_timestamped": False,
            "xlsx_include_csv_backups": True,
            "xlsx_sheets": [
                "summary",
                "positions",
                "portfolio_events",
                "stage_a_stability",
                "stage_b_selection",
                "policy_summary",
                "capacity_prune_events",
            ],
        }
        
        if config is None:
            config = default_config
        else:
            # Мержим с дефолтами
            merged_config = default_config.copy()
            merged_config.update(config)
            config = merged_config
        
        # Проверяем флаг export_xlsx
        if not config.get("export_xlsx", True):
            return None
        
        # Собираем пути к CSV файлам
        inputs = {
            "positions_csv": self.output_dir / "portfolio_positions.csv",
            "portfolio_events_csv": self.output_dir / "portfolio_events.csv",
            "stage_a_stability_csv": self.output_dir / "strategy_stability.csv",
            "stage_b_selection_csv": self.output_dir / "strategy_selection.csv",
            "policy_summary_csv": self.output_dir / "portfolio_policy_summary.csv",
            "capacity_prune_events_csv": None,  # Пока нет отдельного файла
        }
        
        # Вызываем build_report_pack_xlsx
        return build_report_pack_xlsx(
            output_dir=self.output_dir,
            inputs=inputs,
            config=config,
            portfolio_results=portfolio_results,
            runner_stats=runner_stats,
            include_skipped_attempts=include_skipped_attempts,
        )
    
    def save_strategy_trades(self, blueprints: List[StrategyTradeBlueprint], path: Optional[Path] = None) -> None:
        """
        Сохраняет strategy_trades.csv с blueprints стратегий.
        
        Если список blueprints пуст, файл всё равно создаётся с header.
        Файл сохраняется в self.output_dir рядом с остальными отчётами, если path не указан.
        
        :param blueprints: Список StrategyTradeBlueprint для экспорта.
        :param path: Путь к файлу (опционально, по умолчанию output_dir / "strategy_trades.csv").
        """
        import pandas as pd
        
        # Определяем путь к файлу
        if path is None:
            path = self.output_dir / "strategy_trades.csv"
        else:
            path = Path(path)
        
        # Определяем порядок колонок
        columns = [
            "signal_id",
            "strategy_id",
            "contract_address",
            "entry_time",
            "entry_price_raw",
            "entry_mcap_proxy",
            "partial_exits_json",
            "final_exit_json",
            "realized_multiple",
            "max_xn_reached",
            "reason",
        ]
        
        # Преобразуем blueprints в строки CSV через to_row()
        # to_row() уже гарантирует, что final_exit_json = "" при None, и json.dumps(...) при наличии
        csv_rows = []
        for bp in blueprints:
            row = bp.to_row()
            csv_rows.append(row)
        
        # Создаём DataFrame
        if csv_rows:
            df = pd.DataFrame(csv_rows)
            # Убеждаемся, что колонки в правильном порядке
            for col in columns:
                if col not in df.columns:
                    df[col] = None
            df = df[columns]
            
            # Критически важно: final_exit_json должен быть пустой строкой, а не NaN
            if "final_exit_json" in df.columns:
                # Используем pandas nullable string dtype и заполняем NaN пустыми строками
                s = pd.Series(df["final_exit_json"]) if not isinstance(df["final_exit_json"], pd.Series) else df["final_exit_json"]
                df["final_exit_json"] = s.astype("string").fillna("")
        else:
            # Создаём пустой DataFrame с header
            df = pd.DataFrame(columns=columns)  # type: ignore[arg-type]
        
        # Сохраняем CSV с quoting=csv.QUOTE_ALL, чтобы пустая строка записалась как "" (quoted empty string)
        # Это гарантирует, что pandas всегда прочитает пустую строку как "", а не NaN
        df.to_csv(path, index=False, na_rep='', quoting=csv.QUOTE_ALL)
        print(f"[report] Saved strategy_trades.csv to {path} ({len(csv_rows)} blueprints)")
