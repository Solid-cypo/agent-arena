# Sync local commits to VPS via git bundle, then optionally push GitHub from VPS.
# Usage:
#   .\scripts\sync_to_vps.ps1
#   .\scripts\sync_to_vps.ps1 -PushOrigin
#   .\scripts\sync_to_vps.ps1 -RemoteCmd "pytest tests/test_starmie_pilot.py -q"
#
# Prerequisite: commit (or stash) locally first. Uncommitted work is NOT sent.

[CmdletBinding()]
param(
  [switch]$PushOrigin,
  [string]$RemoteCmd = "",
  [string]$VpsHost = "kag-vps",
  [string]$VpsRepo = "/root/agent-arena"
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

function Invoke-Git {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArgs)
  # git writes progress to stderr; do not treat that as a terminating error
  $prev = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    & git @GitArgs
    return $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $prev
  }
}

$status = git status --porcelain
if ($status) {
  Write-Host "Working tree is dirty. Commit or stash before sync:"
  git status -sb
  exit 1
}

$bundle = Join-Path $env:TEMP ("agent-arena-{0}.bundle" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
$remoteBundle = "/tmp/agent-arena-from-local.bundle"
$applyScriptLocal = Join-Path $PSScriptRoot "vps_apply_bundle.sh"
$applyScriptRemote = "/tmp/vps_apply_bundle.sh"

Invoke-Git fetch vps master 1>$null 2>$null | Out-Null
$baseRef = $null
$ErrorActionPreference = "Continue"
& git rev-parse --verify vps/master 1>$null 2>$null
if ($LASTEXITCODE -eq 0) { $baseRef = "vps/master" }
if (-not $baseRef) {
  & git rev-parse --verify origin/master 1>$null 2>$null
  if ($LASTEXITCODE -eq 0) { $baseRef = "origin/master" }
}
$ErrorActionPreference = "Stop"
if (-not $baseRef) { throw "No base ref (vps/master or origin/master)" }

$aheadOut = & git rev-list --count "${baseRef}..HEAD"
$ahead = [int]$aheadOut
Write-Host "Commits to sync (${baseRef}..HEAD): $ahead"

if ($ahead -eq 0) {
  Write-Host "Nothing new to bundle."
  if ($RemoteCmd) {
    ssh -o BatchMode=yes $VpsHost "cd $VpsRepo && $RemoteCmd"
    if ($LASTEXITCODE -ne 0) { throw "RemoteCmd failed" }
  }
  exit 0
}

Write-Host "Creating bundle: $bundle"
if ((Invoke-Git bundle create $bundle "${baseRef}..HEAD") -ne 0) { throw "git bundle create failed" }

Write-Host "Uploading bundle + apply script..."
scp $bundle "${VpsHost}:${remoteBundle}"
if ($LASTEXITCODE -ne 0) { throw "scp bundle failed" }
scp $applyScriptLocal "${VpsHost}:${applyScriptRemote}"
if ($LASTEXITCODE -ne 0) { throw "scp apply script failed" }

$pushFlag = if ($PushOrigin) { "1" } else { "0" }
# Escape RemoteCmd for single-quoted remote arg: end quote, escaped quote, reopen
$remoteCmdArg = $RemoteCmd.Replace("'", "'\''")

Write-Host "Applying on VPS..."
ssh -o BatchMode=yes $VpsHost "chmod +x $applyScriptRemote && bash $applyScriptRemote '$VpsRepo' '$remoteBundle' '$pushFlag' '$remoteCmdArg'"
if ($LASTEXITCODE -ne 0) { throw "VPS apply failed" }

Invoke-Git fetch vps master | Out-Null
$localTip = (& git rev-parse --short HEAD).Trim()
$vpsTip = (& git rev-parse --short vps/master).Trim()
Write-Host ("Sync OK. Local={0} vps/master={1}" -f $localTip, $vpsTip)
Remove-Item $bundle -Force -ErrorAction SilentlyContinue
