#!/usr/bin/env python3
"""
Iperf3 Multi-Node Testing Framework
Tests bandwidth between all node pairs and generates bottleneck analysis
"""

import subprocess
import json
import time
import os
import sys
from typing import Dict, List, Tuple
from dataclasses import dataclass
from datetime import datetime
import statistics

@dataclass
class TestResult:
    """Store iperf3 test results"""
    source: str
    destination: str
    protocol: str
    duration: int
    throughput_mbps: float
    throughput_gbps: float
    cpu_server: float
    cpu_client: float
    lost_packets: int
    jitter_ms: float
    timestamp: str

class Iperf3Tester:
    def __init__(self, nodes: List[str], duration: int = 300, threads: int = 16):
        """
        Initialize tester with node IPs
        nodes: List of IP addresses
        duration: Test duration in seconds
        threads: Number of iperf3 parallel streams
        """
        self.nodes = nodes
        self.duration = duration
        self.threads = threads
        self.results: List[TestResult] = []
        self.ssh_user = "root"
        self.ssh_key = None
        
    def check_node_connectivity(self) -> bool:
        """Verify all nodes are reachable"""
        print("\n[*] Checking node connectivity...")
        all_reachable = True
        for node in self.nodes:
            try:
                result = subprocess.run(
                    f"ping -c 1 {node}",
                    shell=True,
                    capture_output=True,
                    timeout=2
                )
                if result.returncode == 0:
                    print(f"  ✓ {node} is reachable")
                else:
                    print(f"  ✗ {node} is NOT reachable")
                    all_reachable = False
            except Exception as e:
                print(f"  ✗ {node} check failed: {e}")
                all_reachable = False
        return all_reachable

    def start_iperf3_server(self, node: str, port: int = 5201) -> bool:
        """Start iperf3 server on a node via SSH"""
        try:
            cmd = f"ssh -o ConnectTimeout=5 {self.ssh_user}@{node} 'pkill -f iperf3 || true; iperf3 -s -D -p {port}'"
            print(f"  [*] Starting iperf3 server on {node}:{port}")
            result = subprocess.run(cmd, shell=True, capture_output=True, timeout=10)
            time.sleep(1)
            return True
        except Exception as e:
            print(f"  [!] Failed to start server on {node}: {e}")
            return False

    def run_iperf3_test(self, src: str, dst: str, port: int = 5201) -> TestResult:
        """Run iperf3 test from source to destination"""
        try:
            # Run iperf3 with JSON output
            cmd = f"ssh -o ConnectTimeout=5 {self.ssh_user}@{src} 'iperf3 -c {dst} -p {port} -t {self.duration} -P {self.threads} -J'"
            
            print(f"  [→] Testing {src} → {dst}")
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                timeout=self.duration + 30,
                text=True
            )
            
            if result.returncode != 0:
                print(f"    [!] Test failed: {result.stderr[:100]}")
                return None
            
            # Parse JSON output
            try:
                data = json.loads(result.stdout)
                end = data.get('end', {})
                sum_sent = end.get('sum_sent', {})
                sum_received = end.get('sum_received', {})
                
                throughput_bps = sum_sent.get('bits_per_second', 0)
                throughput_mbps = throughput_bps / 1_000_000
                throughput_gbps = throughput_bps / 1_000_000_000
                
                # Get CPU utilization
                cpu_server = end.get('cpu_utilization_percent', {}).get('host', 0)
                cpu_client = end.get('cpu_utilization_percent', {}).get('remote', 0)
                
                # Get packet loss (UDP only)
                lost_packets = sum_received.get('lost_packets', 0)
                jitter_ms = sum_received.get('jitter_ms', 0)
                
                test_result = TestResult(
                    source=src,
                    destination=dst,
                    protocol="TCP",
                    duration=self.duration,
                    throughput_mbps=throughput_mbps,
                    throughput_gbps=throughput_gbps,
                    cpu_server=cpu_server,
                    cpu_client=cpu_client,
                    lost_packets=lost_packets,
                    jitter_ms=jitter_ms,
                    timestamp=datetime.now().isoformat()
                )
                
                print(f"    [✓] {throughput_gbps:.2f} Gbps, CPU: {cpu_client:.1f}% (client)")
                return test_result
                
            except json.JSONDecodeError as e:
                print(f"    [!] JSON parse error: {e}")
                print(f"    Raw output: {result.stdout[:200]}")
                return None
                
        except subprocess.TimeoutExpired:
            print(f"  [!] Test timeout for {src} → {dst}")
            return None
        except Exception as e:
            print(f"  [!] Test execution error: {e}")
            return None

    def run_all_tests(self) -> List[TestResult]:
        """Run bidirectional tests between all node pairs"""
        print(f"\n[*] Running iperf3 tests ({self.duration}s each, {self.threads} threads)")
        print(f"    Nodes: {', '.join(self.nodes)}")
        
        # Start all servers
        print("\n[*] Starting iperf3 servers on all nodes...")
        for node in self.nodes:
            self.start_iperf3_server(node)
        
        time.sleep(2)
        
        # Run tests between all pairs
        print("\n[*] Running bandwidth tests between all pairs (bidirectional)...")
        for src in self.nodes:
            for dst in self.nodes:
                if src != dst:
                    result = self.run_iperf3_test(src, dst)
                    if result:
                        self.results.append(result)
                    time.sleep(1)
        
        # Cleanup servers
        print("\n[*] Stopping iperf3 servers...")
        for node in self.nodes:
            try:
                subprocess.run(
                    f"ssh {self.ssh_user}@{node} 'pkill -f iperf3'",
                    shell=True,
                    capture_output=True,
                    timeout=5
                )
            except:
                pass
        
        return self.results

    def analyze_results(self) -> Dict:
        """Analyze test results and identify bottlenecks"""
        if not self.results:
            return {}
        
        analysis = {
            'test_date': datetime.now().isoformat(),
            'total_tests': len(self.results),
            'nodes_tested': len(self.nodes),
            'throughput_stats': {},
            'cpu_utilization': {},
            'bottlenecks': [],
            'per_node_stats': {}
        }
        
        # Overall throughput statistics
        throughputs_gbps = [r.throughput_gbps for r in self.results]
        analysis['throughput_stats'] = {
            'min_gbps': min(throughputs_gbps),
            'max_gbps': max(throughputs_gbps),
            'avg_gbps': statistics.mean(throughputs_gbps),
            'median_gbps': statistics.median(throughputs_gbps),
            'stdev_gbps': statistics.stdev(throughputs_gbps) if len(throughputs_gbps) > 1 else 0
        }
        
        # CPU utilization statistics
        cpu_clients = [r.cpu_client for r in self.results]
        cpu_servers = [r.cpu_server for r in self.results]
        analysis['cpu_utilization'] = {
            'avg_client_cpu': statistics.mean(cpu_clients),
            'avg_server_cpu': statistics.mean(cpu_servers),
            'max_client_cpu': max(cpu_clients),
            'max_server_cpu': max(cpu_servers)
        }
        
        # Per-node statistics
        for node in self.nodes:
            sent_results = [r for r in self.results if r.source == node]
            received_results = [r for r in self.results if r.destination == node]
            
            if sent_results:
                sent_throughputs = [r.throughput_gbps for r in sent_results]
                analysis['per_node_stats'][f'{node}_sent'] = {
                    'count': len(sent_throughputs),
                    'avg_gbps': statistics.mean(sent_throughputs),
                    'min_gbps': min(sent_throughputs),
                    'max_gbps': max(sent_throughputs)
                }
            
            if received_results:
                recv_throughputs = [r.throughput_gbps for r in received_results]
                analysis['per_node_stats'][f'{node}_recv'] = {
                    'count': len(recv_throughputs),
                    'avg_gbps': statistics.mean(recv_throughputs),
                    'min_gbps': min(recv_throughputs),
                    'max_gbps': max(recv_throughputs)
                }
        
        # Identify bottlenecks
        avg_throughput = analysis['throughput_stats']['avg_gbps']
        threshold = avg_throughput * 0.8  # 20% degradation threshold
        
        for result in self.results:
            if result.throughput_gbps < threshold:
                analysis['bottlenecks'].append({
                    'path': f"{result.source} → {result.destination}",
                    'throughput_gbps': result.throughput_gbps,
                    'degradation_percent': ((avg_throughput - result.throughput_gbps) / avg_throughput) * 100
                })
        
        # Hardware constraints analysis
        if analysis['cpu_utilization']['max_client_cpu'] > 80:
            analysis['bottlenecks'].append({
                'type': 'CPU Bottleneck',
                'description': f"Client CPU utilization reached {analysis['cpu_utilization']['max_client_cpu']:.1f}%",
                'severity': 'HIGH'
            })
        
        return analysis

    def generate_report(self, output_file: str = None) -> str:
        """Generate readable report from results"""
        if not output_file:
            output_file = f"iperf3_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        analysis = self.analyze_results()
        
        report = []
        report.append("=" * 80)
        report.append("IPERF3 MULTI-NODE NETWORK PERFORMANCE TEST REPORT")
        report.append("=" * 80)
        report.append(f"\nTest Date: {analysis['test_date']}")
        report.append(f"Nodes Tested: {', '.join(self.nodes)}")
        report.append(f"Total Tests: {analysis['total_tests']}")
        report.append(f"Test Duration: {self.duration} seconds per test")
        report.append(f"Parallel Threads: {self.threads}")
        
        # Throughput Summary
        report.append("\n" + "=" * 80)
        report.append("THROUGHPUT SUMMARY")
        report.append("=" * 80)
        stats = analysis['throughput_stats']
        report.append(f"  Average Throughput:  {stats['avg_gbps']:.2f} Gbps")
        report.append(f"  Median Throughput:   {stats['median_gbps']:.2f} Gbps")
        report.append(f"  Min Throughput:      {stats['min_gbps']:.2f} Gbps")
        report.append(f"  Max Throughput:      {stats['max_gbps']:.2f} Gbps")
        report.append(f"  Std Deviation:       {stats['stdev_gbps']:.2f} Gbps")
        
        # CPU Utilization
        report.append("\n" + "=" * 80)
        report.append("CPU UTILIZATION ANALYSIS")
        report.append("=" * 80)
        cpu = analysis['cpu_utilization']
        report.append(f"  Avg Client CPU:      {cpu['avg_client_cpu']:.1f}%")
        report.append(f"  Max Client CPU:      {cpu['max_client_cpu']:.1f}%")
        report.append(f"  Avg Server CPU:      {cpu['avg_server_cpu']:.1f}%")
        report.append(f"  Max Server CPU:      {cpu['max_server_cpu']:.1f}%")
        
        # Per-Node Statistics
        report.append("\n" + "=" * 80)
        report.append("PER-NODE STATISTICS")
        report.append("=" * 80)
        for node_stat, stats_data in analysis['per_node_stats'].items():
            report.append(f"\n  {node_stat}:")
            report.append(f"    Connections: {stats_data['count']}")
            report.append(f"    Avg Throughput: {stats_data['avg_gbps']:.2f} Gbps")
            report.append(f"    Min Throughput: {stats_data['min_gbps']:.2f} Gbps")
            report.append(f"    Max Throughput: {stats_data['max_gbps']:.2f} Gbps")
        
        # Bottleneck Analysis
        report.append("\n" + "=" * 80)
        report.append("BOTTLENECK ANALYSIS")
        report.append("=" * 80)
        
        if analysis['bottlenecks']:
            for i, bottleneck in enumerate(analysis['bottlenecks'], 1):
                report.append(f"\n  [{i}] Bottleneck Identified:")
                if 'path' in bottleneck:
                    report.append(f"      Path: {bottleneck['path']}")
                    report.append(f"      Throughput: {bottleneck['throughput_gbps']:.2f} Gbps")
                    report.append(f"      Degradation: {bottleneck['degradation_percent']:.1f}%")
                elif 'type' in bottleneck:
                    report.append(f"      Type: {bottleneck['type']}")
                    report.append(f"      Description: {bottleneck['description']}")
                    if 'severity' in bottleneck:
                        report.append(f"      Severity: {bottleneck['severity']}")
        else:
            report.append("\n  No significant bottlenecks detected.")
            report.append("  Performance is consistent across all paths.")
        
        # Detailed Results Table
        report.append("\n" + "=" * 80)
        report.append("DETAILED TEST RESULTS")
        report.append("=" * 80)
        report.append(f"\n{'Source':<15} {'Dest':<15} {'Throughput':<15} {'CPU Client':<12} {'CPU Server':<12}")
        report.append("-" * 80)
        
        for result in sorted(self.results, key=lambda x: x.throughput_gbps, reverse=True):
            report.append(
                f"{result.source:<15} {result.destination:<15} "
                f"{result.throughput_gbps:>6.2f} Gbps    "
                f"{result.cpu_client:>6.1f}%      {result.cpu_server:>6.1f}%"
            )
        
        # Recommendations
        report.append("\n" + "=" * 80)
        report.append("RECOMMENDATIONS")
        report.append("=" * 80)
        
        recommendations = []
        if stats['stdev_gbps'] > stats['avg_gbps'] * 0.2:
            recommendations.append("  • High variance in throughput - check for network congestion or link issues")
        if cpu['max_client_cpu'] > 80:
            recommendations.append("  • Client CPU is heavily utilized - consider increasing parallel processes or optimizing app")
        if cpu['max_server_cpu'] > 80:
            recommendations.append("  • Server CPU is heavily utilized - potential NIC driver or interrupt handling issue")
        if stats['min_gbps'] < stats['max_gbps'] * 0.7:
            recommendations.append("  • Significant throughput variation - investigate specific paths for issues")
        
        if recommendations:
            for rec in recommendations:
                report.append(rec)
        else:
            report.append("  • System is performing well with balanced utilization across all nodes")
        
        report_text = "\n".join(report)
        
        # Write to file
        with open(output_file, 'w') as f:
            f.write(report_text)
        
        print(f"\n[✓] Report saved to: {output_file}")
        return report_text

