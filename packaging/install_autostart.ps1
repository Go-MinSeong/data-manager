# Data Manager - Windows 자동 시작 등록/해제
#
#   등록: powershell -ExecutionPolicy Bypass -File packaging\install_autostart.ps1
#   해제: powershell -ExecutionPolicy Bypass -File packaging\install_autostart.ps1 -Uninstall
#
# 현재 사용자의 시작 프로그램 폴더에 바로가기를 만든다(관리자 권한 불필요).
# macOS 의 LaunchAgent(install_autostart.sh) 에 대응한다.

param([switch]$Uninstall)

$ErrorActionPreference = "Stop"

$StartupDir   = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupDir "Data Manager.lnk"

if ($Uninstall) {
    if (Test-Path $ShortcutPath) {
        Remove-Item -Force $ShortcutPath
        Write-Host "자동 시작 해제됨: $ShortcutPath"
    } else {
        Write-Host "등록된 자동 시작이 없습니다."
    }
    exit 0
}

# 설치된 exe 위치 찾기 — 우선순위: %LOCALAPPDATA%, Program Files, 빌드 산출물
$Candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Data Manager\Data Manager.exe"),
    (Join-Path $env:ProgramFiles "Data Manager\Data Manager.exe"),
    (Join-Path (Split-Path -Parent $PSScriptRoot) "dist\Data Manager\Data Manager.exe")
)
$Exe = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Exe) {
    throw "Data Manager.exe 를 찾을 수 없습니다. 다음 위치 중 하나에 설치하세요:`n" + ($Candidates -join "`n")
}

$WScript  = New-Object -ComObject WScript.Shell
$Shortcut = $WScript.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath       = $Exe
$Shortcut.WorkingDirectory = Split-Path -Parent $Exe
$Shortcut.Description      = "Data Manager - S3/SFTP 데이터 전송"
$Shortcut.Save()

Write-Host "자동 시작 등록됨"
Write-Host "  실행 파일: $Exe"
Write-Host "  바로가기 : $ShortcutPath"
