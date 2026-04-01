#!/usr/bin/env python3
"""
Diagnostic Tool - Troubleshoot iperf3 test failures
"""

import subprocess
import json
import sys
import time

def test_ssh(node: str, ssh_user: str = "root") -> tuple:
    """Test SSH connectivity"""
    try:
        cmd = f"ssh -o ConnectTimeout=5 {ssh_user}@{node} 'echo OK'"
        result = subprocess.run(cmd, shell=True, capture_output=True, timeout=10, text=True)
        if result.returncode == 0:
            return True, "SSH OK"
        else:
            return False, result.stderr[:100]
    except Exception as e:
        return False, str(e)

def test_iperf3_version(node: str, ssh_user: str = "root") -> tuple:
    """Check iperf3 version"""
    try:
        cmd = f"ssh -o ConnectTimeout=5 {ssh_user}@{node} 'iperf3 -v'"
        result = subprocess.run(cmd, shell=True, capture_output=True, timeout=10, text=True)
        if result.returncode == 0:
            version = result.stdout.strip()
            return True, version
        else:
            return False, result.stderr[:100]
    except Exception as e:
        return False, str(e)

def test_single_iperf3_run(src: str, dst: str, ssh_user: str = "root", duration: int = 10) -> tuple:
    """Run a single short iperf3 test"""
    try:
        # Start server
        print(f"  [*] Starting server on {dst}...")
        subprocess.run(
            f"ssh -o ConnectTimeout=5 {ssh_user}@{dst} 'pkill -f iperf3; sleep 1; iperf3 -s -D'",
            shell=True,
            capture_output=True,
            timeout=10
        )
        time.sleep(2)
        
        # Run client
        print(f"  [*] Running test {src} → {dst} (duration: {duration}s)...")
        cmd = f"ssh -o ConnectTimeout=5 {ssh_user}@{src} 'iperf3 -c {dst} -t {duration} -P 2 -J'"
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            timeout=duration + 15,
            text=True
        )
        
        if result.returncode != 0:
            return False, f"Command failed: {result.stderr[:200]}"
        
        # Try to parse JSON
        try:
            data = json.loads(result.stdout)
            throughput_bps = data.get('end', {}).get('sum_sent', {}).get('bits_per_second', 0)
            throughput_gbps = throughput_bps / 1_000_000_000
            return True, f"{throughput_gbps:.2f} Gbps (JSON parsed OK)"
        except json.JSONDecodeError as e:
            return False, f"JSON parse error: {str(e)[:100]}\nRaw output: {result.stdout[:300]}"
        
    except subprocess.TimeoutExpired:
        return False, "Test timeout"
    except Exception as e:
        return False, str(e)

def main():
    nodes = ["220.0.0.101", "220.0.0.103", "220.0.0.104", "220.0.0.106"]
    ssh_user = "root"
    
    print("=" * 80)
    print("IPERF3 DIAGNOSTIC TOOL")
    print("=" * 80)
    
    # Step 1: SSH Connectivity
    print("\n[STEP 1] Testing SSH Connectivity")
    print("-" * 80)
    ssh_ok = True
    for node in nodes:
        success, msg = test_ssh(node, ssh_user)
        status = "✓" if success else "✗"
        print(f"  {status} {node}: {msg}")
        if not success:
            ssh_ok = False
    
    if not ssh_ok:
        print("\n[!] SSH connectivity issues detected!")
        print("    Check firewall and SSH key configuration")
        return False
    
    # Step 2: iperf3 Version
    print("\n[STEP 2] Checking iperf3 Installation")
    print("-" * 80)
    iperf3_ok = True
    for node in nodes:
        success, msg = test_iperf3_version(node, ssh_user)
        status = "✓" if success else "✗"
        print(f"  {status} {node}: {msg}")
        if not success:
            iperf3_ok = False
    
    if not iperf3_ok:
        print("\n[!] iperf3 not installed on some nodes!")
        print("    Run: python setup_nodes.py")
        return False
    
    # Step 3: Single Test Run
    print("\n[STEP 3] Running Single Test (Diagnostic)")
    print("-" * 80)
    src = nodes[0]
    dst = nodes[1]
    print(f"\n  Testing: {src} → {dst}")
    success, msg = test_single_iperf3_run(src, dst, ssh_user, duration=10)
    
    if success:
        print(f"  [✓] Test successful: {msg}")
        print("\n[✓] All diagnostics passed!")
        print("    The issue might be in the main test runner configuration.")
        print("    Try running: python iperf3_test_runner.py --verbose (if available)")
        return True
    else:
        print(f"  [✗] Test failed: {msg}")
        print("\n[!] Diagnostic found the problem:")
        
        if "JSON" in msg:
            print("\n    ISSUE: iperf3 is not outputting valid JSON")
            print("    SOLUTION:")
            print("      1. Check iperf3 version: ssh root@220.0.0.101 iperf3 -v")
            print("      2. Ensure iperf3 is at least version 3.0")
            print("      3. Try with explicit version flag: -J (JSON output)")
        elif "Command failed" in msg:
            print("\n    ISSUE: iperf3 command execution failed")
            print("    SOLUTION:")
            print("      1. Test manually: ssh root@220.0.0.101 iperf3 -c 220.0.0.103 -t 5")
            print("      2. Check error messages above")
        elif "timeout" in msg.lower():
            print("\n    ISSUE: Test timed out")
            print("    SOLUTION:")
            print("      1. Check network latency: ping 220.0.0.103")
            print("      2. Check if nodes are on same network")
            print("      3. Check for network congestion")
        
        return False

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n[!] Interrupted")
        sys.exit(130)
    except Exception as e:
        print(f"\n[!] Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
