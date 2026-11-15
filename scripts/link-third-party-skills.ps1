# link-third-party-skills.ps1 — link third-party skill folders into this repo's skills\.
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path $PSScriptRoot -Parent
$thirdParty = Join-Path $repoRoot 'third_party'
$destRoot = Join-Path $repoRoot 'skills'

if (-not (Test-Path -LiteralPath $destRoot)) {
    New-Item -ItemType Directory -Force -Path $destRoot | Out-Null
    Write-Host "Created: $destRoot"
}

if (-not (Test-Path -LiteralPath $thirdParty)) {
    Write-Host "No third_party directory found - nothing to link."
    exit 0
}

$thirdPartyFull = (Resolve-Path -LiteralPath $thirdParty).Path.TrimEnd('\')
$seen = @{}
$linked = 0
$skipped = 0

function Get-LinkTargetFull {
    param([string]$Path)
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if (-not $item) { return $null }
    if ($item.LinkType -ne 'Junction' -and $item.LinkType -ne 'SymbolicLink') { return $null }
    $target = if ($item.Target -is [string]) { $item.Target } else { $item.Target[0] }
    try {
        return (Resolve-Path -LiteralPath $target).Path
    } catch {
        return $null
    }
}

function Test-ManagedThirdPartySkillLink {
    param(
        [string]$Path,
        [string]$ThirdPartyFull
    )
    $target = Get-LinkTargetFull -Path $Path
    if (-not $target) { return $false }
    if (-not $target.StartsWith($ThirdPartyFull + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        return $false
    }
    return (Test-Path -LiteralPath (Join-Path $target 'SKILL.md'))
}

function Remove-LinkDirectory {
    param([string]$Path)
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSIsContainer) {
        cmd.exe /c "rmdir `"$Path`"" | Out-Null
    } else {
        Remove-Item -LiteralPath $Path -Force
    }
}

function New-SkillDirectoryLink {
    param(
        [string]$LinkPath,
        [string]$TargetPath
    )
    try {
        New-Item -ItemType Junction -Path $LinkPath -Target $TargetPath -Force | Out-Null
        return 'junction'
    } catch {
        New-Item -ItemType SymbolicLink -Path $LinkPath -Target $TargetPath -Force | Out-Null
        return 'symlink'
    }
}

function Add-ThirdPartySkill {
    param([System.IO.DirectoryInfo]$Skill)

        $skillMd = Join-Path $skill.FullName 'SKILL.md'
        if (-not (Test-Path -LiteralPath $skillMd)) { return }

        $name = $skill.Name
        $srcFull = (Resolve-Path -LiteralPath $skill.FullName).Path
        $dest = Join-Path $destRoot $name

        if ($seen.ContainsKey($name)) {
            Write-Host "WARN: duplicate third-party skill name '$name'; keeping the first match."
            $script:skipped += 1
            return
        }
        $seen[$name] = $true

        if (Test-Path -LiteralPath $dest) {
            $item = Get-Item -LiteralPath $dest -Force
            if ($item.LinkType -eq 'Junction' -or $item.LinkType -eq 'SymbolicLink') {
                $current = Get-LinkTargetFull -Path $dest
                if ($current -and $current -ieq $srcFull) {
                    Write-Host "OK (unchanged): skills/$name"
                    $script:linked += 1
                    return
                }
                if (Test-ManagedThirdPartySkillLink -Path $dest -ThirdPartyFull $thirdPartyFull) {
                    Remove-LinkDirectory -Path $dest
                    Write-Host "Refreshed managed link: skills/$name"
                } else {
                    Write-Host "WARN: refusing to overwrite non-managed link: skills/$name"
                    $script:skipped += 1
                    return
                }
            } else {
                Write-Host "WARN: refusing to overwrite local skill or file: skills/$name"
                $script:skipped += 1
                return
            }
        }

        $kind = New-SkillDirectoryLink -LinkPath $dest -TargetPath $srcFull
        Write-Host "Linked: skills/$name ($kind)"
        $script:linked += 1
}

foreach ($pack in (Get-ChildItem -LiteralPath $thirdParty -Directory | Sort-Object Name)) {
    foreach ($candidateRoot in @(
        (Join-Path $pack.FullName 'skills'),
        (Join-Path $pack.FullName '.agents\skills'),
        $pack.FullName
    )) {
        if (-not (Test-Path -LiteralPath $candidateRoot)) { continue }
        foreach ($skill in (Get-ChildItem -LiteralPath $candidateRoot -Directory | Sort-Object Name)) {
            Add-ThirdPartySkill -Skill $skill
        }
    }
}

if ($linked -eq 0 -and $skipped -eq 0) {
    Write-Host "No third-party skills found under supported third_party layouts."
}
