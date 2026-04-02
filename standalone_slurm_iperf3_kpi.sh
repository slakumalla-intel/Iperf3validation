#!/usr/bin/env bash
set -Eeuo pipefail

PARTITION="${PARTITION:-debug}"
NODES_CSV="${NODES_CSV:-}"
NODE_COUNT="${NODE_COUNT:-4}"
DURATION="${DURATION:-30}"
STREAMS="${STREAMS:-8}"
PORT_BASE="${PORT_BASE:-5201}"
EXPECTED_GBPS_PER_DIRECTION="${EXPECTED_GBPS_PER_DIRECTION:-200}"
SSH_USER="${SSH_USER:-root}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=5}"
IP_MODE="${IP_MODE:-admin}"   # admin | hostname | custom_map
CUSTOM_IP_MAP="${CUSTOM_IP_MAP:-}"
RESULT_ROOT="${RESULT_ROOT:-results}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
RESULT_DIR="${RESULT_ROOT}/${RUN_ID}"
SUMMARY_JSON="${RESULT_DIR}/summary.json"
REPORT_TXT="${RESULT_DIR}/report.txt"

mkdir -p "$RESULT_DIR"/{logs,raw,iperf,ping,cpu}

log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*" | tee -a "$REPORT_TXT" >&2; }
die() { echo "ERROR: $*" >&2; exit 1; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"; }

for c in scontrol sinfo ssh python3 iperf3 ping; do need_cmd "$c"; done

remote_exec() {
  local host="$1"
  shift
  local cmd="$*"
  local qcmd
  qcmd=$(printf '%q' "$cmd")
  ssh $SSH_OPTS "${SSH_USER}@${host}" \
    "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; bash -lc ${qcmd}"
}

get_nodes() {
  if [[ -n "$NODES_CSV" ]]; then
    echo "$NODES_CSV" | tr ',' '\n'
    return
  fi
  sinfo -N -h -p "$PARTITION" -o "%N %T" \
    | awk '$2 ~ /idle|mix|allocated/ {print $1}' \
    | head -n "$NODE_COUNT"
}

node_to_ip() {
  local node="$1"

  case "$IP_MODE" in
    hostname)
      echo "$node"
      ;;
    custom_map)
      python3 - "$node" "$CUSTOM_IP_MAP" <<'PY'
import sys
node = sys.argv[1]
raw = sys.argv[2]
m = {}
for item in raw.split(","):
    item = item.strip()
    if "=" in item:
        k, v = item.split("=", 1)
        m[k.strip()] = v.strip()
print(m.get(node, ""))
PY
      ;;
    admin|*)
      local suffix
      suffix="$(echo "$node" | sed -E 's/.*s0*([0-9]+)$/\1/')"
      [[ -n "$suffix" ]] || exit 1
      echo "220.0.0.${suffix}"
      ;;
  esac
}

capture_cpu() {
  local host="$1"
  local out="$2"
  mkdir -p "$(dirname "$out")"
  ssh $SSH_OPTS "${SSH_USER}@${host}" "head -n 1 /proc/stat" >"$out" 2>"${out}.stderr"
}

start_server() {
  local host="$1" port="$2" outprefix="$3"
  remote_exec "$host" "
    rm -f ${outprefix}.pid ${outprefix}.server.log ${outprefix}.server.err;
    nohup iperf3 -s -1 -p ${port} >${outprefix}.server.log 2>${outprefix}.server.err &
    echo \$! > ${outprefix}.pid
    sleep 1
    cat ${outprefix}.pid
  " 2>>"${RESULT_DIR}/logs/server_start.stderr" || true
}

run_ping() {
  local src="$1" dst="$2" outfile="$3"
  remote_exec "$src" "ping -c 4 -i 0.2 -W 1 ${dst}" >"$outfile" 2>"${outfile}.stderr" || true
}

run_client() {
  local src="$1" dst="$2" port="$3" json_out="$4" err_out="$5"
  remote_exec "$src" "iperf3 -c ${dst} -p ${port} -t ${DURATION} -P ${STREAMS} -J" >"$json_out" 2>"$err_out"
  return $?
}

