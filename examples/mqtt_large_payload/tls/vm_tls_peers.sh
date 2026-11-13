#!/usr/bin/env bash
# TLS peers on the dev VM for tls_client_test.py's VM cases; certificates from make_bench_certs.sh copied to ~/tmp/tls-bench.
#   ssh ktritz@192.168.50.142 'bash ~/tmp/tls-bench/vm_tls_peers.sh start|stop'
#   18892 vmgood (valid, serverAuth)   18893 expired   18894 notyet   18895 clientonly (clientAuth EKU only)
#   18896 silent: accepts TCP, never sends a byte (a peer that never answers the TLS ClientHello)
# openssl s_server completes or refuses the handshake, then never answers MQTT, so a valid certificate ends in the
# client's CONNACK timeout and a refused one in a TLS error. Stopped by the PIDs it saved.
set -u
DIR="$HOME/tmp/tls-bench"
cd "$DIR"
case "${1:-}" in
start)
  for spec in vmgood:18892 expired:18893 notyet:18894 clientonly:18895; do
    name=${spec%%:*}; port=${spec##*:}
    nohup openssl s_server -quiet -accept "$port" -cert "$name.pem" -key "$name.key" -cert_chain ca.pem \
      > "s_server_$name.log" 2>&1 < /dev/null &
    echo $! >> peers.pid
  done
  nohup python3 -c '
import socket, time
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(("0.0.0.0", 18896)); s.listen(8)
held = []
while True:
    c, a = s.accept(); held.append(c); print("accepted", a, flush=True)
' > silent.log 2>&1 < /dev/null &
  echo $! >> peers.pid
  sleep 1
  ss -ltn | grep -E ':1889[2-6] ' ;;
stop)
  [ -f peers.pid ] && xargs -r kill < peers.pid 2>/dev/null; rm -f peers.pid
  ss -ltn | grep -cE ':1889[2-6] ' || true ;;
*) echo "usage: $0 start|stop"; exit 1 ;;
esac
