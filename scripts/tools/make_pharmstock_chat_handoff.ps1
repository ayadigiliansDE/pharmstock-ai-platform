param(
    [string]$ProjectRoot = (Get-Location).Path,
    [string]$OutputZip = ""
)

$ErrorActionPreference = "Stop"

function Get-FullPathNormalized {
    param([Parameter(Mandatory = $true)][string]$Path)

    $full = [System.IO.Path]::GetFullPath($Path)
    while ($full.Length -gt 3 -and ($full.EndsWith("\") -or $full.EndsWith("/"))) {
        $full = $full.Substring(0, $full.Length - 1)
    }
    return $full
}

function Get-RelativePathCompat {
    param(
        [Parameter(Mandatory = $true)][string]$BasePath,
        [Parameter(Mandatory = $true)][string]$TargetPath
    )

    # PowerShell 5.1 runs on .NET Framework, where Path.GetRelativePath is unavailable.
    # Both paths used by this script must be inside ProjectRoot, so a validated
    # prefix/sub-string implementation is simpler and avoids fragile Char casts.
    $base = Get-FullPathNormalized -Path $BasePath
    $target = Get-FullPathNormalized -Path $TargetPath
    $comparison = [System.StringComparison]::OrdinalIgnoreCase

    if ([string]::Equals($base, $target, $comparison)) {
        return ""
    }

    $separator = [System.IO.Path]::DirectorySeparatorChar.ToString()
    $prefix = $base + $separator

    if (-not $target.StartsWith($prefix, $comparison)) {
        throw "Target path is outside ProjectRoot. Base='$base' Target='$target'"
    }

    return $target.Substring($prefix.Length)
}

$ProjectRoot = Get-FullPathNormalized -Path $ProjectRoot
if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "ProjectRoot does not exist or is not a directory: $ProjectRoot"
}

if ([string]::IsNullOrWhiteSpace($OutputZip)) {
    $OutputZip = Join-Path $ProjectRoot "pharmstock-ai-platform-v2-chat-handoff.zip"
}
else {
    $OutputZip = [System.IO.Path]::GetFullPath($OutputZip)
}

$outputParent = Split-Path -Path $OutputZip -Parent
if (-not [string]::IsNullOrWhiteSpace($outputParent)) {
    New-Item -ItemType Directory -Path $outputParent -Force | Out-Null
}

$TempRoot = Join-Path $env:TEMP ("pharmstock_handoff_" + [guid]::NewGuid().ToString("N"))
$BundleRoot = Join-Path $TempRoot "pharmstock-ai-platform-v2"

$ExcludedDirs = @(
    ".git", ".venv", "venv", "env",
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    "node_modules", "dist", "build", "target",
    "data", "datasets", "warehouse", "spark-warehouse",
    "logs", "tmp", "temp", ".terraform"
)

$ExcludedExtensions = @(
    ".parquet", ".csv", ".feather", ".orc", ".avro",
    ".joblib", ".pkl", ".pickle", ".db", ".sqlite", ".sqlite3",
    ".tar", ".gz", ".tgz", ".7z", ".rar", ".zip",
    ".whl", ".pyc", ".pyo", ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".mp4", ".mov"
)

$AlwaysUsefulNames = @(
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    ".dockerignore", ".gitignore", ".env.example", "pyproject.toml",
    "pytest.ini", "ruff.toml", "requirements.txt", "poetry.lock", "uv.lock"
)

$AllowedExtensions = @(
    ".py", ".sql", ".md", ".txt", ".json", ".yml", ".yaml", ".toml",
    ".ini", ".cfg", ".ps1", ".sh", ".bat", ".cmd", ".properties",
    ".xml", ".tf", ".tfvars", ".example"
)

function Test-ExcludedPath {
    param([Parameter(Mandatory = $true)][string]$FullName)

    $relative = Get-RelativePathCompat -BasePath $ProjectRoot -TargetPath $FullName
    $parts = $relative -split '[\\/]'
    foreach ($part in $parts) {
        if ($ExcludedDirs -contains $part) {
            return $true
        }
    }
    return $false
}

function Copy-HandoffFile {
    param([Parameter(Mandatory = $true)][System.IO.FileInfo]$File)

    $relative = Get-RelativePathCompat -BasePath $ProjectRoot -TargetPath $File.FullName
    if ([string]::IsNullOrWhiteSpace($relative)) {
        return
    }

    $destination = Join-Path $BundleRoot $relative
    $destinationDir = Split-Path -Path $destination -Parent
    if (-not [string]::IsNullOrWhiteSpace($destinationDir)) {
        New-Item -ItemType Directory -Path $destinationDir -Force | Out-Null
    }
    Copy-Item -LiteralPath $File.FullName -Destination $destination -Force
}

New-Item -ItemType Directory -Path $BundleRoot -Force | Out-Null

try {
    Get-ChildItem -LiteralPath $ProjectRoot -Recurse -File -Force | ForEach-Object {
        $file = $_
        if (Test-ExcludedPath -FullName $file.FullName) { return }

        $ext = $file.Extension.ToLowerInvariant()
        $name = $file.Name
        $isUseful = ($AllowedExtensions -contains $ext) -or ($AlwaysUsefulNames -contains $name)
        if (-not $isUseful) { return }
        if ($ExcludedExtensions -contains $ext) { return }
        if ($file.Length -gt 10MB) { return }

        Copy-HandoffFile -File $file
    }

    # Explicitly retain small text reports from artifacts even if future exclusion
    # rules become stricter. Existing destinations are safely overwritten.
    $ArtifactsRoot = Join-Path $ProjectRoot "artifacts"
    if (Test-Path -LiteralPath $ArtifactsRoot -PathType Container) {
        Get-ChildItem -LiteralPath $ArtifactsRoot -Recurse -File -Force |
            Where-Object {
                $_.Length -le 2MB -and @(".json", ".md", ".txt") -contains $_.Extension.ToLowerInvariant()
            } |
            ForEach-Object {
                Copy-HandoffFile -File $_
            }
    }

    $GitCommit = "unavailable"
    $gitCommand = Get-Command git -ErrorAction SilentlyContinue
    if ($null -ne $gitCommand) {
        try {
            $candidateCommit = (& git -C $ProjectRoot rev-parse HEAD 2>$null)
            if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($candidateCommit)) {
                $GitCommit = $candidateCommit.Trim()
            }
        }
        catch {
            $GitCommit = "unavailable"
        }
    }

    $Manifest = @"
# PharmStock AI Platform V2 — Chat Handoff

Generated: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
Project root: $ProjectRoot
Git commit: $GitCommit
PowerShell compatibility: Windows PowerShell 5.1+

This package intentionally excludes virtual environments, raw/generated datasets,
Parquet/CSV warehouse files, trained-model binaries, Docker volumes/images, logs,
temporary files, and nested archives.

It keeps source code, SQL, tests, Docker/Terraform/dbt/Airflow configuration,
README files, and small JSON/Markdown/TXT artifacts needed for review.

IMPORTANT CURRENT STAGE NOTE:
Stage 7K must not be treated as complete unless the latest live run contains all
Stage 7K PASS markers.
"@

    Set-Content -LiteralPath (Join-Path $BundleRoot "CHAT_HANDOFF.md") -Value $Manifest -Encoding UTF8

    if (Test-Path -LiteralPath $OutputZip) {
        Remove-Item -LiteralPath $OutputZip -Force
    }

    $bundleItems = Get-ChildItem -LiteralPath $BundleRoot -Force
    if ($bundleItems.Count -eq 0) {
        throw "Handoff bundle is empty; refusing to create an empty archive."
    }

    Compress-Archive `
        -Path (Join-Path $BundleRoot "*") `
        -DestinationPath $OutputZip `
        -CompressionLevel Optimal `
        -Force

    if (-not (Test-Path -LiteralPath $OutputZip -PathType Leaf)) {
        throw "Handoff ZIP was not created: $OutputZip"
    }

    $ZipInfo = Get-Item -LiteralPath $OutputZip
    if ($ZipInfo.Length -le 0) {
        throw "Handoff ZIP is empty: $OutputZip"
    }

    Write-Host ""
    Write-Host "HANDOFF_ZIP=$($ZipInfo.FullName)"
    Write-Host ("HANDOFF_SIZE_MB={0:N2}" -f ($ZipInfo.Length / 1MB))
    Write-Host "HANDOFF_POWERSHELL_COMPAT=5.1+"
    Write-Host "HANDOFF_STATUS=PASS"
}
finally {
    if (Test-Path -LiteralPath $TempRoot) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
