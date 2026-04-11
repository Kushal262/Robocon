import tkinter as tk
from tkinter import ttk, messagebox
import serial
import serial.tools.list_ports
import threading
import time

class ServoController:
    def __init__(self, root):
        self.root = root
        self.root.title("RDS5160 Dual Servo Controller")
        self.root.geometry("520x480")
        self.root.resizable(False, False)
        self.root.configure(bg="#1e1e2e")

        self.serial_conn = None
        self.connected = False
        self.current_angle = 0

        self.build_ui()

    def build_ui(self):
        BG    = "#1e1e2e"
        CARD  = "#2a2a3e"
        ACC   = "#7c6af7"
        TXT   = "#e0e0f0"
        MUTED = "#888aaa"

        # ── Title ──────────────────────────────────────────────
        tk.Label(self.root, text="RDS5160 Dual Servo Controller",
                 font=("Segoe UI", 16, "bold"),
                 bg=BG, fg=TXT).pack(pady=(20, 4))

        tk.Label(self.root, text="60 kg·cm  |  0° – 270°  |  7.4V 2S  |  Arduino Mega",
                 font=("Segoe UI", 9), bg=BG, fg=MUTED).pack()

        # ── Connection Card ────────────────────────────────────
        conn_frame = tk.Frame(self.root, bg=CARD, bd=0, relief="flat")
        conn_frame.pack(fill="x", padx=24, pady=(18, 10))

        inner = tk.Frame(conn_frame, bg=CARD)
        inner.pack(fill="x", padx=16, pady=12)

        tk.Label(inner, text="COM Port:", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 10)).grid(row=0, column=0, sticky="w")

        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(inner, textvariable=self.port_var,
                                       width=12, state="readonly",
                                       font=("Segoe UI", 10))
        self.port_combo.grid(row=0, column=1, padx=(8, 6))

        tk.Button(inner, text="Refresh", command=self.refresh_ports,
                  bg="#3a3a50", fg=TXT, relief="flat", padx=8,
                  font=("Segoe UI", 9), cursor="hand2",
                  activebackground="#4a4a60", activeforeground=TXT
                  ).grid(row=0, column=2, padx=4)

        self.conn_btn = tk.Button(inner, text="Connect",
                                  command=self.toggle_connection,
                                  bg=ACC, fg="white", relief="flat",
                                  padx=14, font=("Segoe UI", 9, "bold"),
                                  cursor="hand2",
                                  activebackground="#6a58e0",
                                  activeforeground="white")
        self.conn_btn.grid(row=0, column=3, padx=(6, 0))

        self.status_dot = tk.Label(inner, text="●  Disconnected",
                                   bg=CARD, fg="#ff5f5f",
                                   font=("Segoe UI", 9))
        self.status_dot.grid(row=1, column=0, columnspan=4,
                              sticky="w", pady=(8, 0))

        self.refresh_ports()

        # ── Angle Slider Card ──────────────────────────────────
        ctrl_frame = tk.Frame(self.root, bg=CARD)
        ctrl_frame.pack(fill="x", padx=24, pady=6)

        inner2 = tk.Frame(ctrl_frame, bg=CARD)
        inner2.pack(fill="x", padx=16, pady=16)

        # Angle display
        self.angle_label = tk.Label(inner2, text="0°",
                                    font=("Segoe UI", 42, "bold"),
                                    bg=CARD, fg=ACC)
        self.angle_label.pack()

        tk.Label(inner2, text="Target Angle", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 9)).pack()

        # Slider
        self.slider = tk.Scale(inner2, from_=0, to=270,
                               orient="horizontal", length=420,
                               bg=CARD, fg=TXT, troughcolor="#3a3a50",
                               highlightthickness=0, bd=0,
                               activebackground=ACC,
                               font=("Segoe UI", 9),
                               command=self.on_slider_change,
                               resolution=1)
        self.slider.pack(pady=(10, 0))

        # Min / Max labels
        lbl_row = tk.Frame(inner2, bg=CARD)
        lbl_row.pack(fill="x")
        tk.Label(lbl_row, text="0°", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side="left")
        tk.Label(lbl_row, text="270°", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side="right")

        # ── Manual Entry ───────────────────────────────────────
        entry_frame = tk.Frame(self.root, bg=BG)
        entry_frame.pack(pady=6)

        tk.Label(entry_frame, text="Type angle:",
                 bg=BG, fg=MUTED, font=("Segoe UI", 10)
                 ).pack(side="left", padx=(0, 8))

        self.angle_entry = tk.Entry(entry_frame, width=6,
                                    font=("Segoe UI", 13, "bold"),
                                    justify="center",
                                    bg=CARD, fg=TXT,
                                    insertbackground=TXT,
                                    relief="flat")
        self.angle_entry.pack(side="left")
        self.angle_entry.insert(0, "0")
        self.angle_entry.bind("<Return>", self.on_entry_send)

        tk.Button(entry_frame, text="Send",
                  command=self.on_entry_send,
                  bg=ACC, fg="white", relief="flat",
                  padx=14, font=("Segoe UI", 10, "bold"),
                  cursor="hand2",
                  activebackground="#6a58e0",
                  activeforeground="white"
                  ).pack(side="left", padx=(8, 0))

        # ── Preset Buttons ─────────────────────────────────────
        preset_frame = tk.Frame(self.root, bg=BG)
        preset_frame.pack(pady=8)

        tk.Label(preset_frame, text="Presets:", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 10))

        for angle in [0, 45, 90, 135, 180, 225, 270]:
            tk.Button(preset_frame, text=f"{angle}°",
                      command=lambda a=angle: self.send_angle(a),
                      bg="#3a3a50", fg=TXT, relief="flat",
                      padx=10, pady=4, font=("Segoe UI", 9),
                      cursor="hand2",
                      activebackground=ACC,
                      activeforeground="white"
                      ).pack(side="left", padx=3)

        # ── Log ────────────────────────────────────────────────
        log_frame = tk.Frame(self.root, bg=CARD)
        log_frame.pack(fill="both", expand=True, padx=24, pady=(6, 18))

        self.log = tk.Text(log_frame, height=5, bg=CARD, fg=MUTED,
                           font=("Consolas", 9), relief="flat",
                           state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, padx=8, pady=8)

        self.log_msg("System ready. Connect Arduino and press Connect.")

    # ── Port helpers ───────────────────────────────────────────
    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_combo["values"] = ports
        if ports:
            self.port_combo.set(ports[0])
        else:
            self.port_combo.set("")

    def toggle_connection(self):
        if self.connected:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        port = self.port_var.get()
        if not port:
            messagebox.showerror("Error", "No COM port selected.")
            return
        try:
            self.serial_conn = serial.Serial(port, 9600, timeout=2)
            time.sleep(2)            # wait for Arduino reset
            self.connected = True
            self.conn_btn.config(text="Disconnect", bg="#e05f5f")
            self.status_dot.config(text="●  Connected", fg="#5fdf8f")
            self.log_msg(f"Connected to {port} @ 9600 baud")
            threading.Thread(target=self.read_serial, daemon=True).start()
        except Exception as e:
            messagebox.showerror("Connection Error", str(e))

    def disconnect(self):
        self.connected = False
        if self.serial_conn:
            self.serial_conn.close()
        self.conn_btn.config(text="Connect", bg="#7c6af7")
        self.status_dot.config(text="●  Disconnected", fg="#ff5f5f")
        self.log_msg("Disconnected.")

    # ── Serial read thread ─────────────────────────────────────
    def read_serial(self):
        while self.connected:
            try:
                if self.serial_conn.in_waiting:
                    line = self.serial_conn.readline().decode().strip()
                    if line:
                        self.log_msg(f"Arduino: {line}")
            except:
                break

    # ── Angle sending ──────────────────────────────────────────
    def send_angle(self, angle):
        self.slider.set(angle)
        self.angle_label.config(text=f"{angle}°")
        self.angle_entry.delete(0, "end")
        self.angle_entry.insert(0, str(angle))
        if self.connected and self.serial_conn:
            try:
                msg = f"{angle}\n"
                self.serial_conn.write(msg.encode())
                self.log_msg(f"Sent angle: {angle}°")
            except Exception as e:
                self.log_msg(f"Error: {e}")
        else:
            self.log_msg("Not connected — angle not sent.")

    def on_slider_change(self, val):
        angle = int(float(val))
        self.angle_label.config(text=f"{angle}°")
        self.angle_entry.delete(0, "end")
        self.angle_entry.insert(0, str(angle))
        if self.connected and self.serial_conn:
            try:
                self.serial_conn.write(f"{angle}\n".encode())
            except:
                pass

    def on_entry_send(self, event=None):
        try:
            angle = int(self.angle_entry.get())
            if 0 <= angle <= 270:
                self.send_angle(angle)
            else:
                messagebox.showwarning("Out of Range",
                                       "Enter a value between 0 and 270.")
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter a number.")

    # ── Log helper ─────────────────────────────────────────────
    def log_msg(self, msg):
        self.log.config(state="normal")
        self.log.insert("end", f"» {msg}\n")
        self.log.see("end")
        self.log.config(state="disabled")


if __name__ == "__main__":
    root = tk.Tk()
    app = ServoController(root)
    root.mainloop()