cleanup_servers() {
  local pidfile
  while read -r pidfile host; do
    [[ -n "${pidfile:-}" && -n "${host:-}" ]] || continue
    remote_exec "$host" "if [[ -f \"${pidfile}\" ]]; then kill \$(cat \"${pidfile}\") >/dev/null 2>&1 || true; fi" >/dev/null 2>&1 || true
  done < "${RESULT_DIR}/server_pid_inventory.txt"
}
trap cleanup_servers EXIT
: > "${RESULT_DIR}/server_pid_inventory.txt"

mapfile -t NODES < <(get_nodes)
[[ "${#NODES[@]}" -eq "$NODE_COUNT" ]] || die "Expected ${NODE_COUNT} nodes, got ${#NODES[@]}"

declare -A NODE_IP
for n in "${NODES[@]}"; do
  NODE_IP["$n"]="$(node_to_ip "$n")"
  [[ -n "${NODE_IP[$n]}" ]] || die "Could not resolve IP for $n"
done

{
  echo "SLURM IPERF3 KPI REPORT"
  echo "========================================================================================================================"
  echo "Run ID         : $RUN_ID"
  echo "Partition      : $PARTITION"
  echo "Nodes          : ${NODES[*]}"
  echo "Duration       : ${DURATION}s"
  echo "Streams        : ${STREAMS}"
  echo "Expected/dir   : ${EXPECTED_GBPS_PER_DIRECTION}.0 Gbps"
  echo "Result dir     : ${RESULT_DIR}"
  echo
} | tee "$REPORT_TXT"

declare -a META_FILES

