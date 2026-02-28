import pygame
import time

def main():
    pygame.init()
    pygame.joystick.init()

    if pygame.joystick.get_count() == 0:
        print("[ERROR] No controller detected. Please connect it first.")
        return

    js = pygame.joystick.Joystick(0)
    js.init()
    
    print("=" * 50)
    print(f"Controller Connected: {js.get_name()}")
    num_buttons = js.get_numbuttons()
    print(f"Number of buttons detected: {num_buttons}")
    print("=" * 50)
    print("\nPress the L1 and R1 buttons on your controller.")
    print("Watch the terminal to see which button numbers light up!")
    print("\nPress Ctrl+C to quit.\n")

    try:
        while True:
            pygame.event.pump()
            
            # Check all buttons and see which ones are currently pressed
            pressed = []
            for i in range(num_buttons):
                if js.get_button(i):
                    pressed.append(str(i))
            
            if pressed:
                print(f"\rButtons currently pressed: {', '.join(pressed)}          ", end="", flush=True)
            else:
                print("\rWaiting for button press...                        ", end="", flush=True)
                
            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n\nDone.")
    finally:
        pygame.quit()

if __name__ == "__main__":
    main()
