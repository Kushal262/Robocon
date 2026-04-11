import serial
import time

# CHANGE THIS to match the Arduino Mega's port (e.g., 'COM3' on Windows, '/dev/ttyACM0' on Linux/Raspberry Pi)
PORT = 'COM4' 
BAUD_RATE = 9600

def connect_to_arduino(port):
    try:
        print(f"Connecting to Arduino on {port}...")
        arduino = serial.Serial(port, BAUD_RATE, timeout=2)
        time.sleep(2)  # Wait for Arduino to reset upon connection
        print("Connected!")
        # Clear out any startup messages from Arduino
        while arduino.in_waiting > 0:
            msg = arduino.readline().decode('utf-8').strip()
            print("Arduino Boot Message:", msg)
        return arduino
    except Exception as e:
        print(f"Failed to connect: {e}")
        return None

def move_servo(arduino, angle):
    print(f"\nCommanding servo to {angle}°")
    # Send angle followed by a newline so the Arduino knows the command is complete
    command = f"{angle}\n"
    arduino.write(command.encode('utf-8'))
    
    # Wait and read the response
    time.sleep(0.1)
    if arduino.in_waiting > 0:
        response = arduino.readline().decode('utf-8').strip()
        print(f"Arduino replied: {response}")

if __name__ == "__main__":
    arduino = connect_to_arduino(PORT)
    
    if arduino:
        try:
            while True:
                user_input = input("\nEnter angle (0-270) or 'q' to quit: ")
                if user_input.lower() == 'q':
                    break
                
                try:
                    angle = int(user_input)
                    if 0 <= angle <= 270:
                        move_servo(arduino, angle)
                    else:
                        print("Please enter a number between 0 and 270.")
                except ValueError:
                    print("Invalid input! Please enter an integer.")
        except KeyboardInterrupt:
            print("\nExiting...")
        finally:
            arduino.close()
            print("Connection closed.")
