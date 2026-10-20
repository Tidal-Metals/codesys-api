# RTU line speed vs baud rate with the native Modbus_COM master on COM1 (the ModbusFB counterpart is
# run_baud_series.ps1). Builds unmapped native servers once (native_timing_manifest.py: 6 registers, 10 ms cycles,
# the ME31 parked), then for each rate: sets Modbus_COM's baud rate, downloads, re-applies the COM12 simulator at
# that rate and measures (measure_bus.py; the simulator counts each unit's replies). Then one 120-register run at
# the last rate. Results: results/bus/native_baud_<rate>_<registers><Tag>.json. -BusTaskMs sets the bus task (the
# native master's bus cycle task) for every download, -FrameGapMs its TimeBetweenFrames (CODESYS default 10). Ends back on the ModbusFB serial line (Modbus_COM removed,
# ModbusFB build with a 5 ms bus task downloaded, simulator at 9600).
param([int[]]$Bauds = @(9600, 19200, 38400, 57600, 115200), [int]$Seconds = 30, [int]$BusTaskMs = 5,
      [string]$Tag = "", [switch]$SkipLarge, [int]$FrameGapMs = 10)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$bench = "examples\plc_architecture\bench"
$out = "$PSScriptRoot\results\bus"
Set-Location $root
$token = (Get-Content "$root\tmp\arch_bench\reservation.json" -Raw | ConvertFrom-Json).reservation.token

function Measure-Native([int]$baud, [int]$registers) {
    python $bench\bus_sim.py apply --token $token --serial-baud $baud | Out-Null
    python $bench\measure_bus.py --name "native_baud_$($baud)_$registers$Tag" --seconds $Seconds --gateway-period 1000 `
        --out "$out\native_baud_$($baud)_$registers$Tag.json" | Out-Null
    Write-Output "measured $baud baud, $registers registers"
}

function Deploy-Native {
    python $bench\apply_bench.py 2000 --serial native --bus-task-ms $BusTaskMs | Select-String '"success"' | Out-Null
    python $bench\deploy_bench.py | Out-Null
}

python $bench\make_bench_sources.py 2000 tmp\arch_bench\src --serial native | Out-Null
python $bench\add_native_serial.py --com 1 --baud $Bauds[0] --frame-gap-ms $FrameGapMs | Out-Null
$manifest = python $bench\native_timing_manifest.py 6 10
python modbus_device_driver_runner.py $manifest --skip-simulator | Out-Null
foreach ($baud in $Bauds) {
    python $bench\add_native_serial.py --com 1 --baud $baud --frame-gap-ms $FrameGapMs | Out-Null
    Deploy-Native
    Measure-Native $baud 6
}
if (-not $SkipLarge) {
    $last = $Bauds[-1]
    $manifest = python $bench\native_timing_manifest.py 120 10
    python $bench\add_native_serial.py --com 1 --baud $last --frame-gap-ms $FrameGapMs | Out-Null
    python modbus_device_driver_runner.py $manifest --skip-simulator | Out-Null
    Deploy-Native
    Measure-Native $last 120
}

python $bench\add_native_serial.py --remove | Out-Null
python $bench\apply_bench.py 2000 | Out-Null
python $bench\deploy_bench.py | Out-Null
python $bench\bus_sim.py apply --token $token | Out-Null
Write-Output "restored ModbusFB serial line"
