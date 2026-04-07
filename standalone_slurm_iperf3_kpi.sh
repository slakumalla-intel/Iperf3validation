#!/usr/bin/env bash
set -Eeuo pipefail

PARTITION="${PARTITION:-debug}"
NODES_CSV="${NODES_CSV:-}"
NODE_COUNT="${NODE_COUNT:-4}"
DURATION="${DURATION:-30}"
STREAMS="${STREAMS:-8}"
STREAM_SCALE_LIST="${STREAM_SCALE_LIST:-}"
PORT_BASE="${PORT_BASE:-5201}"
EXPECTED_GBPS_PER_DIRECTION="${EXPECTED_GBPS_PER_DIRECTION:-200}"
CORE_SCALE_LIST="${CORE_SCALE_LIST:-}"
CORE_STEPS="${CORE_STEPS:-16,32,64,96,128}"
ZEROCOPY="${ZEROCOPY:-0}"
SSH_USER="${SSH_USER:-root}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=5}"
IP_MODE="${IP_MODE:-admin}"   # admin | hostname | custom_map
CUSTOM_IP_MAP="${CUSTOM_IP_MAP:-}"
RESULT_ROOT="${RESULT_ROOT:-results}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
RESULT_DIR="${RESULT_ROOT}/${RUN_ID}"
REPORT_TXT="${RESULT_DIR}/report.txt"
LOG_DIR="${RESULT_DIR}/logs"
SERVER_PID_FILE="${RESULT_DIR}/server_pid_inventory.txt"

mkdir -p "$RESULT_DIR" "$LOG_DIR"
: > "$SERVER_PID_FILE"

log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*" | tee -a "$REPORT_TXT" >&2; }
die() { echo "ERROR: $*" >&2; exit 1; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"; }

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

normalize_csv() {
  local input="$1"
  local -a parts=()
  local raw trimmed

  IFS=',' read -r -a parts <<< "$input"
  for raw in "${parts[@]}"; do
    trimmed="$(trim "$raw")"
    [[ -n "$trimmed" ]] && printf '%s\n' "$trimmed"
  done
}

validate_positive_int() {
  local value="$1"
  local label="$2"

  [[ "$value" =~ ^[0-9]+$ ]] || die "$label must be a positive integer, got '$value'"
  (( value > 0 )) || die "$label must be greater than zero, got '$value'"
}

resolve_core_steps() {
  if [[ -n "$CORE_SCALE_LIST" ]]; then
    printf '%s' "$CORE_SCALE_LIST"
  else
    printf '%s' "$CORE_STEPS"
  fi
}

build_iperf_client_args() {
  local streams="$1"
  local args="-t ${DURATION} -P ${streams} -J"
  if [[ "$ZEROCOPY" == "1" ]]; then
    args+=" --zerocopy"
  fi
  printf '%s' "$args"
}

for c in sinfo ssh python3 iperf3 ping taskset; do
  need_cmd "$c"
done

remote_exec() {
  local host="$1"; shift
  ssh $SSH_OPTS "${SSH_USER}@${host}" \
    "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; bash -lc '$*'"
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

capture_core_count() {
  local host="$1"
  local out="$2"
  mkdir -p "$(dirname "$out")"
  ssh $SSH_OPTS "${SSH_USER}@${host}" "nproc" >"$out" 2>"${out}.stderr"
}

make_cpu_range() {
  local n="$1"
  local last=$((n - 1))
  if (( last < 0 )); then
    echo "0"
  else
    echo "0-${last}"
  fi
}

clamp_core_count() {
  local requested="$1"
  local available="$2"
  if (( requested > available )); then
    echo "$available"
  else
    echo "$requested"
  fi
}

start_server() {
  local host="$1"
  local port="$2"
  local outprefix="$3"
  local cpu_range="$4"

  remote_exec "$host" "
    rm -f ${outprefix}.pid ${outprefix}.server.log ${outprefix}.server.err
    nohup taskset -c ${cpu_range} iperf3 -s -1 -p ${port} > ${outprefix}.server.log 2> ${outprefix}.server.err &
    echo \$! > ${outprefix}.pid
    sleep 1
    cat ${outprefix}.pid
  " 2>>"${LOG_DIR}/server_start.stderr" || true
}

run_ping() {
  local src="$1"
  local dst="$2"
  local outfile="$3"
  remote_exec "$src" "ping -c 4 -i 0.2 -W 1 ${dst}" >"$outfile" 2>"${outfile}.stderr" || true
}

run_client() {
  local src="$1"
  local dst="$2"
  local port="$3"
  local json_out="$4"
  local err_out="$5"
  local cpu_range="$6"
  local streams="$7"

  remote_exec "$src" "taskset -c ${cpu_range} iperf3 -c ${dst} -p ${port} $(build_iperf_client_args "$streams")" >"$json_out" 2>"$err_out"
  return $?
}

cleanup_servers() {
  local pidfile host
  while read -r pidfile host; do
    [[ -n "${pidfile:-}" && -n "${host:-}" ]] || continue
    remote_exec "$host" "if [[ -f '${pidfile}' ]]; then kill \$(cat '${pidfile}') >/dev/null 2>&1 || true; fi" >/dev/null 2>&1 || true
  done < "$SERVER_PID_FILE"
}
trap cleanup_servers EXIT

mapfile -t NODES < <(get_nodes)
[[ "${#NODES[@]}" -eq "$NODE_COUNT" ]] || die "Expected ${NODE_COUNT} nodes, got ${#NODES[@]}"

CORE_STEPS="$(resolve_core_steps)"
mapfile -t CORE_LIST < <(normalize_csv "$CORE_STEPS")
[[ "${#CORE_LIST[@]}" -gt 0 ]] || die "No valid core steps were provided"
for core_value in "${CORE_LIST[@]}"; do
  validate_positive_int "$core_value" "Core step"
done

STREAM_SWEEP_ENABLED=0
declare -a STREAM_LIST=()
if [[ -n "$STREAM_SCALE_LIST" ]]; then
  mapfile -t STREAM_LIST < <(normalize_csv "$STREAM_SCALE_LIST")
  [[ "${#STREAM_LIST[@]}" -gt 0 ]] || die "STREAM_SCALE_LIST was provided but no valid stream values were found"
  for stream_value in "${STREAM_LIST[@]}"; do
    validate_positive_int "$stream_value" "Stream count"
  done
  STREAM_SWEEP_ENABLED=1
fi

DEFAULT_STREAMS="$(trim "$STREAMS")"
validate_positive_int "$DEFAULT_STREAMS" "STREAMS"

CORE_STEPS_DISPLAY="$(IFS=,; echo "${CORE_LIST[*]}")"
STREAM_STEPS_DISPLAY="$DEFAULT_STREAMS"
if (( STREAM_SWEEP_ENABLED )); then
  STREAM_STEPS_DISPLAY="$(IFS=,; echo "${STREAM_LIST[*]}")"
fi

case "$ZEROCOPY" in
  0|1) ;;
  *) die "ZEROCOPY must be 0 or 1, got '$ZEROCOPY'" ;;
