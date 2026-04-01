# QUICK START GUIDE - Iperf3 Multi-Node Testing

## Prerequisites Checklist

- [ ] Python 3.7+ installed (`python --version`)
- [ ] SSH access configured to all 4 nodes
- [ ] Can SSH to nodes without password prompts (SSH key recommended)
- [ ] iperf3 installed on all nodes (or use setup script)

## Step-by-Step Setup

### 1. Verify Python Installation

```powershell
python --version
```

Expected output: `Python 3.7.0` or higher

### 2. Test SSH Access

Open PowerShell and test each node:

```powershell
ssh root@200.0.0.101 "hostname"
ssh root@200.0.0.103 "hostname"
ssh root@200.0.0.104 "hostname"
ssh root@200.0.0.106 "hostname"
```

If prompts for password, configure SSH keys (skip to end of this guide for help).

### 3. Run Tests with One Command

```powershell
# Full workflow (setup + test + analyze)
python orchestrate.py --full

# Or individually:
python orchestrate.py --setup    # Install iperf3 on nodes
python orchestrate.py --test     # Run bandwidth tests
python orchestrate.py --analyze  # Analyze results
```

### 4. View Results

Two types of reports are generated:

**Main Performance Report** (iperf3_report_*.txt)
```powershell
type iperf3_report_*.txt | more
```

**Bottleneck Analysis** (bottleneck_analysis.txt)
```powershell
type bottleneck_analysis.txt | more
```

## What Gets Tested

Your 4-node system will be tested in this pattern:

```
Node 101 → Node 103, Node 104, Node 106
Node 103 → Node 101, Node 104, Node 106
Node 104 → Node 101, Node 103, Node 106
Node 106 → Node 101, Node 103, Node 104

Total: 12 bidirectional test paths
```

Each test:
- Runs for 300 seconds (5 minutes)
- Uses 16 parallel streams (optimized for 160 cores)
- Reports throughput, CPU usage, and packet loss

## Expected Output

### Console Output
```
================================================================================
[*] Checking node connectivity...
  ✓ 200.0.0.101 is reachable
  ✓ 200.0.0.103 is reachable
  ✓ 200.0.0.104 is reachable
  ✓ 200.0.0.106 is reachable

[*] Starting iperf3 servers on all nodes...
  [*] Starting iperf3 server on 200.0.0.101:5201
  [*] Starting iperf3 server on 200.0.0.103:5201
  ...

[*] Running bandwidth tests between all pairs...
  [→] Testing 200.0.0.101 → 200.0.0.103
    [✓] 45.23 Gbps, CPU: 32.1% (client)
  [→] Testing 200.0.0.101 → 200.0.0.104
    [✓] 48.15 Gbps, CPU: 35.8% (client)
  ...

[✓] Report saved to: iperf3_report_20260401_143045.txt
[✓] JSON results saved to: iperf3_results_20260401_143045.json
```

### Generated Files

After running, you'll have:

1. **iperf3_report_YYYYMMDD_HHMMSS.txt** - Human-readable performance report
2. **iperf3_results_YYYYMMDD_HHMMSS.json** - Raw benchmark data
3. **bottleneck_analysis.txt** - Detailed bottleneck findings and recommendations

## Interpreting Results

### Good Performance (No Bottlenecks)

```
THROUGHPUT SUMMARY
  Average Throughput: 92.50 Gbps
  Std Deviation: 2.10 Gbps (low variance = consistent)
  CPU Client: 45.2% (normal)
```

✓ Network is performing well balancing throughput and system efficiency.

### CPU Bottleneck (App Limited)

```
CPU UTILIZATION ANALYSIS
  Max Client CPU: 98.5% (saturated)
  Throughput: 32.4 Gbps (lower than expected)
```

⚠️ Application is CPU-bound. Options:
- Increase number of nodes
- Optimize application code
- Enable NIC offloading features

### Network Congestion (Bandwidth Limited)

```
LINK SATURATION ANALYSIS
  Path 200.0.0.101 → 200.0.0.103: 98.5% saturation
  Throughput: 98.50 Gbps (approaching NIC limit)
```

