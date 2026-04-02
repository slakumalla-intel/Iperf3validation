# Iperf3 Slurm Network Performance Testing Suite

Comprehensive Slurm-native network performance testing framework for Linux HPC systems. Tests bidirectional bandwidth, latency, jitter, and identifies CPU/fabric/PCIe bottlenecks with detailed KPI tables.

## Overview

This suite validates 200 Gbps bidirectional network performance across your 4-node rack system using Slurm job scheduling. It applies kernel/NIC tuning, runs TCP/UDP tests, collects PCIe/network error signatures, and produces KPI reports showing bandwidth vs expected, CPU utilization, latency, and bottleneck classification.

**System Configuration:**
- **4 Nodes**: sc00901112s0101, sc00901112s0103, sc00901112s0104, sc00901112s0106
- **Partition**: debug
- **Cores per node**: 160 cores
- **Target bandwidth**: 200 Gbps per direction (400 Gbps aggregate)
- **Test protocol**: TCP bidirectional + UDP latency/jitter
- **Parallel streams**: 32 (tuned for 160-core systems)
- **Test pairings**: 12 (all source-destination combinations)

## Requirements

### Submission Node (node 9 or login node)
- Python 3.7+
- Slurm tools: `sbatch`, `squeue`, `sacct`
- Network tools: `ping`

### Compute Nodes
- CentOS 7/8 or RHEL 7/8+
- iperf3 (installed or will be during job execution)
- Linux kernel 4.0+ (for BBR congestion control)
- Privileged access to apply network tuning (root capable)

## Files

| File | Purpose |
|------|---------|
| `orchestrate.py` | Main orchestrator - submits Slurm job and generates report |
| `iperf3_test_runner.py` | Slurm job script - applies tuning, runs tests, collects metrics |
| `bottleneck_analyzer.py` | KPI report generator - produces formatted tables |
| `diagnostic.py` | Troubleshooting tool for single node testing |
| `README.md` | This file |

## Quick Start (3 Commands)

### 1. Navigate to project directory
```bash
cd /root/Iperf3validation
```

### 2. Verify dependencies
```bash
python3 --version          # Should be 3.7+
which sbatch               # Should be in /usr/bin or /usr/local/bin
which iperf3               # iperf3 will be installed by the job
```

### 3. Run the test suite
```bash
python3 orchestrate.py
```

The script will:
1. ✓ Submit Slurm batch job to `debug` partition
2. ✓ Apply kernel/NIC tuning on each compute node
3. ✓ Start iperf3 servers
4. ✓ Run bidirectional TCP tests (P=32 parallel streams)
5. ✓ Run UDP latency/jitter tests
6. ✓ Collect PCIe/network/interface error telemetry
7. ✓ Generate summary.json and KPI report table
8. ✓ Display formatted bottleneck analysis

**Typical runtime**: 10-15 minutes total

## Installation

### On CentOS (if not already done)
```bash
sudo yum update -y
sudo yum install -y \
  python3 \
  iperf3 \
  iproute \
  ethtool \
  net-tools \
  pciutils \
  dmesg
```

### Verify Slurm is available
```bash
sinfo
squeue
sacct --version
```

Expected output from `sinfo`:
```
PARTITION AVAIL  TIMELIMIT  NODES  STATE NODELIST
debug*       up   infinite      4   idle sc00901112s[0101,0103-0104,0106]
```

## Running Tests

### Option A: Default run (recommended)
```bash
python3 orchestrate.py
```
Uses:
- Duration: 120 seconds per test
- Streams: 32 parallel TCP connections
- Partition: debug (auto-detected)

### Option B: Custom parameters
```bash
python3 orchestrate.py \
  --duration 300 \
  --streams 64 \
  --udp-duration 30 \
  --udp-bandwidth-gbps 30 \
  --time-limit 02:00:00
```

### Option C: Submit without waiting
```bash
python3 orchestrate.py --submit-only
```
Then later check results:
```bash
squeue -u root
python3 bottleneck_analyzer.py
```

## Results

