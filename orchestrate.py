#!/usr/bin/env python3
"""
Orchestrator for Slurm deployment + KPI reporting.
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run(cmd, title: str) -> int:
    print("\n" + "=" * 100)
    print(f"[*] {title}")
    print("=" * 100)
    proc = subprocess.run(cmd)
    return proc.returncode


def latest_summary() -> str:
    candidates = sorted(Path("results").glob("*/summary.json"), reverse=True)
    return str(candidates[0]) if candidates else ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Slurm iperf3 workflow orchestrator")
    parser.add_argument("--partition", default="")
    parser.add_argument("--account", default="")
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--streams", type=int, default=32)
    parser.add_argument("--udp-duration", type=int, default=20)
    parser.add_argument("--udp-bandwidth-gbps", type=int, default=20)
    parser.add_argument("--expected-gbps-per-direction", type=float, default=200.0)
    parser.add_argument("--time-limit", default="01:00:00")
    parser.add_argument("--interface", default="")
    parser.add_argument("--submit-only", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()

    if not args.report_only:
        cmd = [
            sys.executable,
            "iperf3_test_runner.py",
            "--duration",
            str(args.duration),
            "--streams",
            str(args.streams),
            "--udp-duration",
            str(args.udp_duration),
            "--udp-bandwidth-gbps",
            str(args.udp_bandwidth_gbps),
            "--expected-gbps-per-direction",
            str(args.expected_gbps_per_direction),
            "--time-limit",
            args.time_limit,
        ]
        if args.partition:
            cmd += ["--partition", args.partition]
        if args.account:
            cmd += ["--account", args.account]
        if args.interface:
            cmd += ["--interface", args.interface]
        if args.submit_only:
            cmd += ["--submit-only"]

        rc = run(cmd, "Submit and run Slurm workload")
        if rc != 0:
            return rc

    if args.submit_only:
        print("[*] Submit-only mode requested. Skipping report generation.")
        return 0

    summary = latest_summary()
    if not summary:
        print("[!] No summary.json found under results/*")
        return 1

    report_cmd = [sys.executable, "bottleneck_analyzer.py", "--summary", summary]
    return run(report_cmd, "Generate KPI report tables")


if __name__ == "__main__":
    raise SystemExit(main())
