#!/usr/bin/env python3
"""
Slurm-native iperf3 workload runner for rack validation.

Features:
- Slurm deployment over explicit node list.
- Kernel/NIC tuning hooks for high-throughput testing.
- Pairwise bidirectional TCP + UDP jitter/loss + ICMP latency.
- Pre/post telemetry capture for PCIe, network stack, interface and ring counters.
- JSON summary suitable for tabular reporting.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


DEFAULT_NODES = ["sc00901112s0101", "sc00901112s0103", "sc00901112s0104", "sc00901112s0106"]


@dataclass
class RunnerConfig:
    nodes: List[str]
    duration_sec: int = 120
    tcp_omit_sec: int = 5
    streams: int = 32
    udp_duration_sec: int = 20
    udp_bandwidth_gbps: int = 20
    ping_count: int = 20
    interface_hint: str = ""
    partition: str = ""
    account: str = ""
    time_limit: str = "01:00:00"
    slurm_cpus_per_task: int = 160
    slurm_cpu_bind: str = "cores"
    server_cpu: int = 0
    client_cpu: int = 1
    results_root: str = "results"
    run_id: str = ""
    expected_gbps_per_direction: float = 200.0


class SlurmIperfRunner:
    def __init__(self, cfg: RunnerConfig):
        self.cfg = cfg
        self.repo_root = Path(__file__).resolve().parent
        if not self.cfg.run_id:
            self.cfg.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.result_dir = self.repo_root / self.cfg.results_root / self.cfg.run_id
        self.result_dir.mkdir(parents=True, exist_ok=True)

    def _run_local(self, cmd: List[str], check: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, text=True, capture_output=True, check=check)

    def validate_slurm_tools(self) -> None:
        required = ["sbatch", "squeue", "sacct"]
        missing = [tool for tool in required if shutil.which(tool) is None]
        if missing:
            raise RuntimeError(
                "Missing required Slurm tools on controller node: " + ", ".join(missing)
            )

    def _build_slurm_script(self) -> str:
        node_list = ",".join(self.cfg.nodes)
        partition_line = f"#SBATCH --partition={self.cfg.partition}" if self.cfg.partition else ""
        account_line = f"#SBATCH --account={self.cfg.account}" if self.cfg.account else ""

        script = f"""#!/usr/bin/env bash
    #SBATCH --job-name=iperf3_200g_{self.cfg.run_id}
#SBATCH --nodes={len(self.cfg.nodes)}
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=160
#SBATCH --exclusive
#SBATCH --nodelist={node_list}
#SBATCH --time={self.cfg.time_limit}
#SBATCH --output={self.result_dir.as_posix()}/slurm-%j.out
#SBATCH --error={self.result_dir.as_posix()}/slurm-%j.err
{partition_line}
{account_line}

set -euo pipefail

RESULT_DIR="{self.result_dir.as_posix()}"
mkdir -p "$RESULT_DIR/raw"

NODES=({" ".join(self.cfg.nodes)})
DURATION={self.cfg.duration_sec}
TCP_OMIT={self.cfg.tcp_omit_sec}
STREAMS={self.cfg.streams}
UDP_DURATION={self.cfg.udp_duration_sec}
UDP_BW_G={self.cfg.udp_bandwidth_gbps}
PING_COUNT={self.cfg.ping_count}
IF_HINT="{self.cfg.interface_hint}"
CPUS_PER_TASK={self.cfg.slurm_cpus_per_task}
CPU_BIND="{self.cfg.slurm_cpu_bind}"
SERVER_CPU={self.cfg.server_cpu}
CLIENT_CPU={self.cfg.client_cpu}

log() {{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}}

remote_helper='set -euo pipefail
peer="${{PEER:-}}"
iface_hint="${{IF_HINT:-}}"
if [[ -n "$iface_hint" ]]; then
  iface="$iface_hint"
