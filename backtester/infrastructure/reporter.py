# backtester/reporter.py
from typing import List, Dict, Any
import json
from pathlib import Path


class Reporter:
    def __init__(self, output_dir: str = "output/reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_results(self, strategy_name: str, results: List[Dict[str, Any]]) -> None:
        out_path = self.output_dir / f"{strategy_name}.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
