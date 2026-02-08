# sxopen.ps1 - Protocol Handler for sx_obsidian
# Parses sxopen:<path> and sxreveal:<path>

param (
    [string]$Url
)

# Logging Setup
$LogDir = "$env:LOCALAPPDATA\sx_obsidian\logs"
if (!(Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = "$LogDir\protocol.log"

function Write-Log {
    param([string]$Message)
    $Stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$Stamp] $Message" | Out-File -FilePath $LogFile -Append
}

function Show-ErrorDialog {
    param(
        [string]$Title,
        [string]$Message
    )
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        [System.Windows.Forms.MessageBox]::Show(
            $Message,
            $Title,
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    } catch {
        # If UI isn't available (rare), just log.
        Write-Log "UI dialog failed: $_"
    }
}

function Normalize-TargetPath {
    param([string]$Raw)

    if (-not $Raw) { return "" }
    $p = $Raw.Trim('"').Trim("'").Trim()

    # Support file:///C:/... links if they ever appear.
    if ($p -match '^file:(\/\/\/)?') {
        try {
            $u = [Uri]$p
            if ($u.IsFile) {
                return $u.LocalPath
            }
        } catch {
            # Fall through.
        }
        $p = $p -replace '^file:(\/\/\/)?', ''
    }

    # Common URL-style path: /T:/Vault/... -> T:\Vault\...
    if ($p -match '^\/[A-Za-z]:\/') {
        $p = $p.TrimStart('/')
    }

    return $p
}

try {
    Write-Log "Received URL: $Url"

    # 1. Parse Protocol and Path
    # URL format: sxopen:T%3A%5CPath%5Cto%5Cfile.mp4
    if ($Url -match "^(sxopen|sxreveal):(.*)") {
        $Protocol = $Matches[1]
        $EncodedPath = $Matches[2]
        
        # 2. Decode URL
        $DecodedPath = [uri]::UnescapeDataString($EncodedPath)
        
        # 3. Clean up path (strip quotes if any)
        $CleanPath = Normalize-TargetPath -Raw $DecodedPath
        
        Write-Log "Parsed Protocol: $Protocol, Decoded Path: $CleanPath"

        if (-not $CleanPath) {
            Write-Log "ERROR: Empty path after parsing"
            Show-ErrorDialog -Title "SX Protocol Error" -Message "No file path was provided to the protocol handler.\n\nRaw URL: $Url"
            exit 1
        }

        # Help users debug the #1 real-world issue: generator emitted Linux/WSL paths, but Obsidian is running on Windows.
        if ($CleanPath -match '^\/mnt\/' -or $CleanPath -match '^\/(home|Users)\/' ) {
            Write-Log "ERROR: Detected Linux/WSL-style path on Windows: $CleanPath"
            Show-ErrorDialog -Title "SX Protocol Error" -Message (
                "This link contains a Linux/WSL-style path, but you clicked it from Windows.\n\n" +
                "Path: $CleanPath\n\n" +
                "Fix: set PATH_STYLE_<profile>=windows and set VAULT_WINDOWS_<profile>=<Drive>:\\... in sx_obsidian/.env, then re-run sync."
            )
            exit 1
        }

        # 4. Validate File Exists
        if (Test-Path -Path $CleanPath) {
            if ($Protocol -eq "sxopen") {
                Write-Log "Opening file: $CleanPath"
                Start-Process -FilePath $CleanPath
            }
            elseif ($Protocol -eq "sxreveal") {
                Write-Log "Revealing file in Explorer: $CleanPath"
                Start-Process explorer.exe -ArgumentList "/select, ""$CleanPath"""
            }
        }
        else {
            Write-Log "ERROR: File not found - $CleanPath"
            Show-ErrorDialog -Title "SX Protocol Error" -Message (
                "File not found:\n$CleanPath\n\n" +
                "If this is a drive-letter mismatch, ensure VAULT_WINDOWS_<profile> points to the correct vault root on Windows, and PATH_STYLE_<profile>=windows.\n\n" +
                "See log: $LogFile"
            )
        }
    }
    else {
        Write-Log "ERROR: Invalid URL format - $Url"
        Show-ErrorDialog -Title "SX Protocol Error" -Message "Invalid protocol URL: $Url\n\nExpected: sxopen:<path> or sxreveal:<path>"
    }
}
catch {
    Write-Log "EXCEPTION: $_"
    Show-ErrorDialog -Title "SX Protocol Error" -Message "An unexpected error occurred.\n\n$_\n\nSee log: $LogFile"
}
