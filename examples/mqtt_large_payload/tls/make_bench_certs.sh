#!/usr/bin/env bash
# Throwaway TLS material for the MQTT TLS bench tests, written to tmp/mqtt5_bench/tls (gitignored):
#   ca.pem / ca.key            "Bench MQTT Test CA" (ECDSA P-256, 1 year); the PLC trusts this one
#   server.pem / server.key    self-signed, untrusted (CN untrusted-bench-broker, SAN IP 192.168.50.108)
#   trusted.pem / trusted.key  signed by the CA, SAN IP 192.168.50.108 (this PC): the good broker
#   wronghost.pem / .key       signed by the CA, SAN IP 192.168.50.99: right CA, wrong name
#   wildcard / cnonly / ipdns  signed by the CA: SAN *.bench.local; no SAN, CN cn-broker.local; SAN DNS:192.168.50.108
# Re-running keeps an existing CA, so the PLC's trust store stays valid; delete ca.* to start over.
set -euo pipefail
OUT="$(cd "$(dirname "$0")/../../.." && pwd)/tmp/mqtt5_bench/tls"
mkdir -p "$OUT" && cd "$OUT"
export MSYS_NO_PATHCONV=1
if [ ! -f ca.pem ]; then
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -keyout ca.key -out ca.pem -days 365 \
    -subj "/CN=Bench MQTT Test CA/O=Tidal Metals bench" \
    -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign"
fi
openssl x509 -in ca.pem -outform DER -out ca.der
if [ ! -f server.pem ]; then
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -keyout server.key -out server.pem \
    -days 365 -subj "/CN=untrusted-bench-broker" -addext "subjectAltName=IP:192.168.50.108,IP:192.168.50.155"
fi
leaf() {  # name, SAN ('' for none), CN (default bench-broker-<name>)
  openssl req -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -keyout "$1.key" -out "$1.csr" \
    -subj "/CN=${3:-bench-broker-$1}"
  printf 'basicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\n' > "$1.ext"
  [ -n "$2" ] && printf 'subjectAltName=%s\n' "$2" >> "$1.ext"
  openssl x509 -req -in "$1.csr" -CA ca.pem -CAkey ca.key -CAcreateserial -out "$1.pem" -days 90 -extfile "$1.ext"
  cat "$1.pem" ca.pem > "$1.chain.pem"
  rm -f "$1.csr" "$1.ext"
}
leaf trusted "IP:192.168.50.108,DNS:bench-broker.local"
leaf wronghost "IP:192.168.50.99"
leaf wildcard "DNS:*.bench.local"                       # one label matches, two labels and the apex don't
leaf cnonly "" "cn-broker.local"                        # no SAN: only the subject CN names it
leaf ipdns "DNS:192.168.50.108"                         # an IP written as a DNS SAN, no IP SAN
# For tls/vm_tls_peers.sh on the dev VM (openssl s_server; MQTTug refuses to serve these): validity and purpose
dated() {  # name, not_before, not_after, extendedKeyUsage
  openssl req -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -keyout "$1.key" -out "$1.csr" -subj "/CN=bench-$1"
  printf 'subjectAltName=IP:192.168.50.142\nbasicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=%s\n' \
    "$4" > "$1.ext"
  openssl x509 -req -in "$1.csr" -CA ca.pem -CAkey ca.key -CAcreateserial -out "$1.pem" -not_before "$2" \
    -not_after "$3" -extfile "$1.ext"
  cat "$1.pem" ca.pem > "$1.chain.pem"
  rm -f "$1.csr" "$1.ext"
}
dated vmgood "$(date -u -d '-1 day' +%Y%m%d%H%M%SZ)" "$(date -u -d '+90 days' +%Y%m%d%H%M%SZ)" serverAuth
dated expired 20250101000000Z 20250201000000Z serverAuth
dated notyet "$(date -u -d '+1 year' +%Y%m%d%H%M%SZ)" "$(date -u -d '+2 years' +%Y%m%d%H%M%SZ)" serverAuth
dated clientonly "$(date -u -d '-1 day' +%Y%m%d%H%M%SZ)" "$(date -u -d '+90 days' +%Y%m%d%H%M%SZ)" clientAuth
for f in ca trusted wronghost wildcard cnonly ipdns server; do
  [ -f "$f.pem" ] && printf '%-10s %s | %s\n' "$f" "$(openssl x509 -in "$f.pem" -noout -subject)" \
    "$(openssl x509 -in "$f.pem" -noout -ext subjectAltName 2>/dev/null | tail -1 | tr -s ' ')"
done
openssl verify -CAfile ca.pem trusted.pem wronghost.pem wildcard.pem cnonly.pem ipdns.pem