All results are saved under `results/<run_id>/` where run_id is a timestamp (e.g., `20260401_143045`)

### Key Output Files
- **summary.json** - Structured KPI data (machine-readable)
- **kpi_report.txt** - Formatted tables with bottleneck analysis
- **raw/** - Raw iperf3 JSON outputs, ethtool stats, dmesg, lspci info

### Example Report Output
```
============================================================
SLURM IPERF3 KPI REPORT
============================================================
Summary source : results/20260401_143045/summary.json
Generated at   : 2026-04-01T14:30:45.123456
Pairs tested   : 12
Avg Agg Gbps   : 185.45
Min/Max Agg    : 175.23 / 195.67

Bandwidth vs Expected
+-----------------------------------+--------+--------+--------+----------+-------+----------+----------+---------+-----------+-----------+---------+---------------+
| Path                              | TX Gbps| RX Gbps| Agg Gbps| Expected | % Exp | CPU Host%| CPU Rem% |Retrans  | UDP Jit ms| UDP Lost%| Ping ms | Bottleneck    |
+-----------------------------------+--------+--------+--------+----------+-------+----------+----------+---------+-----------+-----------+---------+---------------+
| sc00901112s0101->sc00901112s0103  |  98.2  |  87.3  |  185.5  |  400.0   | 46.4% |  42.5    |  38.2    |    0    |   0.045   |   0.0    |  0.350  | fabric_or_nic |
| sc00901112s0101->sc00901112s0104  |  92.1  |  89.7  |  181.8  |  400.0   | 45.5% |  38.2    |  36.1    |    0    |   0.051   |   0.0    |  0.362  | fabric_or_nic |
...

Node-level Error Signatures
+-----------------------------------+----------+-----------+-------------+-----------+
| Node                              | PCIe/AER | Net Stack | Iface Errors| Ring Over |
+-----------------------------------+----------+-----------+-------------+-----------+
| sc00901112s0101                   |    0     |     0     |      0      |     0     |
| sc00901112s0103                   |    0     |     0      |      0      |     0     |
| sc00901112s0104                   |    0     |     0      |      0      |     0     |
| sc00901112s0106                   |    0     |     0      |      0      |     0     |
+-----------------------------------+----------+-----------+-------------+-----------+

Top Findings
1. All paths are below 80% of expected bidirectional throughput.
2. Likely bottleneck is fabric/NIC PHY given low CPU utilization.
```

## Understanding the Report

### Bandwidth vs Expected Table

| Column | Meaning | What to Look For |
|--------|---------|------------------|
| **Path** | Source → Destination node | N/A |
| **TX Gbps** | Transmit throughput | Higher is better; ideally ~200 Gbps |
| **RX Gbps** | Receive throughput | Higher is better; ideally ~200 Gbps |
| **Agg Gbps** | TX + RX aggregate | Target: 400 Gbps (200G each direction) |
| **Expected** | Target bidirectional throughput | 400 Gbps (2 × 200 Gbps links) |
| **% Exp** | Percent of expected | 80-100% = good; <80% = investigate |
| **CPU Host%** | CPU utilization on sender | <85% = CPU not bottleneck |
| **CPU Rem%** | CPU utilization on receiver | <85% = CPU not bottleneck |
| **Retrans** | TCP retransmissions | 0 = no packet loss; >1000 = congestion |
| **UDP Jit ms** | UDP jitter (variation in latency) | <0.1 ms = excellent; >1 ms = unstable |
| **UDP Lost%** | UDP packet loss | 0% = perfect; >0.5% = congestion/errors |
| **Ping ms** | ICMP round-trip latency | <1 ms = excellent; >2 ms = suspect |
| **Bottleneck** | Identified constraint | cpu_or_kernel_stack, packet_loss_or_congestion, fabric_or_nic_limit, none |

### Bottleneck Classification

- **none** - Path is performing well (≥80% expected, no errors)
- **cpu_or_kernel_stack** - CPU >85% on host/remote; tune kernel or increase nodes
- **packet_loss_or_congestion** - High retransmits; check for network congestion/errors
- **fabric_or_nic_limit** - Low throughput despite low CPU; NIC or fabric is limiting factor

### Node-level Error Signatures

Error counts from dmesg, ethtool stats, and interface counters post-run:
- **PCIe/AER** - PCIe Advanced Error Reporting (AER) events
- **Net Stack** - Kernel network stack errors (timeouts, watchdog, resets)
- **Iface Errors** - NIC interface errors (rx_errors, tx_errors, dropped, overrun)
- **Ring Over** - TX/RX ring buffer overflows

**Expected**: All zeros. Non-zero indicates hardware/driver issues.

## Troubleshooting

### Job won't submit: "sbatch not found"
```bash
which sbatch
# If empty, check Slurm installation
sinfo --version
```

### Job fails: "No test results collected"
Check the Slurm output log:
```bash
cat results/*/slurm_job.sh
# Examine the raw iperf3 outputs
cat results/*/raw/*_tcp.stderr
cat results/*/raw/*_udp.stderr
```

### Very low throughput reported
Check if tuning applied correctly:
```bash
# Inspect what was attempted
cat results/*/raw/sc00901112s0101_post/ethtool_features.txt
cat results/*/raw/sc00901112s0101_post/ethtool_ring.txt
```

### Network stack errors in report
Run diagnostic on single node first:
```bash
python3 diagnostic.py
```

### Can't generate report: "No summary.json found"
Wait for Slurm job to complete:
```bash
squeue -u root
# Once job completes (not in queue), run:
python3 bottleneck_analyzer.py
```

## Advanced Usage

### Specify a different NIC interface
```bash
python3 orchestrate.py --interface eno1
```

### Run longer test for stability
```bash
python3 orchestrate.py --duration 600 --time-limit 02:00:00
```

### Use more parallel streams for saturating NICs
```bash
python3 orchestrate.py --streams 128
```

### Custom Slurm parameters
Edit `iperf3_test_runner.py` line 87-92 to add extra Slurm directives:
```python
#SBATCH --exclusive     # Request exclusive node access
#SBATCH --ntasks-per-node=1
```

## Expected Performance Baseline

For 160-core nodes with 200 Gbps NICs, well-tuned systems should achieve:

| Metric | Expected |
|--------|----------|
| Aggregate Gbps (bidirectional) | 350-400 Gbps |
| CPU Host utilization | 20-50% |
| CPU Remote utilization | 20-50% |
| UDP jitter | <0.1 ms |
| UDP packet loss | 0% |
| Ping RTT | <0.5 ms |
| TCP retransmits | 0 (or <100) |

If you're consistently below 80% of expected, the bottleneck is likely:
1. **Fabric/NIC PHY** - Check switch port config, cable quality
2. **Network stack tuning** - Script applies automatically; verify it succeeded
3. **Interrupt handling** - May need CPU affinity (not yet automated)
4. **Background traffic** - Run during off-peak hours

## Support

For issues, provide the following:
```bash
# Check job status
squeue -u root

# Get job ID and look at Slurm output
ls -ltr results/*/

# Examine detailed errors
cat results/latest/raw/*_tcp.stderr
cat results/latest/raw/*_udp.stderr

# View system info from post-run
cat results/latest/raw/sc00901112s0101_post/dmesg_tail.txt
cat results/latest/raw/sc00901112s0101_post/lspci_vv.txt
```

## References

- [iperf3 Documentation](https://software.es.net/iperf/)
- [Linux Network Tuning Guide](https://fasterdata.es.net/host-tuning/)
- [BBR Congestion Control](https://research.google/pubs/bbr-congestion-based-congestion-control/)
- [Slurm Documentation](https://slurm.schedmd.com/sbatch.html)

---

**Framework Version**: 2.0 (Slurm-native)
**Last Updated**: 2026-04-01
**Python Version**: 3.7+
**iperf3 Version**: 3.0+
**CentOS Version**: 7/8+
**Test Nodes**: sc00901112s[0101,0103-0104,0106]