else
    peer_ip=$(scontrol show node "$peer" 2>/dev/null | tr " " "\n" | awk -F= "/^NodeAddr=/{{print \\$2; exit}}")
    target="${{peer_ip:-$peer}}"
    iface=$(ip route get "$target" 2>/dev/null | awk "{{for(i=1;i<=NF;i++) if(\\$i==\"dev\") print \\$(i+1)}}" | head -n1)
  if [[ -z "$iface" ]]; then iface="eth0"; fi
fi
'

host_snapshot() {{
  local phase="$1"
  local node="$2"
  local peer="${{3:-${{NODES[0]}}}}"

        srun --export=ALL,PEER="$peer",IF_HINT="$IF_HINT" --nodes=1 --ntasks=1 --cpus-per-task="$CPUS_PER_TASK" --cpu-bind="$CPU_BIND" -w "$node" bash -lc "
    $remote_helper
    out=\"$RESULT_DIR/raw/${{node}}_${{phase}}\"
    mkdir -p \"$out\"

    uname -a > \"$out/uname.txt\" 2>&1 || true
    lscpu > \"$out/lscpu.txt\" 2>&1 || true
    ip -s link show \"$iface\" > \"$out/ip_link_stats.txt\" 2>&1 || true
    ethtool \"$iface\" > \"$out/ethtool.txt\" 2>&1 || true
    ethtool -k \"$iface\" > \"$out/ethtool_features.txt\" 2>&1 || true
    ethtool -g \"$iface\" > \"$out/ethtool_ring.txt\" 2>&1 || true
    ethtool -S \"$iface\" > \"$out/ethtool_stats.txt\" 2>&1 || true
    nstat -az > \"$out/nstat.txt\" 2>&1 || true
    cat /proc/interrupts > \"$out/interrupts.txt\" 2>&1 || true
    lspci -vv > \"$out/lspci_vv.txt\" 2>&1 || true
    dmesg -T | tail -n 3000 > \"$out/dmesg_tail.txt\" 2>&1 || true

    echo \"$iface\" > \"$out/interface.txt\"
  "
}}

apply_tuning() {{
  local node="$1"
  local peer="${{2:-${{NODES[0]}}}}"

        srun --export=ALL,PEER="$peer",IF_HINT="$IF_HINT" --nodes=1 --ntasks=1 --cpus-per-task="$CPUS_PER_TASK" --cpu-bind="$CPU_BIND" -w "$node" bash -lc "
    $remote_helper

    # Kernel tuning for high-bandwidth transport.
    sysctl -w net.core.rmem_max=134217728 || true
    sysctl -w net.core.wmem_max=134217728 || true
    sysctl -w net.core.netdev_max_backlog=300000 || true
    sysctl -w net.core.somaxconn=65535 || true
    sysctl -w net.ipv4.tcp_rmem='4096 87380 134217728' || true
    sysctl -w net.ipv4.tcp_wmem='4096 65536 134217728' || true
    sysctl -w net.ipv4.tcp_mtu_probing=1 || true
    sysctl -w net.ipv4.tcp_congestion_control=bbr || true

    # NIC ring/offload/coalescing tuning.
    ethtool -G \"$iface\" rx 4096 tx 4096 || true
    ethtool -K \"$iface\" gro on gso on tso on rx on tx on || true
    ethtool -C \"$iface\" adaptive-rx on adaptive-tx on || true
  "
}}

start_servers() {{
  local node="$1"
    srun --nodes=1 --ntasks=1 --cpus-per-task="$CPUS_PER_TASK" --cpu-bind="$CPU_BIND" -w "$node" bash -lc '
    set -euo pipefail
        pkill -x iperf3 || true
        sleep 1
                taskset -c "$SERVER_CPU" iperf3 -s -D -p 5201
  '
}}

stop_servers() {{
  local node="$1"
        srun --nodes=1 --ntasks=1 --cpus-per-task="$CPUS_PER_TASK" --cpu-bind="$CPU_BIND" -w "$node" bash -lc 'pkill -x iperf3 || true'
}}

