# Start the private bench MQTTug with one plain listener and the TLS listeners below (make_bench_certs.sh,
# make_lechain_certs.sh):
#   1886 plain | 8886 trusted (CA-signed, SAN 192.168.50.108) | 8887 untrusted self-signed | 8888 CA-signed, wrong SAN
#   8889 SAN *.bench.local | 8890 no SAN, CN cn-broker.local | 8891 SAN DNS:192.168.50.108 (no IP SAN)
#   8892 / 8893 Let's Encrypt-shaped RSA chains A / B, 8894 ECDSA chain C (make_lechain_certs.sh)
# Runs the binary under esp32-gateway-platform/tmp/hq-mqtt-stack/bin, the only path with a firewall rule; the 1884 HQ
# evaluation stack shares it, so stop this one only by the PID in tmp/mqtt5_bench/broker.pid (-Stop does that).
param([switch]$Stop)
$repo = (Resolve-Path "$PSScriptRoot\..\..\..").Path
$bench = "$repo\tmp\mqtt5_bench"
$tls = "$bench\tls"
$pidFile = "$bench\broker.pid"
if (Test-Path $pidFile) {
    $old = Get-Process -Id ([int](Get-Content $pidFile)) -ErrorAction SilentlyContinue
    if ($old -and $old.ProcessName -eq 'mqttug-broker') {
        $listening = netstat -ano | Select-String ":1886 .*LISTENING\s+$($old.Id)$"
        if ($listening) { Stop-Process -Id $old.Id -Confirm:$false; "stopped broker $($old.Id)" }
    }
}
if ($Stop) { return }
$exe = "$env:USERPROFILE\projects\esp32-gateway-platform\tmp\hq-mqtt-stack\bin\mqttug-broker.exe"
$brokerArgs = @(
    "--config", "$bench\mqttug.toml",
    "--bind", "0.0.0.0:1886",
    "--bind", "0.0.0.0:8886,tls_cert=$tls\trusted.chain.pem,tls_key=$tls\trusted.key",
    "--bind", "0.0.0.0:8887,tls_cert=$tls\server.pem,tls_key=$tls\server.key",
    "--bind", "0.0.0.0:8888,tls_cert=$tls\wronghost.chain.pem,tls_key=$tls\wronghost.key",
    "--bind", "0.0.0.0:8889,tls_cert=$tls\wildcard.chain.pem,tls_key=$tls\wildcard.key",
    "--bind", "0.0.0.0:8890,tls_cert=$tls\cnonly.chain.pem,tls_key=$tls\cnonly.key",
    "--bind", "0.0.0.0:8891,tls_cert=$tls\ipdns.chain.pem,tls_key=$tls\ipdns.key")
# Let's Encrypt-shaped RSA hierarchies from make_lechain_certs.sh, when made
if (Test-Path "$tls\le\chain_a.pem") {
    $brokerArgs += @("--bind", "0.0.0.0:8892,tls_cert=$tls\le\chain_a.pem,tls_key=$tls\le\leafa.key",
                     "--bind", "0.0.0.0:8893,tls_cert=$tls\le\chain_b.pem,tls_key=$tls\le\leafb.key")
}
if (Test-Path "$tls\le\chain_c.pem") {
    $brokerArgs += @("--bind", "0.0.0.0:8894,tls_cert=$tls\le\chain_c.pem,tls_key=$tls\le\leafc.key")
}
$p = Start-Process -FilePath $exe -ArgumentList $brokerArgs -WorkingDirectory $bench -WindowStyle Hidden `
    -RedirectStandardOutput "$bench\broker.out.log" -RedirectStandardError "$bench\broker.err.log" -PassThru
Set-Content $pidFile $p.Id
Start-Sleep 2
if ($p.HasExited) { Get-Content "$bench\broker.err.log" -Tail 10; throw "broker exited" }
"broker $($p.Id) listening:"
netstat -ano | Select-String "LISTENING\s+$($p.Id)$" | ForEach-Object { $_.Line.Trim() }
