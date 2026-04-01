#!/bin/bash
# ============================================
#  R2 Robot — Launcher script for systemd service
#  This wrapper sets up the environment so pygame
#  works headless (no monitor/keyboard needed).
# ============================================

# Tell SDL/pygame to use dummy video driver (no monitor needed)
export SDL_VIDEODRIVER=dummy

# Ensure we're in the right directory
cd /home/r1/Desktop/ROBOCON_pi

# Run the robot control script using the R2 virtual environment
# 'exec' replaces this shell with Python — cleaner for systemd
exec /home/r1/Desktop/ROBOCON_pi/R2/bin/python3 r2_pi_ps4.py
