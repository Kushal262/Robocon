import tkinter as tk
from tkinter import ttk, messagebox
import serial
import serial.tools.list_ports
import threading
import time

NUM_SERVOS = 6

# Accent colours for each servo (to tell them apart at a glance)
SERVO_COLORS = [
    "#7c6af7",   # purple
    "#f76a8a",   # pink
    "#6af7c1",   # mint
    "#f7b96a",   # orange
    "#6ab4f7",   # blue
    "#f7e16a",   # yellow
]


class ServoController:
    def __init__(self, root):
        self.root = root
        self.root.title("6-Servo Controller  |  Arduino Mega")
        self.root.geometry("960x830")
        self.root.resizable(False, False)
        self.root.configure(bg="#1e1e2e")

        self.serial_conn = None
        self.connected = False
        self._propagating = False   # recursion guard for link updates

        # Per-servo state
        self.sliders      = [None] * NUM_SERVOS
        self.angle_labels = [None] * NUM_SERVOS
        self.angle_entries= [None] * NUM_SERVOS
        self.range_vars   = [None] * NUM_SERVOS   # StringVar "180" or "270"
        self.max_labels   = [None] * NUM_SERVOS   # label showing max on slider

        # Link state
        self.link_vars    = [None] * NUM_SERVOS   # StringVar: "None","Servo 1",…
        self.mode_vars    = [None] * NUM_SERVOS   # StringVar: "Pair","Mirror"
        self.link_status  = [None] * NUM_SERVOS   # Label showing link info

        self.build_ui()

    # ================================================================
    #  UI
    # ================================================================
    def build_ui(self):
        BG    = "#1e1e2e"
        CARD  = "#2a2a3e"
        TXT   = "#e0e0f0"
        MUTED = "#888aaa"
        ACC   = "#7c6af7"

        # ── Title ──────────────────────────────────────────────
        tk.Label(self.root, text="6-Servo Controller",
                 font=("Segoe UI", 18, "bold"),
                 bg=BG, fg=TXT).pack(pady=(14, 2))

        tk.Label(self.root,
                 text="RDS5160  |  180° / 270° per channel  |  Pair & Mirror linking",
                 font=("Segoe UI", 9), bg=BG, fg=MUTED).pack()

        # ── Connection Card ────────────────────────────────────
        conn_frame = tk.Frame(self.root, bg=CARD, bd=0, relief="flat")
        conn_frame.pack(fill="x", padx=24, pady=(12, 6))

        inner = tk.Frame(conn_frame, bg=CARD)
        inner.pack(fill="x", padx=16, pady=10)

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
                              sticky="w", pady=(6, 0))

        self.refresh_ports()

        # ── Servo Grid  (2 columns × 3 rows) ──────────────────
        grid_frame = tk.Frame(self.root, bg=BG)
        grid_frame.pack(fill="both", expand=True, padx=24, pady=4)

        for idx in range(NUM_SERVOS):
            row = idx // 2
            col = idx % 2
            self._build_servo_card(grid_frame, idx, row, col)

        # ── Log ────────────────────────────────────────────────
        log_frame = tk.Frame(self.root, bg=CARD)
        log_frame.pack(fill="x", padx=24, pady=(4, 12))

        self.log = tk.Text(log_frame, height=3, bg=CARD, fg=MUTED,
                           font=("Consolas", 9), relief="flat",
                           state="disabled", wrap="word")
        self.log.pack(fill="x", padx=8, pady=8)

        self.log_msg("System ready. Connect Arduino and press Connect.")

    # ── Build one servo card ───────────────────────────────────
    def _build_servo_card(self, parent, idx, row, col):
        CARD  = "#2a2a3e"
        TXT   = "#e0e0f0"
        MUTED = "#888aaa"
        color = SERVO_COLORS[idx]

        card = tk.Frame(parent, bg=CARD)
        card.grid(row=row, column=col, padx=6, pady=4, sticky="nsew")
        parent.columnconfigure(col, weight=1)
        parent.rowconfigure(row, weight=1)

        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="both", expand=True, padx=12, pady=8)

        # ── Header row: title + range selector ────────────────
        hdr = tk.Frame(inner, bg=CARD)
        hdr.pack(fill="x")

        tk.Label(hdr, text=f"Servo {idx + 1}",
                 font=("Segoe UI", 11, "bold"),
                 bg=CARD, fg=color).pack(side="left")

        tk.Label(hdr, text=f"Pin {[2,3,4,5,6,7][idx]}",
                 font=("Segoe UI", 8), bg=CARD, fg=MUTED
                 ).pack(side="left", padx=(8, 0))

        # Range dropdown (180 / 270)
        range_var = tk.StringVar(value="270")
        self.range_vars[idx] = range_var

        range_combo = ttk.Combobox(hdr, textvariable=range_var,
                                   values=["180", "270"], width=4,
                                   state="readonly",
                                   font=("Segoe UI", 9))
        range_combo.pack(side="right")
        range_combo.bind("<<ComboboxSelected>>",
                         lambda e, i=idx: self._on_range_change(i))

        tk.Label(hdr, text="Range °:", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side="right", padx=(0, 4))

        # ── Angle display ─────────────────────────────────────
        self.angle_labels[idx] = tk.Label(inner, text="0°",
                                          font=("Segoe UI", 22, "bold"),
                                          bg=CARD, fg=color)
        self.angle_labels[idx].pack(pady=(2, 0))

        # ── Slider ────────────────────────────────────────────
        slider = tk.Scale(inner, from_=0, to=270,
                          orient="horizontal", length=350,
                          bg=CARD, fg=TXT, troughcolor="#3a3a50",
                          highlightthickness=0, bd=0,
                          activebackground=color,
                          font=("Segoe UI", 8),
                          command=lambda v, i=idx: self._on_slider(i, v),
                          resolution=1, showvalue=False)
        slider.pack(fill="x", pady=(2, 0))
        self.sliders[idx] = slider

        # Min / Max labels
        lbl_row = tk.Frame(inner, bg=CARD)
        lbl_row.pack(fill="x")
        tk.Label(lbl_row, text="0°", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 8)).pack(side="left")
        max_lbl = tk.Label(lbl_row, text="270°", bg=CARD, fg=MUTED,
                           font=("Segoe UI", 8))
        max_lbl.pack(side="right")
        self.max_labels[idx] = max_lbl

        # ── Entry + Send row ──────────────────────────────────
        entry_row = tk.Frame(inner, bg=CARD)
        entry_row.pack(fill="x", pady=(2, 0))

        entry = tk.Entry(entry_row, width=5,
                         font=("Segoe UI", 10, "bold"),
                         justify="center", bg="#3a3a50", fg=TXT,
                         insertbackground=TXT, relief="flat")
        entry.pack(side="left")
        entry.insert(0, "0")
        entry.bind("<Return>", lambda e, i=idx: self._on_entry_send(i))
        self.angle_entries[idx] = entry

        tk.Button(entry_row, text="Send",
                  command=lambda i=idx: self._on_entry_send(i),
                  bg=color, fg="white", relief="flat",
                  padx=10, font=("Segoe UI", 9, "bold"),
                  cursor="hand2",
                  activebackground="#6a58e0",
                  activeforeground="white"
                  ).pack(side="left", padx=(6, 0))

        # Quick presets
        self._build_presets(inner, idx, 270, color)

        # ── Link Controls ─────────────────────────────────────
        sep = tk.Frame(inner, bg="#3a3a50", height=1)
        sep.pack(fill="x", pady=(6, 4))

        link_frame = tk.Frame(inner, bg=CARD)
        link_frame.pack(fill="x")

        tk.Label(link_frame, text="🔗", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side="left")

        # Link-to dropdown
        link_var = tk.StringVar(value="None")
        self.link_vars[idx] = link_var

        link_options = ["None"] + [f"Servo {i+1}" for i in range(NUM_SERVOS) if i != idx]
        link_combo = ttk.Combobox(link_frame, textvariable=link_var,
                                  values=link_options, width=8,
                                  state="readonly", font=("Segoe UI", 8))
        link_combo.pack(side="left", padx=(4, 4))
        link_combo.bind("<<ComboboxSelected>>",
                        lambda e, i=idx: self._on_link_change(i))

        # Mode dropdown
        mode_var = tk.StringVar(value="Pair")
        self.mode_vars[idx] = mode_var

        mode_combo = ttk.Combobox(link_frame, textvariable=mode_var,
                                  values=["Pair", "Mirror"], width=6,
                                  state="readonly", font=("Segoe UI", 8))
        mode_combo.pack(side="left", padx=(0, 4))
        mode_combo.bind("<<ComboboxSelected>>",
                        lambda e, i=idx: self._on_mode_change(i))

        # Status label
        status_lbl = tk.Label(link_frame, text="Independent",
                              bg=CARD, fg=MUTED, font=("Segoe UI", 8))
        status_lbl.pack(side="left", padx=(4, 0))
        self.link_status[idx] = status_lbl

    def _build_presets(self, parent, idx, max_angle, color):
        """Create a row of preset buttons for the given max angle."""
        TXT = "#e0e0f0"

        # Remove old preset frame if it exists
        tag = f"_preset_frame_{idx}"
        old = getattr(self, tag, None)
        if old:
            old.destroy()

        preset_frame = tk.Frame(parent, bg="#2a2a3e")
        preset_frame.pack(fill="x", pady=(2, 0))
        setattr(self, tag, preset_frame)

        if max_angle == 180:
            angles = [0, 30, 60, 90, 120, 150, 180]
        else:
            angles = [0, 45, 90, 135, 180, 225, 270]

        for a in angles:
            tk.Button(preset_frame, text=f"{a}°",
                      command=lambda ang=a, i=idx: self.send_angle(i, ang),
                      bg="#3a3a50", fg=TXT, relief="flat",
                      padx=5, pady=1, font=("Segoe UI", 8),
                      cursor="hand2",
                      activebackground=color,
                      activeforeground="white"
                      ).pack(side="left", padx=2)

    # ================================================================
    #  Range change
    # ================================================================
    def _on_range_change(self, idx):
        new_max = int(self.range_vars[idx].get())
        self.sliders[idx].config(to=new_max)
        self.max_labels[idx].config(text=f"{new_max}°")

        # Clamp current value
        cur = self.sliders[idx].get()
        if cur > new_max:
            self.sliders[idx].set(new_max)

        # Rebuild presets
        color = SERVO_COLORS[idx]
        inner = self.sliders[idx].master
        self._build_presets(inner, idx, new_max, color)

        self.log_msg(f"Servo {idx+1} range → {new_max}°")

    # ================================================================
    #  Link controls
    # ================================================================
    def _on_link_change(self, idx):
        link_to = self.link_vars[idx].get()
        if link_to == "None":
            self.link_status[idx].config(text="Independent", fg="#888aaa")
            self.log_msg(f"Servo {idx+1}: unlinked")
            return

        target_idx = int(link_to.split()[1]) - 1

        # Block circular references
        if self._would_create_cycle(idx, target_idx):
            self.link_vars[idx].set("None")
            self.link_status[idx].config(text="⚠ Circular!", fg="#ff5f5f")
            self.log_msg(f"Servo {idx+1}: circular link blocked!")
            messagebox.showwarning("Circular Link",
                f"Cannot link Servo {idx+1} → {link_to}.\n"
                "This would create a circular chain.")
            self.root.after(2000,
                lambda: self.link_status[idx].config(
                    text="Independent", fg="#888aaa"))
            return

        mode = self.mode_vars[idx].get()
        self.link_status[idx].config(
            text=f"→ {link_to} ({mode})", fg="#5fdf8f")
        self.log_msg(f"Servo {idx+1}: linked → {link_to} ({mode})")

        # Immediately sync to leader
        self._sync_follower(idx)

    def _on_mode_change(self, idx):
        link_to = self.link_vars[idx].get()
        if link_to != "None":
            mode = self.mode_vars[idx].get()
            self.link_status[idx].config(text=f"→ {link_to} ({mode})")
            self.log_msg(f"Servo {idx+1}: mode → {mode}")
            self._sync_follower(idx)

    def _would_create_cycle(self, follower_idx, leader_idx):
        """Check if linking follower→leader would create a circular chain."""
        visited = set()
        current = leader_idx
        while current is not None:
            if current == follower_idx:
                return True
            if current in visited:
                return False
            visited.add(current)
            link_to = self.link_vars[current].get()
            if link_to == "None":
                current = None
            else:
                current = int(link_to.split()[1]) - 1
        return False

    def _sync_follower(self, follower_idx):
        """Immediately sync a follower servo to its leader's current angle."""
        link_to = self.link_vars[follower_idx].get()
        if link_to == "None":
            return

        leader_idx = int(link_to.split()[1]) - 1
        leader_angle = self.sliders[leader_idx].get()
        leader_max = int(self.range_vars[leader_idx].get())
        follower_max = int(self.range_vars[follower_idx].get())
        mode = self.mode_vars[follower_idx].get()

        follower_angle = self._calc_follower_angle(
            leader_angle, leader_max, follower_max, mode)

        # Update follower UI + send serial (no further propagation)
        self._update_servo_ui(follower_idx, follower_angle)
        self._serial_send(follower_idx, follower_angle)

    def _calc_follower_angle(self, leader_angle, leader_max, follower_max, mode):
        """Calculate follower angle from leader angle based on mode."""
        ratio = leader_angle / leader_max if leader_max > 0 else 0

        if mode == "Pair":
            return int(ratio * follower_max)
        elif mode == "Mirror":
            return int((1.0 - ratio) * follower_max)
        return 0

    def _propagate_to_followers(self, leader_idx, updated=None):
        """Recursively update all servos that follow this leader."""
        if updated is None:
            updated = {leader_idx}

        leader_angle = self.sliders[leader_idx].get()
        leader_max = int(self.range_vars[leader_idx].get())

        for i in range(NUM_SERVOS):
            if i in updated:
                continue
            link_to = self.link_vars[i].get()
            if link_to == f"Servo {leader_idx + 1}":
                updated.add(i)
                follower_max = int(self.range_vars[i].get())
                mode = self.mode_vars[i].get()
                follower_angle = self._calc_follower_angle(
                    leader_angle, leader_max, follower_max, mode)

                self._update_servo_ui(i, follower_angle)
                self._serial_send(i, follower_angle)

                # Chain: this follower may also be a leader
                self._propagate_to_followers(i, updated)

    def _update_servo_ui(self, idx, angle):
        """Update slider, label, entry for a servo without triggering callbacks."""
        self._propagating = True
        self.sliders[idx].set(angle)
        self._propagating = False
        self.angle_labels[idx].config(text=f"{angle}°")
        self.angle_entries[idx].delete(0, "end")
        self.angle_entries[idx].insert(0, str(angle))

    # ================================================================
    #  Slider / Entry callbacks
    # ================================================================
    def _on_slider(self, idx, val):
        if self._propagating:
            return
        angle = int(float(val))
        self.angle_labels[idx].config(text=f"{angle}°")
        self.angle_entries[idx].delete(0, "end")
        self.angle_entries[idx].insert(0, str(angle))
        self._serial_send(idx, angle)
        self._propagate_to_followers(idx)

    def _on_entry_send(self, idx, event=None):
        max_angle = int(self.range_vars[idx].get())
        try:
            angle = int(self.angle_entries[idx].get())
            if 0 <= angle <= max_angle:
                self.send_angle(idx, angle)
            else:
                messagebox.showwarning("Out of Range",
                                       f"Enter 0 – {max_angle} for Servo {idx+1}.")
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter a number.")

    # ================================================================
    #  Angle sending
    # ================================================================
    def send_angle(self, idx, angle):
        """Update UI widgets, push to Arduino, and propagate to followers."""
        self._update_servo_ui(idx, angle)
        self._serial_send(idx, angle, log=True)
        self._propagate_to_followers(idx)

    def _serial_send(self, idx, angle, log=False):
        """Low-level send:  <id>,<angle>,<max_angle>\n"""
        max_angle = int(self.range_vars[idx].get())
        if self.connected and self.serial_conn:
            try:
                msg = f"{idx},{angle},{max_angle}\n"
                self.serial_conn.write(msg.encode())
                if log:
                    self.log_msg(f"Servo {idx+1}: sent {angle}° (range {max_angle}°)")
            except Exception as e:
                self.log_msg(f"Error: {e}")
        else:
            if log:
                self.log_msg("Not connected — angle not sent.")

    # ================================================================
    #  Connection
    # ================================================================
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