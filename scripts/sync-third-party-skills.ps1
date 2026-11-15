# sync-third-party-skills.ps1 — initialize/update third-party skill packs, then refresh shared skills links.
param(
    [switch]$Remote,
    [switch]$InstallTools
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$gitmodules = Join-Path $repoRoot '.gitmodules'
$config = Join-Path $repoRoot 'third-party-skills.json'
$repoName = Split-Path $repoRoot -Leaf
$toolVenvRoot = if ($env:AI_SDLC_KIT_TOOL_VENV_ROOT) {
    $env:AI_SDLC_KIT_TOOL_VENV_ROOT
} else {
    Join-Path (Join-Path ([Environment]::GetFolderPath('UserProfile')) '.venv') $repoName
}

function Get-ToolPath {
    param(
        [string]$Name,
        [string]$Requires
    )
    $cmd = Get-Command $Requires -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $localUnix = Join-Path $toolVenvRoot "$Name/bin/$Requires"
    if (Test-Path -LiteralPath $localUnix) { return $localUnix }

    $localWin = Join-Path $toolVenvRoot "$Name/Scripts/$Requires.exe"
    if (Test-Path -LiteralPath $localWin) { return $localWin }

    return $null
}

function Install-PythonTool {
    param(
        [string]$Name,
        [string]$PythonPackage
    )
    $venv = Join-Path $toolVenvRoot $Name
    $pythonUnix = Join-Path $venv 'bin/python'
    $pythonWin = Join-Path $venv 'Scripts/python.exe'

    if (-not (Test-Path -LiteralPath $pythonUnix) -and -not (Test-Path -LiteralPath $pythonWin)) {
        python -m venv $venv
    }

    $pythonExe = if (Test-Path -LiteralPath $pythonUnix) { $pythonUnix } else { $pythonWin }
    & $pythonExe -m pip install --upgrade pip
    & $pythonExe -m pip install $PythonPackage
}

if (Test-Path -LiteralPath $config) {
    $data = Get-Content -LiteralPath $config -Raw | ConvertFrom-Json
    foreach ($pack in $data.packs) {
        $path = [string]$pack.path
        $repo = [string]$pack.repo

        if ($path -notlike 'third_party/*') {
            throw "Invalid third-party path: $path"
        }
        if ($repo -notmatch '^(https?://|git@)') {
            throw "Invalid repo URL for ${path}: $repo"
        }

        $target = Join-Path $repoRoot $path
        if (-not (Test-Path -LiteralPath $target)) {
            git -C $repoRoot submodule add $repo $path
        }
    }

    foreach ($installer in $data.installers) {
        $name = [string]$installer.name
        $requires = [string]$installer.requires
        $pythonPackage = [string]$installer.pythonPackage
        $dest = [string]$installer.dest
        $command = @($installer.command)

        if (-not $name) { throw 'Installer missing name' }
        if (-not $requires) { throw "Installer $name missing requires" }
        if ($dest -notlike 'third_party/*') {
            throw "Invalid installer dest for ${name}: $dest"
        }
        if ($command.Count -eq 0) {
            throw "Installer $name missing command"
        }

        $skillMd = Join-Path (Join-Path (Join-Path $repoRoot $dest) $name) 'SKILL.md'
        if (Test-Path -LiteralPath $skillMd) { continue }

        $tool = Get-ToolPath -Name $name -Requires $requires
        if (-not $tool) {
            if ($InstallTools -and $pythonPackage) {
                Install-PythonTool -Name $name -PythonPackage $pythonPackage
            }
        }

        $tool = Get-ToolPath -Name $name -Requires $requires
        if (-not $tool) {
            Write-Warning "Skipping installer '$name'; missing command: $requires"
            continue
        }

        Push-Location $repoRoot
        try {
            if ($command[0] -eq $requires) {
                $command[0] = $tool
            }
            & $command[0] $command[1..($command.Count - 1)]
            if ($LASTEXITCODE -ne 0) {
                throw "Installer $name failed with exit code $LASTEXITCODE"
            }
        } finally {
            Pop-Location
        }
    }
}

if (Test-Path -LiteralPath $gitmodules) {
    if ($Remote) {
        git -C $repoRoot submodule update --init --remote --recursive
    } else {
        git -C $repoRoot submodule update --init --recursive
    }
}

& (Join-Path $PSScriptRoot 'link-third-party-skills.ps1')

# pack skills this sync just filled get their Codex links in
# ~/.agents/skills too, without a second run of the link script.
$pyCmd = $null
foreach ($candidate in @('python3', 'python')) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($found -and $found.Source -notlike '*\WindowsApps\*') { $pyCmd = $candidate; break }
}
if ($pyCmd) {
    & $pyCmd (Join-Path $PSScriptRoot 'link-codex-skills.py')
    if ($LASTEXITCODE -ne 0) {
        Write-Host "WARNING: Codex skills are not linked; run scripts\link-symbolic-folders.ps1"
    }
}
