# link-symbolic-folders.ps1 — junctions/symlink from profile into this repo (run once per machine; re-run after moving the repo).
#   %USERPROFILE%\.claude\skills       -> <repo>\skills
#   %USERPROFILE%\.claude\context      -> <repo>\context (AGENTS.md, CLAUDE.md; optional PRD.md, TECHSPEC.md)
#   %USERPROFILE%\.claude\hooks        -> <repo>\hooks   (Claude Code stop/notification hooks)
#   %USERPROFILE%\.cursor\skills      -> <repo>\skills
#   %USERPROFILE%\.cursor\context     -> <repo>\context  (AGENTS.md, CLAUDE.md; optional PRD.md, TECHSPEC.md)
#   %USERPROFILE%\.cursor\rules       -> <repo>\cursor-rules\shared
#   %USERPROFILE%\.cursor\commands   -> <repo>\cursor-commands  (Cursor / slash commands, .md)
#   %USERPROFILE%\.claude\CLAUDE.md   -> file symlink -> <repo>\context\CLAUDE.md  (Claude Code)
#   <repo>\AGENTS.md                 -> file symlink -> <repo>\context\AGENTS.md  (the repo loads its own canon; gitignored)
# Also removes legacy junctions: .cursor\global-docs, .cursor\global-rules (old names).
# Then registers the hooks of hooks\ in %USERPROFILE%\.claude\settings.json through scripts\register-claude-hooks.py
# and for Codex in %USERPROFILE%\.codex\hooks.json, trusted, through scripts\register-codex-hooks.py,
# and links each skill into %USERPROFILE%\.agents\skills for Codex through scripts\link-codex-skills.py.
# Directories: mklink /J. CLAUDE.md: file symlink (may need Developer Mode or admin if cross-volume).
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$repoSkills = Join-Path $repoRoot 'skills'
$repoContext = Join-Path $repoRoot 'context'
$repoHooks = Join-Path $repoRoot 'hooks'
$repoCursorRulesShared = Join-Path $repoRoot 'cursor-rules\shared'
$repoCursorCommands = Join-Path $repoRoot 'cursor-commands'
$userProfile = [Environment]::GetFolderPath('UserProfile')
$claudeDir = Join-Path $userProfile '.claude'
$claudeSkills = Join-Path $claudeDir 'skills'
$claudeContext = Join-Path $claudeDir 'context'
$cursorDir = Join-Path $userProfile '.cursor'
$cursorSkills = Join-Path $cursorDir 'skills'
$cursorContext = Join-Path $cursorDir 'context'
$cursorRules = Join-Path $cursorDir 'rules'
$cursorCommands = Join-Path $cursorDir 'commands'

foreach ($dir in @($repoSkills, $repoContext, $repoHooks, (Split-Path $repoCursorRulesShared -Parent), $repoCursorRulesShared, $repoCursorCommands)) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        Write-Host "Created: $dir"
    }
}

$agents = Join-Path $repoContext 'AGENTS.md'
$claudeMdRepo = Join-Path $repoContext 'CLAUDE.md'
foreach ($f in @($agents, $claudeMdRepo)) {
    if (-not (Test-Path $f)) {
        Set-Content -LiteralPath $f -Encoding utf8 -Value "# $(Split-Path $f -Leaf)`n`n"
        Write-Host "Created: $f"
    }
}

if (-not (Test-Path $claudeDir)) {
    New-Item -ItemType Directory -Force -Path $claudeDir | Out-Null
    Write-Host "Created: $claudeDir"
}
if (-not (Test-Path $cursorDir)) {
    New-Item -ItemType Directory -Force -Path $cursorDir | Out-Null
    Write-Host "Created: $cursorDir"
}

