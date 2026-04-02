#!/usr/bin/env bash
set -Eeuo pipefail

# -----------------------------
# Edit for your environment
# -----------------------------
NODES=(
  sc00901112s0101
  sc00901112s0103
  sc00901112s0104
  sc00901112s0106
)

SSH_USER="${SSH_USER:-root}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=5}"

IFACE="${IFACE:-enP1s23f1np1}"

# Ring settings
RX_RING="${RX_RING:-2047}"
TX_RING="${TX_RING:-2047}"

# Channel setting
COMBINED_CHANNELS="${COMBINED_CHANNELS:-64}"

# TCP / kernel tuning
RMEM_MAX="${RMEM_MAX:-67108864}"
WMEM_MAX="${WMEM_MAX:-67108864}"
TCP_RMEM_1="${TCP_RMEM_1:-4096}"
TCP_RMEM_2="${TCP_RMEM_2:-262144}"
TCP_RMEM_3="${TCP_RMEM_3:-67108864}"

TCP_WMEM_1="${TCP_WMEM_1:-4096}"
TCP_WMEM_2="${TCP_WMEM_2:-262144}"
TCP_WMEM_3="${TCP_WMEM_3:-67108864}"

NETDEV_MAX_BACKLOG="${NETDEV_MAX_BACKLOG:-250000}"

SYSCTL_FILE="${SYSCTL_FILE:-/etc/sysctl.d/99-iperf-tuning.conf}"

# -----------------------------
# Helpers
# -----------------------------
run_remote() {
  local host="$1"
  shift
  ssh $SSH_OPTS "${SSH_USER}@${host}" "$@"
}

for node in "${NODES[@]}"; do
  echo
  echo "==================== ${node} ===================="

  run_remote "$node" "bash -s" <<EOF
set -Eeuo pipefail

IFACE="${IFACE}"
RX_RING="${RX_RING}"
TX_RING="${TX_RING}"
COMBINED_CHANNELS="${COMBINED_CHANNELS}"

RMEM_MAX="${RMEM_MAX}"
WMEM_MAX="${WMEM_MAX}"
TCP_RMEM_1="${TCP_RMEM_1}"
TCP_RMEM_2="${TCP_RMEM_2}"
TCP_RMEM_3="${TCP_RMEM_3}"
TCP_WMEM_1="${TCP_WMEM_1}"
TCP_WMEM_2="${TCP_WMEM_2}"
TCP_WMEM_3="${TCP_WMEM_3}"
NETDEV_MAX_BACKLOG="${NETDEV_MAX_BACKLOG}"

SYSCTL_FILE="${SYSCTL_FILE}"

echo "[INFO] Host: \$(hostname)"
echo "[INFO] Interface: \${IFACE}"

if ! ip link show "\${IFACE}" >/dev/null 2>&1; then
  echo "[ERROR] Interface \${IFACE} not found"
  exit 1
fi

echo "[INFO] Ring settings before:"
ethtool -g "\${IFACE}" || true

echo "[INFO] Channel settings before:"
ethtool -l "\${IFACE}" || true

echo "[INFO] Applying ring settings..."
ethtool -G "\${IFACE}" rx "\${RX_RING}" tx "\${TX_RING}"

echo "[INFO] Checking max supported combined channels..."
MAX_COMBINED=\$(ethtool -l "\${IFACE}" | awk '
  /Pre-set maximums:/ {mode="max"; next}
  /Current hardware settings:/ {mode="cur"; next}
  mode=="max" && /^Combined:/ {print \$2; exit}
')
CUR_COMBINED=\$(ethtool -l "\${IFACE}" | awk '
  /Pre-set maximums:/ {mode="max"; next}
  /Current hardware settings:/ {mode="cur"; next}
  mode=="cur" && /^Combined:/ {print \$2; exit}
')

if [[ ! "\${MAX_COMBINED}" =~ ^[0-9]+$ ]]; then
  echo "[WARN] Could not determine max combined channels; skipping channel change"
else
  TARGET_COMBINED="\${COMBINED_CHANNELS}"
  if (( TARGET_COMBINED > MAX_COMBINED )); then
    TARGET_COMBINED="\${MAX_COMBINED}"
  fi

  echo "[INFO] Current combined=\${CUR_COMBINED}, max combined=\${MAX_COMBINED}, target combined=\${TARGET_COMBINED}"
  ethtool -L "\${IFACE}" combined "\${TARGET_COMBINED}"
fi

echo "[INFO] Writing persistent sysctl config to \${SYSCTL_FILE}"
cat > "\${SYSCTL_FILE}" <<SYSCTL_EOF
net.core.rmem_max=\${RMEM_MAX}
net.core.wmem_max=\${WMEM_MAX}
net.core.netdev_max_backlog=\${NETDEV_MAX_BACKLOG}
net.ipv4.tcp_rmem=\${TCP_RMEM_1} \${TCP_RMEM_2} \${TCP_RMEM_3}
net.ipv4.tcp_wmem=\${TCP_WMEM_1} \${TCP_WMEM_2} \${TCP_WMEM_3}
net.ipv4.tcp_window_scaling=1
net.ipv4.tcp_sack=1
SYSCTL_EOF

echo "[INFO] Applying only \${SYSCTL_FILE}"
sysctl -p "\${SYSCTL_FILE}" >/tmp/sysctl_apply.out 2>/tmp/sysctl_apply.err || {
  echo "[ERROR] sysctl apply failed for \${SYSCTL_FILE}"
  cat /tmp/sysctl_apply.err || true
  exit 1
}

echo "[INFO] Ring settings after:"
ethtool -g "\${IFACE}" || true

echo "[INFO] Channel settings after:"
ethtool -l "\${IFACE}" || true

echo "[INFO] Key sysctls after:"
sysctl net.core.rmem_max
sysctl net.core.wmem_max
sysctl net.core.netdev_max_backlog
sysctl net.ipv4.tcp_rmem
sysctl net.ipv4.tcp_wmem
sysctl net.ipv4.tcp_window_scaling
sysctl net.ipv4.tcp_sack

echo "[INFO] Short NIC counter snapshot:"
ethtool -S "\${IFACE}" | egrep 'rx_total_buf_errors|rx_buf_errors|rx_filter_miss|rx_tpa_errors|missed_irqs' || true

echo "[INFO] Done on \$(hostname)"
EOF
done

echo
echo "All nodes processed."