run_pair() {{
  local src="$1"
  local dst="$2"
  local stem="${{src}}_to_${{dst}}"

  log "TCP bidirectional test $src -> $dst"
    srun --nodes=1 --ntasks=1 --cpus-per-task="$CPUS_PER_TASK" --cpu-bind="$CPU_BIND" -w "$src" bash -lc '
    set -euo pipefail
        taskset -c "$CLIENT_CPU" iperf3 -c "'"$dst"'" -p 5201 -O '"$TCP_OMIT"' -t '"$DURATION"' -P '"$STREAMS"' --bidir -J --get-server-output
  ' > "$RESULT_DIR/raw/${{stem}}_tcp.json" 2> "$RESULT_DIR/raw/${{stem}}_tcp.stderr" || true

  log "UDP jitter/loss test $src -> $dst"
    srun --nodes=1 --ntasks=1 --cpus-per-task="$CPUS_PER_TASK" --cpu-bind="$CPU_BIND" -w "$src" bash -lc '
    set -euo pipefail
        taskset -c "$CLIENT_CPU" iperf3 -c "'"$dst"'" -p 5201 -u -b '"$UDP_BW_G"'G -l 256 -t '"$UDP_DURATION"' -J --get-server-output
  ' > "$RESULT_DIR/raw/${{stem}}_udp.json" 2> "$RESULT_DIR/raw/${{stem}}_udp.stderr" || true

  log "Ping RTT sample $src -> $dst"
    srun --nodes=1 --ntasks=1 --cpus-per-task="$CPUS_PER_TASK" --cpu-bind="$CPU_BIND" -w "$src" bash -lc '
    set -euo pipefail
    ping -c '"$PING_COUNT"' "'"$dst"'"
  ' > "$RESULT_DIR/raw/${{stem}}_ping.txt" 2> "$RESULT_DIR/raw/${{stem}}_ping.stderr" || true
}}

log "Starting pre-check snapshots"
for n in "${{NODES[@]}}"; do
    host_snapshot pre "$n" "${{NODES[0]}}"
done

log "Applying tuning on all nodes"
for n in "${{NODES[@]}}"; do
    apply_tuning "$n" "${{NODES[0]}}"
done

log "Starting iperf3 servers"
for n in "${{NODES[@]}}"; do
  start_servers "$n"
done
sleep 2

log "Running pair matrix"
for src in "${{NODES[@]}}"; do
  for dst in "${{NODES[@]}}"; do
    if [[ "$src" != "$dst" ]]; then
      run_pair "$src" "$dst"
    fi
  done
done

log "Stopping servers"
for n in "${{NODES[@]}}"; do
  stop_servers "$n"
done

log "Collecting post-check snapshots"
for n in "${{NODES[@]}}"; do
  PEER="${{NODES[0]}}" IF_HINT="$IF_HINT" host_snapshot post "$n" "${{NODES[0]}}"
done

