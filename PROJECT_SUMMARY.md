# Iperf3 Validation Suite - Project Summary

## What's Included

This is a complete, production-ready iperf3 testing framework for your 4-node rack system (220.0.0.101, 220.0.0.103, 220.0.0.104, 220.0.0.106).

### Core Components

```
iperf3_test_runner.py       - Main test orchestrator (700+ lines)
├─ Connectivity checking
├─ Server management
├─ Bidirectional testing
├─ Performance metrics collection
└─ Report generation

bottleneck_analyzer.py      - Advanced diagnostics (400+ lines)
├─ Link saturation analysis
├─ CPU bottleneck detection
├─ Asymmetric path detection
├─ Performance consistency analysis
└─ Actionable recommendations

setup_nodes.py              - Automated node setup (90 lines)
├─ iperf3 installation
├─ Multi-OS support
└─ Verification

orchestrate.py              - Master controller (100 lines)
├─ Workflow orchestration
├─ One-command testing
└─ Report discovery
```

### Documentation

```
README.md                   - Complete user guide (450+ lines)
QUICKSTART.md               - Step-by-step setup (300+ lines)
config.ini                  - Configuration template
requirements.txt            - Python dependencies (none!)
```

## Quick Start (2 Steps)

### Step 1: Verify SSH Access
```powershell
ssh root@220.0.0.101 "echo Test"
```

### Step 2: Run Full Test Suite
```powershell
python orchestrate.py --full
```

That's it! You'll get:
- ✓ Performance metrics for all 4 nodes
- ✓ 12 bidirectional test paths
- ✓ CPU utilization analysis
- ✓ Bottleneck identification
- ✓ 2 detailed reports (text + JSON)

## What Happens During Testing

### Phase 1: Connectivity Check (1 minute)
- Pings all 4 nodes to verify network reachability
- Warns if any node is unreachable

### Phase 2: Node Setup (optional)
- Installs iperf3 if not already present
- Supports Ubuntu, CentOS, RHEL, Fedora
- Uses apt, yum, or dnf package managers

### Phase 3: Server Startup (1 minute)
- Starts iperf3 servers on all 4 nodes
- Listens on port 5201
- Running in daemon mode (no console output)

### Phase 4: Bandwidth Testing (30-45 minutes)
Tests all node pairs:
```
220.0.0.101 → 103, 104, 106     (3 tests)
220.0.0.103 → 101, 104, 106     (3 tests)
220.0.0.104 → 101, 103, 106     (3 tests)
220.0.0.106 → 101, 103, 104     (3 tests)
                          TOTAL: 12 tests
```

Each test:
- Duration: 300 seconds (5 minutes)
- Parallel streams: 16 (tuneable)
- Metrics: throughput, CPU, latency

### Phase 5: Analysis
- Computes statistics (mean, median, stdev)
- Identifies performance anomalies
- Detects bottlenecks
- Generates recommendations

### Phase 6: Reporting
Produces:
1. **iperf3_report_TIMESTAMP.txt** - Human-readable with tables
2. **iperf3_results_TIMESTAMP.json** - Raw data for tools
3. **bottleneck_analysis.txt** - Detailed findings

## Report Examples

### Main Report Shows:
```
THROUGHPUT SUMMARY
  Average: 92.50 Gbps
  Range: 45.23 - 98.45 Gbps
  Consistency: 2.1% variation

CPU UTILIZATION
  Client Peak: 67.8%
  Server Peak: 52.4%

PER-NODE STATISTICS
  220.0.0.101 sent: avg 45.2 Gbps, min 38.1, max 52.3
  220.0.0.101 recv: avg 47.8 Gbps, min 40.5, max 55.2
  ... (for all 4 nodes)

DETAILED RESULTS
Source          Dest            Throughput      CPU Client    CPU Server
220.0.0.101     220.0.0.103      45.23 Gbps      32.1%         28.5%
220.0.0.101     220.0.0.104      48.15 Gbps      35.8%         31.2%
... (all 12 paths)
```

### Bottleneck Analysis Shows:

```
[EXECUTIVE SUMMARY]
Average Throughput: 92.50 Gbps
Consistency: 2.1% (excellent)

[LINK SATURATION ANALYSIS]
🟢 OK    Path 1: 45.23 Gbps (45.2% saturation)
🟡 HIGH  Path 5: 82.30 Gbps (82.3% saturation)
🔴 CRIT  Path 12: 98.50 Gbps (98.5% saturation)

[CPU BOTTLENECK ANALYSIS]
Client CPU: avg 42.1%, max 67.8% (normal)
Server CPU: avg 35.2%, max 52.4% (good)

[ASYMMETRIC PATH ANALYSIS]
All paths symmetric (< 5% difference)

[BOTTLENECK ASSESSMENT]
Bottlenecks Detected:
  1. Link saturation on path 12 (98.5%)

[RECOMMENDATIONS]
• Consider load balancing across more paths
• Check cable quality on high-saturation links
• Monitor thermal conditions during sustained load
```

