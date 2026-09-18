#!/bin/bash
# 有真人在线时每 15 秒往控制台发 "stats"，记录 CPU / 入出流量 / server fps 到 CSV；同时开关 SourceMod 的 vprof。
# 用环境变量覆盖默认值：L4D2_HOME、CONSOLE_LOG、OUT、QUERY_HOST、QUERY_PORT、TMUX_SESSION
L4D2_HOME=${L4D2_HOME:-$HOME}
CON=${CONSOLE_LOG:-$L4D2_HOME/log/console/l4d2server-console.log}
OUT=${OUT:-$L4D2_HOME/log/perf-samples.csv}
QUERY_HOST=${QUERY_HOST:-$(hostname -I 2>/dev/null | awk '{print $1}')}
QUERY_PORT=${QUERY_PORT:-27015}
SESSION=${TMUX_SESSION:-l4d2server}
mkdir -p "$(dirname "$OUT")"
[ -f "$OUT" ] || echo "time,humans,cpu%,in_bytes,out_bytes,fps,players" > "$OUT"
prof=0
players() {
python3 - "$QUERY_HOST" "$QUERY_PORT" <<'PY'
import socket,sys
h,p=sys.argv[1],int(sys.argv[2])
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(2)
req=b"\xFF\xFF\xFF\xFFTSource Engine Query\x00"
try:
    s.sendto(req,(h,p)); d,_=s.recvfrom(4096)
    if d[4:5]==b"A": s.sendto(req+d[5:9],(h,p)); d,_=s.recvfrom(4096)
    i=6
    for _ in range(4): i=d.index(b"\x00",i)+1
    print(max(0,d[i+2]-d[i+4]))
except Exception: print(-1)
PY
}
send() { TERM=screen tmux -L "$(ls /tmp/tmux-$(id -u)/ 2>/dev/null | head -1)" send-keys -t "$SESSION" "$1" ENTER 2>/dev/null; }
while true; do
  n=$(players)
  if [ "$n" -gt 0 ] 2>/dev/null; then
    if [ $prof -eq 0 ]; then send "sm prof start vprof"; prof=1; fi
    before=$(wc -l < "$CON"); send "stats"; sleep 2
    line=$(sed "s/\x1b\[[0-9;]*m//g" "$CON" | tail -n +$((before+1)) | grep -E '^\s*[0-9]+(\.[0-9]+)?\s+[0-9]' | tail -1)
    if [ -n "$line" ]; then set -- $line; echo "$(date +%H:%M:%S),$n,$1,$2,$3,$6,$7" >> "$OUT"; fi   # L4D2 stats: CPU In Out Uptime Users FPS Players (In/Out = bytes/s)
    sleep 13
  else
    if [ $prof -eq 1 ]; then send "sm prof dump"; sleep 3; send "sm prof stop"; prof=0; fi
    sleep 30
  fi
done
