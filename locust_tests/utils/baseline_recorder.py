"""
Baseline recording and comparison for performance testing

Records performance baselines and detects regressions
"""
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional


class BaselineRecorder:
    """
    Record and compare performance baselines
    """

    def __init__(self, baseline_dir='locust_tests/reports/baseline'):
        """
        Initialize baseline recorder

        Args:
            baseline_dir: Directory to store baseline files
        """
        self.baseline_dir = Path(baseline_dir)
        self.baseline_dir.mkdir(parents=True, exist_ok=True)

    def get_git_commit(self):
        """
        Get current git commit hash

        Returns:
            Commit hash string or 'unknown'
        """
        try:
            result = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()[:8]  # Short hash
        except Exception:
            pass
        return 'unknown'

    def get_git_branch(self):
        """Get current git branch name"""
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return 'unknown'

    def record_baseline(self, metrics_data: Dict, description: str = ""):
        """
        Save baseline metrics with timestamp

        Args:
            metrics_data: Dict with performance metrics
            description: Optional description of this baseline
        """
        timestamp = datetime.now().isoformat()
        commit = self.get_git_commit()
        branch = self.get_git_branch()

        filename = f"baseline_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{commit}.json"

        data = {
            'timestamp': timestamp,
            'git_commit': commit,
            'git_branch': branch,
            'description': description,
            'metrics': metrics_data,
        }

        filepath = self.baseline_dir / filename
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"✓ Baseline recorded: {filepath}")

        # Update 'latest' link
        latest = self.baseline_dir / 'latest.json'
        if latest.exists():
            latest.unlink()

        # Copy to latest
        with open(latest, 'w') as f:
            json.dump(data, f, indent=2)

        return filepath

    def load_baseline(self, baseline_name: str = 'latest') -> Optional[Dict]:
        """
        Load baseline by name

        Args:
            baseline_name: Name of baseline file (without .json) or 'latest'

        Returns:
            Baseline data dict or None if not found
        """
        if not baseline_name.endswith('.json'):
            baseline_name += '.json'

        filepath = self.baseline_dir / baseline_name

        if not filepath.exists():
            return None

        with open(filepath, 'r') as f:
            return json.load(f)

    def compare_to_baseline(
        self,
        current_metrics: Dict,
        baseline_name: str = 'latest',
        regression_threshold: float = 20.0
    ) -> Dict:
        """
        Compare current metrics to baseline

        Args:
            current_metrics: Current performance metrics (P95 times)
            baseline_name: Baseline to compare against
            regression_threshold: Percentage threshold for regression (default 20%)

        Returns:
            Comparison dict with results
        """
        baseline = self.load_baseline(baseline_name)

        if baseline is None:
            return {
                'status': 'no_baseline',
                'message': f'No baseline found: {baseline_name}'
            }

        baseline_metrics = baseline.get('metrics', {})
        comparison = {
            'baseline': {
                'timestamp': baseline.get('timestamp'),
                'commit': baseline.get('git_commit'),
                'branch': baseline.get('git_branch'),
            },
            'endpoints': {},
            'regressions': [],
            'improvements': [],
            'status': 'pass'
        }

        # Compare each endpoint
        for endpoint, current_time in current_metrics.items():
            baseline_time = baseline_metrics.get(endpoint)

            if baseline_time is None:
                comparison['endpoints'][endpoint] = {
                    'status': 'new',
                    'current': current_time,
                    'baseline': None,
                    'delta_percent': None
                }
                continue

            # Calculate percentage change
            delta = ((current_time - baseline_time) / baseline_time) * 100

            endpoint_data = {
                'current': current_time,
                'baseline': baseline_time,
                'delta_percent': delta,
                'delta_absolute': current_time - baseline_time,
            }

            # Classify as regression or improvement
            if delta > regression_threshold:
                endpoint_data['status'] = 'regression'
                comparison['regressions'].append({
                    'endpoint': endpoint,
                    **endpoint_data
                })
                comparison['status'] = 'fail'
            elif delta < -10:  # >10% improvement
                endpoint_data['status'] = 'improvement'
                comparison['improvements'].append({
                    'endpoint': endpoint,
                    **endpoint_data
                })
            else:
                endpoint_data['status'] = 'stable'

            comparison['endpoints'][endpoint] = endpoint_data

        return comparison

    def print_comparison(self, comparison: Dict):
        """
        Print formatted comparison results

        Args:
            comparison: Comparison dict from compare_to_baseline()
        """
        print("\n" + "="*60)
        print("BASELINE COMPARISON")
        print("="*60)

        if comparison['status'] == 'no_baseline':
            print(f"\n⚠️  {comparison['message']}")
            print("\n   Run baseline recording first:")
            print("   python locust_tests/utils/baseline_recorder.py record")
            print("="*60)
            return

        baseline_info = comparison['baseline']
        print(f"\nBaseline:")
        print(f"  Timestamp: {baseline_info['timestamp']}")
        print(f"  Commit: {baseline_info['commit']}")
        print(f"  Branch: {baseline_info['branch']}")

        # Regressions
        regressions = comparison['regressions']
        if regressions:
            print(f"\n❌ REGRESSIONS ({len(regressions)}):")
            for reg in sorted(regressions, key=lambda x: x['delta_percent'], reverse=True):
                print(f"   {reg['endpoint']:40} "
                      f"{reg['baseline']:.3f}s → {reg['current']:.3f}s "
                      f"({reg['delta_percent']:+.1f}%)")

        # Improvements
        improvements = comparison['improvements']
        if improvements:
            print(f"\n✅ IMPROVEMENTS ({len(improvements)}):")
            for imp in sorted(improvements, key=lambda x: x['delta_percent']):
                print(f"   {imp['endpoint']:40} "
                      f"{imp['baseline']:.3f}s → {imp['current']:.3f}s "
                      f"({imp['delta_percent']:+.1f}%)")

        # Summary
        print(f"\nSummary:")
        print(f"  Total endpoints: {len(comparison['endpoints'])}")
        print(f"  Regressions: {len(regressions)}")
        print(f"  Improvements: {len(improvements)}")
        print(f"  Status: {'❌ FAIL' if comparison['status'] == 'fail' else '✅ PASS'}")

        print("="*60)

        return comparison['status'] == 'pass'

    def list_baselines(self):
        """List all available baselines"""
        baselines = sorted(self.baseline_dir.glob('baseline_*.json'))

        if not baselines:
            print("No baselines found")
            return

        print("\nAvailable baselines:")
        print("-" * 80)
        for baseline in baselines:
            with open(baseline, 'r') as f:
                data = json.load(f)

            print(f"  {baseline.name}")
            print(f"    Timestamp: {data.get('timestamp', 'unknown')}")
            print(f"    Commit: {data.get('git_commit', 'unknown')}")
            print(f"    Branch: {data.get('git_branch', 'unknown')}")
            if data.get('description'):
                print(f"    Description: {data['description']}")
            print()