## Key Features

✅ **Multi-node testing** - All pairwise combinations
✅ **Bidirectional tests** - Tests both directions
✅ **CPU tracking** - Client and server CPU per test
✅ **Automated reporting** - Text + JSON outputs
✅ **Bottleneck detection** - Identifies specific issues
✅ **Zero dependencies** - Python stdlib only
✅ **Cross-platform** - Windows/Linux control node
✅ **Production-ready** - Error handling, timeouts, retries
✅ **Scalable** - Easily extend to 8, 16, 32 nodes
✅ **Data preservation** - All results saved to files

## Performance Targets

For reference, with 160-core systems and 100GbE NICs:

| Scenario | Expected Perf | Indicates |
|----------|---------------|-----------|
| 90-98 Gbps | ✓ Excellent | WAN speed saturation |
| 70-90 Gbps | ✓ Good | Well-tuned system |
| 50-70 Gbps | ⚠️ Fair | CPU/Driver overhead |
| < 50 Gbps | ✗ Poor | Investigate bottleneck |

Your system should achieve **45-95 Gbps** per path based on:
- NIC type (100GbE recommended)
- Network infrastructure
- System tuning
- Background workload

## Advanced Usage

### Run Only Tests (Skipping Setup)
```powershell
python orchestrate.py --test
```

### Run Only Analysis
```powershell
python orchestrate.py --analyze
```

### Manual Invocation
```powershell
python iperf3_test_runner.py       # Run tests
python bottleneck_analyzer.py      # Analyze
python setup_nodes.py              # Install iperf3
```

### Customize Parameters

Edit `iperf3_test_runner.py` line 340-342:
```python
duration = 600    # Increase to 10 minutes
threads = 32      # Use more parallel streams
```

## Integration with Your Workflow

### Run Daily
```powershell
# Add to scheduled task or cron
python orchestrate.py --full > test_results.log
```

### Trend Analysis
```powershell
# Keep JSON results for longitudinal analysis
# Each run creates timestamped JSON file
# Compare results over weeks/months
```

### Alert on Changes
```powershell
# Parse JSON results and alert if:
# - Throughput drops > 10%
# - CPU usage increases abnormally
# - New bottlenecks appear
```

## System Requirements

### Control Machine
- Windows 10+, Linux, or macOS
- Python 3.7+
- SSH client (built-in on Linux/Mac, built-in on Windows 10+)

### Test Nodes
- Linux (Ubuntu, CentOS, RHEL, Fedora, etc.)
- iperf3 (automated installation available)
- Network connectivity between all nodes
- SSH/sudo access from control machine

## Network Requirements

- All 4 nodes must be on same network segment or routable
- Suggest direct switch connection (lowest latency/loss)
- Minimum 1GbE, optimal 100GbE for meaningful tests
- No firewall blocking port 5201 (iperf3) between nodes

## Limitations & Future Enhancements

✓ Current:
- TCP benchmarking
- 4 nodes (easily extended)
- Single test duration
- Point-in-time snapshot

🔮 Could add:
- UDP latency/jitter tests
- Multi-hop/cross-rack testing
- Historical trending
- Real-time dashboard
- Automatic tuning recommendations
- Test result comparison

## File Structure

```
Iperf3validation/
├── iperf3_test_runner.py        # Main orchestrator
├── bottleneck_analyzer.py       # Diagnostic tool
├── setup_nodes.py               # Node setup
├── orchestrate.py               # Master controller
├── README.md                    # Complete docs
├── QUICKSTART.md                # Quick guide
├── config.ini                   # Configuration
├── requirements.txt             # Dependencies
├── PROJECT_SUMMARY.md           # This file
├── TIMESTAMP/
│   ├── iperf3_report_*.txt      # Performance report
│   ├── iperf3_results_*.json    # Raw results
│   └── bottleneck_analysis.txt  # Diagnostics
```

## Getting Started Right Now

1. **Verify you can SSH to nodes**
   ```powershell
   ssh root@220.0.0.101 "echo ready"
   ```

2. **Run the complete test suite**
   ```powershell
   python orchestrate.py --full
   ```

3. **Read the reports**
   ```powershell
   type iperf3_report_*.txt
   type bottleneck_analysis.txt
   ```

That's all! You now have comprehensive network performance data for your 4-node rack system.

---

**Questions?** → See README.md
**Troubleshooting?** → See QUICKSTART.md
**Want to customize?** → See config.ini and script docstrings

**Created**: April 1, 2026
**Framework Version**: 1.0
**Python Version**: 3.7+
**iperf3 Version**: 3.x+

