# provision.ps1 — Idempotent provisioning for chatPlays Windows test VM
$ErrorActionPreference = "Stop"

# Force TLS 1.2 for downloads (Server 2019 defaults may not include it)
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ── Python ───────────────────────────────────────────────────────────────────

$python_version = "3.11.9"
$python_installer = "$env:TEMP\python-$python_version-amd64.exe"
$python_url = "https://www.python.org/ftp/python/$python_version/python-$python_version-amd64.exe"

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "Installing Python $python_version ..."
    if (-not (Test-Path $python_installer)) {
        Invoke-WebRequest -Uri $python_url -OutFile $python_installer -UseBasicParsing
    }
    Start-Process $python_installer -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0" -Wait -NoNewWindow
    # Refresh PATH for the current session
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
    Write-Host "Python installed."
} else {
    Write-Host "Python already installed: $($py.Source)"
}

python --version

# ── Python packages (vgamepad install triggers ViGEmBus MSI) ─────────────────

Write-Host "Installing Python packages ..."
python -m pip install --upgrade pip --quiet
python -m pip install vgamepad pytest pytest-asyncio --quiet

# vgamepad's setup.py installs ViGEmBus 1.17.333 via its bundled MSI.
# Verify the driver is running after pip install.
$vigem_service = Get-Service -Name ViGEmBus -ErrorAction SilentlyContinue
if (-not $vigem_service -or $vigem_service.Status -ne "Running") {
    Write-Host "ViGEmBus not running after vgamepad install, installing manually ..."
    $msi = Get-ChildItem "C:\Program Files\Python311\Lib\site-packages\vgamepad\win\vigem\install\x64" -Filter "*.msi" | Select-Object -First 1
    if ($msi) {
        msiexec /i $msi.FullName /quiet /norestart /l*v "$env:TEMP\vigem_msi.log"
        Start-Sleep 5
    } else {
        Write-Error "Could not find ViGEmBus MSI in vgamepad package."
    }
}

# Verify ViGEmBus is running
sc.exe query ViGEmBus | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Error "ViGEmBus service is not running."
}

# ── Xbox 360 Controller Driver (xusb21 — required on Windows Server) ────────
#
# Windows Server editions do not ship xusb22.sys (the Xbox 360 controller
# class driver).  ViGEmBus creates child PDOs with hardware ID
# USB\VID_045E&PID_028E; without a matching function driver, virtual
# gamepads cannot be plugged in.
#
# We extract the xusb21 driver from the Xbox 360 Accessories installer
# (freely redistributable), add it to the driver store, pre-create the
# kernel service, and do a warm-up plug cycle so PnP binds the driver
# before the test suite runs.

$xusb_svc = Get-Service -Name xusb21 -ErrorAction SilentlyContinue
if (-not $xusb_svc) {
    Write-Host "Installing Xbox 360 controller driver (xusb21) ..."

    # Download 7-Zip (needed to extract the WiX Burn bundle headlessly)
    if (-not (Test-Path "C:\Program Files\7-Zip\7z.exe")) {
        $7zUrl = "https://www.7-zip.org/a/7z2409-x64.msi"
        $7zMsi = "$env:TEMP\7z.msi"
        if (-not (Test-Path $7zMsi)) {
            Invoke-WebRequest -Uri $7zUrl -OutFile $7zMsi -UseBasicParsing
        }
        msiexec /i $7zMsi /quiet /norestart
        Start-Sleep 3
    }

    # Download Xbox 360 Accessories installer
    $xboxExe = "$env:TEMP\Xbox360_64Eng.exe"
    if (-not (Test-Path $xboxExe)) {
        $xboxUrl = "https://archive.org/download/xbox-360-64-eng_202408/Xbox360_64Eng.exe"
        Invoke-WebRequest -Uri $xboxUrl -OutFile $xboxExe -UseBasicParsing
    }

    # Extract with 7-Zip
    $extractDir = "$env:TEMP\xbox360_extracted"
    if (Test-Path $extractDir) { Remove-Item $extractDir -Recurse -Force }
    & "C:\Program Files\7-Zip\7z.exe" x $xboxExe "-o$extractDir" -y | Out-Null

    # Add driver to store (win7/x64 variant — compatible with Server 2019)
    $driverDir = "$extractDir\xbox360\setup64\files\driver\win7"
    pnputil /add-driver "$driverDir\xusb21.inf" /install | Out-Host

    # Copy the correct x64 binary into System32\drivers and create the
    # kernel service.  pnputil puts it in the DriverStore but PnP may
    # copy a corrupted version on first device-install; doing it
    # explicitly avoids the race.
    $repoDir = Get-ChildItem "C:\Windows\System32\DriverStore\FileRepository" -Filter "xusb21.inf_amd64_*" -Directory | Select-Object -First 1
    Copy-Item "$($repoDir.FullName)\x64\xusb21.sys" "C:\Windows\System32\drivers\xusb21.sys" -Force
    sc.exe create xusb21 binpath= "\SystemRoot\System32\drivers\xusb21.sys" type= kernel start= demand | Out-Host

    Write-Host "xusb21 driver installed."
} else {
    Write-Host "xusb21 driver already installed."
}

# Ensure the service exists and the binary is present
sc.exe query xusb21 | Out-Host

# ── Warm-up: trigger PnP driver binding ─────────────────────────────────────
#
# The first vigem_target_add after a fresh install fails because PnP has
# not yet associated xusb21 with the Xbox 360 hardware ID.  A single
# failed-then-retried cycle teaches PnP; subsequent calls succeed
# immediately.

Write-Host "Running vgamepad warm-up cycle ..."
python -c "
import vgamepad.win.vigem_client as vcli
import vgamepad.win.vigem_commons as vcom
import time
busp = vcli.vigem_alloc()
vcli.vigem_connect(busp)
devp = vcli.vigem_target_x360_alloc()
err = vcli.vigem_target_add(busp, devp)
if err != vcom.VIGEM_ERRORS.VIGEM_ERROR_NONE.value:
    vcli.vigem_target_free(devp)
    time.sleep(5)
    devp = vcli.vigem_target_x360_alloc()
    err = vcli.vigem_target_add(busp, devp)
if err == vcom.VIGEM_ERRORS.VIGEM_ERROR_NONE.value:
    vcli.vigem_target_remove(busp, devp)
    vcli.vigem_target_free(devp)
    print('warm-up OK')
else:
    print(f'warm-up failed: {vcom.VIGEM_ERRORS(err).name}')
vcli.vigem_disconnect(busp)
vcli.vigem_free(busp)
"
if ($LASTEXITCODE -ne 0) {
    Write-Error "vgamepad warm-up failed."
}

python -m pip install -e "C:\chatplays" --quiet

# ── Smoke test ───────────────────────────────────────────────────────────────

Write-Host "Running vgamepad smoke test ..."
python -c "import vgamepad; g = vgamepad.VX360Gamepad(); del g; print('vgamepad OK')"
if ($LASTEXITCODE -ne 0) {
    Write-Error "vgamepad smoke test failed."
}

Write-Host "Provisioning complete."
