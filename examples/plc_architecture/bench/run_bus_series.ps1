# Bus benchmark series on the running bench application. -Mode fb: the ModbusFB adapter on both lines.
# -Mode native: the serial line is the device tree's Modbus_COM master (apply_bench.py 2000 --serial native);
# the gateway line is unchanged. Native poll rates are set by the channel cycle time at download, so its
# saturation run needs a download with --native-cycle-ms 0 first: run it alone with -Runs saturation.
# Each run: measure_bus.py on the PLC while verify_arch.py checks every value at the broker.
param([ValidateSet("fb", "native")][string]$Mode = "fb", [int]$Seconds = 60,
      [string[]]$Runs = @("baseline", "saturation", "dead"))
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$out = "$PSScriptRoot\results\bus"
New-Item -ItemType Directory -Force $out | Out-Null
Set-Location $root
$token = (Get-Content "$root\tmp\arch_bench\reservation.json" -Raw | ConvertFrom-Json).reservation.token
$serial = if ($Mode -eq "fb") { @("--serial-period", "1000", "--fb-serial", "on") } else { @() }
$serialFast = if ($Mode -eq "fb") { @("--serial-period", "0", "--fb-serial", "on") } else { @() }
$plans = @(
    @{ name = "baseline";   silent = "";     args = @("--gateway-period", "1000") + $serial },
    @{ name = "saturation"; silent = "";     args = @("--gateway-period", "0") + $serialFast },
    @{ name = "dead";       silent = "25,5"; args = @("--gateway-period", "1000") + $serial }
)
foreach ($run in $plans | Where-Object { $Runs -contains $_.name }) {
    $name = "$Mode`_$($run.name)"
    python examples\plc_architecture\bench\bus_sim.py apply --token $token --silent "$($run.silent)" | Out-Null
    $verify = Start-Process -FilePath python -ArgumentList @("examples\plc_architecture\bench\verify_arch.py", "--seconds", ($Seconds + 15),
        "--expected", "tmp\arch_bench\src\expected_bus_values.json", "--out", "$out\verify_$name.json") -PassThru -WindowStyle Hidden
    python examples\plc_architecture\bench\measure_bus.py --name $name --seconds $Seconds @($run.args) --out "$out\$name.json"
    $verify.WaitForExit(180000) | Out-Null
}
python examples\plc_architecture\bench\bus_sim.py apply --token $token | Out-Null
