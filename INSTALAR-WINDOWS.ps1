[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

if ($PSVersionTable.PSVersion.Major -lt 5) {
    throw 'Se necesita Windows PowerShell 5.1 o PowerShell 7 o posterior.'
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host 'Instalando uv para el usuario actual...'
    irm https://astral.sh/uv/install.ps1 | iex
}

# uv actualiza el PATH para las terminales nuevas. Incluirlo aqui permite
# continuar en esta misma ventana despues de instalar uv.
$uvBin = Join-Path $env:USERPROFILE '.local\bin'
if (Test-Path $uvBin) {
    $env:Path = "$uvBin;$env:Path"
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    throw 'No se encontro uv. Cierra PowerShell, abrelo de nuevo y ejecuta este archivo otra vez.'
}

if (-not (Test-Path (Join-Path $PSScriptRoot 'pyproject.toml'))) {
    throw 'Este instalador debe ejecutarse desde la raiz del repositorio clonado.'
}

Write-Host 'Preparando Moodle MCP desde el repositorio clonado...'
Write-Host 'El comando mcp-moodle quedara en el PATH y se abrira el asistente.'
& $uv.Source --directory $PSScriptRoot run python scripts/install_linux.py --family windows
if ($LASTEXITCODE -ne 0) {
    throw 'No se pudo instalar Moodle MCP. Revisa el mensaje anterior e intentalo de nuevo.'
}
