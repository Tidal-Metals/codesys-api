#!/usr/bin/env bash
# Two certificate hierarchies shaped like Let's Encrypt's in 2026 (RSA-4096 roots, a cross-signed root, an RSA-2048
# intermediate, an RSA-4096 leaf; served chain = leaf, intermediate, cross-signed root), written to
# tmp/mqtt5_bench/tls/le/. For tls_client_test.py's le_* cases through start_tls_broker.ps1 (listeners 8892, 8893).
#   A: the PLC trusts only rootXa (as ISRG Root X1 today): the chain must be built through the cross-signed rootYa
#   B: the PLC trusts only the self-signed rootYb (as ISRG Root YR later); the server still sends rootYb cross-signed
#      by rootXb, which the PLC doesn't trust
# Each leaf names 192.168.50.108 (the bench broker host). Re-running keeps existing files.
set -euo pipefail
OUT="$(cd "$(dirname "$0")/../../.." && pwd)/tmp/mqtt5_bench/tls/le"
mkdir -p "$OUT" && cd "$OUT"
export MSYS_NO_PATHCONV=1
ca_ext='basicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid'
make_hierarchy() {  # suffix
  local s=$1
  [ -f "chain_$s.pem" ] && return
  openssl req -x509 -newkey rsa:4096 -nodes -keyout "rootX$s.key" -out "rootX$s.pem" -days 3650 -subj "/CN=Bench Root X$s" \
    -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign"
  openssl req -x509 -newkey rsa:4096 -nodes -keyout "rootY$s.key" -out "rootY$s.pem" -days 3650 -subj "/CN=Bench Root Y$s" \
    -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign"
  # rootY cross-signed by rootX: same subject and key as the self-signed rootY
  openssl req -new -key "rootY$s.key" -subj "/CN=Bench Root Y$s" -out "rootY${s}_cross.csr"
  printf "$ca_ext\n" > ca.ext
  openssl x509 -req -in "rootY${s}_cross.csr" -CA "rootX$s.pem" -CAkey "rootX$s.key" -CAcreateserial -days 3000 \
    -extfile ca.ext -out "rootY${s}_cross.pem"
  # intermediate (RSA-2048) under rootY
  openssl req -newkey rsa:2048 -nodes -keyout "inter$s.key" -subj "/CN=Bench YR1 $s" -out "inter$s.csr"
  printf "basicConstraints=critical,CA:TRUE,pathlen:0\nkeyUsage=critical,digitalSignature,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n" > inter.ext
  openssl x509 -req -in "inter$s.csr" -CA "rootY$s.pem" -CAkey "rootY$s.key" -CAcreateserial -days 1000 \
    -extfile inter.ext -out "inter$s.pem"
  # leaf (RSA-4096) under the intermediate
  openssl req -newkey rsa:4096 -nodes -keyout "leaf$s.key" -subj "/CN=bench-le-$s" -out "leaf$s.csr"
  printf "subjectAltName=IP:192.168.50.108\nbasicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nauthorityKeyIdentifier=keyid\n" > leaf.ext
  openssl x509 -req -in "leaf$s.csr" -CA "inter$s.pem" -CAkey "inter$s.key" -CAcreateserial -days 90 \
    -extfile leaf.ext -out "leaf$s.pem"
  cat "leaf$s.pem" "inter$s.pem" "rootY${s}_cross.pem" > "chain_$s.pem"
  openssl x509 -in "rootX$s.pem" -outform DER -out "rootX$s.der"
  openssl x509 -in "rootY$s.pem" -outform DER -out "rootY$s.der"
  rm -f ./*.csr ca.ext inter.ext leaf.ext
}
# C: Let's Encrypt's default ECDSA chain: leaf (P-256) <- YE1 (P-384) <- Root YE (P-384, cross-signed by X2) <- X2
# (P-384, cross-signed by X1) <- X1 (RSA 4096, the only root the PLC trusts)
make_ecdsa_hierarchy() {  # suffix
  local s=$1
  [ -f "chain_$s.pem" ] && return
  local p384="-newkey ec -pkeyopt ec_paramgen_curve:secp384r1"
  openssl req -x509 -newkey rsa:4096 -nodes -keyout "rootX$s.key" -out "rootX$s.pem" -days 3650 -subj "/CN=Bench Root X1 $s" \
    -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign"
  openssl req -x509 $p384 -nodes -keyout "x2$s.key" -out "x2$s.pem" -days 3650 -sha384 -subj "/CN=Bench Root X2 $s" \
    -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign"
  openssl req -x509 $p384 -nodes -keyout "ye$s.key" -out "ye$s.pem" -days 3650 -sha384 -subj "/CN=Bench Root YE $s" \
    -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign"
  printf "$ca_ext\n" > ca.ext
  openssl req -new -key "x2$s.key" -subj "/CN=Bench Root X2 $s" -out x2.csr
  openssl x509 -req -in x2.csr -CA "rootX$s.pem" -CAkey "rootX$s.key" -CAcreateserial -days 3000 -extfile ca.ext \
    -out "x2${s}_cross.pem"
  openssl req -new -key "ye$s.key" -subj "/CN=Bench Root YE $s" -out ye.csr
  openssl x509 -req -in ye.csr -CA "x2$s.pem" -CAkey "x2$s.key" -CAcreateserial -days 3000 -sha384 -extfile ca.ext \
    -out "ye${s}_cross.pem"
  openssl req $p384 -nodes -keyout "inter$s.key" -subj "/CN=Bench YE1 $s" -out inter.csr
  printf "basicConstraints=critical,CA:TRUE,pathlen:0\nkeyUsage=critical,digitalSignature,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n" > inter.ext
  openssl x509 -req -in inter.csr -CA "ye$s.pem" -CAkey "ye$s.key" -CAcreateserial -days 1000 -sha384 -extfile inter.ext \
    -out "inter$s.pem"
  openssl req -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -keyout "leaf$s.key" -subj "/CN=bench-le-$s" -out leaf.csr
  printf "subjectAltName=IP:192.168.50.108\nbasicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\nauthorityKeyIdentifier=keyid\n" > leaf.ext
  openssl x509 -req -in leaf.csr -CA "inter$s.pem" -CAkey "inter$s.key" -CAcreateserial -days 90 -sha384 -extfile leaf.ext \
    -out "leaf$s.pem"
  cat "leaf$s.pem" "inter$s.pem" "ye${s}_cross.pem" "x2${s}_cross.pem" > "chain_$s.pem"
  openssl x509 -in "rootX$s.pem" -outform DER -out "rootX$s.der"
  rm -f ./*.csr ca.ext inter.ext leaf.ext
}
make_hierarchy a
make_hierarchy b
make_ecdsa_hierarchy c
cat interc.pem yec_cross.pem x2c_cross.pem > untrusted_c.pem
echo "C, trusting rootXc (RSA, X1-like) only:"; openssl verify -CAfile rootXc.pem -untrusted untrusted_c.pem leafc.pem
rm -f untrusted_c.pem
cat intera.pem rootYa_cross.pem > untrusted_a.pem; cat interb.pem rootYb_cross.pem > untrusted_b.pem
echo "A, trusting rootXa only:"; openssl verify -CAfile rootXa.pem -untrusted untrusted_a.pem leafa.pem
echo "B, trusting rootYb only:"; openssl verify -CAfile rootYb.pem -untrusted untrusted_b.pem leafb.pem
rm -f untrusted_a.pem untrusted_b.pem
ls -1 ./*.der
