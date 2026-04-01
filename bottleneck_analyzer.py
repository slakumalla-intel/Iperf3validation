#!/usr/bin/env python3
"""
Bottleneck Analysis Tool - Detailed network performance diagnosis
"""

import json
import sys
from typing import Dict, List
from pathlib import Path
import statistics

class BottleneckAnalyzer:
    """Analyze iperf3 results for network bottlenecks"""
    
    def __init__(self, json_results_file: str = None):
        self.results = []
        self.analysis = {}
        
        if json_results_file:
            self.load_results(json_results_file)
    
    def load_results(self, json_file: str):
        """Load results from JSON file"""
        try:
            with open(json_file, 'r') as f:
                self.results = json.load(f)
            print(f"[✓] Loaded {len(self.results)} test results from {json_file}")
        except FileNotFoundError:
            print(f"[!] File not found: {json_file}")
            sys.exit(1)
        except json.JSONDecodeError:
            print(f"[!] Invalid JSON in {json_file}")
            sys.exit(1)
    
    def analyze_link_saturation(self) -> Dict:
        """Analyze if links are saturated"""
        if not self.results:
            return {}
        
        # Theoretical max for 160-core nodes with NIC bandwidth
        # Assuming 100GbE NICs (most common with high-core servers)
        theoretical_max_gbps = 100.0  # Single 100GbE link
        dual_link = 200.0  # If dual NICs
        
        link_analysis = {
            'theoretical_max_100ge': theoretical_max_gbps,
            'theoretical_max_dual_100ge': dual_link,
            'paths': {}
        }
        
        for result in self.results:
            path = f"{result['source']} → {result['destination']}"
            throughput = result['throughput_gbps']
            saturation_pct = (throughput / theoretical_max_gbps) * 100
            
            link_analysis['paths'][path] = {
                'throughput_gbps': throughput,
                'saturation_percent': saturation_pct,
                'headroom_gbps': theoretical_max_gbps - throughput
            }
        
        return link_analysis
    
    def analyze_cpu_bottleneck(self) -> Dict:
        """Analyze if CPU is the bottleneck"""
        cpu_analysis = {
            'client_cpu_high': False,
            'server_cpu_high': False,
            'findings': []
        }
        
        client_cpus = [r['cpu_client'] for r in self.results]
        server_cpus = [r['cpu_server'] for r in self.results]
        
        if client_cpus:
            avg_client = statistics.mean(client_cpus)
            max_client = max(client_cpus)
            cpu_analysis['avg_client_cpu'] = avg_client
            cpu_analysis['max_client_cpu'] = max_client
            
            if max_client > 90:
                cpu_analysis['client_cpu_high'] = True
                cpu_analysis['findings'].append(
                    f"⚠️  Client CPU is at {max_client:.1f}% - potential bottleneck"
                )
            elif max_client > 70:
                cpu_analysis['findings'].append(
                    f"⚠️  Client CPU is at {max_client:.1f}% - approaching saturation"
                )
        
        if server_cpus:
            avg_server = statistics.mean(server_cpus)
            max_server = max(server_cpus)
            cpu_analysis['avg_server_cpu'] = avg_server
            cpu_analysis['max_server_cpu'] = max_server
            
            if max_server > 90:
                cpu_analysis['server_cpu_high'] = True
                cpu_analysis['findings'].append(
                    f"⚠️  Server CPU is at {max_server:.1f}% - potential bottleneck"
                )
            elif max_server > 70:
                cpu_analysis['findings'].append(
                    f"⚠️  Server CPU is at {max_server:.1f}% - approaching saturation"
                )
        
        return cpu_analysis
    
    def analyze_asymmetric_paths(self) -> Dict:
        """Identify asymmetric performance between nodes"""
        asymmetry = {
            'issues': [],
            'node_pairs': {}
        }
        
        # Group results by node pairs
        paths_by_pair = {}
        for result in self.results:
            src = result['source']
            dst = result['destination']
            pair_key = tuple(sorted([src, dst]))
            
            if pair_key not in paths_by_pair:
                paths_by_pair[pair_key] = {'forward': None, 'reverse': None}
            
            if src == pair_key[0]:
                paths_by_pair[pair_key]['forward'] = result['throughput_gbps']
            else:
                paths_by_pair[pair_key]['reverse'] = result['throughput_gbps']
        
        # Analyze asymmetry
        for pair, directions in paths_by_pair.items():
            if directions['forward'] is not None and directions['reverse'] is not None:
                forward = directions['forward']
                reverse = directions['reverse']
                diff_percent = abs(forward - reverse) / max(forward, reverse) * 100
                
                asymmetry['node_pairs'][f"{pair[0]} ↔ {pair[1]}"] = {
                    'forward_gbps': forward,
                    'reverse_gbps': reverse,
                    'difference_percent': diff_percent
                }
                
                if diff_percent > 20:
                    asymmetry['issues'].append(
                        f"High asymmetry {pair[0]} ↔ {pair[1]}: {diff_percent:.1f}% "
                        f"({forward:.2f} vs {reverse:.2f} Gbps)"
                    )
        
        return asymmetry
    
    def analyze_consistency(self) -> Dict:
        """Analyze performance consistency across tests"""
        throughputs = [r['throughput_gbps'] for r in self.results]
        
        consistency = {
            'mean_gbps': statistics.mean(throughputs),
            'median_gbps': statistics.median(throughputs),
            'min_gbps': min(throughputs),
            'max_gbps': max(throughputs),
            'stdev_gbps': statistics.stdev(throughputs) if len(throughputs) > 1 else 0,
            'cv_percent': 0,  # Coefficient of variation
            'findings': []
        }
        
        if consistency['mean_gbps'] > 0:
            consistency['cv_percent'] = (consistency['stdev_gbps'] / consistency['mean_gbps']) * 100
        
        if consistency['cv_percent'] > 20:
            consistency['findings'].append(
                f"⚠️  High variability in throughput (CV: {consistency['cv_percent']:.1f}%) - "
                "indicates unstable performance"
            )
        elif consistency['cv_percent'] > 10:
            consistency['findings'].append(
                f"⚠️  Moderate variability in throughput (CV: {consistency['cv_percent']:.1f}%)"
            )
        else:
            consistency['findings'].append(
                f"✓ Consistent performance (CV: {consistency['cv_percent']:.1f}%)"
            )
        
        return consistency
    
    def generate_report(self, output_file: str = None) -> str:
        """Generate comprehensive bottleneck analysis report"""
        
        link_analysis = self.analyze_link_saturation()
        cpu_analysis = self.analyze_cpu_bottleneck()
        asymmetry = self.analyze_asymmetric_paths()
        consistency = self.analyze_consistency()
        
        report = []
        report.append("=" * 80)
        report.append("NETWORK BOTTLENECK ANALYSIS REPORT")
        report.append("=" * 80)
        
        # Executive Summary
        report.append("\n[EXECUTIVE SUMMARY]")
        report.append("-" * 80)
        report.append(f"Average Throughput: {consistency['mean_gbps']:.2f} Gbps")
        report.append(f"Performance Range: {consistency['min_gbps']:.2f} - {consistency['max_gbps']:.2f} Gbps")
        report.append(f"Consistency (CV): {consistency['cv_percent']:.1f}%")
        
        # Link Analysis
        report.append("\n[LINK SATURATION ANALYSIS]")
        report.append("-" * 80)
        report.append(f"Assuming 100GbE NIC per node (theoretical max: {link_analysis['theoretical_max_100ge']} Gbps)")
        report.append("")
        
        saturation_levels = []
        for path, stats in link_analysis['paths'].items():
            saturation = stats['saturation_percent']
            saturation_levels.append(saturation)
            
            if saturation > 80:
                status = "🔴 CRITICAL"
            elif saturation > 60:
                status = "🟡 HIGH"
            else:
                status = "🟢 OK"
            
            report.append(
                f"{status} {path}: {stats['throughput_gbps']:>6.2f} Gbps "
                f"({saturation:>5.1f}% saturation)"
            )
        
        avg_saturation = statistics.mean(saturation_levels) if saturation_levels else 0
        report.append(f"\nAverage Link Saturation: {avg_saturation:.1f}%")
        
        # CPU Analysis
        report.append("\n[CPU BOTTLENECK ANALYSIS]")
        report.append("-" * 80)
        if 'max_client_cpu' in cpu_analysis:
            report.append(f"Client CPU - Avg: {cpu_analysis['avg_client_cpu']:.1f}%, Max: {cpu_analysis['max_client_cpu']:.1f}%")
        if 'max_server_cpu' in cpu_analysis:
            report.append(f"Server CPU - Avg: {cpu_analysis['avg_server_cpu']:.1f}%, Max: {cpu_analysis['max_server_cpu']:.1f}%")
        
        for finding in cpu_analysis['findings']:
            report.append(finding)
        
        # Asymmetry Analysis
        report.append("\n[ASYMMETRIC PATH ANALYSIS]")
        report.append("-" * 80)
        
        if asymmetry['issues']:
            for issue in asymmetry['issues']:
                report.append(f"  ⚠️  {issue}")
        else:
            report.append("  ✓ All paths show symmetric performance")
        
        report.append("\nDetailed path metrics:")
        for pair, metrics in asymmetry['node_pairs'].items():
            report.append(
                f"  {pair}: "
                f"{metrics['forward_gbps']:.2f} ↔ {metrics['reverse_gbps']:.2f} Gbps "
                f"(diff: {metrics['difference_percent']:.1f}%)"
            )
        
        # Consistency Analysis
        report.append("\n[PERFORMANCE CONSISTENCY]")
        report.append("-" * 80)
        report.append(f"Mean (μ): {consistency['mean_gbps']:.2f} Gbps")
        report.append(f"Median: {consistency['median_gbps']:.2f} Gbps")
        report.append(f"Std Dev (σ): {consistency['stdev_gbps']:.2f} Gbps")
        report.append(f"Coefficient of Variation: {consistency['cv_percent']:.1f}%")
        for finding in consistency['findings']:
            report.append(finding)
        
        # Overall Assessment
        report.append("\n[BOTTLENECK ASSESSMENT]")
        report.append("-" * 80)
        
        bottlenecks_found = []
        
        if cpu_analysis['client_cpu_high'] or cpu_analysis['server_cpu_high']:
            bottlenecks_found.append("CPU UTILIZATION")
        
        if avg_saturation > 80:
            bottlenecks_found.append("LINK SATURATION")
        
        if asymmetry['issues']:
            bottlenecks_found.append("ASYMMETRIC PATHS")
        
        if consistency['cv_percent'] > 15:
            bottlenecks_found.append("PERFORMANCE VARIABILITY")
        
        if bottlenecks_found:
            report.append("Bottlenecks Detected:")
            for i, bottleneck in enumerate(bottlenecks_found, 1):
                report.append(f"  {i}. {bottleneck}")
        else:
            report.append("✓ No significant bottlenecks detected")
            report.append("Network performance is healthy and well-balanced")
        
        # Recommendations
        report.append("\n[RECOMMENDATIONS]")
        report.append("-" * 80)
        
        recommendations = []
        
        if avg_saturation > 70:
            recommendations.append(
                "• Consider upgrading to higher bandwidth NICs (200GbE) if sustained full "
                "throughput is required"
            )
        
        if cpu_analysis['client_cpu_high']:
            recommendations.append(
                "• Client CPU is saturated - enable NIC offloading features (LRO, TSO)"
            )
            recommendations.append(
                "• Consider tuning interrupt affinity and network driver parameters"
            )
        
        if cpu_analysis['server_cpu_high']:
            recommendations.append(
                "• Server CPU is saturated - optimize application-level network processing"
            )
            recommendations.append(
                "• Investigate NIC interrupt handling and consider increasing queue depths"
            )
        
        if asymmetry['issues']:
            recommendations.append(
                "• Check for asymmetric routing or link quality issues on identified paths"
            )
            recommendations.append(
                "• Verify all network interfaces are operating at same speed/duplex"
            )
        
        if consistency['cv_percent'] > 15:
            recommendations.append(
                "• Profile network traffic for congestion patterns"
            )
            recommendations.append(
                "• Check for background traffic on the network"
            )
        
        if recommendations:
            for rec in recommendations:
                report.append(rec)
        else:
            recommendations.append("• System is performing optimally - maintain current configuration")
        
        report_text = "\n".join(report)
        
        # Save report
        if output_file:
            with open(output_file, 'w') as f:
                f.write(report_text)
            print(f"[✓] Report saved to: {output_file}")
        
        return report_text

def main():
    # Find latest JSON results file
    results_dir = Path(".")
    json_files = sorted(results_dir.glob("iperf3_results_*.json"), reverse=True)
    
    if not json_files:
        print("[!] No iperf3 results JSON files found")
        print("    Run iperf3_test_runner.py first to generate results")
        sys.exit(1)
    
    latest_file = str(json_files[0])
    print(f"[*] Analyzing {latest_file}...\n")
    
    analyzer = BottleneckAnalyzer(latest_file)
    report = analyzer.generate_report(output_file="bottleneck_analysis.txt")
    print(report)

if __name__ == "__main__":
    main()