⚠️ Network link is saturated. Options:
- Use higher capacity NICs (200GbE instead of 100GbE)
- Distribute load across more links
- Add dedicated network infrastructure

## Troubleshooting

### Issue: "Nodes are not reachable"

**Solution**: Check network connectivity

```powershell
# Test ping
ping 200.0.0.101

# Test SSH manually
ssh root@200.0.0.101 echo test
```

### Issue: SSH hangs or times out

**Solution**: Configure SSH with timeout and connection settings

```powershell
ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no root@200.0.0.101 "echo test"
```

### Issue: "iperf3: command not found"

**Solution**: Install iperf3 on nodes

```powershell
# Run setup script
python setup_nodes.py

# Or manually on each node:
# For Ubuntu/Debian:
ssh root@200.0.0.101 "apt-get update && apt-get install -y iperf3"

# For CentOS/RHEL:
ssh root@200.0.0.101 "yum install -y iperf3"
```

### Issue: Very low throughput (< 10 Gbps)

**Solution**: Check physical network

1. Verify network cables are connected properly
2. Check port status on switch: `ssh admin@switch "show port status 1/1"`
3. Verify speed negotiation: Check both ends are 100GbE
4. Check for errors: `ssh root@200.0.0.101 "ethtool eth0 | grep -i speed"`

### Issue: Results vary significantly between runs

**Common causes:**
- Background network traffic
- System processes using CPU
- Power management affecting clock speed
- Thermal throttling

**Solution:**
- Run tests during off-peak hours
- Stop unnecessary services: `ssh root@200.0.0.101 "systemctl stop [service]"`
- Increase test duration for more stable average

## Customization

### Change Test Duration

Edit the test runner:

```powershell
# Edit line 341 in iperf3_test_runner.py
duration = 600  # 10 minutes instead of 5
```

### Use Different SSH User

For Ubuntu/EC2 instances:

```powershell
# Edit line 20 in iperf3_test_runner.py
self.ssh_user = "ubuntu"
```

For CentOS/RHEL:

```powershell
self.ssh_user = "centos"
```

### Increase Parallel Streams for More Throughput

For the 160 cores, you can use more threads:

```powershell
# Edit line 340 in iperf3_test_runner.py
threads = 32  # More parallel connections
```

## Performance Baseline

Expected performance for well-tuned 160-core systems:

| Link Type | Expected Throughput | Notes |
|-----------|-------------------|-------|
| 100GbE | 90-98 Gbps | Single NIC, saturated |
| 100GbE | 40-60 Gbps | Lower due to CPU limits |
| 10GbE | 9-10 Gbps | Single 10G link |

Your system with 4 nodes should achieve **45-95 Gbps** per path depending on:
- NIC speed (100GbE recommended)
- Network switch fabric
- NIC drivers
- System configuration

## Next Steps

After getting results:

1. **Share bottleneck_analysis.txt** with your network team for review
2. **Keep JSON results** for trend analysis over time
3. **Run tests monthly** to ensure consistent performance
4. **Optimize** based on recommendations in the bottleneck report

## Additional Resources

- **iperf3 Manual**: https://software.es.net/iperf/
- **Network Tuning**: https://fasterdata.es.net/host-tuning/
- **Linux TCP Tuning**: https://wiki.linuxfoundation.org/networking/nettune

## Support

For issues:

1. Check that all nodes are reachable: `ping 200.0.0.10X`
2. Verify iperf3 is installed: `ssh root@200.0.0.101 iperf3 -v`
3. Check SSH configuration: `ssh root@200.0.0.101 echo "Test"`
4. Review error messages in console output
5. Check generated JSON file for raw data

---

**Ready to test?**

```powershell
python orchestrate.py --full
```

This will automatically:
1. Install iperf3 (if needed)
2. Run all tests (takes ~12-15 minutes for 12 paths × 5 min)
3. Generate comprehensive reports
4. Identify bottlenecks and provide recommendations