esac

declare -A NODE_IP
for n in "${NODES[@]}"; do
  NODE_IP["$n"]="$(node_to_ip "$n")"
  [[ -n "${NODE_IP[$n]}" ]] || die "Could not resolve IP for $n"
done

{
  echo "SLURM IPERF3 CORE SWEEP REPORT"
  echo "================================================================================================================================================================"
  echo "Run ID         : $RUN_ID"
  echo "Partition      : $PARTITION"
  echo "Nodes          : ${NODES[*]}"
  echo "Duration       : ${DURATION}s"
  echo "Streams        : ${STREAM_STEPS_DISPLAY}"
  echo "Zerocopy       : ${ZEROCOPY}"
  echo "Expected/dir   : ${EXPECTED_GBPS_PER_DIRECTION}.0 Gbps"
  echo "Core steps     : ${CORE_STEPS_DISPLAY}"
  echo "Result dir     : ${RESULT_DIR}"
  echo
} | tee "$REPORT_TXT"

for req_cores_raw in "${CORE_LIST[@]}"; do
  req_cores="$(trim "$req_cores_raw")"
  [[ -n "$req_cores" ]] || continue

  if (( STREAM_SWEEP_ENABLED )); then
    declare -a ACTIVE_STREAM_LIST=("${STREAM_LIST[@]}")
  else
    declare -a ACTIVE_STREAM_LIST=("$DEFAULT_STREAMS")
  fi

  for stream_count_raw in "${ACTIVE_STREAM_LIST[@]}"; do
    stream_count="$(trim "$stream_count_raw")"
    [[ -n "$stream_count" ]] || continue

    SCALE_DIR="${RESULT_DIR}/cores_${req_cores}/streams_${stream_count}"
    CPU_DIR="${SCALE_DIR}/cpu"
    PING_DIR="${SCALE_DIR}/ping"
    IPERF_DIR="${SCALE_DIR}/iperf"
    RAW_DIR="${SCALE_DIR}/raw"
    SUMMARY_JSON="${SCALE_DIR}/summary.json"

    mkdir -p "$SCALE_DIR" "$CPU_DIR" "$PING_DIR" "$IPERF_DIR" "$RAW_DIR"

    log "Starting core-scale test for ${req_cores} cores with ${stream_count} streams"

    declare -a META_FILES=()

    for ((i=0; i<${#NODES[@]}; i++)); do
      src="${NODES[$i]}"
      dst_node="${NODES[$(( (i+1) % ${#NODES[@]} ))]}"
      src_ip="${NODE_IP[$src]}"
      dst_ip="${NODE_IP[$dst_node]}"
      port=$((PORT_BASE + i))
      pair_id="$(printf 'pair_%02d' "$i")"

      cores_src="${CPU_DIR}/${pair_id}_${src}_cores.txt"
      cores_dst="${CPU_DIR}/${pair_id}_${dst_node}_cores.txt"

      capture_core_count "$src" "$cores_src"
      capture_core_count "$dst_node" "$cores_dst"

      src_total="$(tr -d '[:space:]' < "$cores_src" 2>/dev/null || echo 1)"
      dst_total="$(tr -d '[:space:]' < "$cores_dst" 2>/dev/null || echo 1)"
      [[ "$src_total" =~ ^[0-9]+$ ]] || src_total=1
      [[ "$dst_total" =~ ^[0-9]+$ ]] || dst_total=1

      src_used="$(clamp_core_count "$req_cores" "$src_total")"
      dst_used="$(clamp_core_count "$req_cores" "$dst_total")"
      src_range="$(make_cpu_range "$src_used")"
      dst_range="$(make_cpu_range "$dst_used")"

      tx_json="${IPERF_DIR}/${pair_id}_tx.json"
      rx_json="${IPERF_DIR}/${pair_id}_rx.json"
      tx_err="${IPERF_DIR}/${pair_id}_tx.stderr"
      rx_err="${IPERF_DIR}/${pair_id}_rx.stderr"
      ping_out="${PING_DIR}/${pair_id}.ping.txt"

      cpu_src_before="${CPU_DIR}/${pair_id}_${src}_before.txt"
      cpu_src_after="${CPU_DIR}/${pair_id}_${src}_after.txt"
      cpu_dst_before="${CPU_DIR}/${pair_id}_${dst_node}_before.txt"
      cpu_dst_after="${CPU_DIR}/${pair_id}_${dst_node}_after.txt"

      srv_dst_prefix="/tmp/${pair_id}_dst_${port}_c${req_cores}_s${stream_count}"
      srv_src_prefix="/tmp/${pair_id}_src_${port}_c${req_cores}_s${stream_count}"

      log "Testing ${src} (${src_ip}) -> ${dst_node} (${dst_ip}) with requested cores=${req_cores}, streams=${stream_count}, src_range=${src_range}, dst_range=${dst_range}"

      capture_cpu "$src" "$cpu_src_before"
      capture_cpu "$dst_node" "$cpu_dst_before"
      run_ping "$src" "$dst_ip" "$ping_out"

      start_server "$dst_node" "$port" "$srv_dst_prefix" "$dst_range" >/dev/null
      echo "${srv_dst_prefix}.pid ${dst_node}" >> "$SERVER_PID_FILE"

      set +e
      run_client "$src" "$dst_ip" "$port" "$tx_json" "$tx_err" "$src_range" "$stream_count"
      tx_rc=$?
      set -e

      start_server "$src" "$port" "$srv_src_prefix" "$src_range" >/dev/null
      echo "${srv_src_prefix}.pid ${src}" >> "$SERVER_PID_FILE"

      set +e
      run_client "$dst_node" "$src_ip" "$port" "$rx_json" "$rx_err" "$dst_range" "$stream_count"
      rx_rc=$?
      set -e

      capture_cpu "$src" "$cpu_src_after"
      capture_cpu "$dst_node" "$cpu_dst_after"

      meta="${RAW_DIR}/${pair_id}.meta.json"
      cat > "$meta" <<EOF
{
  "pair_id": "${pair_id}",
  "requested_cores": ${req_cores},
  "requested_streams": ${stream_count},
  "src": "${src}",
  "src_ip": "${src_ip}",
  "dst_node": "${dst_node}",
  "dst_ip": "${dst_ip}",
  "port": ${port},
  "src_core_range": "${src_range}",
  "dst_core_range": "${dst_range}",
  "src_used_cores": ${src_used},
  "dst_used_cores": ${dst_used},
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
  "cores_src": "${cores_src}",
  "cores_dst": "${cores_dst}",
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
from datetime import datetime, UTC

summary_path = sys.argv[1]
expected_per_dir = float(sys.argv[2])
meta_files = sys.argv[3:]

def read_text(path):
    try:
        with open(path) as f:
            return f.read()
    except Exception:
        return ""

def read_int_file(path, default=0):
    txt = read_text(path).strip()
    try:
        return int(txt)
    except Exception:
        return default

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
    txt = read_text(path)
    if not txt:
        return None
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("cpu "):
            try:
                return [int(x) for x in line.split()[1:]]
            except Exception:
                return None
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

    host_cores = read_int_file(meta["cores_src"], 0)
    remote_cores = read_int_file(meta["cores_dst"], 0)
    host_busy_cores = round((cpu_h * host_cores) / 100.0, 2) if host_cores > 0 else 0.0
    remote_busy_cores = round((cpu_r * remote_cores) / 100.0, 2) if remote_cores > 0 else 0.0

    agg = round(tx_gbps + rx_gbps, 2)
    exp = round(expected_per_dir * 2.0, 2)
    pct = round((agg / exp) * 100.0, 2) if exp else 0.0

    gbps_per_host_busy_core = round((agg / host_busy_cores), 2) if host_busy_cores > 0 else 0.0
    gbps_per_remote_busy_core = round((agg / remote_busy_cores), 2) if remote_busy_cores > 0 else 0.0

    errs = []
    for e in (tx_err, rx_err, ping_err, cpu_h_err, cpu_r_err):
        if e:
            errs.append(e)

    if agg > 0:
        status = "OK" if not errs else "WARN"
    else:
        status = "ERROR"

    rows.append({
        "requested_cores": meta.get("requested_cores", 0),
        "requested_streams": meta.get("requested_streams", 0),
        "src": meta["src"],
        "dst": meta["dst_ip"],
        "path": f'{meta["src"]}->{meta["dst_ip"]}',
        "src_used_cores": meta.get("src_used_cores", 0),
        "dst_used_cores": meta.get("dst_used_cores", 0),
        "src_core_range": meta.get("src_core_range", ""),
        "dst_core_range": meta.get("dst_core_range", ""),
        "tx_gbps": tx_gbps,
        "rx_gbps": rx_gbps,
        "agg_gbps": agg,
        "expected_agg_gbps": exp,
        "pct_of_expected": pct,
        "cpu_host_pct": cpu_h,
        "cpu_remote_pct": cpu_r,
        "host_cores": host_cores,
        "remote_cores": remote_cores,
        "host_busy_cores": host_busy_cores,
        "remote_busy_cores": remote_busy_cores,
        "gbps_per_host_busy_core": gbps_per_host_busy_core,
        "gbps_per_remote_busy_core": gbps_per_remote_busy_core,
        "retransmits": tx_retr + rx_retr,
        "ping_avg_ms": round(ping_avg, 3),
        "status": status,
        "error": " | ".join(errs)
    })

valid = [r for r in rows if r["agg_gbps"] > 0]
summary = {
    "generated_at": datetime.now(UTC).isoformat(),
    "requested_cores": rows[0]["requested_cores"] if rows else 0,
    "requested_streams": rows[0]["requested_streams"] if rows else 0,
    "pairs_attempted": len(rows),
    "pairs_with_data": len(valid),
    "avg_agg_gbps": round(statistics.mean([r["agg_gbps"] for r in valid]), 2) if valid else 0.0,
    "min_agg_gbps": round(min([r["agg_gbps"] for r in valid]), 2) if valid else 0.0,
    "max_agg_gbps": round(max([r["agg_gbps"] for r in valid]), 2) if valid else 0.0,
    "avg_host_busy_cores": round(statistics.mean([r["host_busy_cores"] for r in valid]), 2) if valid else 0.0,
    "avg_remote_busy_cores": round(statistics.mean([r["remote_busy_cores"] for r in valid]), 2) if valid else 0.0,
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
print(f"Core Budget Summary: {s.get('requested_cores', 0)} cores")
print(f"Streams           : {s.get('requested_streams', 0)}")
print("Summary source :", sys.argv[1])
print("Generated at   :", s["generated_at"])
print("Pairs attempted:", s["pairs_attempted"])
print("Pairs with data:", s["pairs_with_data"])
print("Avg Agg Gbps   :", s["avg_agg_gbps"])
print("Min/Max Agg    :", f"{s['min_agg_gbps']} / {s['max_agg_gbps']}")
print("Avg Busy Cores :", f"host={s.get('avg_host_busy_cores',0.0)} remote={s.get('avg_remote_busy_cores',0.0)}")
print()
print("+-----------------------------------+-------+---------+---------+----------+-------+-----------+-----------+----------+----------+-----------+-----------+---------+-------------+--------+")
print("| Path                              | Req C | TX Gbps | RX Gbps | Agg Gbps | % Exp | CPU Host% | Host Core | CPU Rem% | Rem Core | Gbps/HCore| Gbps/RCore| Retrans | Ping Avg ms | Status |")
print("+-----------------------------------+-------+---------+---------+----------+-------+-----------+-----------+----------+----------+-----------+-----------+---------+-------------+--------+")
for r in rows:
    print("| {path:<33} | {req:>5} | {tx:>7} | {rx:>7} | {agg:>8} | {pct:>5} | {ch:>9} | {hc:>9} | {cr:>8} | {rc:>8} | {gh:>9} | {gr:>9} | {ret:>7} | {ping:>11} | {st:<6} |".format(
        path=r["path"][:33],
        req=r["requested_cores"],
        tx=f(r["tx_gbps"]),
        rx=f(r["rx_gbps"]),
        agg=f(r["agg_gbps"]),
        pct=f(r["pct_of_expected"]),
        ch=f(r["cpu_host_pct"]),
        hc=f(r["host_busy_cores"]),
        cr=f(r["cpu_remote_pct"]),
        rc=f(r["remote_busy_cores"]),
        gh=f(r["gbps_per_host_busy_core"]),
        gr=f(r["gbps_per_remote_busy_core"]),
        ret=r["retransmits"],
        ping=f(r["ping_avg_ms"], 3),
        st=r["status"],
    ))
print("+-----------------------------------+-------+---------+---------+----------+-------+-----------+-----------+----------+----------+-----------+-----------+---------+-------------+--------+")
print()
print("Top Findings")
for r in rows:
    base = f"agg={r['agg_gbps']} Gbps, host_cpu={r['cpu_host_pct']}% ({r['host_busy_cores']} cores), remote_cpu={r['cpu_remote_pct']}% ({r['remote_busy_cores']} cores)"
    if r["error"]:
        print(f"- {r['path']}: {r['status']} | {base} | {r['error']}")
    else:
        print(f"- {r['path']}: {r['status']} | {base}, retrans={r['retransmits']}")
PY
  done

done

python3 - "$RESULT_DIR" <<'PY' | tee -a "$REPORT_TXT"
import json, os, glob, re, sys

root = os.path.abspath(sys.argv[1])
rows = []

for path in sorted(glob.glob(os.path.join(root, "cores_*", "summary.json"))):
    m = re.search(r'cores_(\d+)', path)
    cores = int(m.group(1)) if m else 0
    with open(path) as f:
        s = json.load(f)
    rows.append({
        "cores": cores,
        "pairs": s.get("pairs_with_data", 0),
        "avg_agg_gbps": s.get("avg_agg_gbps", 0.0),
        "min_agg_gbps": s.get("min_agg_gbps", 0.0),
        "max_agg_gbps": s.get("max_agg_gbps", 0.0),
        "avg_host_busy_cores": s.get("avg_host_busy_cores", 0.0),
        "avg_remote_busy_cores": s.get("avg_remote_busy_cores", 0.0),
    })

print()
print("Core Scaling Summary")
print("+--------+-------+--------------+--------------+--------------+----------------+----------------+")
print("| Cores  | Pairs | Avg Agg Gbps | Min Agg Gbps | Max Agg Gbps | Avg Host Cores | Avg Rem Cores  |")
print("+--------+-------+--------------+--------------+--------------+----------------+----------------+")
for r in rows:
    print("| {cores:>6} | {pairs:>5} | {avg:>12.2f} | {minv:>12.2f} | {maxv:>12.2f} | {host:>14.2f} | {rem:>14.2f} |".format(
        cores=r["cores"],
        pairs=r["pairs"],
        avg=r["avg_agg_gbps"],
        minv=r["min_agg_gbps"],
        maxv=r["max_agg_gbps"],
        host=r["avg_host_busy_cores"],
        rem=r["avg_remote_busy_cores"],
    ))
print("+--------+-------+--------------+--------------+--------------+----------------+----------------+")
PY

log "Done. Report: ${REPORT_TXT}"
log "Results root: ${RESULT_DIR}"
