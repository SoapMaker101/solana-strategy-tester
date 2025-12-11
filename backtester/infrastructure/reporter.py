# backtester/infrastructure/reporter.py

from __future__ import annotations

from typing import List, Dict, Any, Optional
import json
import statistics
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter

import numpy as np


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
        print(f"📊 Saved CSV report to {csv_path}")

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
        print(f"📄 Saved HTML report to {html_path}")

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
            print("⚠️ matplotlib not available, skipping equity curve plot")
            return None
        except Exception as e:
            print(f"⚠️ Failed to plot equity curve: {e}")
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
            print(f"⚠️ Failed to plot PnL distribution: {e}")
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
            print(f"⚠️ Failed to plot exit reasons: {e}")
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
            print(f"⚠️ Failed to plot trades timeline: {e}")
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
            print(f"📈 Saved equity curve to {equity_path}")
        
        # Сохраняем позиции в CSV
        positions_data = []
        for pos in portfolio_result.positions:
            positions_data.append({
                "signal_id": pos.signal_id,
                "contract_address": pos.contract_address,
                "entry_time": pos.entry_time.isoformat() if pos.entry_time else None,
                "entry_price": pos.entry_price,
                "exit_time": pos.exit_time.isoformat() if pos.exit_time else None,
                "exit_price": pos.exit_price,
                "size_sol": pos.size,
                "pnl_pct": pos.pnl_pct,
                "pnl_sol": pos.meta.get("pnl_sol", 0.0) if pos.meta else 0.0,
                "raw_pnl_pct": pos.meta.get("raw_pnl_pct", 0.0) if pos.meta else 0.0,
                "fee_pct": pos.meta.get("fee_pct", 0.0) if pos.meta else 0.0,
                "status": pos.status,
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
        print(f"📊 Saved portfolio stats to {stats_path}")
        
        # Строим график equity curve портфеля
        self.plot_portfolio_equity_curve(strategy_name, portfolio_result)

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
            
            print(f"📈 Saved portfolio equity curve chart to {output_path}")
            return output_path
        except ImportError:
            print("⚠️ matplotlib not available, skipping portfolio equity curve plot")
            return None
        except Exception as e:
            print(f"⚠️ Failed to plot portfolio equity curve: {e}")
            return None
