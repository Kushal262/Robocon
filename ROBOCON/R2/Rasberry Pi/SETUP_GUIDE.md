# Raspberry Pi 4 — Complete Setup Guide for R2 Robot

> Everything you need: OS install → packages → PS4 Bluetooth pairing →
> serial wiring → auto-start service → troubleshooting.

---

## Step 1: Install Raspberry Pi OS

1. Download and install **Raspberry Pi Imager** on your PC.
2. Flash **Raspberry Pi OS (64-bit)** onto a microSD card.
   - In Imager → Settings (gear icon):
     - Set hostname: `r1-pi`
     - Enable SSH (password authentication)
     - Set username: `r1`, password: (your choice)
     - Configure Wi-Fi (your network SSID + password)
3. Insert the microSD card into the Pi and power it on.
4. SSH in from your PC:
   ```
   ssh r1@<PI_IP_ADDRESS>
   ```

---

## Step 2: Update System

```bash
sudo apt update && sudo apt upgrade -y
```

---

## Step 3: Install Required Packages

```bash
sudo apt install python3-pygame python3-serial joystick -y
```

- `python3-pygame` — reads PS4 controller input
- `python3-serial` — communicates with Arduino Mega over USB
- `joystick` — provides `jstest` for testing controller

---

## Step 4: Give Serial Port Permission (one-time)

```bash
sudo usermod -aG dialout r1
```

Then **reboot** for it to take effect:

```bash
sudo reboot
```

---

## Step 5: Connect Arduino Mega via USB

Plug a USB cable from Raspberry Pi USB port to Arduino Mega's USB port.

Verify it's detected:
```bash
ls /dev/ttyACM*
```

You should see `/dev/ttyACM0`. This is the serial port the script uses.

---

## Step 6: Pair PS4 Controller via Bluetooth

This is a **one-time setup**. After pairing + trusting, the controller
will auto-connect every time you press the PS button.

### 6a. Enter Bluetooth pairing mode on the controller

Hold **SHARE + PS** buttons together for ~5 seconds until the **light bar
blinks rapidly in white/blue**. This means the controller is in pairing mode.

### 6b. Pair from the Raspberry Pi

Open a terminal (SSH or local) and run:

```bash
sudo bluetoothctl
```

Inside the `bluetoothctl` prompt, type these commands one by one:

```
power on
agent on
default-agent
scan on
```

### 6c. Wait for the controller to appear

Watch the scan output. You'll see something like:

```
[NEW] Device AA:BB:CC:DD:EE:FF Wireless Controller
```

**Copy the MAC address** (the `AA:BB:CC:DD:EE:FF` part). It's different
for every controller.

### 6d. Pair, trust, and connect

Replace `AA:BB:CC:DD:EE:FF` with YOUR controller's MAC address:

```
pair AA:BB:CC:DD:EE:FF
```

If it asks for confirmation, type `yes`.

```
trust AA:BB:CC:DD:EE:FF
```

> **`trust` is the critical command!** This tells the Pi to automatically
> accept connections from this controller in the future. Without trust,
> you'd have to manually pair every time.

```
connect AA:BB:CC:DD:EE:FF
```

The controller's light bar should turn **solid blue** — it's connected!

```
exit
```

### 6e. Verify the controller works

```bash
jstest /dev/input/js0
```

Move the joysticks and press buttons — you should see values changing.
Press `Ctrl+C` to exit.

### 6f. Test auto-reconnect

1. Turn off the controller (hold PS button for 10 seconds).
2. Wait 5 seconds.
3. Press the **PS button** once.
4. The controller should reconnect automatically (light bar turns solid blue).

If auto-reconnect doesn't work, see the **Troubleshooting** section below.

---

## Step 7: Copy Files to the Pi

### Option A: Using the deploy script (from your Windows PC)

```powershell
# In PowerShell on your PC:
cd "d:\kushal\Downloads D\ROBOCON\R2\Rasberry Pi"
.\deploy_and_run.ps1
```

This copies `r2_pi_ps4.py` to `/home/r1/robot/` on the Pi.

### Option B: Manual SCP

From your Windows PC (PowerShell):

```powershell
scp "d:\kushal\Downloads D\ROBOCON\R2\Rasberry Pi\r2_pi_ps4.py" r1@<PI_IP>:/home/r1/robot/
scp "d:\kushal\Downloads D\ROBOCON\R2\Rasberry Pi\start_r2.sh" r1@<PI_IP>:/home/r1/robot/
scp "d:\kushal\Downloads D\ROBOCON\R2\Rasberry Pi\r2-robot.service" r1@<PI_IP>:/home/r1/robot/
```

