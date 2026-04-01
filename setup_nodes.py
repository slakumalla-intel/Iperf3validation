#!/usr/bin/env python3
"""
Node Setup Script - Install iperf3 on all nodes
"""

import subprocess
import sys
from typing import List

def setup_node(node: str, ssh_user: str = "root") -> bool:
    """Install iperf3 on a node"""
    try:
        print(f"\n[*] Setting up {node}...")
        
        # Detect OS and install iperf3
        commands = [
            # Try apt (Debian/Ubuntu)
            f"ssh {ssh_user}@{node} 'apt-get update && apt-get install -y iperf3' 2>/dev/null",
            # Try yum (RHEL/CentOS)
            f"ssh {ssh_user}@{node} 'yum install -y iperf3' 2>/dev/null",
            # Try dnf (Fedora)
            f"ssh {ssh_user}@{node} 'dnf install -y iperf3' 2>/dev/null",
        ]
        
        for cmd in commands:
            print(f"  [*] Attempting: {cmd.split('&&')[0] if '&&' in cmd else 'install command'}")
            result = subprocess.run(cmd, shell=True, capture_output=True, timeout=60)
            if result.returncode == 0 or "already" in result.stderr.lower():
                print(f"  [✓] iperf3 installed on {node}")
                return True
        
        print(f"  [!] Failed to install iperf3 on {node}")
        return False
        
    except Exception as e:
        print(f"  [!] Setup error: {e}")
        return False

def verify_iperf3(node: str, ssh_user: str = "root") -> bool:
    """Verify iperf3 is installed and working"""
    try:
        cmd = f"ssh {ssh_user}@{node} 'iperf3 -v'"
        result = subprocess.run(cmd, shell=True, capture_output=True, timeout=5, text=True)
        if result.returncode == 0:
            version = result.stdout.strip()
            print(f"  [✓] iperf3 verified on {node}: {version}")
            return True
        else:
            print(f"  [!] iperf3 verification failed on {node}")
            return False
    except Exception as e:
        print(f"  [!] Verification error: {e}")
        return False

def main():
    nodes = ["200.0.0.101", "200.0.0.103", "200.0.0.104", "200.0.0.106"]
    ssh_user = "root"
    
    print("=" * 60)
    print("IPERF3 NODE SETUP")
    print("=" * 60)
    print(f"\nInstalling iperf3 on {len(nodes)} nodes...")
    
    successful = 0
    for node in nodes:
        if setup_node(node, ssh_user):
            successful += 1
    
    print(f"\n[*] Verifying installations...")
    verified = 0
    for node in nodes:
        if verify_iperf3(node, ssh_user):
            verified += 1
    
    print(f"\n[✓] Setup complete: {verified}/{len(nodes)} nodes verified")
    
    if verified == len(nodes):
        print("\n[✓] All nodes are ready for testing!")
        return 0
    else:
        print(f"\n[!] Only {verified}/{len(nodes)} nodes are ready")
        return 1

if __name__ == "__main__":
    sys.exit(main())
