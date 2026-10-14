# Instala tarefa local do ArayFlow. NAO liga publicacao por conta propria.
# Antes de executar, configure ARAYFLOW_AUTOPUBLISH_ENABLED=true no .env.
# Precisa de sessao Windows logada para utilizar credenciais OAuth Desktop.
[CmdletBinding()]
param([switch]$Remove)

$ErrorActionPreference = 'Stop'
$TaskName = 'ArayFlow Publisher'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Worker = Join-Path $Root 'scheduled_publish.py'

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
    Write-Host 'Tarefa ArayFlow Publisher removida.'
    exit 0
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python do ambiente .venv nao encontrado: $Python"
}
if (-not (Test-Path -LiteralPath $Worker)) {
    throw "Script agendado nao encontrado: $Worker"
}
$Identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$Action = New-ScheduledTaskAction -Execute $Python -Argument ('"{0}" --once --live' -f $Worker) -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$Principal = New-ScheduledTaskPrincipal -UserId $Identity -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description 'ArayFlow: verifica posts aprovados a cada 5 minutos; prepara e publica na Meta no horario do Sheets' -Force | Out-Null

Write-Host "Tarefa instalada: $TaskName"
Write-Host 'Executa a cada 5 minutos por ate 3650 dias, somente com este usuario logado.'
Write-Host 'O agendador somente publica se ARAYFLOW_AUTOPUBLISH_ENABLED=true no .env.'
Write-Host 'Para interromper: Disable-ScheduledTask -TaskName "ArayFlow Publisher"'
Write-Host 'Para remover: .\install_scheduler.ps1 -Remove'
