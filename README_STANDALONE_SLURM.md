# Standalone Slurm Workflow: NIC Tuning + Performance Sweep

This guide is for the standalone path only:
1. Apply NIC/channel/sysctl tuning across nodes.
2. Run standalone Slurm-style workload sweeps and collect KPI results.

It uses:
- `apply_net_tuning_with_channels.sh`
- `standalone_slurm_iperf3_kpi.sh`

## Executive Summary (2026-04-03 Baseline)

- Run ID: `20260403_050628` on `debug` partition, 4 nodes, `120s` tests, `8` streams.
- Core sweep `16,32,64,96,128` delivered best average aggregate throughput at `128` cores: `306.04 Gbps`.
- Peak single-path aggregate reached `357.39 Gbps` (`sc00901112s0103 -> 220.0.0.104`).
- Scaling is non-monotonic (dip at `64` cores), indicating placement/queue/NUMA effects rather than CPU saturation.
- Busy cores stayed low (roughly `4-5.3` active cores average), so CPU headroom remains available.
- Retransmits remain high on weaker paths, and one latency outlier (`6.246 ms`) was observed at `128` cores.

Immediate actions:
- Re-run `64/96/128` core points 3 times each to establish variance.
- At fixed `128` cores, sweep streams (`8,16,32,64`) to map throughput ceiling.
- Correlate retransmit spikes with switch port and NIC queue counters on weak paths.

## 1. Prerequisites

Run from your project directory:

```bash
cd /root/Iperf3validation
```

Required tools on submit node:

```bash
which ssh scontrol sinfo python3 iperf3 ping
```

Required access:
- Passwordless SSH from submit node to each test node as root (or sudo-capable user).
- `ethtool` and `sysctl` available on compute nodes.

## 2. Make Scripts Executable

```bash
chmod +x apply_net_tuning_with_channels.sh
chmod +x standalone_slurm_iperf3_kpi.sh
```

## 3. Apply Tuning Profiles (Channels Sweep)

Run tuning with different channel counts:

```bash
COMBINED_CHANNELS=32  ./apply_net_tuning_with_channels.sh
COMBINED_CHANNELS=64  ./apply_net_tuning_with_channels.sh
COMBINED_CHANNELS=128 ./apply_net_tuning_with_channels.sh
```

Notes:
- The script auto-clamps requested combined channels to NIC maximum.
- Default interface is `enP1s23f1np1`. Override with `IFACE=<your_nic>`.

Example with explicit interface:

```bash
IFACE=eno1 COMBINED_CHANNELS=64 ./apply_net_tuning_with_channels.sh
```

## 4. Validate Tuning Applied

Quick check per node:

```bash
for n in sc00901112s0101 sc00901112s0103 sc00901112s0104 sc00901112s0106; do
  echo "===== $n ====="
  ssh root@$n "ethtool -l enP1s23f1np1 | sed -n '1,25p'; sysctl net.core.rmem_max net.core.wmem_max net.core.netdev_max_backlog"
done
```

## 5. Run Standalone Workload (TCP Max Throughput)

Recommended first run (UDP disabled):

```bash
RUN_UDP=0 \
CORE_SCALE_LIST="1,8,16,32,48,64,72,96,128,144,192" \
STREAM_SCALE_LIST="1,8,16,32,48,64,72,96,128,144,192" \
DURATION=120 TCP_OMIT=5 \
./standalone_slurm_iperf3_kpi.sh
```

What this does:
- Runs full src->dst pair matrix across all nodes.
- Sweeps requested core counts.
- Scales stream count with your stream list.
- Pins server/client processes with `taskset`.
- Produces per-scale and per-path KPI output.

## 6. Run with UDP KPI Enabled

If you also want jitter/loss measurements:

```bash
RUN_UDP=1 \
UDP_BW_G=200 UDP_DURATION=15 \
CORE_SCALE_LIST="32,64,96,128" \
STREAM_SCALE_LIST="32,64,96,128" \
DURATION=120 TCP_OMIT=5 \
./standalone_slurm_iperf3_kpi.sh
```

## 7. Result Files

Each run writes to:

```text
results/<run_id>/
```

Key outputs:
- `results/<run_id>/summary.json`
- `results/<run_id>/report.txt`
- `results/<run_id>/iperf/*` (raw TCP/UDP JSON and stderr)
- `results/<run_id>/ping/*`
- `results/<run_id>/cpu/*`
- `results/<run_id>/raw/*.meta.json`

## 8. Compare Tuning Profiles

Run this sequence for each channel profile (32, 64, 128):
1. Apply tuning with `COMBINED_CHANNELS=<value>`.
2. Execute standalone workload script with same sweep settings.
3. Save or rename run folders for comparison.

Example:

```bash
COMBINED_CHANNELS=64 ./apply_net_tuning_with_channels.sh
RUN_UDP=0 CORE_SCALE_LIST="1,8,16,32,48,64,72,96,128,144,192" STREAM_SCALE_LIST="1,8,16,32,48,64,72,96,128,144,192" DURATION=120 TCP_OMIT=5 ./standalone_slurm_iperf3_kpi.sh
```

Then compare:
- `avg_agg_gbps`
- best `scale_summary` entries
- retransmits and CPU percentages

