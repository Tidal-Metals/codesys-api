# RTU line speed vs baud rate, ModbusFB serial line (line 2) of the running bench application.
# For each rate: the COM12 simulator is re-applied at that rate, the PLC line is switched online (sweep_block_size.py
# --baud), the real ME31 (unit 1, fixed at 9600) is parked, and every simulated unit is read at each block size.
# Results: results/bus/baud_fb_<rate><Tag>.json (e.g. -Tag _bus2ms after a download with apply_bench.py
# --bus-task-ms 2). Ends with the simulator back at 9600 (the PLC line restores itself).
param([int[]]$Bauds = @(9600, 19200, 38400, 57600, 115200), [string]$Counts = "6,30,120", [int]$Seconds = 30,
      [string]$Tag = "")
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$out = "$PSScriptRoot\results\bus"
Set-Location $root
$token = (Get-Content "$root\tmp\arch_bench\reservation.json" -Raw | ConvertFrom-Json).reservation.token
foreach ($baud in $Bauds) {
    python examples\plc_architecture\bench\bus_sim.py apply --token $token --serial-baud $baud | Out-Null
    Write-Output "baud $baud"
    python examples\plc_architecture\bench\sweep_block_size.py --line 2 --baud $baud --park-units 1 --counts $Counts `
        --seconds $Seconds --out "$out\baud_fb_$baud$Tag.json"
}
python examples\plc_architecture\bench\bus_sim.py apply --token $token | Out-Null
