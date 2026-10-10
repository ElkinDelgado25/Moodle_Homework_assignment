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

# uv actualiza el PATH para las terminales nuevas. Incluirlo aquÃ­ permite
# continuar en esta misma ventana despuÃ©s de instalar uv.
$uvBin = Join-Path $env:USERPROFILE '.local\bin'
if (Test-Path $uvBin) {
    $env:Path = "$uvBin;$env:Path"
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    throw 'No se encontrÃ³ uv. Cierra PowerShell, Ã¡brelo de nuevo y ejecuta este archivo otra vez.'
}

if (-not (Test-Path (Join-Path $PSScriptRoot 'pyproject.toml'))) {
    throw 'Este instalador debe ejecutarse desde la raÃ­z del repositorio clonado.'
}

Write-Host 'Preparando Moodle MCP desde el repositorio clonado...'
Write-Host 'Se instalarÃ¡n las dependencias y se abrirÃ¡ el asistente de configuraciÃ³n.'
& $uv.Source --directory $PSScriptRoot run mcp-moodle setup
if ($LASTEXITCODE -ne 0) {
    throw 'uv no pudo preparar Moodle MCP. Revisa el mensaje anterior e intÃ©ntalo de nuevo.'
}
