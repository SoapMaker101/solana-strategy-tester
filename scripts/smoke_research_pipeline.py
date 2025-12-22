"""
Smoke test для research pipeline (Stage A → Stage B).

Проверяет:
1. Наличие portfolio_positions.csv
2. Запуск Stage A
3. Запуск Stage B
4. Корректность hit rates в selection CSV
"""
import argparse
import sys
from pathlib import Path
import pandas as pd


def check_portfolio_positions(positions_path: Path) -> bool:
    """
    Проверяет наличие и корректность portfolio_positions.csv.
    
    :param positions_path: Путь к portfolio_positions.csv
    :return: True если файл корректен, False иначе
    """
    if not positions_path.exists():
        print(f"❌ ERROR: portfolio_positions.csv not found at {positions_path}")
        return False
    
    try:
        df = pd.read_csv(positions_path)
        
        if len(df) == 0:
            print(f"⚠️  WARNING: portfolio_positions.csv is empty")
            return False
        
        # Проверяем обязательные колонки
        required_cols = ["strategy", "signal_id", "pnl_sol", "max_xn_reached", "hit_x2", "hit_x5"]
        missing_cols = [col for col in required_cols if col not in df.columns]
        
        if missing_cols:
            print(f"❌ ERROR: Missing required columns in portfolio_positions.csv: {missing_cols}")
            return False
        
        print(f"✅ OK: portfolio_positions.csv found with {len(df)} positions")
        return True
        
    except Exception as e:
        print(f"❌ ERROR: Failed to read portfolio_positions.csv: {e}")
        return False