log "Done"
"""
        return textwrap.dedent(script)

    def submit_slurm_job(self) -> str:
        script_path = self.result_dir / "slurm_job.sh"
        script_path.write_text(self._build_slurm_script(), encoding="utf-8")
        script_path.chmod(0o755)

        proc = self._run_local(["sbatch", str(script_path)], check=True)
        tokens = proc.stdout.strip().split()
        if not tokens or not tokens[-1].isdigit():
            raise RuntimeError(f"Unexpected sbatch output: {proc.stdout.strip()}")
        return tokens[-1]

    def wait_for_completion(self, job_id: str, poll_sec: int = 8) -> None:
        while True:
            proc = self._run_local(["squeue", "-h", "-j", job_id])
            if proc.returncode != 0:
                break
            if not proc.stdout.strip():
                break
            print(f"[*] Waiting for Slurm job {job_id} ...")
            time.sleep(poll_sec)

    def collect_job_metadata(self, job_id: str) -> Dict[str, str]:
        proc = self._run_local(
            ["sacct", "-j", job_id, "--format=JobID,State,Elapsed,NodeList", "-P", "-n"]
        )
        return {
            "job_id": job_id,
            "sacct": proc.stdout.strip(),
            "sacct_err": proc.stderr.strip(),
        }


def _safe_json_load(path: Path) -> Optional[Dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def _extract_tcp_metrics(data: Dict) -> Dict[str, float]:
    end = data.get("end", {})
    sum_sent = end.get("sum_sent", {})
    sum_received = end.get("sum_received", {})
    cpu = end.get("cpu_utilization_percent", {})

    tx_bps = float(sum_sent.get("bits_per_second", 0.0))
    rx_bps = float(sum_received.get("bits_per_second", 0.0))

    return {
        "tx_gbps": tx_bps / 1e9,
        "rx_gbps": rx_bps / 1e9,
        "agg_gbps": (tx_bps + rx_bps) / 1e9,
        "retransmits": float(sum_sent.get("retransmits", 0.0)),
        "cpu_host": float(cpu.get("host_total", 0.0)),
        "cpu_remote": float(cpu.get("remote_total", 0.0)),
    }


def _extract_udp_metrics(data: Dict) -> Dict[str, float]:
    end = data.get("end", {})
    udp = end.get("sum", {}) if "sum" in end else end.get("sum_received", {})
    return {
        "udp_jitter_ms": float(udp.get("jitter_ms", 0.0)),
        "udp_lost_percent": float(udp.get("lost_percent", 0.0)),
    }


def _parse_ping_avg_ms(ping_text: str) -> float:
    for line in ping_text.splitlines():
        if "min/avg/max" in line and "=" in line:
            rhs = line.split("=", 1)[1].strip()
            vals = rhs.split(" ", 1)[0].split("/")
            if len(vals) >= 2:
                try:
                    return float(vals[1])
                except ValueError:
                    return 0.0
    return 0.0


def _count_error_signatures(text: str) -> Dict[str, int]:
    signatures = {
        "pcie_aer": ["aer", "pcie bus error", "uncorrected", "corrected error"],
        "net_stack": ["netdev watchdog", "tx timeout", "reset adapter", "xid"],
        "ring_overflow": ["rx_missed", "rx_no_buffer", "fifo"],
        "iface_errors": ["rx_errors", "tx_errors", "dropped", "overrun", "carrier"],
    }
    lowered = text.lower()
    return {k: sum(lowered.count(p) for p in pats) for k, pats in signatures.items()}


def _parse_ethtool_stats(text: str) -> Dict[str, int]:
    counters: Dict[str, int] = {}
    for line in text.splitlines():
        m = re.match(r"\s*([A-Za-z0-9_./-]+)\s*:\s*(-?\d+)\s*$", line)
        if m:
            counters[m.group(1).lower()] = int(m.group(2))
    return counters


def _parse_ip_link_stats(text: str) -> Dict[str, int]:
    # Parse Linux ip -s link blocks for RX/TX errors and dropped fields.
    rx_errors = rx_dropped = tx_errors = tx_dropped = 0
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if line.strip().startswith("RX:") and idx + 1 < len(lines):
            nums = lines[idx + 1].split()
            if len(nums) >= 4:
                rx_errors = int(nums[2])
                rx_dropped = int(nums[3])
        if line.strip().startswith("TX:") and idx + 1 < len(lines):
            nums = lines[idx + 1].split()
            if len(nums) >= 4:
                tx_errors = int(nums[2])
                tx_dropped = int(nums[3])
    return {
        "rx_errors": rx_errors,
        "rx_dropped": rx_dropped,
        "tx_errors": tx_errors,
        "tx_dropped": tx_dropped,
    }


def _delta(post: int, pre: int) -> int:
    return post - pre if post >= pre else 0


def _extract_node_deltas(pre_dir: Path, post_dir: Path) -> Dict[str, int]:
    pre_eth = _parse_ethtool_stats((pre_dir / "ethtool_stats.txt").read_text(encoding="utf-8", errors="replace") if (pre_dir / "ethtool_stats.txt").exists() else "")
    post_eth = _parse_ethtool_stats((post_dir / "ethtool_stats.txt").read_text(encoding="utf-8", errors="replace") if (post_dir / "ethtool_stats.txt").exists() else "")

    pre_ip = _parse_ip_link_stats((pre_dir / "ip_link_stats.txt").read_text(encoding="utf-8", errors="replace") if (pre_dir / "ip_link_stats.txt").exists() else "")
    post_ip = _parse_ip_link_stats((post_dir / "ip_link_stats.txt").read_text(encoding="utf-8", errors="replace") if (post_dir / "ip_link_stats.txt").exists() else "")

    return {
        "rx_errors_delta": _delta(post_ip.get("rx_errors", 0), pre_ip.get("rx_errors", 0)),
        "tx_errors_delta": _delta(post_ip.get("tx_errors", 0), pre_ip.get("tx_errors", 0)),
        "rx_dropped_delta": _delta(post_ip.get("rx_dropped", 0), pre_ip.get("rx_dropped", 0)),
        "tx_dropped_delta": _delta(post_ip.get("tx_dropped", 0), pre_ip.get("tx_dropped", 0)),
        "rx_missed_errors_delta": _delta(post_eth.get("rx_missed_errors", 0), pre_eth.get("rx_missed_errors", 0)),
        "rx_no_buffer_count_delta": _delta(post_eth.get("rx_no_buffer_count", 0), pre_eth.get("rx_no_buffer_count", 0)),
    }


def build_summary(result_dir: Path, nodes: List[str], expected_per_dir_gbps: float) -> Dict:
    raw = result_dir / "raw"
    tcp_files = sorted(raw.glob("*_tcp.json"))

    rows: List[Dict] = []
    expected_agg = expected_per_dir_gbps * 2.0

    for tcp_path in tcp_files:
        stem = tcp_path.name.replace("_tcp.json", "")
        parts = stem.split("_to_")
        if len(parts) != 2:
            continue
        src, dst = parts

        tcp_data = _safe_json_load(tcp_path)
        udp_data = _safe_json_load(raw / f"{stem}_udp.json")

        ping_path = raw / f"{stem}_ping.txt"
        ping_txt = ping_path.read_text(encoding="utf-8", errors="replace") if ping_path.exists() else ""

        tcp = _extract_tcp_metrics(tcp_data or {})
        udp = _extract_udp_metrics(udp_data or {})
        ping_avg = _parse_ping_avg_ms(ping_txt)
        pct_expected = (tcp["agg_gbps"] / expected_agg * 100.0) if expected_agg else 0.0

        bottleneck = "none"
        if tcp["agg_gbps"] < expected_agg * 0.8:
            if max(tcp["cpu_host"], tcp["cpu_remote"]) > 85.0:
                bottleneck = "cpu_or_kernel_stack"
            elif tcp["retransmits"] > 1000 or udp["udp_lost_percent"] > 0.5:
                bottleneck = "packet_loss_or_congestion"
            else:
                bottleneck = "fabric_or_nic_limit"

        rows.append(
            {
                "src": src,
                "dst": dst,
                "tx_gbps": round(tcp["tx_gbps"], 2),
                "rx_gbps": round(tcp["rx_gbps"], 2),
                "agg_gbps": round(tcp["agg_gbps"], 2),
                "expected_agg_gbps": round(expected_agg, 2),
                "pct_of_expected": round(pct_expected, 2),
                "cpu_host_pct": round(tcp["cpu_host"], 2),
                "cpu_remote_pct": round(tcp["cpu_remote"], 2),
                "retransmits": int(tcp["retransmits"]),
                "udp_jitter_ms": round(udp["udp_jitter_ms"], 3),
                "udp_lost_pct": round(udp["udp_lost_percent"], 3),
                "ping_avg_ms": round(ping_avg, 3),
                "bottleneck": bottleneck,
            }
        )

    node_health = []
    for node in nodes:
        pre_dir = raw / f"{node}_pre"
        post_dir = raw / f"{node}_post"

        text_blobs = []
        for fn in ["dmesg_tail.txt", "ethtool_stats.txt", "ip_link_stats.txt", "nstat.txt", "lspci_vv.txt"]:
            p = post_dir / fn
            if p.exists():
                text_blobs.append(p.read_text(encoding="utf-8", errors="replace"))
        merged = "\n".join(text_blobs)

        sig = _count_error_signatures(merged)
        deltas = _extract_node_deltas(pre_dir, post_dir)
        node_health.append({"node": node, **sig, **deltas})

    agg_vals = [r["agg_gbps"] for r in rows]
    summary = {
        "generated_at": datetime.now().isoformat(),
        "expected_gbps_per_direction": expected_per_dir_gbps,
        "rows": rows,
        "node_health": node_health,
        "overall": {
            "pairs_tested": len(rows),
            "avg_agg_gbps": round(sum(agg_vals) / len(agg_vals), 2) if agg_vals else 0.0,
            "min_agg_gbps": round(min(agg_vals), 2) if agg_vals else 0.0,
            "max_agg_gbps": round(max(agg_vals), 2) if agg_vals else 0.0,
        },
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Slurm-native iperf3 test runner")
    parser.add_argument("--nodes", nargs="+", default=DEFAULT_NODES)
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--tcp-omit", type=int, default=5)
    parser.add_argument("--streams", type=int, default=32)
    parser.add_argument("--udp-duration", type=int, default=20)
    parser.add_argument("--udp-bandwidth-gbps", type=int, default=20)
    parser.add_argument("--ping-count", type=int, default=20)
    parser.add_argument("--interface", default="")
    parser.add_argument("--partition", default="")
    parser.add_argument("--account", default="")
    parser.add_argument("--time-limit", default="01:00:00")
    parser.add_argument("--cpus-per-task", type=int, default=160)
    parser.add_argument("--cpu-bind", default="cores")
    parser.add_argument("--server-cpu", type=int, default=0)
    parser.add_argument("--client-cpu", type=int, default=1)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--expected-gbps-per-direction", type=float, default=200.0)
    parser.add_argument("--submit-only", action="store_true")
    args = parser.parse_args()

    if args.cpus_per_task < 1:
        raise ValueError("--cpus-per-task must be >= 1")
    if args.server_cpu < 0 or args.client_cpu < 0:
        raise ValueError("--server-cpu and --client-cpu must be >= 0")
    if args.server_cpu >= args.cpus_per_task or args.client_cpu >= args.cpus_per_task:
        raise ValueError("--server-cpu/--client-cpu must be less than --cpus-per-task")
    if args.tcp_omit < 0:
        raise ValueError("--tcp-omit must be >= 0")

    cfg = RunnerConfig(
        nodes=args.nodes,
        duration_sec=args.duration,
        tcp_omit_sec=args.tcp_omit,
        streams=args.streams,
        udp_duration_sec=args.udp_duration,
        udp_bandwidth_gbps=args.udp_bandwidth_gbps,
        ping_count=args.ping_count,
        interface_hint=args.interface,
        partition=args.partition,
        account=args.account,
        time_limit=args.time_limit,
        slurm_cpus_per_task=args.cpus_per_task,
        slurm_cpu_bind=args.cpu_bind,
        server_cpu=args.server_cpu,
        client_cpu=args.client_cpu,
        run_id=args.run_id,
        expected_gbps_per_direction=args.expected_gbps_per_direction,
    )

    runner = SlurmIperfRunner(cfg)

    try:
        runner.validate_slurm_tools()
        job_id = runner.submit_slurm_job()
        print(f"[*] Submitted Slurm job: {job_id}")

        meta = runner.collect_job_metadata(job_id)
        (runner.result_dir / "job_meta_pre.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )

        if args.submit_only:
            print(f"[*] Submit-only mode. Results directory: {runner.result_dir}")
            return 0

        runner.wait_for_completion(job_id)

        meta_after = runner.collect_job_metadata(job_id)
        (runner.result_dir / "job_meta_post.json").write_text(
            json.dumps(meta_after, indent=2), encoding="utf-8"
        )

        summary = build_summary(
            runner.result_dir,
            cfg.nodes,
            expected_per_dir_gbps=cfg.expected_gbps_per_direction,
        )
        summary_path = runner.result_dir / "summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        print(f"[*] Completed. Summary: {summary_path}")
        return 0

    except Exception as exc:
        print(f"[!] Runner failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
