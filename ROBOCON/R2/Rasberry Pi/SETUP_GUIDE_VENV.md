# Raspberry Pi 4 — Setup Guide (Virtual Environment Method)

> Alternative setup using Python virtual environment.
> Project files live in `/home/r1/Desktop/ROBOCON_pi/`.
>
> ⚠️ **Note:** For a dedicated robot Pi, the system package method
> (`sudo apt install python3-pygame python3-serial`) is simpler and
> recommended. Use this venv guide only if you specifically want
> isolated Python packages.

---

## What Is a Virtual Environment?

A **virtual environment (R1)** is an isolated Python installation
inside a folder. Packages you install go into that folder instead of
the system-wide Python. This means:

```
System Python (/usr/bin/python3)
├── System packages (used by OS tools)
└── NOT affected by your project

Your venv (/home/r1/Desktop/ROBOCON_pi/R1/bin/python3)
├── pygame        ← only YOUR project sees this
├── pyserial      ← only YOUR project sees this
└── Completely isolated from system Python
```

**When it's useful:**
- Multiple projects on the same Pi needing different package versions
- You want to use `pip install` on Raspberry Pi OS Bookworm+ (which
  blocks pip outside venv via PEP 668)
- You want exact control over package versions

**When it's overkill:**
- Your Pi runs a single robot script (this is you!)
- You only need 2 packages
- You're using apt system packages anyway

---

## Folder Structure on the Pi

```
/home/r1/Desktop/ROBOCON_pi/
├── venv/                 ← Python virtual environment (auto-generated)
│   ├── bin/
│   │   ├── python3       ← Isolated Python interpreter
│   │   └── pip3          ← Isolated pip
│   └── lib/              ← Installed packages go here
├── r2_pi_ps4.py          ← Main robot controller script
├── start_r2.sh           ← Launcher script for systemd
└── requirements.txt      ← Package list
```

---

## Step 1: Install Raspberry Pi OS

1. Use **Raspberry Pi Imager** to flash **Raspberry Pi OS (64-bit)**.
2. In settings: username `r1`, enable SSH, configure Wi-Fi.
3. Boot and SSH in:
   ```bash
   ssh r1@<PI_IP_ADDRESS>
   ```

---

## Step 2: Update System & Install Base Tools

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-venv python3-dev libsdl2-dev libsdl2-mixer-dev \
  libsdl2-image-dev libsdl2-ttf-dev joystick -y
```

What these are:
- `python3-venv` — lets you create virtual environments
- `python3-dev` — Python headers needed to compile pygame from pip
- `libsdl2-*` — SDL2 libraries that pygame needs (graphics, audio, input)
- `joystick` — for testing PS4 controller with `jstest`

---

## Step 3: Give Serial Port Permission

```bash
sudo usermod -aG dialout r1
sudo reboot
```

---

## Step 4: Create the Project Folder & Virtual Environment

SSH back in after reboot:

```bash
# Create project folder on Desktop
mkdir -p /home/r1/Desktop/ROBOCON_pi

# Create virtual environment inside it
cd /home/r1/Desktop/ROBOCON_pi
python3 -m venv R1
```

This creates the `venv/` folder with an isolated Python interpreter.

---

## Step 5: Activate the Virtual Environment & Install Packages

```bash
# Activate the venv (your prompt will change to show "(R1)")
source /home/r1/Desktop/ROBOCON_pi/venv/bin/activate

# Now pip installs go into the venv, NOT system Python
pip install pygame pyserial

# Verify installation
python3 -c "import pygame; print('pygame', pygame.ver)"
python3 -c "import serial; print('pyserial OK')"

# Deactivate when done (optional — just returns to normal shell)
deactivate
```

> **Note:** `pip install pygame` may take 5-10 minutes on a Pi 4 because
> it compiles from source. That's why we installed the SDL2 dev libraries
> in Step 2 — without them, this step would fail.

### Optional: Create requirements.txt

```bash
echo "pygame" > /home/r1/Desktop/ROBOCON_pi/requirements.txt
echo "pyserial" >> /home/r1/Desktop/ROBOCON_pi/requirements.txt
```

This lets you reinstall all packages in one command:
```bash
source R1/bin/activate && pip install -r requirements.txt
```

---

## Step 6: Pair PS4 Controller via Bluetooth

Same process regardless of venv or system packages:

### Put controller in pairing mode
Hold **SHARE + PS** buttons for ~5 seconds until light bar blinks rapidly.

### Pair from the Pi
```bash
sudo bluetoothctl
```

Inside bluetoothctl:
```
power on
agent on
default-agent
scan on
```

Wait for `[NEW] Device AA:BB:CC:DD:EE:FF Wireless Controller` to appear.

```
pair AA:BB:CC:DD:EE:FF
trust AA:BB:CC:DD:EE:FF
connect AA:BB:CC:DD:EE:FF
exit
```

> **`trust` is critical!** Without it, the controller won't auto-reconnect.

### Verify
```bash
jstest /dev/input/js0
```

Move sticks, press buttons — values should change. `Ctrl+C` to exit.

---

## Step 7: Connect Arduino Mega via USB

Plug USB cable from Pi to Arduino Mega. Verify:
```bash
ls /dev/ttyACM*
```
Should show `/dev/ttyACM0`.

---

## Step 8: Copy Files to the Pi

### From your Windows PC (PowerShell):

```powershell
$PI_IP = "10.89.196.234"
$PI_DIR = "/home/r1/Desktop/ROBOCON_pi"