def run_stage_a(reports_dir: Path) -> bool:
    """
    Запускает Stage A программно.
    
    :param reports_dir: Директория с reports
    :return: True если Stage A успешно выполнен, False иначе
    """
    try:
        from backtester.research.run_stage_a import main as stage_a_main
        import sys as sys_module
        
        # Сохраняем оригинальные аргументы
        original_argv = sys_module.argv.copy()
        
        try:
            # Устанавливаем аргументы для Stage A
            sys_module.argv = [
                "run_stage_a",
                "--reports-dir", str(reports_dir),
                "--output-csv", str(reports_dir / "strategy_stability.csv"),
            ]
            
            # Запускаем Stage A
            stage_a_main()
            
            # Проверяем что файл создан
            stability_path = reports_dir / "strategy_stability.csv"
            if not stability_path.exists():
                print(f"❌ ERROR: strategy_stability.csv not created by Stage A")
                return False
            
            print(f"✅ OK: Stage A completed, strategy_stability.csv created")
            return True
            
        finally:
            # Восстанавливаем оригинальные аргументы
            sys_module.argv = original_argv
            
    except Exception as e:
        print(f"❌ ERROR: Stage A failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_stage_b(stability_csv: Path) -> bool:
    """
    Запускает Stage B программно.
    
    :param stability_csv: Путь к strategy_stability.csv
    :return: True если Stage B успешно выполнен, False иначе
    """
    try:
        from backtester.decision.run_stage_b import main as stage_b_main
        import sys as sys_module
        
        # Сохраняем оригинальные аргументы
        original_argv = sys_module.argv.copy()
        
        try:
            # Устанавливаем аргументы для Stage B
            output_csv = stability_csv.parent / "strategy_selection.csv"
            sys_module.argv = [
                "run_stage_b",
                "--stability-csv", str(stability_csv),
                "--output-csv", str(output_csv),
            ]
            
            # Запускаем Stage B
            stage_b_main()
            
            # Проверяем что файл создан
            if not output_csv.exists():
                print(f"❌ ERROR: strategy_selection.csv not created by Stage B")
                return False
            
            print(f"✅ OK: Stage B completed, strategy_selection.csv created")
            return True
            
        finally:
            # Восстанавливаем оригинальные аргументы
            sys_module.argv = original_argv
            
    except Exception as e:
        print(f"❌ ERROR: Stage B failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_hit_rates(positions_path: Path, selection_path: Path) -> bool:
    """
    Проверяет что hit rates в selection CSV не все нули при наличии max_xn>=2.
    
    :param positions_path: Путь к portfolio_positions.csv
    :param selection_path: Путь к strategy_selection.csv
    :return: True если hit rates корректны, False иначе
    """
    try:
        # Загружаем portfolio_positions.csv
        positions_df = pd.read_csv(positions_path)
        
        # Проверяем наличие позиций с max_xn_reached>=2
        if "max_xn_reached" in positions_df.columns:
            positions_with_x2 = positions_df[positions_df["max_xn_reached"] >= 2.0]
            if len(positions_with_x2) > 0:
                print(f"ℹ️  INFO: Found {len(positions_with_x2)} positions with max_xn_reached>=2.0")
            else:
                print(f"ℹ️  INFO: No positions with max_xn_reached>=2.0 found (this is OK)")
        else:
            positions_with_x2 = pd.DataFrame()  # Пустой DataFrame если колонки нет
        
        # Загружаем strategy_selection.csv
        if not selection_path.exists():
            print(f"⚠️  WARNING: strategy_selection.csv not found, skipping hit rates check")
            return True
        
        selection_df = pd.read_csv(selection_path)
        
        if len(selection_df) == 0:
            print(f"⚠️  WARNING: strategy_selection.csv is empty")
            return True
        
        # Проверяем наличие колонок hit_rate_x2/x5
        if "hit_rate_x2" not in selection_df.columns or "hit_rate_x5" not in selection_df.columns:
            print(f"⚠️  WARNING: hit_rate_x2/x5 columns not found in strategy_selection.csv")
            return True
        
        # Проверяем что hit rates не все нули (если есть позиции с max_xn_reached>=2)
        if len(positions_with_x2) > 0:
            runner_strategies = selection_df[selection_df["strategy"].str.lower().str.contains("runner", na=False)]
            if len(runner_strategies) > 0:
                all_zero_x2 = (runner_strategies["hit_rate_x2"] == 0.0).all()
                if all_zero_x2:
                    print(f"❌ ERROR: All hit_rate_x2 are 0, but positions with max_xn_reached>=2 exist")
                    return False
                else:
                    print(f"✅ OK: hit_rate_x2 is not all zeros for Runner strategies")
        
        print(f"✅ OK: Hit rates check passed")
        return True
        
    except Exception as e:
        print(f"❌ ERROR: Failed to check hit rates: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """
    Главная функция smoke test.
    """
    parser = argparse.ArgumentParser(
        description="Smoke test for research pipeline (Stage A → Stage B)"
    )
    
    parser.add_argument(
        "--run-dir",
        type=str,
        required=True,
        help="Path to output/reports directory (e.g., output/reports or output/run_2025_07_01_runner_baseline)"
    )
    
    parser.add_argument(
        "--skip-stage-a",
        action="store_true",
        help="Skip Stage A (assume strategy_stability.csv already exists)"
    )
    
    parser.add_argument(
        "--skip-stage-b",
        action="store_true",
        help="Skip Stage B (assume strategy_selection.csv already exists)"
    )
    
    args = parser.parse_args()
    
    run_dir = Path(args.run_dir)
    
    if not run_dir.exists():
        print(f"❌ ERROR: Directory not found: {run_dir}")
        sys.exit(1)
    
    print("=" * 60)
    print("Smoke Test: Research Pipeline (Stage A → Stage B)")
    print("=" * 60)
    print(f"Run directory: {run_dir}")
    print()
    
    # Шаг 1: Проверка portfolio_positions.csv
    positions_path = run_dir / "portfolio_positions.csv"
    if not check_portfolio_positions(positions_path):
        print("\n❌ FAILED: portfolio_positions.csv check")
        sys.exit(1)
    
    print()
    
    # Шаг 2: Запуск Stage A
    if not args.skip_stage_a:
        if not run_stage_a(run_dir):
            print("\n❌ FAILED: Stage A")
            sys.exit(1)
        print()
    else:
        print("⏭️  SKIPPED: Stage A (--skip-stage-a)")
        print()
    
    # Шаг 3: Запуск Stage B
    stability_csv = run_dir / "strategy_stability.csv"
    if not args.skip_stage_b:
        if not stability_csv.exists():
            print(f"❌ ERROR: strategy_stability.csv not found at {stability_csv}")
            print("   Run Stage A first or remove --skip-stage-a flag")
            sys.exit(1)
        
        if not run_stage_b(stability_csv):
            print("\n❌ FAILED: Stage B")
            sys.exit(1)
        print()
    else:
        print("⏭️  SKIPPED: Stage B (--skip-stage-b)")
        print()
    
    # Шаг 4: Проверка hit rates
    selection_path = run_dir / "strategy_selection.csv"
    if not check_hit_rates(positions_path, selection_path):
        print("\n❌ FAILED: Hit rates check")
        sys.exit(1)
    
    print()
    print("=" * 60)
    print("✅ SUCCESS: All smoke tests passed!")
    print("=" * 60)
    sys.exit(0)


if __name__ == "__main__":
    main()