## 9. Latest Core Sweep Baseline (Run `20260403_050628`)

Use this as the current reference dataset for standalone core scaling.

Run metadata:
- Partition: `debug`
- Nodes: `sc00901112s0101 sc00901112s0103 sc00901112s0104 sc00901112s0106`
- Duration: `120s`
- Streams: `8`
- Expected per direction: `200 Gbps`
- Core steps: `16,32,64,96,128`
- Results root: `results/20260403_050628`

Execution command:

```bash
RUN_UDP=0 CORE_SCALE_LIST="1,8,16,32,48,64,72,96,128,144,192" STREAM_SCALE_LIST="1,8,16,32,48,64,72,96,128,144,192" DURATION=120 TCP_OMIT=5 ./standalone_slurm_iperf3_kpi.sh
```

Core scaling summary (from `results/20260403_050628/report.txt`):

| Cores | Pairs | Avg Agg Gbps | Min Agg Gbps | Max Agg Gbps | Avg Host Cores | Avg Rem Cores |
|------:|------:|-------------:|-------------:|-------------:|---------------:|--------------:|
| 16    | 4     | 263.48       | 253.80       | 273.54       | 4.24           | 4.15          |
| 32    | 4     | 282.62       | 254.10       | 317.14       | 4.81           | 4.65          |
| 64    | 4     | 261.66       | 249.48       | 274.54       | 4.10           | 4.14          |
| 96    | 4     | 284.86       | 260.02       | 316.56       | 4.75           | 4.65          |
| 128   | 4     | 306.04       | 274.08       | 357.39       | 5.19           | 5.33          |

Per-pair highlights:
- Strongest path across sweeps: `sc00901112s0103 -> 220.0.0.104` (up to `357.39 Gbps` at 128 cores).
- Weakest recurring path: `sc00901112s0106 -> 220.0.0.101` (as low as `252.52 Gbps` at 64 cores).
- All pairs report `OK` status for all tested core budgets.

### Technical Analysis (for team sharing)

1. Throughput vs core budget is non-monotonic but trends upward at high core counts.
  - Average aggregate improves from `263.48` (16c) to `306.04 Gbps` (128c), about `+16.2%`.
  - Local dip at 64 cores (`261.66 Gbps`) suggests scheduler/NUMA/IRQ alignment effects rather than raw CPU shortage.

2. Effective busy cores stay low relative to requested cores.
  - Even with 128 requested cores, average busy cores are only about `5.19` host and `5.33` remote.
  - This indicates the workload is not compute-saturated; performance is likely constrained by flow distribution, NIC queue handling, or fabric path quality.

3. Path asymmetry remains significant.
  - Best observed pair reaches `357.39 Gbps` while weaker links remain around `250-275 Gbps`.
  - Recommend validating link-level parity for weaker paths (switch port counters, NIC queue stats, PCIe lane width/speed, and route consistency).

4. Retransmissions are persistently high and generally increase at higher core budgets on some paths.
  - Example: `sc00901112s0106 -> 220.0.0.101` rises to `1,595,706` retrans at 128 cores.
  - This can mask true headroom and indicates congestion or loss domain pressure despite low ping averages.

5. Latency is mostly stable, with one notable outlier.
  - Most ping averages stay around `0.31-0.52 ms`.
  - `sc00901112s0104 -> 220.0.0.106` at 128 cores shows `6.246 ms`, an outlier worth immediate retest and switch/NIC telemetry correlation.

6. Current best operating point in this run set.
  - For maximum observed aggregate throughput, `128 cores / 8 streams` is best in this dataset.
  - For efficiency (`Gbps per busy core`), several mid-scale points remain competitive, so choose profile based on whether peak bandwidth or stability is the primary KPI.

Recommended next validation run:
- Keep `DURATION=120`, `TCP_OMIT=5`, and repeat `64/96/128` core points 3x for variance bands.
- Increase stream sweep around top region (`8,16,32,64`) at fixed `128` cores.
- Capture concurrent switch/NIC counters during run windows to map retrans spikes to specific links/queues.

## 10. Troubleshooting

If tuning fails:
- Verify interface name (`IFACE`).
- Verify SSH access and root permissions.
- Check `ethtool -l <iface>` supports combined channel updates.

If workload fails:
- Check `results/<run_id>/iperf/*stderr`.
- Check reachability between node admin IPs.
- Start with smaller scales first:

```bash
RUN_UDP=0 CORE_SCALE_LIST="8,16,32" STREAM_SCALE_LIST="8,16,32" DURATION=60 TCP_OMIT=3 ./standalone_slurm_iperf3_kpi.sh
```

## 11. Minimal Daily Command Set

```bash
cd /root/Iperf3validation
chmod +x apply_net_tuning_with_channels.sh standalone_slurm_iperf3_kpi.sh
COMBINED_CHANNELS=64 ./apply_net_tuning_with_channels.sh
RUN_UDP=0 CORE_SCALE_LIST="1,8,16,32,48,64,72,96,128,144,192" STREAM_SCALE_LIST="1,8,16,32,48,64,72,96,128,144,192" DURATION=120 TCP_OMIT=5 ./standalone_slurm_iperf3_kpi.sh
```