scp "d:\kushal\Downloads D\ROBOCON\R2\Rasberry Pi\r2_pi_ps4.py" "r1@${PI_IP}:${PI_DIR}/"
scp "d:\kushal\Downloads D\ROBOCON\R2\Rasberry Pi\start_r2.sh" "r1@${PI_IP}:${PI_DIR}/"
scp "d:\kushal\Downloads D\ROBOCON\R2\Rasberry Pi\r2-robot.service" "r1@${PI_IP}:${PI_DIR}/"
```

Or use the deploy script:
```powershell
.\deploy_and_run.ps1
```

---

## Step 9: Test Manually

```bash
# IMPORTANT: Must use the venv's Python, not system Python!
cd Robot 1
./R1/bin/python3 r2_pi_ps4.py
```

Or equivalently:
```bash
cd /home/r1/Desktop/ROBOCON_pi
source R1/bin/activate
python3 r2_pi_ps4.py
```

Verify everything works: controller detected, Arduino PONG, robot moves.

---

## Step 10: Set Up Auto-Start Service

### 10a. Update start_r2.sh for venv

The launcher script **must use the venv's Python**, not system Python.
Edit it on the Pi:

```bash
nano /home/r1/Desktop/ROBOCON_pi/start_r2.sh
```

Contents should be:
```bash
#!/bin/bash
# R2 Robot — Launcher script for systemd (VENV version)

# Tell SDL/pygame to use dummy video driver (no monitor needed)
export SDL_VIDEODRIVER=dummy

# Use the virtual environment's Python interpreter directly
# (no need to "source activate" — just call the venv python)
cd /home/r1/Desktop/ROBOCON_pi
exec /home/r1/Desktop/ROBOCON_pi/R1/bin/python3 r2_pi_ps4.py
```

Make it executable:
```bash
chmod +x /home/r1/Desktop/ROBOCON_pi/start_r2.sh
```

### 10b. Update r2-robot.service for the new path

```bash
sudo nano /etc/systemd/system/r2-robot.service
```

Contents:
```ini
[Unit]
Description=R2 Robot Controller (PS4 → Pi → Mega)
After=bluetooth.target
Wants=bluetooth.target

[Service]
Type=simple
User=r1
Group=r1
WorkingDirectory=/home/r1/Desktop/ROBOCON_pi
ExecStart=/bin/bash /home/r1/Desktop/ROBOCON_pi/start_r2.sh
Restart=on-failure
RestartSec=3
StartLimitIntervalSec=60
StartLimitBurst=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### 10c. Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable r2-robot
sudo systemctl start r2-robot
sudo systemctl status r2-robot
```

### 10d. Reboot and verify

```bash
sudo reboot
# After reboot:
sudo systemctl status r2-robot
journalctl -u r2-robot -f
```

---

## Service Management Cheat Sheet

| Command | What it does |
|---------|--------------|
| `sudo systemctl start r2-robot` | Start now |
| `sudo systemctl stop r2-robot` | Stop (motors stop) |
| `sudo systemctl restart r2-robot` | Restart |
| `sudo systemctl status r2-robot` | Show status |
| `sudo systemctl enable r2-robot` | Auto-start on boot |
| `sudo systemctl disable r2-robot` | Disable auto-start |
| `journalctl -u r2-robot -f` | Follow live logs |

---

## Key Difference from System Package Method

| What | System Packages (SETUP_GUIDE.md) | Virtual Env (this guide) |
|------|----------------------------------|--------------------------|
| Install packages | `sudo apt install python3-pygame python3-serial` | `source R1/bin/activate && pip install pygame pyserial` |
| Run manually | `python3 r2_pi_ps4.py` | `./R1/bin/python3 r2_pi_ps4.py` |
| Service launcher | `exec python3 r2_pi_ps4.py` | `exec /home/r1/Desktop/ROBOCON_pi/R1/bin/python3 r2_pi_ps4.py` |
| Project path | `/home/r1/robot/` | `/home/r1/Desktop/ROBOCON_pi/` |
| SDL2 libraries | Pre-compiled with apt | Must install libsdl2-dev for pip to compile |
| Setup time | ~2 minutes | ~10-15 minutes (pip compiles pygame) |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `pip install pygame` fails | Make sure you installed SDL2 dev packages (Step 2) |
| `ModuleNotFoundError: pygame` | You're using system python instead of venv python. Use `./R1/bin/python3` |
| Service runs but can't import pygame | Check `start_r2.sh` uses venv python path, not `python3` |
| `externally-managed-environment` error | You're trying to pip install outside venv. Activate venv first. |
| Everything else | Same troubleshooting as SETUP_GUIDE.md |
