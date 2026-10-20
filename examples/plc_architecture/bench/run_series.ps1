# Two-task bench series: control task timing while the comms task publishes all 2,000 tags every second.
# Each run measures on the PLC (measure_bench.py) while verify_arch.py checks every message on the broker.
param([int]$Seconds = 60)
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$out = "$PSScriptRoot\results"
New-Item -ItemType Directory -Force $out | Out-Null
$runs = @(
    @{ name = "comms_off";          args = @("--comms", "off") },
    @{ name = "calls1_per250";      args = @("--calls", "1", "--tags-per-call", "250") },
    @{ name = "budget5_per250";     args = @("--calls", "16", "--budget-us", "5000", "--tags-per-call", "250") },
    @{ name = "budget10_per250";    args = @("--calls", "16", "--budget-us", "10000", "--tags-per-call", "250") },
    @{ name = "budget10_per2000";   args = @("--calls", "16", "--budget-us", "10000", "--tags-per-call", "2000") },
    @{ name = "budget40_per2000";   args = @("--calls", "32", "--budget-us", "40000", "--tags-per-call", "2000") }
)
Set-Location $root
foreach ($run in $runs) {
    $verify = Start-Process -FilePath python -ArgumentList @("examples\plc_architecture\bench\verify_arch.py", "--seconds", ($Seconds + 10), "--out", "$out\verify_$($run.name).json") -PassThru -WindowStyle Hidden
    python examples\plc_architecture\bench\measure_bench.py --seconds $Seconds --settle 6 @($run.args) --out "$out\$($run.name).json" | Out-Null
    $verify.WaitForExit(120000) | Out-Null
    $m = Get-Content "$out\$($run.name).json" -Raw | ConvertFrom-Json
    $v = Get-Content "$out\verify_$($run.name).json" -Raw | ConvertFrom-Json
    "{0}: control interval {1}-{2} us, max dev {3} us, dev bands {4}/{5}/{6}/{7}/{8}/{9}, exec mean {10} max {11} | comms exec max {12}, publish {13} us, calls {14} | broker {15}/{16} complete, {17} B" -f `
        $run.name, $m.'control.MinIntervalUs', $m.'control.MaxIntervalUs', $m.'control.MaxDeviationUs', `
        $m.'control.Deviation[0]', $m.'control.Deviation[1]', $m.'control.Deviation[2]', $m.'control.Deviation[3]', $m.'control.Deviation[4]', $m.'control.Deviation[5]', `
        $m.'control.MeanExecUs', $m.'control.MaxExecUs', $m.'comms.MaxExecUs', $m.'comms.LastPublishUs', $m.'comms.MaxClientCalls', `
        $v.complete, $v.messages, $v.bytesMax
}