---

## Step 8: Test the Script Manually (first time)

SSH into the Pi and run:

```bash
cd /home/r1/robot
python3 r2_pi_ps4.py
```

Make sure:
- ✅ PS4 controller is detected
- ✅ Arduino responds with PONG
- ✅ Robot moves when you push the joystick
- ✅ Pressing `Ctrl+C` stops the script cleanly

---

## Step 9: Set Up Auto-Start Service

This makes the script start **automatically on every boot** — no SSH
or manual commands needed. Just power on the Pi and the robot is ready.

### 9a. Make the launcher script executable

```bash
chmod +x /home/r1/robot/start_r2.sh
```

### 9b. Install the systemd service file

```bash
sudo cp /home/r1/robot/r2-robot.service /etc/systemd/system/
sudo systemctl daemon-reload
```

### 9c. Enable auto-start on boot

```bash
sudo systemctl enable r2-robot
```

### 9d. Start the service now (without rebooting)

```bash
sudo systemctl start r2-robot
```

### 9e. Check that it's running

```bash
sudo systemctl status r2-robot
```

You should see `Active: active (running)` in green.

### 9f. View live logs

```bash
journalctl -u r2-robot -f
```

This shows all `print()` output from the script in real-time.
Press `Ctrl+C` to stop following logs.

### 9g. Reboot and verify

```bash
sudo reboot
```

After reboot, SSH in and check:
```bash
sudo systemctl status r2-robot
journalctl -u r2-robot --no-pager -n 30
```

---

## Step 10: Service Management Cheat Sheet

| Command | What it does |
|---------|--------------|
| `sudo systemctl start r2-robot` | Start the service now |
| `sudo systemctl stop r2-robot` | Stop the service (motors stop) |
| `sudo systemctl restart r2-robot` | Restart (stop then start) |
| `sudo systemctl status r2-robot` | Show status + recent logs |
| `sudo systemctl enable r2-robot` | Enable auto-start on boot |
| `sudo systemctl disable r2-robot` | Disable auto-start |
| `journalctl -u r2-robot -f` | Follow live log output |
| `journalctl -u r2-robot --no-pager -n 100` | Last 100 log lines |
| `journalctl -u r2-robot --since "5 min ago"` | Recent logs |

---

## How Boot Sequence Works

```
Power ON Raspberry Pi
    │
    ├── Linux kernel boots (~10s)
    ├── systemd starts background services
    │     ├── bluetooth.service starts
    │     └── r2-robot.service waits for bluetooth ✓
    │
    ├── Bluetooth ready
    │     └── r2-robot.service starts
    │           ├── start_r2.sh sets SDL_VIDEODRIVER=dummy
    │           └── python3 r2_pi_ps4.py runs
    │                 ├── Waits up to 60s for PS4 controller
    │                 │   (press PS button on controller now)
    │                 ├── Controller connects ✓
    │                 ├── Auto-selects /dev/ttyACM0
    │                 ├── PING → PONG ✓
    │                 └── ROBOT READY (~15-25s from power on)
    │
    └── If script crashes → auto-restart in 3 seconds
```

---

## Files Summary

| File | Purpose | Location on Pi |
|------|---------|----------------|
| `r2_pi_ps4.py` | Main robot controller script | `/home/r1/robot/` |
| `start_r2.sh` | Launcher wrapper (headless pygame) | `/home/r1/robot/` |
| `r2-robot.service` | systemd service config | `/etc/systemd/system/` |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `No serial port found` | Check USB cable. Run `ls /dev/ttyACM*` |
| `Permission denied` on serial | Run `sudo usermod -aG dialout r1` and reboot |
| No controller after 60s | Re-pair: run `sudo bluetoothctl`, then `scan on`, `pair`, `trust`, `connect` |
| Controller connects then disconnects | Install: `sudo apt install joystick`. Test: `jstest /dev/input/js0` |
| Controller won't auto-reconnect | Make sure you ran `trust AA:BB:CC:DD:EE:FF` in bluetoothctl |
| Service won't start | Check logs: `journalctl -u r2-robot --no-pager -n 50` |
| Service starts but controller not found | Press PS button on controller AFTER boot. Script waits 60s. |
| `SDL_Init` error in service mode | Make sure `start_r2.sh` has `export SDL_VIDEODRIVER=dummy` |
| Script works manually but not as service | Check `User=r1` in service file. Check paths match. |
| Want to edit the script | Edit on PC → run `deploy_and_run.ps1` → restart service: `sudo systemctl restart r2-robot` |
