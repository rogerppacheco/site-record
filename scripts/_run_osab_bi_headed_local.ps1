$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

# Uma janela só: recusa se já houver OUTRO importar_osab_bi_pap / Chromium Playwright
# (ignora este script e a cadeia de processos pai)
$parentIds = @($PID)
try {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$PID" -ErrorAction SilentlyContinue
    while ($p -and $p.ParentProcessId -and $p.ParentProcessId -ne 0) {
        $parentIds += $p.ParentProcessId
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($p.ParentProcessId)" -ErrorAction SilentlyContinue
    }
} catch {}
$dup = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and (
        $_.CommandLine -match 'importar_osab_bi_pap' -or
        $_.CommandLine -match 'ms-playwright\\chromium'
    ) -and ($parentIds -notcontains $_.ProcessId)
}
if ($dup) {
    Write-Host "ABORTADO: ja existe processo OSAB BI / Playwright headed. Encerre antes de rodar de novo:"
    $dup | ForEach-Object { Write-Host ("  pid={0} {1}" -f $_.ProcessId, $_.Name) }
    exit 2
}

$pg = railway variables --service Postgres --json | ConvertFrom-Json
$public = $pg.DATABASE_PUBLIC_URL
if (-not $public) { throw "DATABASE_PUBLIC_URL ausente no serviço Postgres" }

# Injeta vars do site-record e sobrescreve DB para o proxy público
$json = railway variables --service site-record --json | ConvertFrom-Json
foreach ($p in $json.PSObject.Properties) {
    if ($null -ne $p.Value -and "$($p.Value)" -ne "") {
        Set-Item -Path "Env:$($p.Name)" -Value "$($p.Value)"
    }
}
$env:DATABASE_URL = $public
$env:DATABASE_UNPOOLED_URL = $public
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "Iniciando teste headed (UMA janela Chromium). Aprove MFA se pedir."
Write-Host "Matricula: TT713110 | pular-importacao=1"
python manage.py importar_osab_bi_pap --headed --pular-importacao --matricula TT713110
exit $LASTEXITCODE
