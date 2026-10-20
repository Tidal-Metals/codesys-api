# Set the FTDI latency timer of USB-RS485 adapters, by USB serial (COM numbers re-enumerate). Needs admin:
#   Start-Process pwsh -Verb RunAs -ArgumentList '-File', '<this file>', '-Serials', 'BG00XX03A,BG041BD0A'
# The FTDI default of 16 ms holds every short frame (a Modbus request or reply) in the adapter until the timer
# expires, so a simulated device seems ~16 ms slow; 1 ms makes the bench answer like a real device. The
# device is restarted so the driver reads the new value: stop the simulator on that port first.
param([string]$Serials = "BG00XX03A,BG041BD0A", [int]$LatencyMs = 1)
foreach ($serial in $Serials.Split(",")) {
    $device = Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match "^FTDIBUS\\VID_0403\+PID_6001\+$($serial.Trim())\\" }
    if (-not $device) { Write-Output "$serial not present"; continue }
    $key = "HKLM:\SYSTEM\CurrentControlSet\Enum\$($device.InstanceId)\Device Parameters"
    Set-ItemProperty -Path $key -Name LatencyTimer -Value $LatencyMs -Type DWord
    pnputil /restart-device "$($device.InstanceId)" | Out-Null
    $value = (Get-ItemProperty -Path $key).LatencyTimer
    Write-Output "$serial $($device.FriendlyName) LatencyTimer=$value"
}
