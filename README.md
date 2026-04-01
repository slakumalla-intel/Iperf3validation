# Iperf3 Multi-Node Network Performance Testing Suite

Comprehensive network performance testing framework for rack systems with detailed bottleneck analysis.

## Overview

This suite tests bandwidth performance between all node pairs in a multi-node system, analyzes CPU utilization, and identifies network bottlenecks.

**Configuration:**
- **4 Nodes**: 220.0.0.101, 220.0.0.103, 220.0.0.104, 220.0.0.106
- **Cores per node**: 160 cores
- **Test protocol**: TCP (bidirectional)
- **Parallel streams**: 16 (tuned for 160-core systems)
- **Test duration**: 300 seconds per test
- **Total paths**: 12 (6 node pairs × 2 directions)

## Requirements

### On Control Machine (Windows/Linux)
- Python 3.7+
- SSH access to all 4 nodes with root/sudo privileges
- SSH key-based authentication (recommended) or password auth

### On Test Nodes
- iperf3 installed (any recent version)
- Linux OS (Ubuntu, CentOS, RHEL, Fedora, etc.)
- Network connectivity between all nodes

## Files

| File | Purpose |
|------|---------|
| `iperf3_test_runner.py` | Main testing orchestrator - runs benchmarks and generates reports |
| `setup_nodes.py` | Installs iperf3 on all test nodes |
| `bottleneck_analyzer.py` | Detailed analysis of bottlenecks and performance issues |
| `README.md` | This file |

## Quick Start

### 1. Configure SSH Access

Ensure you can SSH to all nodes without password prompts:

```bash
# Edit iperf3_test_runner.py and set ssh_user if needed (line 20)
# Default: root

# Test SSH access
ssh root@220.0.0.101 "echo 'SSH works'"
ssh root@220.0.0.103 "echo 'SSH works'"
ssh root@220.0.0.104 "echo 'SSH works'"
ssh root@220.0.0.106 "echo 'SSH works'"
```

### 2. Setup Nodes (Optional)

If iperf3 is not installed on nodes, run setup:

```bash
python setup_nodes.py
```

### 3. Run Performance Tests

```bash
python iperf3_test_runner.py
```

**What happens:**
1. ✓ Checks connectivity to all 4 nodes
2. ✓ Starts iperf3 servers on all nodes
3. ✓ Runs bidirectional tests between all node pairs
4. ✓ Collects CPU utilization metrics
5. ✓ Generates text report (iperf3_report_YYYYMMDD_HHMMSS.txt)
6. ✓ Saves JSON results (iperf3_results_YYYYMMDD_HHMMSS.json)

### 4. Analyze Bottlenecks

```bash
python bottleneck_analyzer.py
```

**Generates:**
- Bottleneck Analysis Report
- Link saturation analysis
- CPU bottleneck detection
- Path asymmetry analysis
- Performance consistency metrics

## Understanding the Reports

### Main Report (iperf3_report_*.txt)

Shows overall performance metrics:

```
THROUGHPUT SUMMARY
  Average Throughput:  45.67 Gbps        # Mean across all paths
  Median Throughput:   44.23 Gbps
  Min Throughput:      38.45 Gbps        # Slowest path
  Max Throughput:      52.10 Gbps        # Fastest path
  Std Deviation:       4.23 Gbps         # Variability

CPU UTILIZATION ANALYSIS
  Avg Client CPU:      25.3%
  Max Client CPU:      67.8%             # Peak utilization
  Avg Server CPU:      18.1%
  Max Server CPU:      52.4%

BOTTLENECK ANALYSIS
  [1] Path: 220.0.0.101 → 220.0.0.103
      Throughput: 38.45 Gbps
      Degradation: 15.8%
```

### Bottleneck Analysis Report (bottleneck_analysis.txt)

Detailed diagnosis with recommendations:

```
[LINK SATURATION ANALYSIS]
Assuming 100GbE NIC per node (theoretical max: 100.00 Gbps)

🟢 OK    220.0.0.101 → 220.0.0.103:   45.67 Gbps (45.7% saturation)
🟡 HIGH  220.0.0.101 → 220.0.0.104:   82.30 Gbps (82.3% saturation)
```

### JSON Results (iperf3_results_*.json)

Raw data for custom analysis:

```json
[
  {
    "source": "220.0.0.101",
    "destination": "220.0.0.103",
    "throughput_gbps": 45.67,
    "throughput_mbps": 45670.00,
    "cpu_client": 25.3,
    "cpu_server": 18.1,
    "timestamp": "2026-04-01T14:23:45"
  }
]
```

## Interpreting Results

### Performance Levels

| Metric | Status | Interpretation |
|--------|--------|-----------------|
| > 90 Gbps | 🟢 Excellent | Near-wire speed 100GbE |
| 70-90 Gbps | 🟡 Good | Well utilized 100GbE link |
| 50-70 Gbps | 🟠 Fair | Application or CPU limited |
| < 50 Gbps | 🔴 Poor | Serious bottleneck |

