# List the public interfaces and methods of the CODESYS 4 service assemblies, to map the JSON-RPC
# surface the browser UI talks to. Read-only: loads assemblies for metadata only.
# Usage: pwsh -File list_rpc_surface.ps1 [-Filter Online] > out.txt
param([string]$Filter = '', [string]$C4Dir = 'C:\Program Files\CODESYS-4')

$dlls = Get-ChildItem $C4Dir -Recurse -Filter 'CODESYS.C4.*.dll' |
    Where-Object { $_.FullName -notmatch '\\(de|en)\\' } | Sort-Object FullName -Unique
[AppDomain]::CurrentDomain.add_AssemblyResolve({
    param($s, $e)
    $name = (New-Object Reflection.AssemblyName $e.Name).Name
    $hit = Get-ChildItem $C4Dir -Recurse -Filter "$name.dll" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($hit) { [Reflection.Assembly]::LoadFrom($hit.FullName) } else { $null }
})
foreach ($dll in $dlls) {
    try { $asm = [Reflection.Assembly]::LoadFrom($dll.FullName) } catch { continue }
    try { $types = $asm.GetTypes() } catch [Reflection.ReflectionTypeLoadException] { $types = $_.Exception.Types | Where-Object { $_ } }
    foreach ($t in $types | Where-Object { $_.IsPublic -and $_.IsInterface -and $_.FullName -match $Filter }) {
        "== $($t.FullName)  [$($dll.Name)]"
        try {
            foreach ($m in $t.GetMethods()) {
                $ps = ($m.GetParameters() | ForEach-Object { "$($_.ParameterType.Name) $($_.Name)" }) -join ', '
                "    $($m.ReturnType.Name) $($m.Name)($ps)"
            }
        } catch { "    <methods unavailable: $($_.Exception.Message)>" }
    }
}
