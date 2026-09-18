#!/bin/bash
# L4D2 Ops Panel 安装脚本：生成 panel.json、自签名证书、systemd 服务。以运行游戏的那个用户执行（例如 l4d2server）。
set -e
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "需要 python3"; exit 1; }
ask() { local v; read -r -p "$1 [$2]: " v; echo "${v:-$2}"; }
echo "== L4D2 Ops Panel 安装 =="
GAME_DIR=$(ask "游戏目录 (…/left4dead2)" "$HOME/serverfiles/left4dead2")
LGSM=$(ask "LinuxGSM 实例脚本（没有则留空）" "$HOME/l4d2server")
RCON_HOST=$(ask "RCON/查询地址（L4D2 不回应 127.0.0.1，填服务器网卡 IP）" "$(hostname -I 2>/dev/null | awk '{print $1}')")
RCON_PORT=$(ask "RCON 端口" "27015")
CONSOLE_LOG=$(ask "控制台日志（LinuxGSM 默认；没有则留空）" "$HOME/log/console/l4d2server-console.log")
PERF=$(ask "性能采样 CSV（tools/perf-sampler.sh 产出；没有则留空）" "$HOME/log/perf-samples.csv")
DD=$(ask "DepotDownloader 路径（用于创意工坊下载；没有则留空）" "$HOME/tools/depotdownloader/DepotDownloader")
HOST=$(ask "对外显示的域名或 IP（可空）" "")
MODE=$(ask "监听方式：1 = 自带 HTTPS（自签名证书） 2 = 仅本机 8080，前面放 nginx" "1")
if [ "$MODE" = "1" ]; then PORT=$(ask "端口" "8443"); BIND=0.0.0.0; TLS=true; else PORT=8080; BIND=127.0.0.1; TLS=false; fi
PASS=$(python3 -c 'import secrets;print(secrets.token_urlsafe(12))')
python3 - "$GAME_DIR" "$LGSM" "$RCON_HOST" "$RCON_PORT" "$CONSOLE_LOG" "$PERF" "$DD" "$HOST" "$PORT" "$BIND" "$TLS" "$PASS" <<'PY'
import json,sys
a=sys.argv[1:]
c={"password":a[11],"port":int(a[8]),"bind":a[9],"tls":a[10]=="true","cert":"cert.pem","key":"key.pem","session_days":7,
   "rcon_host":a[2],"rcon_port":int(a[3]),"rcon_password":"","game_dir":a[0],"lgsm_script":a[1],"console_log":a[4],"perf_csv":a[5],
   "depotdownloader":a[6],"panel_title":"L4D2 运维面板","display_host":a[7],"max_upload_mb":3072,"protected_addons":["admin_system.vpk"]}
json.dump(c,open("panel.json","w"),ensure_ascii=False,indent=2); print("panel.json 已写入")
PY
chmod 600 panel.json
if [ "$TLS" = true ] && [ ! -f cert.pem ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 3650 -subj "/CN=${HOST:-l4d2panel}" $( [ -n "$HOST" ] && echo -addext "subjectAltName=DNS:$HOST" ) >/dev/null 2>&1 && chmod 600 key.pem && echo "自签名证书已生成（cert.pem / key.pem，浏览器首次访问需点“继续”）"
fi
UNIT=/etc/systemd/system/l4d2panel.service
if command -v systemctl >/dev/null && [ -w /etc/systemd/system ] || sudo -n true 2>/dev/null; then
  sudo tee "$UNIT" >/dev/null <<UNITEOF
[Unit]
Description=L4D2 Ops Panel
After=network.target

[Service]
User=$(whoami)
WorkingDirectory=$(pwd)
ExecStart=/usr/bin/python3 $(pwd)/panel.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNITEOF
  sudo systemctl daemon-reload && sudo systemctl enable --now l4d2panel && echo "systemd 服务 l4d2panel 已启动"
else
  echo "没有 sudo，跳过 systemd。手动启动：python3 $(pwd)/panel.py"
fi
echo
echo "==================================================="
if [ "$TLS" = true ]; then echo "地址：https://${HOST:-<服务器IP>}:$PORT/   （记得在云防火墙放行 TCP $PORT）"; else echo "面板监听 127.0.0.1:8080，请配置 nginx 反代（见 nginx.example.conf）"; fi
echo "密码：$PASS   （保存在 panel.json，改完 systemctl restart l4d2panel）"
echo "==================================================="
