#!/usr/bin/env python3
"""
KPI report generator for Slurm iperf3 run outputs.
Reads results/<run_id>/summary.json and prints/writes clear tables.
"""

import argparse
import json
from pathlib import Path
from typing import Dict, List


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _table(headers: List[str], rows: List[List[object]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(_fmt(cell)))

    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out = [sep]
    out.append("| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)) + " |")
    out.append(sep)
    for row in rows:
        out.append("| " + " | ".join(_fmt(c).ljust(widths[i]) for i, c in enumerate(row)) + " |")
    out.append(sep)
    return "\n".join(out)


def _load_summary(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _bandwidth_rows(summary: Dict) -> List[List[object]]:
    rows = []
    for r in summary.get("rows", []):
        rows.append(
            [
                f"{r['src']}->{r['dst']}",
                r["tx_gbps"],
                r["rx_gbps"],
                r["agg_gbps"],
                r["expected_agg_gbps"],
                f"{r['pct_of_expected']}%",
                r["cpu_host_pct"],
                r["cpu_remote_pct"],
                r["retransmits"],
                r["udp_jitter_ms"],
                r["udp_lost_pct"],
                r["ping_avg_ms"],
                r["bottleneck"],
            ]
        )
    return rows


def _health_rows(summary: Dict) -> List[List[object]]:
    rows = []
    for n in summary.get("node_health", []):
        rows.append(
            [
                n.get("node", ""),
                n.get("pcie_aer", 0),
                n.get("net_stack", 0),
                n.get("iface_errors", 0),
                n.get("ring_overflow", 0),
                n.get("rx_errors_delta", 0),
                n.get("tx_errors_delta", 0),
                n.get("rx_dropped_delta", 0),
                n.get("tx_dropped_delta", 0),
                n.get("rx_missed_errors_delta", 0),
                n.get("rx_no_buffer_count_delta", 0),
            ]
        )
    return rows


def _top_findings(summary: Dict) -> List[str]:
    findings = []
    rows = summary.get("rows", [])
    if not rows:
        return ["No pairwise results found in summary.json"]

    low = [r for r in rows if r.get("pct_of_expected", 0.0) < 80.0]
    if low:
        findings.append(f"{len(low)} paths are below 80% of expected bidirectional throughput.")

    high_loss = [r for r in rows if r.get("udp_lost_pct", 0.0) > 0.5]
    if high_loss:
        findings.append(f"{len(high_loss)} paths show UDP loss > 0.5%.")

    high_rtt = [r for r in rows if r.get("ping_avg_ms", 0.0) > 2.0]
    if high_rtt:
        findings.append(f"{len(high_rtt)} paths show ping average RTT > 2 ms.")

    cpu_bound = [r for r in rows if max(r.get("cpu_host_pct", 0.0), r.get("cpu_remote_pct", 0.0)) > 85.0]
    if cpu_bound:
        findings.append(f"{len(cpu_bound)} paths are likely CPU/network-stack limited (CPU > 85%).")

    err_nodes = [
        n for n in summary.get("node_health", [])
        if n.get("pcie_aer", 0) or n.get("net_stack", 0) or n.get("iface_errors", 0) or n.get("ring_overflow", 0)
    ]
    if err_nodes:
        findings.append(f"{len(err_nodes)} nodes have PCIe/network/interface error signatures in logs/stats.")

    if not findings:
        findings.append("No major bottleneck signatures detected in current run.")

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate KPI bottleneck report")
    parser.add_argument("--summary", default="", help="Path to summary.json")
    parser.add_argument("--out", default="", help="Optional report output file")
    args = parser.parse_args()

    if args.summary:
        summary_path = Path(args.summary)
    else:
        candidates = sorted(Path("results").glob("*/summary.json"), reverse=True)
        if not candidates:
            print("[!] No results/*/summary.json found")
            return 1
        summary_path = candidates[0]

    summary = _load_summary(summary_path)

    bw_headers = [
        "Path",
        "TX Gbps",
        "RX Gbps",
        "Agg Gbps",
        "Expected",
        "% Exp",
        "CPU Host%",
        "CPU Rem%",
        "Retrans",
        "UDP Jit ms",
        "UDP Lost%",
        "Ping Avg ms",
        "Bottleneck",
    ]
    health_headers = [
        "Node",
        "PCIe/AER",
        "Net Stack",
        "Iface Errors",
        "Ring Overflow",
        "RX Err d",
        "TX Err d",
        "RX Drop d",
        "TX Drop d",
        "RX Miss d",
        "RX NoBuf d",
    ]

    bw = _table(bw_headers, _bandwidth_rows(summary))
    health = _table(health_headers, _health_rows(summary))

    overall = summary.get("overall", {})
    lines = []
    lines.append("=" * 120)
    lines.append("SLURM IPERF3 KPI REPORT")
    lines.append("=" * 120)
    lines.append(f"Summary source : {summary_path}")
    lines.append(f"Generated at   : {summary.get('generated_at', '')}")
    lines.append(f"Expected/dir   : {summary.get('expected_gbps_per_direction', 200.0)} Gbps")
    lines.append(f"Pairs tested   : {overall.get('pairs_tested', 0)}")
    lines.append(f"Avg Agg Gbps   : {overall.get('avg_agg_gbps', 0)}")
    lines.append(f"Min/Max Agg    : {overall.get('min_agg_gbps', 0)} / {overall.get('max_agg_gbps', 0)}")
    lines.append("")
    lines.append("Bandwidth vs Expected")
    lines.append(bw)
    lines.append("")
    lines.append("Node-level Error Signatures")
    lines.append(health)
    lines.append("")
    lines.append("Top Findings")
    for idx, f in enumerate(_top_findings(summary), 1):
        lines.append(f"{idx}. {f}")

    report = "\n".join(lines)
    print(report)

    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    else:
        default_out = summary_path.parent / "kpi_report.txt"
        default_out.write_text(report, encoding="utf-8")
        print(f"\n[*] Wrote report: {default_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