def main():
    # Node configuration
    nodes = ["220.0.0.101", "220.0.0.103", "220.0.0.104", "220.0.0.106"]
    
    # Test parameters
    duration = 300  # 5 minutes per test
    threads = 16    # 16 parallel streams to utilize 160 cores
    
    # Create tester
    tester = Iperf3Tester(nodes=nodes, duration=duration, threads=threads)
    
    # Check connectivity
    if not tester.check_node_connectivity():
        print("\n[!] Some nodes are not reachable. Please check network connectivity.")
        print("    Ensure nodes are on the same network and SSH access is configured.")
        sys.exit(1)
    
    # Run tests
    print("\n[*] Starting network performance tests...")
    results = tester.run_all_tests()
    
    if not results:
        print("\n[!] No test results collected. Please check:")
        print("    1. SSH access to nodes")
        print("    2. iperf3 is installed on all nodes")
        print("    3. Firewall rules allow iperf3 traffic")
        sys.exit(1)
    
    # Generate report
    report = tester.generate_report()
    print("\n" + report)
    
    # Save JSON results for further analysis
    json_file = f"iperf3_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(json_file, 'w') as f:
        json.dump([
            {
                'source': r.source,
                'destination': r.destination,
                'throughput_gbps': r.throughput_gbps,
                'throughput_mbps': r.throughput_mbps,
                'cpu_client': r.cpu_client,
                'cpu_server': r.cpu_server,
                'timestamp': r.timestamp
            }
            for r in results
        ], f, indent=2)
    print(f"[✓] JSON results saved to: {json_file}")

if __name__ == "__main__":
    main()