function Ensure-Link {
    param(
        [string]$LinkPath,
        [string]$TargetPath
    )

    if (Test-Path $LinkPath) {
        $item = Get-Item -LiteralPath $LinkPath -Force
        if ($item.LinkType -eq 'Junction' -or $item.LinkType -eq 'SymbolicLink') {
            $t = if ($item.Target -is [string]) { $item.Target } else { $item.Target[0] }
            if ((Resolve-Path $TargetPath).Path -eq (Resolve-Path $t).Path) {
                Write-Host "Already linked: $LinkPath -> $TargetPath"
                return
            }
        }
        $bakName = "$(Split-Path $LinkPath -Leaf).bak_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
        Rename-Item -LiteralPath $LinkPath -NewName $bakName
        Write-Host "Renamed existing folder to: $(Join-Path (Split-Path $LinkPath -Parent) $bakName)"
    }

    $arg = "mklink /J `"$LinkPath`" `"$TargetPath`""
    $exit = (Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', $arg) -Wait -PassThru -NoNewWindow).ExitCode
    if ($exit -ne 0) { throw "mklink /J failed with exit $exit" }
    Write-Host "OK (junction): $LinkPath <<===>> $TargetPath"
}

function Ensure-FileSymlink {
    param(
        [string]$LinkPath,
        [string]$TargetPath
    )
    if (-not (Test-Path -LiteralPath $TargetPath)) {
        throw "Target file missing: $TargetPath"
    }
    $targetFull = (Resolve-Path -LiteralPath $TargetPath).Path

    if (Test-Path -LiteralPath $LinkPath) {
        $item = Get-Item -LiteralPath $LinkPath -Force
        if ($item.LinkType -eq 'SymbolicLink') {
            $t = if ($item.Target -is [string]) { $item.Target } else { $item.Target[0] }
            if ((Resolve-Path -LiteralPath $t).Path -eq $targetFull) {
                Write-Host "Already linked: $LinkPath -> $targetFull"
                return
            }
        }
        $bakName = "$(Split-Path $LinkPath -Leaf).bak_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
        Rename-Item -LiteralPath $LinkPath -NewName $bakName
        Write-Host "Renamed existing file to: $(Join-Path (Split-Path $LinkPath -Parent) $bakName)"
    }

    $ok = $false
    try {
        New-Item -ItemType SymbolicLink -Path $LinkPath -Target $targetFull -Force | Out-Null
        $ok = $true
        Write-Host "OK (file symlink): $LinkPath -> $targetFull"
    } catch {
        $arg = "mklink `"$LinkPath`" `"$targetFull`""
        $exit = (Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', $arg) -Wait -PassThru -NoNewWindow).ExitCode
        if ($exit -eq 0) {
            $ok = $true
            Write-Host "OK (file symlink via cmd): $LinkPath -> $targetFull"
        }
    }
    if (-not $ok) {
        Write-Host "WARN: file symlink failed (try Windows Developer Mode or run PowerShell as Administrator). Target to edit: $targetFull"
    }
}

Ensure-Link -LinkPath $claudeSkills -TargetPath $repoSkills
Ensure-Link -LinkPath $claudeContext -TargetPath $repoContext
Ensure-Link -LinkPath (Join-Path $claudeDir 'hooks') -TargetPath $repoHooks
Ensure-Link -LinkPath $cursorSkills -TargetPath $repoSkills
Ensure-Link -LinkPath $cursorContext -TargetPath $repoContext
Ensure-Link -LinkPath $cursorRules -TargetPath $repoCursorRulesShared
Ensure-Link -LinkPath $cursorCommands -TargetPath $repoCursorCommands

foreach ($legacy in @('global-docs', 'global-rules')) {
    $p = Join-Path $cursorDir $legacy
    if (-not (Test-Path -LiteralPath $p)) { continue }
    $item = Get-Item -LiteralPath $p -Force
    if ($item.LinkType -eq 'Junction' -or $item.LinkType -eq 'SymbolicLink') {
        cmd.exe /c "rmdir `"$p`""
        Write-Host "Removed legacy junction: $p"
    }
}

$legacyClaudeAgents = Join-Path $claudeDir 'AGENTS.md'
if (Test-Path -LiteralPath $legacyClaudeAgents) {
    $item = Get-Item -LiteralPath $legacyClaudeAgents -Force
    if ($item.LinkType -eq 'SymbolicLink') {
        Remove-Item -LiteralPath $legacyClaudeAgents -Force
        Write-Host "Removed legacy symlink: $legacyClaudeAgents"
    }
}

$claudeMdUser = Join-Path $claudeDir 'CLAUDE.md'
Ensure-FileSymlink -LinkPath $claudeMdUser -TargetPath $claudeMdRepo

# the repo-root AGENTS.md is a file symlink to context\AGENTS.md, so this
# repository loads its own canon like any consumer. It stays in .gitignore. A regular
# file left from the old hardlink is removed when it matches the canon; a diverged one
# is renamed to a backup by Ensure-FileSymlink.
$rootAgents = Join-Path $repoRoot 'AGENTS.md'
if (Test-Path -LiteralPath $rootAgents) {
    $rootItem = Get-Item -LiteralPath $rootAgents -Force
    if (-not $rootItem.LinkType) {
        $same = (Get-FileHash -LiteralPath $rootAgents).Hash -eq (Get-FileHash -LiteralPath $agents).Hash
        if ($same) {
            Remove-Item -LiteralPath $rootAgents -Force
            Write-Host "Removed old copy of the canon: $rootAgents"
        }
    }
}
Ensure-FileSymlink -LinkPath $rootAgents -TargetPath $agents

$localBin = Join-Path $env:USERPROFILE '.local\bin'
New-Item -ItemType Directory -Force -Path $localBin | Out-Null
$aiTaskCmd = Join-Path $localBin 'ai-task.cmd'
$ps1Entry = Join-Path $repoRoot 'scripts\ai-task.ps1'
$cmdBody = "@echo off`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"$ps1Entry`" %*"
Set-Content -LiteralPath $aiTaskCmd -Value $cmdBody -Encoding ASCII
Write-Host "OK: $aiTaskCmd -> scripts\ai-task.ps1"
$pathParts = $env:Path -split ';' | Where-Object { $_ -ne '' }
if ($pathParts -notcontains $localBin) {
    Write-Host "ai-task CLI: add to user PATH if needed: $localBin"
} else {
    Write-Host "ai-task CLI: $localBin is already on PATH (run: ai-task --help)"
}

# Link health check: warn about dangling symlinks/junctions under skills\. Targets
# differ by origin, so group by category and print the correct fix per group:
#   - third_party\* (uninitialized submodules) -> run sync-third-party-skills.sh
#   - ~/.agents/skills\* (corporate, pre-tooling) -> re-link with absolute target
#   - anything else -> generic re-link hint
$brokenLinks = Get-ChildItem -LiteralPath $repoSkills -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.LinkType -and -not (Test-Path -LiteralPath $_.FullName) }
if ($brokenLinks) {
    $thirdParty = @(); $corporate = @(); $other = @()
    $agentsSkills = Join-Path (Join-Path $env:USERPROFILE '.agents') 'skills'
    foreach ($b in $brokenLinks) {
        $t = if ($b.Target -is [string]) { $b.Target } else { $b.Target[0] }
        # Resolve a relative target against the link's own directory.
        if ([System.IO.Path]::IsPathRooted($t)) { $resolved = $t }
        else { $resolved = Join-Path (Split-Path -Parent $b.FullName) $t }
        $line = "  $($b.FullName) -> $t"
        if ($resolved -like '*\third_party\*' -or $resolved -like '*/third_party/*') {
            $thirdParty += $line
        } elseif ($resolved -like "$agentsSkills*") {
            $corporate += $line
        } else {
            $other += $line
        }
    }
    Write-Host ""
    Write-Host "WARNING: dangling symlinks in $repoSkills (these skills will NOT load):"
    if ($thirdParty) {
        $thirdParty | ForEach-Object { Write-Host $_ }
        Write-Host "  Fix: run ./scripts/sync-third-party-skills.sh [--install-tools] (or the .ps1 equivalent)"
    }
    if ($corporate) {
        $corporate | ForEach-Object { Write-Host $_ }
        Write-Host "  Fix with absolute targets, e.g.: New-Item -ItemType SymbolicLink -Path <repo>\skills\<name> -Target `$env:USERPROFILE\.agents\skills\<name>"
    }
    if ($other) {
        $other | ForEach-Object { Write-Host $_ }
        Write-Host "  Fix: re-create each link pointing at its real target."
    }
}

# register the hooks of ~/.claude/hooks in ~/.claude/settings.json.
# The registrar merges into the user's own entries and changes nothing on a
# second run; scripts/register-claude-hooks.py says which hook gets which
# onFailure and why. A failure here warns and leaves the file as it was.
$registrar = Join-Path $repoRoot 'scripts\register-claude-hooks.py'
$pyCmd = $null
foreach ($candidate in @('python3', 'python')) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($found -and $found.Source -notlike '*\WindowsApps\*') { $pyCmd = $candidate; break }
}
if ($pyCmd) {
    & $pyCmd $registrar --python $pyCmd
    if ($LASTEXITCODE -ne 0) {
        Write-Host "WARNING: Claude Code hooks are not registered; fix $claudeDir\settings.json and run this script again"
    }
    # the same step registers two of these hooks for Codex in
    # ~/.codex/hooks.json and has Codex trust them.
    & $pyCmd (Join-Path $repoRoot 'scripts\register-codex-hooks.py') --python $pyCmd
    if ($LASTEXITCODE -ne 0) {
        Write-Host "WARNING: Codex hooks are not registered or not trusted; see the message above and run this script again"
    }
} else {
    Write-Host "WARNING: python not found; Claude Code and Codex hooks are not registered (see SETUP.md, Claude Code hooks)"
}

# Codex reads user skills from ~/.agents/skills, a folder other tools
# fill too, so each skill of this clone gets its own link there. The script
# removes only links it made (by target) and leaves every other entry alone;
# scripts\link-codex-skills.py says how.
$codexLinker = Join-Path $repoRoot 'scripts\link-codex-skills.py'
if ($pyCmd) {
    & $pyCmd $codexLinker
    if ($LASTEXITCODE -ne 0) {
        Write-Host "WARNING: Codex skills are not linked; see the message above and run this script again"
    }
} else {
    Write-Host "WARNING: python not found; Codex skills are not linked (see SETUP.md, Codex)"
}

Write-Host ""
Write-Host "Cursor: slash commands (e.g. /make-prd) load from $cursorCommands in every workspace."
Write-Host "Project AGENTS.md: see SETUP_NEW_PROJECT.md and scripts/propagate-agents.sh (not run from this script)."
