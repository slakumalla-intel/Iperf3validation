#!/usr/bin/env python3
"""
Orchestration Script - Easy one-command testing and analysis
Runs the complete iperf3 test suite with optional setup and analysis
"""

import sys
import subprocess
import argparse
from pathlib import Path

def run_command(cmd: str, description: str) -> bool:
    """Run a shell command and return success status"""
    print(f"\n{'=' * 80}")
    print(f"[*] {description}")
    print('=' * 80)
    try:
        result = subprocess.run(cmd, shell=True)
        return result.returncode == 0
    except Exception as e:
        print(f"[!] Error: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description="Iperf3 Multi-Node Testing Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python orchestrate.py --full              # Setup, test, and analyze
  python orchestrate.py --test              # Run tests only
  python orchestrate.py --test --analyze    # Test and analyze
  python orchestrate.py --setup             # Setup nodes only
  python orchestrate.py --analyze           # Analyze last results
        """)
    
    parser.add_argument('--full', action='store_true', 
                        help='Full workflow: setup → test → analyze')
    parser.add_argument('--setup', action='store_true',
                        help='Setup nodes (install iperf3)')
    parser.add_argument('--test', action='store_true',
                        help='Run performance tests')
    parser.add_argument('--analyze', action='store_true',
                        help='Analyze results and bottlenecks')
    
    args = parser.parse_args()
    
    # Default to full workflow if no args
    if not any([args.full, args.setup, args.test, args.analyze]):
        args.full = True
    
    success_count = 0
    total_steps = 0
    
    # STEP 1: Setup
    if args.full or args.setup:
        total_steps += 1
        if run_command(
            f"{sys.executable} setup_nodes.py",
            "STEP 1: Installing iperf3 on nodes"
        ):
            success_count += 1
        else:
            print("[!] Setup failed - continuing with testing anyway...")
    
    # STEP 2: Run Tests
    if args.full or args.test:
        total_steps += 1
        if run_command(
            f"{sys.executable} iperf3_test_runner.py",
            "STEP 2: Running Network Performance Tests"
        ):
            success_count += 1
        else:
            print("[!] Tests failed")
            return False
    
    # STEP 3: Analyze Results
    if args.full or args.analyze:
        total_steps += 1
        if run_command(
            f"{sys.executable} bottleneck_analyzer.py",
            "STEP 3: Analyzing Bottlenecks"
        ):
            success_count += 1
        else:
            print("[!] Analysis failed")
    
    # Summary
    print(f"\n{'=' * 80}")
    print(f"[✓] WORKFLOW COMPLETE: {success_count}/{total_steps} steps successful")
    print('=' * 80)
    
    # Find and display reports
    reports = list(Path('.').glob('*report*.txt'))
    if reports:
        print(f"\nGenerated Reports:")
        for report in sorted(reports, reverse=True)[:3]:
            print(f"  • {report.name}")
    
    results = list(Path('.').glob('*results*.json'))
    if results:
        print(f"\nGenerated Data:")
        for result in sorted(results, reverse=True)[:3]:
            print(f"  • {result.name}")
    
    return success_count == total_steps

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n[!] Interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n[!] Unexpected error: {e}")
        sys.exit(1)
