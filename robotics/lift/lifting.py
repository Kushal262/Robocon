import pygame
import serial
import time

# ===== SERIAL =====
arduino = serial.Serial('COM12', 115200, timeout=1)
time.sleep(2)

# ===== PYGAME =====
pygame.init()
pygame.joystick.init()

joy = pygame.joystick.Joystick(0)
joy.init()

print("Controller connected")

UP_SPEED = 800
DOWN_SPEED = -800

while True:
    pygame.event.pump()

    # ---- R1 (most systems use button 5) ----
    r1_axis = joy.get_axis(4)
    r1 = ((r1_axis + 1) / 2) > 0.2
    # ---- R2 trigger (most systems axis 5) ----
    r2_axis = joy.get_axis(5)
    r2 = ((r2_axis + 1) / 2) > 0.2

    # ---- CONTROL ----
    if r1:
        speed = UP_SPEED
        print("R1 PRESSED → UP")

    elif r2:
        speed = DOWN_SPEED
        print("R2 PRESSED → DOWN")

    else:
        speed = 0
        print("STOP")

    arduino.write((str(speed) + "\n").encode())
    time.sleep(0.05)