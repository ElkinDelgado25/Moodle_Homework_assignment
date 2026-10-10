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

# uv actualiza el PATH para terminales futuras. Añadirlo aquí permite seguir en
# esta misma ventana de PowerShell después de instalar uv.
$uvBin = Join-Path $env:USERPROFILE '.local\bin'
if (Test-Path $uvBin) {
    $env:Path = "$uvBin;$env:Path"
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    throw 'No se encontró uv después de instalarlo. Cierra PowerShell, ábrelo de nuevo y ejecuta este archivo otra vez.'
}

$wheel = Get-ChildItem -Path $PSScriptRoot -Filter 'moodle_homework_assignment-*-py3-none-any.whl' -File |
    Sort-Object Name -Descending |
    Select-Object -First 1
if (-not $wheel) {
    throw 'No se encontró el archivo moodle_homework_assignment-*-py3-none-any.whl junto a este instalador.'
}

Write-Host "Instalando $($wheel.Name)..."
& $uv.Source tool install --reinstall --python 3.11 $wheel.FullName
if ($LASTEXITCODE -ne 0) {
    throw 'uv no pudo instalar Moodle MCP.'
}

$toolBin = & $uv.Source tool dir --bin
if ($LASTEXITCODE -ne 0 -or -not $toolBin) {
    throw 'No se pudo localizar el directorio de herramientas de uv.'
}
$command = Join-Path $toolBin.Trim() 'mcp-moodle.exe'
if (-not (Test-Path $command)) {
    throw "No se encontró mcp-moodle.exe en $toolBin."
}

Write-Host 'Moodle MCP quedó instalado correctamente.' -ForegroundColor Green
Write-Host 'Abriendo el asistente para preparar Chromium y conectar tu agente...'
& $command run
