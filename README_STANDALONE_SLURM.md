# Standalone Slurm Workflow: NIC Tuning + Performance Sweep

This guide is for the standalone path only:
1. Apply NIC/channel/sysctl tuning across nodes.
2. Run standalone Slurm-style workload sweeps and collect KPI results.

It uses:
- `apply_net_tuning_with_channels.sh`
- `standalone_slurm_iperf3_kpi.sh`

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

## 9. Troubleshooting

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

## 10. Minimal Daily Command Set

```bash
cd /root/Iperf3validation
chmod +x apply_net_tuning_with_channels.sh standalone_slurm_iperf3_kpi.sh
COMBINED_CHANNELS=64 ./apply_net_tuning_with_channels.sh
RUN_UDP=0 CORE_SCALE_LIST="1,8,16,32,48,64,72,96,128,144,192" STREAM_SCALE_LIST="1,8,16,32,48,64,72,96,128,144,192" DURATION=120 TCP_OMIT=5 ./standalone_slurm_iperf3_kpi.sh
```
