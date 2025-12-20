# Test script to verify XN analysis module imports
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from backtester.research.xn_analysis import XNAnalysisConfig, XNSignalResult, XNSummaryStats, XNAnalyzer
    print("✓ All imports successful")
    print(f"✓ XNAnalysisConfig: {XNAnalysisConfig}")
    print(f"✓ XNSignalResult: {XNSignalResult}")
    print(f"✓ XNSummaryStats: {XNSummaryStats}")
    print(f"✓ XNAnalyzer: {XNAnalyzer}")
except Exception as e:
    print(f"❌ Import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
