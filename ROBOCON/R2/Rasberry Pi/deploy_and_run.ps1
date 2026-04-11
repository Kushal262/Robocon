# ============================================
# R2 Robot - Deploy & Run Script
# ============================================
# This script copies all robot files to the
# Raspberry Pi and optionally runs the script
# or sets up the auto-start service.
# ============================================

# --- Configuration (change these if needed) ---
$PI_USER = "r1"
$PI_IP   = "10.54.162.234"
$PI_DIR  = "/home/r1/Desktop/ROBOCON_pi"
$LOCAL_DIR = "d:\kushal\Downloads D\ROBOCON\R2\Rasberry Pi"

# --- Step 1: Create the folder on Pi (if it doesn't exist) ---
Write-Host "`n[1/4] Creating folder on Pi..." -ForegroundColor Cyan
ssh ${PI_USER}@${PI_IP} "mkdir -p ${PI_DIR}"

# --- Step 2: Copy all robot files to the Pi ---
Write-Host "[2/4] Copying files to Pi..." -ForegroundColor Cyan

$files = @("r2_pi_ps4.py", "start_r2.sh", "r2-robot.service")
foreach ($file in $files) {
    $localPath = Join-Path $LOCAL_DIR $file
    if (Test-Path $localPath) {
        scp "$localPath" "${PI_USER}@${PI_IP}:${PI_DIR}/${file}"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ERROR: Failed to copy $file" -ForegroundColor Red
            exit 1
        }
        Write-Host "  ✓ $file copied" -ForegroundColor Green
    } else {
        Write-Host "  ⚠ $file not found locally, skipping" -ForegroundColor Yellow
    }
}

# --- Step 3: Make start_r2.sh executable ---
Write-Host "[3/4] Setting permissions..." -ForegroundColor Cyan
ssh ${PI_USER}@${PI_IP} "chmod +x ${PI_DIR}/start_r2.sh"
Write-Host "  ✓ start_r2.sh made executable" -ForegroundColor Green

# --- Step 4: Ask what to do ---
Write-Host "`n[4/4] What would you like to do?" -ForegroundColor Yellow
Write-Host "  [1] Run the script manually (interactive)" -ForegroundColor White
Write-Host "  [2] Install & start the auto-start service" -ForegroundColor White
Write-Host "  [3] Restart the service (after code update)" -ForegroundColor White
Write-Host "  [4] Just deploy, don't run anything" -ForegroundColor White

$choice = Read-Host "`nEnter choice (1/2/3/4)"

switch ($choice) {
    "1" {
        Write-Host "`nRunning r2_pi_ps4.py interactively..." -ForegroundColor Yellow
        Write-Host "(Press Ctrl+C to stop the robot)`n" -ForegroundColor DarkGray
        ssh ${PI_USER}@${PI_IP} "cd ${PI_DIR} && python3 r2_pi_ps4.py"
    }
    "2" {
        Write-Host "`nInstalling auto-start service..." -ForegroundColor Yellow
        ssh ${PI_USER}@${PI_IP} @"
sudo cp ${PI_DIR}/r2-robot.service /etc/systemd/system/ &&
sudo systemctl daemon-reload &&
sudo systemctl enable r2-robot &&
sudo systemctl start r2-robot &&
echo '✓ Service installed, enabled, and started!' &&
sudo systemctl status r2-robot --no-pager
"@
    }
    "3" {
        Write-Host "`nRestarting service with updated code..." -ForegroundColor Yellow
        ssh ${PI_USER}@${PI_IP} @"
sudo cp ${PI_DIR}/r2-robot.service /etc/systemd/system/ &&
sudo systemctl daemon-reload &&
sudo systemctl restart r2-robot &&
echo '✓ Service restarted!' &&
sudo systemctl status r2-robot --no-pager
"@
    }
    "4" {
        Write-Host "`n✓ Files deployed. No action taken." -ForegroundColor Green
    }
    default {
        Write-Host "`n✓ Files deployed. No action taken." -ForegroundColor Green
    }
}

Write-Host "`nDone.`n" -ForegroundColor Cyan
