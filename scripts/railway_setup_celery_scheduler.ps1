# Cria/ativa site-record-scheduler + site-record-celery no projeto banco-de-dados.
# Pré-requisito: railway login
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File scripts\railway_setup_celery_scheduler.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

$ProjectId = if ($env:RAILWAY_PROJECT_ID) { $env:RAILWAY_PROJECT_ID } else { "8db60e30-1dde-43f9-afaa-bfc19682fe0b" }
$WebService = if ($env:RAILWAY_WEB_SERVICE) { $env:RAILWAY_WEB_SERVICE } else { "site-record" }
$SchedulerService = if ($env:RAILWAY_SCHEDULER_SERVICE) { $env:RAILWAY_SCHEDULER_SERVICE } else { "site-record-scheduler" }
$CeleryService = if ($env:RAILWAY_CELERY_SERVICE) { $env:RAILWAY_CELERY_SERVICE } else { "site-record-celery" }
$GitHubRepo = "rogerppacheco/site-record"
$Environment = "production"

function Assert-RailwayAuth {
    railway whoami 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Execute: railway login" -ForegroundColor Yellow
        exit 1
    }
}

function Get-ServiceNames {
    $list = railway service list --json 2>$null | ConvertFrom-Json
    if (-not $list) { return @() }
    return @($list | ForEach-Object { $_.name })
}

function Ensure-Service([string]$Name) {
    $names = Get-ServiceNames
    if ($names -contains $Name) {
        Write-Host "Servico '$Name' ja existe." -ForegroundColor Green
        return
    }
    Write-Host "Criando servico '$Name' (repo $GitHubRepo) ..." -ForegroundColor Yellow
    railway add --service $Name --repo $GitHubRepo --branch main --json
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Falha ao criar '$Name'." -ForegroundColor Red
        exit 1
    }
}

function Copy-WebVariables([string]$TargetService) {
    Write-Host "Copiando variaveis $WebService -> $TargetService ..." -ForegroundColor Yellow
    railway link -p $ProjectId -s $WebService -e $Environment | Out-Null
    $kvLines = @(railway variables --kv 2>$null)
    railway link -p $ProjectId -s $TargetService -e $Environment | Out-Null
    $count = 0
    foreach ($line in $kvLines) {
        if (-not $line -or $line -notmatch '=') { continue }
        $key = $line.Split('=', 2)[0]
        if ($key -match '^RAILWAY_') { continue }
        railway variable set $line --service $TargetService --environment $Environment --skip-deploys 2>$null | Out-Null
        $count++
    }
    Write-Host "Variaveis copiadas para $TargetService : $count" -ForegroundColor Green
}

function Set-ServiceBuildDeploy(
    [string]$Service,
    [string]$DockerfilePath,
    [string]$StartCommand
) {
    Write-Host "Configurando build/deploy de '$Service' ..." -ForegroundColor Yellow
    railway environment edit `
        --project $ProjectId `
        --environment $Environment `
        --service-config $Service build.builder DOCKERFILE `
        --message "Set Dockerfile builder for $Service"
    railway environment edit `
        --project $ProjectId `
        --environment $Environment `
        --service-config $Service build.dockerfilePath $DockerfilePath `
        --message "Set dockerfilePath $DockerfilePath for $Service"
    railway environment edit `
        --project $ProjectId `
        --environment $Environment `
        --service-config $Service deploy.startCommand $StartCommand `
        --message "Set startCommand for $Service"
    railway environment edit `
        --project $ProjectId `
        --environment $Environment `
        --service-config $Service deploy.restartPolicyType ON_FAILURE `
        --message "Set restart policy for $Service"
    railway environment edit `
        --project $ProjectId `
        --environment $Environment `
        --service-config $Service deploy.numReplicas 1 `
        --message "Ensure 1 replica for $Service"
}

Write-Host "=== Railway: scheduler + celery (site-record) ===" -ForegroundColor Cyan
Assert-RailwayAuth
railway link -p $ProjectId -e $Environment | Out-Null

Ensure-Service $SchedulerService
Ensure-Service $CeleryService

Copy-WebVariables $SchedulerService
Copy-WebVariables $CeleryService

Set-ServiceBuildDeploy `
    -Service $SchedulerService `
    -DockerfilePath "Dockerfile.scheduler" `
    -StartCommand "python manage.py run_scheduler"

Set-ServiceBuildDeploy `
    -Service $CeleryService `
    -DockerfilePath "Dockerfile.celery" `
    -StartCommand "celery -A core_config worker --concurrency=1 --max-tasks-per-child=15 --loglevel=info"

Write-Host "Habilitando PAP_CELERY_DISPATCH no web (opcional para fila PAP) ..." -ForegroundColor Yellow
railway variable set PAP_CELERY_DISPATCH=True --service $WebService --environment $Environment --skip-deploys

Write-Host "Deploy scheduler ..." -ForegroundColor Yellow
railway up --detach --yes -s $SchedulerService -e $Environment -p $ProjectId
Write-Host "Deploy celery ..." -ForegroundColor Yellow
railway up --detach --yes -s $CeleryService -e $Environment -p $ProjectId

Write-Host ""
Write-Host "Concluido. Verifique com:" -ForegroundColor Green
Write-Host "  railway service list --json"
Write-Host "  railway logs --service $SchedulerService"
Write-Host "  railway logs --service $CeleryService"
Write-Host "  railway ssh --service $CeleryService -- `"ps aux | grep celery`""
