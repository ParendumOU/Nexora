# Nexora installer — Windows (PowerShell 5.1+)
#
#   powershell -c "irm https://raw.githubusercontent.com/ParendumOU/Nexora/main/install.ps1 | iex"
#
# Interactive: asks a couple of questions, generates all secrets, writes .env,
# starts the Docker stack and runs the database migrations. Safe to re-run.
#
# Overrides (set before running): $env:NEXORA_DIR, $env:NEXORA_PORT, $env:NEXORA_NONINTERACTIVE

$ErrorActionPreference = "Stop"

$RepoUrl    = if ($env:NEXORA_REPO_URL) { $env:NEXORA_REPO_URL } else { "https://github.com/ParendumOU/Nexora.git" }
$DefaultDir = if ($env:NEXORA_DIR)      { $env:NEXORA_DIR }      else { Join-Path $HOME "Nexora" }
$DefaultPort = if ($env:NEXORA_PORT)    { $env:NEXORA_PORT }     else { "80" }
$NonInteractive = ($env:NEXORA_NONINTERACTIVE -eq "1")

function Write-Info($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host " OK $msg" -ForegroundColor Green }
function Fail($msg)       { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

function Ask($prompt, $default) {
    if ($NonInteractive) { return $default }
    $answer = Read-Host "$prompt [$default]"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $default }
    return $answer
}

function Ask-YesNo($prompt, $default) {
    $answer = Ask "$prompt (y/n)" $default
    return ($answer -match '^(y|yes)$')
}

function New-RandomHex($byteCount) {
    $bytes = New-Object byte[] $byteCount
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return (($bytes | ForEach-Object { $_.ToString("x2") }) -join "")
}

function New-FernetKey {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_")
}

Write-Host ""
Write-Host "  Nexora -- self-hosted AI-agent orchestration platform" -ForegroundColor White
Write-Host "  https://nexora.parendum.com" -ForegroundColor White
Write-Host ""

# -- 1. Requirements -----------------------------------------------------------
Write-Info "Checking requirements"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "Docker Desktop is required. Install it from https://www.docker.com/products/docker-desktop/ and re-run."
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail "git is required. Install it from https://git-scm.com/download/win and re-run."
}
docker info 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "Docker Desktop is not running. Start it and re-run." }
docker compose version 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "Docker Compose v2 is required (ships with Docker Desktop)." }
Write-Ok "Docker, Compose, git found"

# -- 2. Get the code -----------------------------------------------------------
if ((Test-Path "docker-compose.yml") -and (Test-Path "backend/src") -and (Test-Path ".env.example")) {
    $InstallDir = (Get-Location).Path
    Write-Ok "Existing Nexora checkout detected -- installing here ($InstallDir)"
} else {
    $InstallDir = Ask "Where should Nexora be installed?" $DefaultDir
    if (Test-Path (Join-Path $InstallDir ".git")) {
        Write-Info "Directory exists -- pulling latest"
        git -C $InstallDir pull --ff-only
        if ($LASTEXITCODE -ne 0) { Fail "git pull failed in $InstallDir" }
    } else {
        Write-Info "Cloning $RepoUrl"
        git clone --depth 1 $RepoUrl $InstallDir
        if ($LASTEXITCODE -ne 0) { Fail "git clone failed" }
    }
    Set-Location $InstallDir
}

# -- 3. Configuration ----------------------------------------------------------
if (Test-Path ".env") {
    Write-Ok ".env already exists -- keeping your configuration"
} else {
    Write-Info "Configuring your instance"
    $HttpPort = Ask "HTTP port for the web UI" $DefaultPort
    $RequireInvite = "false"
    if (Ask-YesNo "Require an invite link to register new users? (recommended for shared servers)" "n") {
        $RequireInvite = "true"
    }

    Write-Info "Generating secrets"
    $PgPass        = New-RandomHex 24
    $RedisPass     = New-RandomHex 24
    $SecretKey     = New-RandomHex 48
    $EncryptionKey = New-FernetKey

    $envContent = Get-Content ".env.example" -Raw
    $envContent = $envContent -replace "(?m)^POSTGRES_PASSWORD=.*",  "POSTGRES_PASSWORD=$PgPass"
    $envContent = $envContent -replace "(?m)^REDIS_PASSWORD=.*",     "REDIS_PASSWORD=$RedisPass"
    $envContent = $envContent -replace "(?m)^SECRET_KEY=.*",         "SECRET_KEY=$SecretKey"
    $envContent = $envContent -replace "(?m)^ENCRYPTION_KEY=.*",     "ENCRYPTION_KEY=$EncryptionKey"
    $envContent = $envContent -replace "(?m)^HTTP_PORT=.*",          "HTTP_PORT=$HttpPort"
    $envContent = $envContent -replace "(?m)^REQUIRE_INVITE=.*",     "REQUIRE_INVITE=$RequireInvite"
    $envContent = $envContent -replace "(?m)^CORS_ORIGINS=.*",       "CORS_ORIGINS=http://localhost,http://localhost:$HttpPort,http://localhost:3000,http://localhost:8080"
    [System.IO.File]::WriteAllText((Join-Path (Get-Location).Path ".env"), $envContent)
    Write-Ok ".env written (secrets generated automatically)"
}

$HttpPort = (Select-String -Path ".env" -Pattern "^HTTP_PORT=(.*)$").Matches[0].Groups[1].Value
if ([string]::IsNullOrWhiteSpace($HttpPort)) { $HttpPort = "80" }

# -- 4. Start --------------------------------------------------------------
Write-Info "Building and starting the stack (first build can take a few minutes)"
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Fail "docker compose up failed. Check the output above." }

Write-Info "Waiting for the backend to become ready"
$attempts = 0
while ($true) {
    docker compose exec -T backend python -c "import sys; sys.exit(0)" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { break }
    $attempts++
    if ($attempts -ge 30) { Fail "Backend did not become ready. Check logs with: docker compose logs backend" }
    Start-Sleep -Seconds 3
}
Write-Ok "Backend is up"

Write-Info "Running database migrations"
$attempts = 0
while ($true) {
    docker compose exec -T backend alembic upgrade head 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { break }
    $attempts++
    if ($attempts -ge 10) { Fail "Migrations failed. Check logs with: docker compose logs backend" }
    Start-Sleep -Seconds 3
}
Write-Ok "Database is ready"

# -- 5. Done ---------------------------------------------------------------
$Url = "http://localhost:$HttpPort"
if ($HttpPort -eq "80") { $Url = "http://localhost" }

Write-Host ""
Write-Host "  Nexora is running!" -ForegroundColor Green
Write-Host ""
Write-Host "  1. Open $Url in your browser"
Write-Host "  2. You will be redirected to /setup -- create your admin account there"
Write-Host ""
Write-Host "  Useful commands (run inside $InstallDir):"
Write-Host "    docker compose logs -f      # tail logs"
Write-Host "    docker compose down         # stop"
Write-Host "    docker compose up -d        # start again"
Write-Host ""
Write-Host "  Docs: https://docs.nexora.parendum.com"
Write-Host ""
