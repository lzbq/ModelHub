[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$rootPath = (Resolve-Path -LiteralPath $ProjectRoot).Path.TrimEnd('\', '/')
$rootPrefix = $rootPath + [IO.Path]::DirectorySeparatorChar
$components = @('token-java', 'token-agent', 'token-web')

function Assert-Contained([string]$Path) {
    $fullPath = [IO.Path]::GetFullPath($Path)
    if (-not $fullPath.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing a path outside the project: $fullPath"
    }
}

Get-Command git -ErrorAction Stop | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $rootPath '.gitignore') -PathType Leaf)) {
    throw 'The project root must have a .gitignore before initialization.'
}
$ignoreRules = [IO.File]::ReadAllText((Join-Path $rootPath '.gitignore'))
foreach ($requiredRule in @('/.git-backups/', '.env', '.env.*')) {
    if (-not [regex]::IsMatch($ignoreRules, '(?m)^' + [regex]::Escape($requiredRule) + '\s*$')) {
        throw "Missing required root .gitignore rule: $requiredRule"
    }
}
foreach ($component in $components) {
    if (-not (Test-Path -LiteralPath (Join-Path $rootPath $component) -PathType Container)) {
        throw "Missing component directory: $component"
    }
}

$rootMetadata = Join-Path $rootPath '.git'
if (Test-Path -LiteralPath $rootMetadata) {
    $metadataItem = Get-Item -Force -LiteralPath $rootMetadata
    if (-not $metadataItem.PSIsContainer -or
        ($metadataItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        @(Get-ChildItem -Force -LiteralPath $rootMetadata).Count -gt 0) {
        throw 'Root .git is not empty. Inspect the existing repository; this script only prepares a new repository.'
    }
}

$backupRoot = Join-Path $rootPath '.git-backups'
if (Test-Path -LiteralPath $backupRoot) {
    $backupItem = Get-Item -Force -LiteralPath $backupRoot
    if (-not $backupItem.PSIsContainer -or ($backupItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'The backup directory must be a regular directory.'
    }
}
$backupBatch = Join-Path $backupRoot ([Guid]::NewGuid().ToString('N'))
Assert-Contained $backupBatch

$moves = @()
foreach ($component in $components) {
    $componentPath = Join-Path $rootPath $component
    $componentItem = Get-Item -Force -LiteralPath $componentPath
    if ($componentItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Linked component directories are not supported: $component"
    }
    $source = Join-Path $componentPath '.git'
    if (-not (Test-Path -LiteralPath $source)) { continue }
    $sourceItem = Get-Item -Force -LiteralPath $source
    if (-not $sourceItem.PSIsContainer -or ($sourceItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Git worktrees and linked metadata need manual handling: $component"
    }
    $source = (Resolve-Path -LiteralPath $source).Path
    $destination = Join-Path $backupBatch ($component + '.git')
    Assert-Contained $source
    Assert-Contained $destination
    if (Test-Path -LiteralPath $destination) { throw "Backup already exists: $destination" }
    $moves += [pscustomobject]@{ Source = $source; Destination = $destination }
}

Write-Output "Project: $rootPath"
foreach ($move in $moves) {
    Write-Output "Back up Git metadata: $($move.Source) -> $($move.Destination)"
}
Write-Output 'Initialize a new root repository with branch main. Old commits stay in the local backup.'
if (-not $Apply) {
    Write-Output 'Preview only. Run again with -Apply to perform these local changes.'
    return
}

if ($moves.Count -gt 0) {
    New-Item -ItemType Directory -Path $backupBatch | Out-Null
    foreach ($move in $moves) {
        Assert-Contained $move.Source
        Assert-Contained $move.Destination
        Move-Item -LiteralPath $move.Source -Destination $move.Destination
    }
}
& git -C $rootPath init -b main
if ($LASTEXITCODE -ne 0) {
    throw "Git initialization failed. Old Git metadata is preserved under $backupBatch."
}
foreach ($privatePath in @('.git-backups/', 'token-agent/.env', 'token-java/.env')) {
    & git -C $rootPath check-ignore --quiet -- $privatePath
    if ($LASTEXITCODE -ne 0) {
        throw "Ignore check failed for $privatePath. Fix .gitignore before staging any files."
    }
}
Write-Output 'Prepared. Review git status and git add --dry-run . before staging.'
Write-Output 'No files have been staged, committed, or pushed.'