# CLI interface
if __name__ == '__main__':
    import sys

    recorder = BaselineRecorder()

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python baseline_recorder.py record [description]  - Record new baseline")
        print("  python baseline_recorder.py compare [baseline]    - Compare to baseline")
        print("  python baseline_recorder.py list                  - List baselines")
        sys.exit(1)

    command = sys.argv[1]

    if command == 'record':
        description = sys.argv[2] if len(sys.argv) > 2 else ""

        # Example metrics - in real use, get from Locust stats
        print("Note: This is a template. In actual use, get metrics from Locust results.")
        example_metrics = {
            '/images/1/view': 0.450,
            '/images/1/full': 2.150,
            '/photometry/lc': 1.800,
        }

        recorder.record_baseline(example_metrics, description)

    elif command == 'compare':
        baseline_name = sys.argv[2] if len(sys.argv) > 2 else 'latest'

        # Example current metrics
        print("Note: This is a template. In actual use, get metrics from Locust results.")
        current_metrics = {
            '/images/1/view': 0.480,
            '/images/1/full': 2.100,
            '/photometry/lc': 2.200,  # Regression!
        }

        comparison = recorder.compare_to_baseline(current_metrics, baseline_name)
        passed = recorder.print_comparison(comparison)

        sys.exit(0 if passed else 1)

    elif command == 'list':
        recorder.list_baselines()

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
