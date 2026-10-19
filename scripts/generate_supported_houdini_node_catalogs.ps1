param(
    [switch]$Check
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Generator = Join-Path $PSScriptRoot 'generate_houdini_node_catalog.py'
$Versions = @('20.0.688', '20.5.684', '21.0.596')

foreach ($Version in $Versions) {
    $Hython = "C:/Program Files/Side Effects Software/Houdini $Version/bin/hython.exe"
    if (-not (Test-Path $Hython)) {
        throw "Houdini $Version hython not found: $Hython"
    }

    $Arguments = @($Generator, '--output-dir', (Join-Path $RepoRoot 'Doc/node_catalog'))
    if ($Check) {
        $Arguments += '--check'
    }
    & $Hython @Arguments
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}