for ((i=0; i<${#NODES[@]}; i++)); do
  src="${NODES[$i]}"
  dst_node="${NODES[$(( (i+1) % ${#NODES[@]} ))]}"
  src_ip="${NODE_IP[$src]}"
  dst_ip="${NODE_IP[$dst_node]}"
  port=$((PORT_BASE + i))
  pair_id="$(printf 'pair_%02d' "$i")"

  tx_json="${RESULT_DIR}/iperf/${pair_id}_tx.json"
  rx_json="${RESULT_DIR}/iperf/${pair_id}_rx.json"
  tx_err="${RESULT_DIR}/iperf/${pair_id}_tx.stderr"
  rx_err="${RESULT_DIR}/iperf/${pair_id}_rx.stderr"
  ping_out="${RESULT_DIR}/ping/${pair_id}.ping.txt"

  cpu_src_before="${RESULT_DIR}/cpu/${pair_id}_${src}_before.txt"
  cpu_src_after="${RESULT_DIR}/cpu/${pair_id}_${src}_after.txt"
  cpu_dst_before="${RESULT_DIR}/cpu/${pair_id}_${dst_node}_before.txt"
  cpu_dst_after="${RESULT_DIR}/cpu/${pair_id}_${dst_node}_after.txt"

  srv_dst_prefix="/tmp/${pair_id}_dst_${port}"
  srv_src_prefix="/tmp/${pair_id}_src_${port}"

  log "Testing ${src} (${src_ip}) -> ${dst_node} (${dst_ip}) port ${port}"

  capture_cpu "$src" "$cpu_src_before"
  capture_cpu "$dst_node" "$cpu_dst_before"
  run_ping "$src" "$dst_ip" "$ping_out"

  start_server "$dst_node" "$port" "$srv_dst_prefix" >/dev/null || true
  echo "${srv_dst_prefix}.pid ${dst_node}" >> "${RESULT_DIR}/server_pid_inventory.txt"

  set +e
  run_client "$src" "$dst_ip" "$port" "$tx_json" "$tx_err"
  tx_rc=$?
  set -e

  start_server "$src" "$port" "$srv_src_prefix" >/dev/null || true
  echo "${srv_src_prefix}.pid ${src}" >> "${RESULT_DIR}/server_pid_inventory.txt"

  set +e
  run_client "$dst_node" "$src_ip" "$port" "$rx_json" "$rx_err"
  rx_rc=$?
  set -e

  capture_cpu "$src" "$cpu_src_after"
  capture_cpu "$dst_node" "$cpu_dst_after"

  meta="${RESULT_DIR}/raw/${pair_id}.meta.json"
  cat > "$meta" <<EOF
{
  "pair_id": "${pair_id}",
  "src": "${src}",
  "src_ip": "${src_ip}",
  "dst_node": "${dst_node}",
  "dst_ip": "${dst_ip}",
  "port": ${port},
  "tx_json": "${tx_json}",
  "rx_json": "${rx_json}",
  "tx_stderr": "${tx_err}",
  "rx_stderr": "${rx_err}",
  "tx_rc": ${tx_rc},
  "rx_rc": ${rx_rc},
  "ping_txt": "${ping_out}",
  "cpu_src_before": "${cpu_src_before}",
  "cpu_src_after": "${cpu_src_after}",
  "cpu_dst_before": "${cpu_dst_before}",
  "cpu_dst_after": "${cpu_dst_after}",
  "dst_server_log": "${srv_dst_prefix}.server.log",
  "dst_server_err": "${srv_dst_prefix}.server.err",
  "src_server_log": "${srv_src_prefix}.server.log",
  "src_server_err": "${srv_src_prefix}.server.err"
}
EOF
  META_FILES+=("$meta")
done

python3 - "$SUMMARY_JSON" "$EXPECTED_GBPS_PER_DIRECTION" "${META_FILES[@]}" <<'PY'
import json, os, re, sys, statistics
from datetime import datetime

summary_path = sys.argv[1]
expected_per_dir = float(sys.argv[2])
meta_files = sys.argv[3:]

def read_text(path):
    try:
        with open(path) as f:
            return f.read()
    except Exception:
        return ""

def parse_json_file(path):
    if not os.path.exists(path):
        return None, f"missing file: {path}"
    txt = read_text(path).strip()
    if not txt:
        return None, f"empty file: {path}"
    try:
        return json.loads(txt), ""
    except Exception as e:
        return None, f"invalid json: {e}"

def parse_iperf(path, stderr_path, rc):
    stderr_txt = read_text(stderr_path).strip()
    data, err = parse_json_file(path)
    if data is None:
        return 0.0, 0, f"client_rc={rc}; {err}; stderr={stderr_txt[:400]}"

    if isinstance(data, dict) and data.get("error"):
        return 0.0, 0, f"client_rc={rc}; iperf_error={data.get('error')}; stderr={stderr_txt[:400]}"

    try:
        end = data.get("end", {})
        sum_received = end.get("sum_received") or {}
        sum_sent = end.get("sum_sent") or {}
        bits = sum_received.get("bits_per_second") or sum_sent.get("bits_per_second") or 0
        retr = sum_sent.get("retransmits", 0) or 0
        if bits == 0:
            return 0.0, int(retr), f"client_rc={rc}; zero_throughput; stderr={stderr_txt[:400]}"
        return round(bits / 1e9, 2), int(retr), ""
    except Exception as e:
        return 0.0, 0, f"client_rc={rc}; parse_error={e}; stderr={stderr_txt[:400]}"

def parse_ping_avg(path):
    txt = read_text(path)
    m = re.search(r'=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)\s*ms', txt)
    return (float(m.group(2)), "") if m else (0.0, "ping avg not found")

def cpu_line(path):
    txt = read_text(path).strip()
    if not txt:
        return None
    line = txt.splitlines()[0].strip()
    if not line.startswith("cpu "):
        return None
    try:
        return [int(x) for x in line.split()[1:]]
    except Exception:
        return None

def cpu_pct(before_path, after_path):
    b, a = cpu_line(before_path), cpu_line(after_path)

    if not b:
        return 0.0, f"cpu before unavailable: {before_path}"
    if not a:
        return 0.0, f"cpu after unavailable: {after_path}"
    if len(b) != len(a):
        return 0.0, f"cpu field mismatch before={len(b)} after={len(a)}"

    total_b, total_a = sum(b), sum(a)
    idle_b = b[3] + (b[4] if len(b) > 4 else 0)
    idle_a = a[3] + (a[4] if len(a) > 4 else 0)

    total_d = total_a - total_b
    idle_d = idle_a - idle_b

    if total_d <= 0:
        return 0.0, "non-positive cpu delta"

    return round(100.0 * (total_d - idle_d) / total_d, 2), ""


rows = []
for mp in meta_files:
    meta = json.loads(read_text(mp))

    tx_gbps, tx_retr, tx_err = parse_iperf(meta["tx_json"], meta["tx_stderr"], meta["tx_rc"])
    rx_gbps, rx_retr, rx_err = parse_iperf(meta["rx_json"], meta["rx_stderr"], meta["rx_rc"])
    ping_avg, ping_err = parse_ping_avg(meta["ping_txt"])
    cpu_h, cpu_h_err = cpu_pct(meta["cpu_src_before"], meta["cpu_src_after"])
    cpu_r, cpu_r_err = cpu_pct(meta["cpu_dst_before"], meta["cpu_dst_after"])

    agg = round(tx_gbps + rx_gbps, 2)
    exp = round(expected_per_dir * 2.0, 2)
    pct = round((agg / exp) * 100.0, 2) if exp else 0.0

    errs = []
    for e in (tx_err, rx_err, ping_err, cpu_h_err, cpu_r_err):
        if e:
            errs.append(e)

    if agg > 0:
        status = "OK" if not errs else "WARN"
    else:
        status = "ERROR"

    rows.append({
        "src": meta["src"],
        "dst": meta["dst_ip"],
        "path": f'{meta["src"]}->{meta["dst_ip"]}',
        "tx_gbps": tx_gbps,
        "rx_gbps": rx_gbps,
        "agg_gbps": agg,
        "expected_agg_gbps": exp,
        "pct_of_expected": pct,
        "cpu_host_pct": cpu_h,
        "cpu_remote_pct": cpu_r,
        "retransmits": tx_retr + rx_retr,
        "ping_avg_ms": round(ping_avg, 3),
        "status": status,
        "error": " | ".join(errs)
    })

valid = [r for r in rows if r["agg_gbps"] > 0]
summary = {
    "generated_at": datetime.utcnow().isoformat(),
    "pairs_attempted": len(rows),
    "pairs_with_data": len(valid),
    "avg_agg_gbps": round(statistics.mean([r["agg_gbps"] for r in valid]), 2) if valid else 0.0,
    "min_agg_gbps": round(min([r["agg_gbps"] for r in valid]), 2) if valid else 0.0,
    "max_agg_gbps": round(max([r["agg_gbps"] for r in valid]), 2) if valid else 0.0,
    "rows": rows
}
with open(summary_path, "w") as f:
    json.dump(summary, f, indent=2)
PY

python3 - "$SUMMARY_JSON" <<'PY' | tee -a "$REPORT_TXT"
import json, sys
s = json.load(open(sys.argv[1]))
rows = s["rows"]

def f(x, n=2):
    return f"{x:.{n}f}" if isinstance(x, float) else str(x)

print()
print("Summary source :", sys.argv[1])
print("Generated at   :", s["generated_at"])
print("Pairs attempted:", s["pairs_attempted"])
print("Pairs with data:", s["pairs_with_data"])
print("Avg Agg Gbps   :", s["avg_agg_gbps"])
print("Min/Max Agg    :", f"{s['min_agg_gbps']} / {s['max_agg_gbps']}")
print()
print("Bandwidth vs Expected")
print("+-----------------------------------+---------+---------+----------+----------+-------+-----------+----------+---------+-------------+--------+")
print("| Path                              | TX Gbps | RX Gbps | Agg Gbps | Expected | % Exp | CPU Host% | CPU Rem% | Retrans | Ping Avg ms | Status |")
print("+-----------------------------------+---------+---------+----------+----------+-------+-----------+----------+---------+-------------+--------+")
for r in rows:
    print("| {path:<33} | {tx:>7} | {rx:>7} | {agg:>8} | {exp:>8} | {pct:>5} | {ch:>9} | {cr:>8} | {ret:>7} | {ping:>11} | {st:<6} |".format(
        path=r["path"][:33], tx=f(r["tx_gbps"]), rx=f(r["rx_gbps"]), agg=f(r["agg_gbps"]),
        exp=f(r["expected_agg_gbps"]), pct=f(r["pct_of_expected"]), ch=f(r["cpu_host_pct"]),
        cr=f(r["cpu_remote_pct"]), ret=r["retransmits"], ping=f(r["ping_avg_ms"],3), st=r["status"]))
print("+-----------------------------------+---------+---------+----------+----------+-------+-----------+----------+---------+-------------+--------+")
print()
print("Top Findings")
for r in rows:
    if r["error"]:
        print(f"- {r['path']}: {r['status']} | {r['error']}")
    else:
        print(f"- {r['path']}: {r['status']} | agg={r['agg_gbps']} Gbps, retrans={r['retransmits']}")
PY