### Bottleneck Types

**1. Link Saturation (Network Bottleneck)**
- If saturation > 80% and throughput increases with more threads: **network limited**
- If saturation doesn't change with parameter tuning: **link speed issue**

**2. CPU Bottleneck**
- Client CPU > 80%: Application limited, tune driver settings
- Server CPU > 80%: Application or interrupt handling limited
- Both high: System is CPU-bound, scale horizontally or optimize app

**3. Asymmetric Paths**
- Forward and reverse throughput differ > 20%: Check routing, duplex settings
- Indicates cable/port/NIC quality issues

**4. Performance Variability**
- Coefficient of Variation (CV) > 20%: Unstable performance
- Indicates network congestion, background traffic, or hardware issues

## Advanced Configuration

### Customize Test Parameters

Edit `iperf3_test_runner.py` in the `main()` function:

```python
def main():
    nodes = ["220.0.0.101", "220.0.0.103", "220.0.0.104", "220.0.0.106"]
    
    duration = 600    # Increase test duration (seconds)
    threads = 32      # Increase parallel streams for more cores
```

### Use Default SSH User

Edit line 20 in `iperf3_test_runner.py`:

```python
self.ssh_user = "ubuntu"  # or "centos", "ec2-user", etc.
```

### Use SSH Key

Add SSH key configuration:

```python
self.ssh_key = "/home/user/.ssh/id_rsa"  # Path to private key
# Then update SSH commands to use: ssh -i {self.ssh_key}
```

## Troubleshooting

### Issue: "Nodes are not reachable"

```bash
# Check network connectivity
ping 220.0.0.101
ping 220.0.0.103
ping 220.0.0.104
ping 220.0.0.106

# Check SSH access
ssh root@220.0.0.101 "hostname"
```

### Issue: "JSON parse error" / No test results

Ensure iperf3 is installed on nodes:

```bash
# On each node:
apt-get install -y iperf3        # Ubuntu/Debian
yum install -y iperf3            # RHEL/CentOS
dnf install -y iperf3            # Fedora

# Verify
iperf3 -v
```

### Issue: Very low throughput (< 10 Gbps)

1. Check network physically: inspect cables, ports, switch
2. Verify NIC drivers on nodes: `ethtool -i eth0`
3. Check for physical link issues: `ethtool eth0`
4. Verify no blocker: `sudo tcpdump -i eth0 src 220.0.0.101`

### Issue: High CPU but low throughput

Enable NIC offloading:

```bash
# On each node
ethtool -K eth0 tso on gso on lro on
ethtool -K eth0 rx-checksum on

# Verify
ethtool -k eth0
```

## Performance Baseline

For 100GbE connections with well-tuned systems:

| Throughput | Interpretation |
|------------|-----------------|
| 95-100 Gbps | Excellent - saturating 100GbE link |
| 80-95 Gbps | Very good - minimal packet loss/retransmit |
| 60-80 Gbps | Good - some CPU or tuning overhead |
| < 60 Gbps | Investigate for bottlenecks |

For 160-core systems with proper tuning:

| CPU Usage | Interpretation |
|-----------|-----------------|
| < 20% | Very low - underutilized |
| 20-40% | Normal - good efficiency |
| 40-70% | Moderate - acceptable load |
| > 80% | High - potential bottleneck |

## Example Scenarios

### Scenario 1: Perfect Network

```
Average Throughput: 96.50 Gbps
Consistency: 2.1% (excellent)
Client CPU: 35.2% (good)
Asymmetry: < 2% (symmetric)
Result: ✓ Network is performing optimally
```

### Scenario 2: CPU-Limited

```
Average Throughput: 52.30 Gbps
Client CPU: 95.2% (saturated)
Server CPU: 88.5% (saturated)
Result: ✗ CPU bottleneck - optimize application or use more nodes
```

### Scenario 3: Asymmetric Paths

```
Path 220.0.0.101→220.0.0.103: 92.1 Gbps
Path 220.0.0.103→220.0.0.101: 45.3 Gbps
Difference: 47% (high asymmetry)
Result: ✗ Check link quality, routing, or NIC settings
```

## Support & Additional Testing

For extended testing beyond this suite:

```bash
# Detailed traffic analysis
sudo tcpdump -i eth0 -w capture.pcap dst 220.0.0.103

# System performance profiling
perf stat iperf3 -c 220.0.0.103 -t 10

# Detailed network metrics
netstat -i
ethtool -S eth0
cat /proc/net/dev
```

## References

- [iperf3 Documentation](https://software.es.net/iperf/)
- [Linux Networking Tuning](https://fasterdata.es.net/host-tuning/)
- [100GbE Network Design](https://www.intel.com/content/www/us/en/networking/network-architecture-design.html)

---

**Generated**: 2026-04-01
**Suite Version**: 1.0
**Test Framework**: iperf3 3.x+

