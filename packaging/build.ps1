# Data Manager - Windows 빌드 스크립트
#
# 사용법 (프로젝트 루트에서):
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# 빌드 순서:
#   1. 프론트엔드(React) 빌드 -> frontend\dist
#   2. PyInstaller -> dist\Data Manager\  (폴더형, Data Manager.exe 포함)
#   3. 배포용 zip
#
# 요구사항: Node.js + npm, uv(또는 .venv), Windows 11 (WebView2 내장)

$ErrorActionPreference = "Stop"

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

Write-Host "=== Data Manager 빌드 시작 (Windows) ==="
Write-Host "프로젝트 루트: $ProjectRoot"

# ------------------------------------------------------------------ #
#  0. 가상환경 확인                                                     #
# ------------------------------------------------------------------ #
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Host "--- .venv 생성 (uv) ---"
    uv venv
    uv pip install -e ".[build]"
    if (-not (Test-Path $Python)) { throw ".venv 생성 실패: $Python 없음" }
}

# ------------------------------------------------------------------ #
#  1. 프론트엔드 빌드                                                   #
# ------------------------------------------------------------------ #
Write-Host ""
Write-Host "--- [1/3] 프론트엔드 빌드 ---"
Push-Location (Join-Path $ProjectRoot "frontend")
if (-not (Test-Path "node_modules")) { npm install }
npm run build
if ($LASTEXITCODE -ne 0) { throw "프론트엔드 빌드 실패" }
Pop-Location

if (-not (Test-Path (Join-Path $ProjectRoot "frontend\dist\index.html"))) {
    throw "frontend\dist\index.html 이 없습니다."
}

# ------------------------------------------------------------------ #
#  2. PyInstaller                                                      #
# ------------------------------------------------------------------ #
Write-Host ""
Write-Host "--- [2/3] PyInstaller 빌드 ---"
Remove-Item -Recurse -Force (Join-Path $ProjectRoot "build") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $ProjectRoot "dist")  -ErrorAction SilentlyContinue

& $Python -m PyInstaller --noconfirm --clean (Join-Path $ProjectRoot "packaging\s3manager.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 빌드 실패" }

$AppDir = Join-Path $ProjectRoot "dist\Data Manager"
if (-not (Test-Path $AppDir)) { throw "빌드 결과가 없습니다: $AppDir" }

# ------------------------------------------------------------------ #
#  3. 패키징                                                            #
# ------------------------------------------------------------------ #
Write-Host ""
Write-Host "--- [3/3] 패키징 ---"
$Zip = Join-Path $ProjectRoot "dist\Data-Manager-win64.zip"
Remove-Item -Force $Zip -ErrorAction SilentlyContinue
Compress-Archive -Path $AppDir -DestinationPath $Zip

Write-Host ""
Write-Host "=== 빌드 성공 ==="
Write-Host "  앱:  $AppDir\Data Manager.exe"
Write-Host "  zip: $Zip   <- 이 파일을 동료에게 전달"
Write-Host ""
Write-Host "코드 서명이 없으므로 첫 실행 시 SmartScreen 경고가 뜹니다."
Write-Host "  -> '추가 정보' -> '실행' (INSTALL.md 참고)"
