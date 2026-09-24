# Test and build rtu-sim.exe into codesys-api\build\ (Git-ignored).
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    go vet ./...
    if ($LASTEXITCODE -ne 0) { throw 'go vet failed' }
    go test ./...
    if ($LASTEXITCODE -ne 0) { throw 'go test failed' }
    $output = Join-Path $PSScriptRoot '..\..\build\rtu-sim.exe'
    go build -trimpath -o $output ./cmd/rtu-sim
    if ($LASTEXITCODE -ne 0) { throw 'go build failed' }
    Write-Host "Built $((Resolve-Path $output).Path)"
}
finally {
    Pop-Location
}
