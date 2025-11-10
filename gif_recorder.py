import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import ImageTk, Image, ImageDraw, ImageFont
import threading
import time
import os
import tempfile
import imageio.v2 as imageio
import numpy as np
import dxcam
from pynput import keyboard, mouse
from pystray import Icon, Menu, MenuItem
import sys
import subprocess
from functools import partial
import json
from collections import deque
import queue
from datetime import datetime
import shutil
import traceback
import psutil

# --- Configuration ---
DEFAULT_RECORD_DURATION = 20
current_record_duration = DEFAULT_RECORD_DURATION
FPS = 20
HOTKEY = "shift+f12"
NOTIFICATION_TITLE = "Gif Recorder"

# --- Helper Functions ---
def set_dark_title_bar(window):
    if sys.platform == 'win32':
        try:
            import ctypes
            window.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            value = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value))
        except Exception as e:
            print(f"Failed to set dark title bar: {e}")

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)

ICON_PATH = resource_path("icon.ico")
SPLASH_SCREEN_PATH = resource_path("SplashScreen.png")
EYE_ICON_PATH = resource_path("eye.png")
AW_ICON_PATH = resource_path("Icons/AW.png")
REC_ICON_PATH = resource_path("Icons/REC.png")
SPLASH_SCREEN_DURATION_MS = 2000

# --- Global Variables ---
camera = None
frames_buffer = None
buffer_lock = threading.Lock()
running = True
is_selecting_region = False
shortcut_window = None
root_for_windows = None
icon = None
drag_start_x, drag_start_y = 0, 0
gui_queue = queue.Queue()
is_shortcut_window_visible = False
shortcut_window_x, shortcut_window_y = None, None
projects_path = None
gallery_window = None
notification_window = None
notification_timer_id = None
selected_monitor_index = 0
capture_mode = 'replay'  # 'replay' or 'autowatch'
autowatch_rules = []
autowatch_last_prompt = {}
autowatch_last_capture = {}
autowatch_capture_in_progress = {}
autowatch_config_window = None
autowatch_is_available = False # Flag for menu state
kpm_events_history = deque() # Stores timestamps of keyboard/mouse events
pressed_keys = set()
pressed_mouse_buttons = set()
keyboard_listener = None
mouse_listener = None
hotkey_listener = None


# Icon PhotoImage objects
eye_photo_image_original = None
aw_photo_image = None
rec_photo_image = None
current_shortcut_icon_id = None # To track the currently displayed icon on canvas
manual_capture_in_progress = False # New flag for manual capture

# Auto-Watch Trigger and Cooldown Options
TRIGGER_OPTIONS = ['Q', 'S', 'D', 'Z', 'A', 'E', '1', '2', '3', '4', '5', 'Enter', 'Space', 'Click Droit', 'Click Gauche', 'Click Milieu', 'Shift', 'Alt', 'Ctrl', '[KPM > 70]', '[KPM > 100]', '[KPM > 200]', '[KPM > 300]']
COOLDOWN_OPTIONS = [1, 2, 3, 4, 5] # in minutes


# --- Auto-Watch ---
class AutoWatchConfigWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Configurer l'Auto-Watch")
        self.geometry("800x500")
        self.config(bg="#2E2E2E")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        set_dark_title_bar(self)

        # Configure ttk styles for dark theme
        style = ttk.Style()
        style.theme_use('clam') # 'clam' theme is easier to customize
        style.configure("Treeview", 
                        background="#1E1E1E", 
                        foreground="white", 
                        fieldbackground="#1E1E1E",
                        rowheight=25)
        style.map('Treeview', 
                  background=[('selected', '#0078D7')],
                  foreground=[('selected', 'white')])
        style.configure("Treeview.Heading", 
                        background="#3E3E3E", 
                        foreground="white", 
                        font=('Arial', 10, 'bold'))
        style.configure("TCombobox", 
                        fieldbackground="#1E1E1E", 
                        background="#3E3E3E", 
                        foreground="white",
                        selectbackground="#0078D7",
                        selectforeground="white")
        style.map('TCombobox',
                  fieldbackground=[('readonly', '#1E1E1E')],
                  selectbackground=[('readonly', '#0078D7')],
                  selectforeground=[('readonly', 'white')])
        style.configure("TButton",
                        background="#4E4E4E",
                        font=('Arial', 10))
        style.map("TButton",
                  background=[('active', '#6E6E6E')])


        explanation = ("Le menu Auto-Watch vous permet de sélectionner un exécutable dont le lancement sera surveillé.\n" 
                       "Puis une touche de votre clavier ou de votre souris que vous effectuez régulièrement dans votre application\n" 
                       "afin de déclencher une mini capture vidéo la séquence sans que vous n'ayez besoin d'y songer.")
        tk.Label(self, text=explanation, bg="#2E2E2E", fg="white", justify=tk.LEFT).pack(pady=10, padx=10, anchor="w")

        # Frame for Treeview and Scrollbar
        tree_frame = tk.Frame(self, bg="#2E2E2E")
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.treeview = ttk.Treeview(tree_frame, columns=("Executable", "Trigger", "Cooldown"), show="headings", style="Treeview")
        self.treeview.heading("Executable", text="Exécutable")
        self.treeview.heading("Trigger", text="Déclencheur")
        self.treeview.heading("Cooldown", text="Cooldown (min)")

        self.treeview.column("Executable", width=300, anchor=tk.W)
        self.treeview.column("Trigger", width=150, anchor=tk.CENTER)
        self.treeview.column("Cooldown", width=100, anchor=tk.CENTER)
        
        self.treeview.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Scrollbar for Treeview
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.treeview.yview)
        self.treeview.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Bind click event for editing
        self.treeview.bind("<Button-1>", self.on_treeview_click)

        btn_frame = tk.Frame(self, bg="#2E2E2E")
        btn_frame.pack(fill=tk.X, pady=10, padx=10)
        tk.Button(btn_frame, text="Ajouter...", command=self.add_rule, fg="white", bg="#4E4E4E", relief=tk.FLAT).pack(side=tk.LEFT)
        tk.Button(btn_frame, text="Supprimer", command=self.remove_rule, fg="white", bg="#dc3545", relief=tk.FLAT).pack(side=tk.LEFT, padx=5)

        self.refresh_rules()

    def refresh_rules(self):
        for i in self.treeview.get_children():
            self.treeview.delete(i)
        for idx, rule in enumerate(autowatch_rules):
            self.treeview.insert("", tk.END, iid=str(idx), values=(rule['exe'], rule['trigger'], rule['cooldown']))

    def add_rule(self):
        # Add a new default rule
        new_rule = {'exe': 'path/to/your/app.exe', 'trigger': 'Click Gauche', 'cooldown': 1, 'before_seconds': 4, 'after_seconds': 6, 'kpm_threshold': 100}
        autowatch_rules.append(new_rule)
        save_config()
        self.refresh_rules()

    def remove_rule(self):
        selected_items = self.treeview.selection()
        if not selected_items:
            messagebox.showinfo("Sélection requise", "Veuillez sélectionner une règle à supprimer.")
            return
        
        if messagebox.askyesno("Confirmer la suppression", "Voulez-vous vraiment supprimer la règle sélectionnée ?"):
            # Remove from autowatch_rules list
            # Iterate in reverse to avoid index issues after deletion
            for item_id in reversed(selected_items):
                index = int(item_id)
                if 0 <= index < len(autowatch_rules):
                    autowatch_rules.pop(index)
            save_config()
            self.refresh_rules()

    def on_treeview_click(self, event):
        # Identify the clicked item and column
        item_id = self.treeview.identify_row(event.y)
        column_id = self.treeview.identify_column(event.x)
        
        if not item_id: return

        # Get the index of the rule in the autowatch_rules list
        rule_index = int(item_id)
        if not (0 <= rule_index < len(autowatch_rules)): return

        # Get the column name
        col_name = self.treeview.heading(column_id, "text")

        # Get the bounding box of the cell
        x, y, width, height = self.treeview.bbox(item_id, column_id)

        # Column 1: Executable
        if col_name == "Exécutable":
            file_path = filedialog.askopenfilename(title="Sélectionner un exécutable", filetypes=[("Executable files", "*.exe")])
            if file_path:
                autowatch_rules[rule_index]['exe'] = file_path
                save_config()
                self.refresh_rules()
        
        # Column 2: Trigger
        elif col_name == "Déclencheur":
            # Create a Combobox for dropdown selection
            current_value = autowatch_rules[rule_index]['trigger']
            
            # Position the combobox over the cell
            cb = ttk.Combobox(self.treeview, values=TRIGGER_OPTIONS, state="readonly", style="TCombobox")
            cb.set(current_value)
            cb.place(x=x, y=y, width=width, height=height)
            cb.update_idletasks() # Force update to ensure correct positioning
            cb.focus_set()
            cb.event_generate('<Button-1>') # Simulate a click to open dropdown immediately

            def on_select(event):
                selected_trigger = cb.get()
                autowatch_rules[rule_index]['trigger'] = selected_trigger
                save_config()
                self.refresh_rules()
                cb.destroy()

            cb.bind("<<ComboboxSelected>>", on_select)
            
        # Column 3: Cooldown
        elif col_name == "Cooldown (min)":
            # Create a Combobox for dropdown selection
            current_value = autowatch_rules[rule_index]['cooldown']
            
            # Position the combobox over the cell
            cb = ttk.Combobox(self.treeview, values=COOLDOWN_OPTIONS, state="readonly", style="TCombobox")
            cb.set(current_value)
            cb.place(x=x, y=y, width=width, height=height)
            cb.update_idletasks() # Force update to ensure correct positioning
            cb.focus_set()
            cb.event_generate('<Button-1>') # Simulate a click to open dropdown immediately

            def on_select(event):
                selected_cooldown = int(cb.get())
                autowatch_rules[rule_index]['cooldown'] = selected_cooldown
                save_config()
                self.refresh_rules()
                cb.destroy()

            cb.bind("<<ComboboxSelected>>", on_select)

    def on_close(self):
        global autowatch_config_window
        autowatch_config_window = None
        self.destroy()

def open_autowatch_config_gui():
    global autowatch_config_window
    if autowatch_config_window and autowatch_config_window.winfo_exists():
        autowatch_config_window.lift()
    else:
        autowatch_config_window = AutoWatchConfigWindow(root_for_windows)
        autowatch_config_window.lift()

def prompt_to_start_autowatch(exe_name):
    """GUI function to ask the user if they want to switch to autowatch mode."""
    root_for_windows.attributes('-topmost', True)
    answer = messagebox.askyesno("Auto-Watch Détecté", f"L'application '{exe_name}' a été détectée.\nVoulez-vous activer le mode Auto-Watch ?")
    root_for_windows.attributes('-topmost', False)
    if answer:
        set_autowatch_mode(force_on=True)

def autowatch_thread_func():
    """The main thread for monitoring processes and handling autowatch logic."""
    global autowatch_last_prompt, autowatch_capture_in_progress, autowatch_is_available
    
    PYNPUT_SPECIAL_KEY_MAP = {
        'enter': keyboard.Key.enter, 'space': keyboard.Key.space,
        'shift': keyboard.Key.shift, 'shift_l': keyboard.Key.shift_l, 'shift_r': keyboard.Key.shift_r,
        'alt': keyboard.Key.alt, 'alt_l': keyboard.Key.alt_l, 'alt_gr': keyboard.Key.alt_gr,
        'ctrl': keyboard.Key.ctrl, 'ctrl_l': keyboard.Key.ctrl_l, 'ctrl_r': keyboard.Key.ctrl_r,
    }
    PYNPUT_MOUSE_MAP = {
        'Click Gauche': mouse.Button.left,
        'Click Droit': mouse.Button.right,
        'Click Milieu': mouse.Button.middle,
    }

    active_monitored_procs = set()
    
    while running:
        try:
            if not autowatch_rules:
                if autowatch_is_available:
                    autowatch_is_available = False
                    if icon: gui_queue.put((icon.update_menu,))
                time.sleep(5)
                continue

            monitored_exes = {os.path.basename(rule['exe']).lower() for rule in autowatch_rules}
            currently_running_monitored = set()

            for proc in psutil.process_iter(['name']):
                try:
                    proc_name = proc.info['name'].lower()
                    if proc_name in monitored_exes:
                        currently_running_monitored.add(proc_name)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            is_now_available = bool(currently_running_monitored)
            if is_now_available != autowatch_is_available:
                autowatch_is_available = is_now_available
                if icon: gui_queue.put((icon.update_menu,))

            newly_launched_procs = currently_running_monitored - active_monitored_procs
            if newly_launched_procs:
                print(f"DEBUG: Detected new processes: {newly_launched_procs}")
                active_monitored_procs.update(newly_launched_procs)
                
                if capture_mode != 'autowatch':
                    exe_to_prompt = list(newly_launched_procs)[0]
                    if time.time() - autowatch_last_prompt.get(exe_to_prompt, 0) > 300:
                        autowatch_last_prompt[exe_to_prompt] = time.time()
                        gui_queue.put((prompt_to_start_autowatch, exe_to_prompt))

            closed_procs = active_monitored_procs - currently_running_monitored
            if closed_procs:
                print(f"DEBUG: Detected closed processes: {closed_procs}")
                active_monitored_procs.difference_update(closed_procs)
                for proc_name in closed_procs:
                    autowatch_last_prompt.pop(proc_name, None)
                
                if not active_monitored_procs and capture_mode == 'autowatch':
                    gui_queue.put((show_notification, "Application surveillée fermée.\nRetour au mode Replay.", 3000))
                    gui_queue.put((set_duration, DEFAULT_RECORD_DURATION))

            if capture_mode == 'autowatch' and active_monitored_procs:
                for rule in autowatch_rules:
                    rule_exe = os.path.basename(rule['exe']).lower()
                    if rule_exe in active_monitored_procs:
                        cooldown_seconds = rule.get('cooldown', 1) * 60
                        
                        if not autowatch_capture_in_progress.get(rule_exe, False) and \
                           time.time() - autowatch_last_capture.get(rule_exe, 0) > cooldown_seconds:
                            
                            trigger_activated = False
                            trigger_type_str = rule.get('trigger', 'Click Gauche')
                            
                            if trigger_type_str in PYNPUT_MOUSE_MAP:
                                button_to_check = PYNPUT_MOUSE_MAP[trigger_type_str]
                                if button_to_check in pressed_mouse_buttons:
                                    trigger_activated = True
                            elif trigger_type_str.startswith('[KPM > '):
                                try:
                                    kpm_threshold = int(trigger_type_str.split(' ')[2].replace(']', ''))
                                    if get_current_kpm() > kpm_threshold:
                                        trigger_activated = True
                                except ValueError:
                                    print(f"WARNING: Invalid KPM threshold in rule: {trigger_type_str}")
                            else: # Assumed to be a keyboard key
                                trigger_key_str = trigger_type_str.lower()
                                key_to_check = PYNPUT_SPECIAL_KEY_MAP.get(trigger_key_str)
                                if not key_to_check:
                                    try:
                                        key_to_check = keyboard.KeyCode.from_char(trigger_key_str)
                                    except Exception:
                                        key_to_check = None
                                
                                if key_to_check and key_to_check in pressed_keys:
                                    trigger_activated = True

                            if trigger_activated:
                                print(f"DEBUG: Auto-watch trigger '{trigger_type_str}' activated for '{rule_exe}'")
                                autowatch_capture_in_progress[rule_exe] = True
                                threading.Thread(target=_process_autowatch_capture, args=(rule,)).start()
                                break
                 
        except Exception as e:
            traceback.print_exc()
        
        time.sleep(0.1)

def get_current_kpm():
    global kpm_events_history
    current_time = time.time()
    # Filter events within the last 30 seconds
    recent_events = [t for t in kpm_events_history if t > current_time - 30]
    # Calculate KPM (events in 30s * 2 to get per minute)
    return len(recent_events) * 2

def _process_autowatch_capture(rule):
    """Grabs frames before and after the trigger and saves them."""
    rule_exe = os.path.basename(rule['exe']).lower()
    try:
        before_sec = rule.get('before_seconds', 2)
        after_sec = rule.get('after_seconds', 4)
        
        num_frames_before = int(before_sec * FPS)
        
        with buffer_lock:
            frames_before = list(frames_buffer)[-num_frames_before:]
        
        last_before_ts = 0
        if frames_before:
            last_before_ts = frames_before[-1][1]
        
        time.sleep(after_sec)
        
        with buffer_lock:
            buffer_copy = list(frames_buffer)
            frames_after = [f for f in buffer_copy if f[1] > last_before_ts]

        all_frames = frames_before + frames_after
        if not all_frames: return

        frames_to_save = [frame for frame, timestamp in all_frames]

        try:
            proj_dir_name = f"AW_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
            project_full_path = os.path.join(projects_path, proj_dir_name)
            os.makedirs(project_full_path, exist_ok=True)
            
            for i, frame in enumerate(frames_to_save):
                frame_path = os.path.join(project_full_path, f"{i:04d}.jpg")
                rgb_frame = frame[..., ::-1]
                imageio.imwrite(frame_path, rgb_frame)
        except Exception as e:
            traceback.print_exc()
    finally:
        autowatch_last_capture[rule_exe] = time.time()
        autowatch_capture_in_progress[rule_exe] = False

def update_aw_indicator_gui():
    global current_shortcut_icon_id
    if not shortcut_window or not shortcut_window.winfo_exists():
        return
    
    try:
        canvas = shortcut_window.winfo_children()[0]
        
        canvas.delete("dynamic_indicator")
        canvas.delete("dynamic_indicator_kpm")

        if not canvas.find_withtag("background_circle"):
            canvas.create_oval(10, 15, 70, 75, fill="black", outline="gray", tags="background_circle")

        base_icon_to_display = None
        kpm_text_to_display = None
        
        is_capturing = any(autowatch_capture_in_progress.values()) or manual_capture_in_progress

        if capture_mode == 'autowatch':
            active_kpm_rule_found = False
            for rule in autowatch_rules:
                rule_exe = os.path.basename(rule['exe']).lower()
                for proc in psutil.process_iter(['name']):
                    try:
                        if proc.info['name'].lower() == rule_exe:
                            if rule.get('trigger', '').startswith('[KPM > '):
                                active_kpm_rule_found = True
                                break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                if active_kpm_rule_found:
                    break

            if active_kpm_rule_found:
                current_kpm = get_current_kpm()
                kpm_text_to_display = str(current_kpm)
                base_icon_to_display = rec_photo_image if is_capturing else aw_photo_image
            else:
                base_icon_to_display = rec_photo_image if is_capturing else aw_photo_image
        elif capture_mode == 'replay':
            base_icon_to_display = rec_photo_image if is_capturing else eye_photo_image_original
        
        if base_icon_to_display:
            current_shortcut_icon_id = canvas.create_image(40, 45, image=base_icon_to_display, anchor=tk.CENTER, tags="dynamic_indicator")
        else:
            text_to_display = "REC" if is_capturing else ("AW" if capture_mode == 'autowatch' else "O_O")
            color_to_display = "red" if is_capturing else ("cyan" if capture_mode == 'autowatch' else "white")
            current_shortcut_icon_id = canvas.create_text(40, 45, text=text_to_display, font=("Arial", 24, "bold"), fill=color_to_display, anchor=tk.CENTER, tags="dynamic_indicator")

        if kpm_text_to_display:
            canvas.create_text(40, 45, text=kpm_text_to_display, font=("Arial", 28, "bold"), fill="white", anchor=tk.CENTER, tags="dynamic_indicator_kpm")
            
        if current_shortcut_icon_id:
             canvas.tag_bind(current_shortcut_icon_id, "<Button-1>", lambda e: on_hotkey_pressed(source='visual_shortcut'))
        else:
             canvas.tag_bind("dynamic_indicator", "<Button-1>", lambda e: on_hotkey_pressed(source='visual_shortcut'))
             canvas.tag_bind("dynamic_indicator_kpm", "<Button-1>", lambda e: on_hotkey_pressed(source='visual_shortcut'))

    except Exception as e:
        print(f"Error updating AW indicator: {e}")

# --- Project Gallery Window (Dark Theme) ---
class ProjectGalleryWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Gif Project Gallery")
        self.geometry("800x600")
        self.config(bg="#2E2E2E")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        set_dark_title_bar(self)
        self.main_frame = tk.Frame(self, bg="#2E2E2E")
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(self.main_frame, bg="#1E1E1E", highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self.main_frame, orient="vertical", command=self.canvas.yview, bg="#2E2E2E")
        self.scrollable_frame = tk.Frame(self.canvas, bg="#1E1E1E")
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10,0), pady=10)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0,10), pady=10)
        self.refresh_projects()

    def on_close(self):
        global gallery_window
        gallery_window = None
        self.destroy()

    def refresh_projects(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        if not projects_path or not os.path.exists(projects_path):
            tk.Label(self.scrollable_frame, text="Project folder not found or not set.", bg="#1E1E1E", fg="white").pack(pady=20)
            return
        project_folders = sorted([f for f in os.listdir(projects_path) if os.path.isdir(os.path.join(projects_path, f))], reverse=True)
        if not project_folders:
            tk.Label(self.scrollable_frame, text="No projects found.", bg="#1E1E1E", fg="white").pack(pady=20)
            return

        self.scrollable_frame.update_idletasks()
        canvas_width = self.canvas.winfo_width()
        widget_width = 300 
        num_columns = max(1, canvas_width // widget_width)
        
        row, col = 0, 0
        for folder in project_folders:
            project_frame = self.add_project_widget(folder)
            project_frame.grid(row=row, column=col, padx=5, pady=5, sticky="nw")
            
            col += 1
            if col >= num_columns:
                col = 0
                row += 1

    def add_project_widget(self, folder_name):
        project_full_path = os.path.join(projects_path, folder_name)
        frame = tk.Frame(self.scrollable_frame, bd=1, relief=tk.SOLID, padx=5, pady=5, bg="#4E4E4E")
        thumbnail_path = os.path.join(project_full_path, "0000.jpg")
        if os.path.exists(thumbnail_path):
            try:
                img = Image.open(thumbnail_path)
                img.thumbnail((160, 90))
                photo = ImageTk.PhotoImage(img)
                thumb_label = tk.Label(frame, image=photo, bg="#4E4E4E", cursor="hand2")
                thumb_label.image = photo
                thumb_label.pack(side=tk.LEFT, padx=5)
                thumb_label.bind("<Button-1>", lambda e, p=project_full_path: self.open_project_in_editor(p))
            except Exception as e:
                print(f"Error loading thumbnail for {folder_name}: {e}")
        info_frame = tk.Frame(frame, bg="#4E4E4E")
        info_frame.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=10)
        tk.Label(info_frame, text=folder_name, font=("Arial", 12, "bold"), bg="#4E4E4E", fg="white").pack(anchor="w")
        delete_button = tk.Button(info_frame, text="Delete", command=lambda p=project_full_path: self.delete_project(p), fg="white", bg="#dc3545", relief=tk.FLAT)
        delete_button.pack(anchor="w", pady=5)
        return frame

    def delete_project(self, project_path):
        if messagebox.askyesno("Confirm Delete", f"Are you sure you want to permanently delete this project?\n{project_path}"):
            try:
                shutil.rmtree(project_path)
                print(f"Deleted project: {project_path}")
                self.refresh_projects()
            except PermissionError:
                messagebox.showerror("Erreur de Permission", "Impossible de supprimer le projet.\nAssurez-vous que les fichiers ne sont pas ouverts dans un autre programme et que vous avez les permissions nécessaires.")
            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible de supprimer le projet: {e}")

    def open_project_in_editor(self, project_path):
        print(f"Opening project folder in editor: {project_path}")
        try:
            subprocess.Popen(get_editor_command() + [project_path])
        except Exception as e:
            print(f"ERROR: Error launching Gif Editor with project folder: {e}")
            messagebox.showerror("Error", f"Could not open project in editor: {e}")

def open_project_gallery_gui():
    global gallery_window
    if gallery_window and gallery_window.winfo_exists():
        gallery_window.lift()
    else:
        gallery_window = ProjectGalleryWindow(root_for_windows)
        gallery_window.lift()

# --- UI Classes and Functions (must be called from main thread) ---
class RegionSelector:
    def __init__(self, master):
        self.master = master
        self.master.attributes('-fullscreen', True)
        self.master.attributes('-alpha', 0.3)
        self.master.attributes('-topmost', True)
        self.canvas = tk.Canvas(self.master, cursor="cross", bg="lightgray"); self.canvas.pack(fill=tk.BOTH, expand=tk.YES)
        self.start_x, self.start_y, self.current_rect, self.region_coords = None, None, None, None
        self.canvas.bind("<ButtonPress-1>", self.on_button_press); self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        self.master.bind("<Escape>", self.on_escape)
        self.canvas.bind("<Escape>", self.on_escape)
        self.master.focus_force()
        self.screen_width, self.screen_height = self.master.winfo_screenwidth(), self.master.winfo_screenheight()

    def on_button_press(self, event): self.start_x, self.start_y = event.x, event.y
    def on_mouse_drag(self, event):
        if self.current_rect: self.canvas.delete(self.current_rect)
        self.current_rect = self.canvas.create_rectangle(self.start_x, self.start_y, event.x, event.y, outline="red", width=2)
    def on_button_release(self, event):
        x1, y1 = min(self.start_x, event.x), min(self.start_y, event.y)
        x2, y2 = max(self.start_x, event.x), max(self.start_y, event.y)
        self.region_coords = (int(x1), int(y1), int(x2 - x1), int(y2 - y1)); self.master.destroy()
    def on_escape(self, event):
        print("DEBUG: Escape key pressed, cancelling selection.")
        self.region_coords = None; self.master.destroy()

def select_capture_region_gui(result_container, event_to_set):
    temp_root = tk.Tk()
    temp_root.attributes('-toolwindow', True)
    temp_root.withdraw()
    selector_window = tk.Toplevel(temp_root)
    selector = RegionSelector(selector_window)
    selector_window.wait_window()
    result_container['result'] = (selector.region_coords, selector.screen_width, selector.screen_height)
    temp_root.destroy()
    event_to_set.set()

def hide_notification():
    global notification_window, notification_timer_id
    if notification_window and notification_window.winfo_exists():
        notification_window.destroy()
    notification_window = None
    notification_timer_id = None

def show_notification(text, duration_ms=3000):
    global notification_window, notification_timer_id
    if notification_timer_id:
        root_for_windows.after_cancel(notification_timer_id)
        notification_timer_id = None
    if not notification_window or not notification_window.winfo_exists():
        notification_window = tk.Toplevel(root_for_windows)
        notification_window.overrideredirect(True)
        notification_window.attributes("-topmost", True)
        notification_window.config(bg="black")
        notification_window.label = tk.Label(notification_window, text=text, bg="white", fg="black", padx=20, pady=10, font=("Arial", 10, "bold"), justify=tk.CENTER)
        notification_window.label.pack(padx=1, pady=1)
    notification_window.label.config(text=text)
    notification_window.update_idletasks()
    w, h = notification_window.winfo_screenwidth(), notification_window.winfo_screenheight()
    nw, nh = notification_window.winfo_reqwidth(), notification_window.winfo_reqheight()
    x = (w - nw) // 2
    y = h - nh - 50
    notification_window.geometry(f"{nw}x{nh}+{x}+{y}")
    notification_timer_id = root_for_windows.after(duration_ms, hide_notification)

def display_splash_screen_gui():
    if not os.path.exists(SPLASH_SCREEN_PATH): return
    splash_screen = tk.Toplevel(root_for_windows); splash_screen.overrideredirect(True)
    try:
        img = Image.open(SPLASH_SCREEN_PATH); photo = ImageTk.PhotoImage(img)
        label = tk.Label(splash_screen, image=photo, bg='white'); label.image = photo; label.pack()
        w, h = splash_screen.winfo_screenwidth(), splash_screen.winfo_screenheight()
        iw, ih = img.width, img.height
        x, y = (w // 2) - (iw // 2), (h // 2) - (ih // 2)
        splash_screen.geometry(f"{iw}x{ih}+{x}+{y}"); splash_screen.update()
        root_for_windows.after(SPLASH_SCREEN_DURATION_MS, splash_screen.destroy)
    except Exception as e: print(f"Error loading splash image: {e}"); splash_screen.destroy()

# --- Core Logic ---
def setup_dxcam():
    global camera, selected_monitor_index
    try:
        print(f"Initializing DXCam on monitor {selected_monitor_index}...")
        camera = dxcam.create(output_idx=selected_monitor_index, output_color="BGR")
        print("DXCam initialized.")
    except Exception as e:
        print(f"Error initializing DXCam on monitor {selected_monitor_index}: {e}")
        if selected_monitor_index != 0:
            print("Falling back to primary monitor (0).")
            try:
                camera = dxcam.create(output_idx=0, output_color="BGR")
                print("DXCam initialized on primary monitor.")
            except Exception as e2:
                print(f"Fatal error: Could not initialize DXCam on primary monitor either: {e2}")
                exit()
        else:
            print(f"Fatal error: Could not initialize DXCam: {e}")
            exit()

def record_screen():
    global frames_buffer, running
    if camera is None: return
    print("Starting screen recording...")
    camera.start(target_fps=FPS)
    last_frame_time = time.time()
    frame_interval = 1 / FPS
    while running:
        if is_selecting_region: time.sleep(0.1); continue
        current_time = time.time()
        if current_time - last_frame_time >= frame_interval:
            try:
                frame = camera.get_latest_frame()
                if frame is not None:
                    with buffer_lock: frames_buffer.append((frame, current_time))
            except Exception as e: print(f"Error during screen recording: {e}")
        time.sleep(0.001)
    camera.stop(); print("Screen recording stopped.")

def get_editor_command():
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'): return [os.path.join(os.path.dirname(sys.executable), "Tool", "Gif Editor.exe")]
    else: return ["python", "gif_editor.py"]

def _process_hotkey_action(source='keyboard'):
    global frames_buffer, is_selecting_region, projects_path, camera, manual_capture_in_progress
    
    manual_capture_in_progress = True
    try:
        print(f"DEBUG: Capture triggered by {source}. Duration: {current_record_duration}s")
        min_frames_needed = int(FPS * 0.5)
        while True:
            with buffer_lock:
                if len(frames_buffer) >= min_frames_needed: break
            time.sleep(0.1)
        selected_region_coords = None
        if source == 'keyboard':
            is_selecting_region = True
            result_container = {}; done_event = threading.Event()
            gui_queue.put((select_capture_region_gui, result_container, done_event))
            done_event.wait()
            region_result = result_container.get('result')
            is_selecting_region = False
            if not region_result or not region_result[0]:
                print("DEBUG: Region selection cancelled."); return
            selected_region_coords, _, _ = region_result
        else: # visual_shortcut
            if camera:
                selected_region_coords = (0, 0, camera.width, camera.height)
            else:
                print("ERROR: Camera not available for full-screen capture."); return
        with buffer_lock: frames_and_times = list(frames_buffer)
        if len(frames_and_times) < 2: print("Not enough frames."); return
        frames_to_process, _ = zip(*frames_and_times)
        cropped_frames = []
        if source == 'keyboard':
            crop_x, crop_y, crop_w, crop_h = selected_region_coords
            if (crop_w < 1): crop_w = 1
            if (crop_h < 1): crop_h = 1
            for frame in frames_to_process:
                h, w, _ = frame.shape
                cx1, cy1, cx2, cy2 = max(0, crop_x), max(0, crop_y), min(w, crop_x + crop_w), min(h, crop_y + crop_h)
                if (cy2 - cy1) > 0 and (cx2 - cx1) > 0:
                    cropped_frames.append(frame[cy1:cy2, cx1:cx2])
        else: # Full screen capture, no cropping needed
            cropped_frames = frames_to_process
        if not cropped_frames: print("DEBUG: No valid frames after processing."); return
        try:
            proj_dir_name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            project_full_path = os.path.join(projects_path, proj_dir_name)
            os.makedirs(project_full_path, exist_ok=True)
            for i, frame in enumerate(cropped_frames):
                frame_path = os.path.join(project_full_path, f"{i:04d}.jpg")
                rgb_frame = frame[..., ::-1]
                imageio.imwrite(frame_path, rgb_frame)
            print(f"Successfully saved {len(cropped_frames)} frames to {project_full_path}")
            gui_queue.put((open_project_gallery_gui,))
        except Exception as e: print(f"Error saving frames to project folder: {e}")
    finally:
        manual_capture_in_progress = False

def on_hotkey_pressed(source='keyboard'):
    threading.Thread(target=_process_hotkey_action, args=(source,), daemon=True).start()

# --- Tray Icon and Menu Setup ---
def set_autowatch_mode(force_on=False):
    global capture_mode
    if not autowatch_rules and not force_on:
        gui_queue.put((messagebox.showinfo, "Aucune règle", "Veuillez d'abord configurer une règle Auto-Watch."))
        return
    
    if autowatch_is_available or force_on:
        capture_mode = 'autowatch'
        if icon: icon.update_menu()
        gui_queue.put((show_notification, "Mode Auto-Watch activé.", 2000))
    else:
        gui_queue.put((messagebox.showinfo, "Application non détectée", "Aucune application surveillée n'est en cours d'exécution."))

def set_duration(duration):
    global current_record_duration, frames_buffer, capture_mode
    
    if capture_mode == 'autowatch':
        gui_queue.put((show_notification, "Désactivation de l'Auto-Watch.", 2000))

    capture_mode = 'replay'
    current_record_duration = duration
    with buffer_lock:
        frames_buffer = deque(list(frames_buffer), maxlen=int(duration * FPS))

    ram_map = { 5: "500 Mo", 20: "2 Go", 60: "6 Go" }
    ram_usage = ram_map.get(duration)
    message = f"Mode Replay: {duration}s"
    if ram_usage:
        message += f"\n(Utilisation RAM estimée: ~{ram_usage})"
    gui_queue.put((show_notification, message, 3000))
    if icon: icon.update_menu()

def duration_menu_items():
    yield MenuItem('Replay: 5 seconds', lambda: set_duration(5), checked=lambda item: capture_mode == 'replay' and current_record_duration == 5)
    yield MenuItem('Replay: 20 seconds', lambda: set_duration(20), checked=lambda item: capture_mode == 'replay' and current_record_duration == 20)
    yield MenuItem('Replay: 60 seconds', lambda: set_duration(60), checked=lambda item: capture_mode == 'replay' and current_record_duration == 60)
    yield Menu.SEPARATOR
    yield MenuItem(
        'Auto-Watch',
        set_autowatch_mode,
        checked=lambda item: capture_mode == 'autowatch',
        enabled=lambda item: autowatch_is_available
    )

def choose_projects_path():
    global projects_path
    new_path = filedialog.askdirectory(title="Select Folder for Gif Projects")
    if new_path:
        projects_path = new_path
        save_config()
        print(f"Projects path set to: {new_path}")

def cleanup_old_gifs():
    for filename in os.listdir(tempfile.gettempdir()):
        if filename.startswith("captured_gif_") and filename.endswith(".gif"):
            try: os.remove(os.path.join(tempfile.gettempdir(), filename))
            except Exception: pass

def exit_application():
    global running, icon, keyboard_listener, mouse_listener, hotkey_listener
    print("Preparing to exit...")
    save_config()
    running = False
    
    if keyboard_listener: keyboard_listener.stop()
    if mouse_listener: mouse_listener.stop()
    if hotkey_listener: hotkey_listener.stop()

    if icon:
        icon.stop()
    gui_queue.put((root_for_windows.destroy,))

def hotkey_listener_thread():
    global hotkey_listener
    
    def on_activate_hotkey():
        on_hotkey_pressed(source='keyboard')

    # Convert 'shift+f12' to pynput format '<shift>+<f12>'
    def format_hotkey(hk):
        return '+'.join(f'<{part}>' if len(part) > 1 else part for part in hk.split('+'))

    try:
        pynput_hotkey = format_hotkey(HOTKEY)
        hotkey_map = {pynput_hotkey: on_activate_hotkey}
        hotkey_listener = keyboard.GlobalHotKeys(hotkey_map)
        hotkey_listener.start()
        hotkey_listener.join()
    except Exception as e:
        print(f"FATAL: Could not set up hotkey listener: {e}")

def monitor_input_events():
    global kpm_events_history, pressed_keys, pressed_mouse_buttons, keyboard_listener, mouse_listener, running

    def on_press(key):
        if key not in pressed_keys:
            pressed_keys.add(key)
            kpm_events_history.append(time.time())

    def on_release(key):
        try:
            pressed_keys.remove(key)
        except KeyError:
            pass

    def on_click(x, y, button, pressed):
        if pressed:
            if button not in pressed_mouse_buttons:
                pressed_mouse_buttons.add(button)
                kpm_events_history.append(time.time())
        else:
            try:
                pressed_mouse_buttons.remove(button)
            except KeyError:
                pass
    
    keyboard_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    mouse_listener = mouse.Listener(on_click=on_click)
    
    keyboard_listener.start()
    mouse_listener.start()
    
    while running:
        while kpm_events_history and kpm_events_history[0] < time.time() - 10:
            kpm_events_history.popleft()
        time.sleep(1)

def _start_drag(event): global drag_start_x, drag_start_y; drag_start_x, drag_start_y = event.x, event.y
def _do_drag(event): global shortcut_window; shortcut_window.geometry(f"+{shortcut_window.winfo_x() - drag_start_x + event.x}+{shortcut_window.winfo_y() - drag_start_y + event.y}")

def _load_or_create_icon(path, text, color):
    """Loads an icon from path, or creates a placeholder if not found."""
    try:
        img = Image.open(path).resize((40, 40), Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except FileNotFoundError:
        print(f"Warning: Icon file not found at {path}. Creating placeholder.")
        icons_dir = os.path.dirname(path)
        if not os.path.exists(icons_dir):
            os.makedirs(icons_dir)

        img = Image.new('RGBA', (40, 40), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((0, 0, 39, 39), fill=color, outline="white")
        try:
            font = ImageFont.truetype("arial.ttf", 20)
        except IOError:
            font = ImageFont.load_default()
        draw.text((20, 20), text, font=font, fill="white", anchor="mm")
        
        try:
            img.save(path)
        except Exception as e:
            print(f"Error saving placeholder icon to {path}: {e}")
        return ImageTk.PhotoImage(img)
    except Exception as e:
        print(f"Error loading icon {path}: {e}. Creating placeholder.")
        img = Image.new('RGBA', (40, 40), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((0, 0, 39, 39), fill=color, outline="white")
        try:
            font = ImageFont.truetype("arial.ttf", 20)
        except IOError:
            font = ImageFont.load_default()
        draw.text((20, 20), text, font=font, fill="white", anchor="mm")
        return ImageTk.PhotoImage(img)

def show_shortcut_window_gui():
    global shortcut_window, root_for_windows, icon, is_shortcut_window_visible, shortcut_window_x, shortcut_window_y, eye_photo_image_original, aw_photo_image, rec_photo_image
    if shortcut_window and shortcut_window.winfo_exists(): shortcut_window.lift(); return
    x_pos = shortcut_window_x if shortcut_window_x is not None else 300
    y_pos = shortcut_window_y if shortcut_window_y is not None else 300
    shortcut_window = tk.Toplevel(root_for_windows)
    shortcut_window.overrideredirect(True); shortcut_window.geometry(f"80x80+{x_pos}+{y_pos}")
    shortcut_window.attributes("-topmost", True); shortcut_window.attributes("-transparentcolor", "#FF00FF")
    shortcut_window.attributes("-toolwindow", True)
    canvas = tk.Canvas(shortcut_window, bg="#FF00FF", highlightthickness=0); canvas.pack(fill=tk.BOTH, expand=tk.YES)
    
    canvas.create_oval(10, 15, 70, 75, fill="black", outline="gray", tags="background_circle")

    drag_handle = canvas.create_rectangle(20, 4, 60, 12, fill="gray", outline="gray", state='hidden')
    
    eye_photo_image_original = _load_or_create_icon(EYE_ICON_PATH, "O_O", "white")
    aw_photo_image = _load_or_create_icon(AW_ICON_PATH, "AW", "cyan")
    rec_photo_image = _load_or_create_icon(REC_ICON_PATH, "REC", "red")

    shortcut_window.eye_photo = eye_photo_image_original
    shortcut_window.aw_photo = aw_photo_image
    shortcut_window.rec_photo = rec_photo_image

    canvas.tag_bind(drag_handle, "<ButtonPress-1>", _start_drag)
    canvas.tag_bind(drag_handle, "<B1-Motion>", _do_drag)
    def _show_handle(e): canvas.itemconfig(drag_handle, state='normal')
    def _hide_handle(e): canvas.itemconfig(drag_handle, state='hidden')
    shortcut_window.bind("<Enter>", _show_handle); shortcut_window.bind("<Leave>", _hide_handle)
    is_shortcut_window_visible = True
    if icon: icon.update_menu()

def hide_shortcut_window_gui():
    global shortcut_window, icon, is_shortcut_window_visible, shortcut_window_x, shortcut_window_y
    if shortcut_window and shortcut_window.winfo_exists():
        shortcut_window_x = shortcut_window.winfo_x()
        shortcut_window_y = shortcut_window.winfo_y()
        shortcut_window.destroy(); shortcut_window = None
    is_shortcut_window_visible = False
    if icon: icon.update_menu()

def toggle_shortcut_window():
    if is_shortcut_window_visible: gui_queue.put((hide_shortcut_window_gui,))
    else: gui_queue.put((show_shortcut_window_gui,))

def set_monitor(index):
    global selected_monitor_index
    if selected_monitor_index == index:
        return
    selected_monitor_index = index
    save_config()
    if icon: icon.update_menu()
    gui_queue.put((show_notification, "Le changement de moniteur sera appliqué\nau prochain redémarrage de l'application.", 5000))

def monitor_menu_items():
    for i in range(4):
        yield MenuItem(
            f'Moniteur {i + 1}',
            partial(set_monitor, i),
            checked=lambda item, index=i: selected_monitor_index == index
        )

def setup_tray_icon():
    if not os.path.exists(ICON_PATH): Image.new('RGB', (64, 64), color='red').save(ICON_PATH, format="ICO")
    try: icon_image = Image.open(ICON_PATH)
    except Exception: icon_image = Image.new('RGB', (64, 64), color='red')
    return Icon("Gif Recorder", icon_image, menu=Menu(
        MenuItem('Afficher Raccourci de Capture', toggle_shortcut_window, checked=lambda item: is_shortcut_window_visible),
        MenuItem('Ouvrir la galerie des projets', lambda: gui_queue.put((open_project_gallery_gui,))),
        MenuItem('Configurer l\'Auto-Watch', lambda: gui_queue.put((open_autowatch_config_gui,))),
        Menu.SEPARATOR,
        MenuItem('Mode de Capture', Menu(duration_menu_items)),
        MenuItem('Moniteur', Menu(monitor_menu_items)),
        MenuItem('Choisir dossier des projets...', lambda: gui_queue.put((choose_projects_path,))),
        MenuItem('Quitter', exit_application)))

# --- Config and Main Execution ---
def load_config():
    global current_record_duration, shortcut_window_x, shortcut_window_y, projects_path, selected_monitor_index, capture_mode, autowatch_rules
    default_projects_path = os.path.join(os.path.expanduser('~'), 'GifRecorderProjects')
    try:
        if os.path.exists('config.json'):
            with open('config.json', 'r') as f:
                config = json.load(f)
                if config.get('record_duration') in [5, 20, 60]: current_record_duration = config['record_duration']
                if 'shortcut_window_x' in config: shortcut_window_x = config['shortcut_window_x']
                if 'shortcut_window_y' in config: shortcut_window_y = config['shortcut_window_y']
                projects_path = config.get('projects_path', default_projects_path)
                selected_monitor_index = config.get('monitor_index', 0)
                capture_mode = config.get('capture_mode', 'replay')
                autowatch_rules = config.get('autowatch_rules', [])
                for rule in autowatch_rules:
                    if 'kpm_threshold' not in rule:
                        rule['kpm_threshold'] = 100
        else:
            projects_path = default_projects_path
            selected_monitor_index = 0
            capture_mode = 'replay'
            autowatch_rules = []
    except Exception:
        projects_path = default_projects_path
        selected_monitor_index = 0
        capture_mode = 'replay'
        autowatch_rules = []

    if not os.path.exists(projects_path):
        try: os.makedirs(projects_path)
        except Exception as e: print(f"Could not create projects directory: {e}")

def save_config():
    global current_record_duration, shortcut_window_x, shortcut_window_y, shortcut_window, projects_path, selected_monitor_index, capture_mode, autowatch_rules
    try:
        if shortcut_window and shortcut_window.winfo_exists():
            shortcut_window_x = shortcut_window.winfo_x()
            shortcut_window_y = shortcut_window.winfo_y()
        config_data = {
            'record_duration': current_record_duration,
            'monitor_index': selected_monitor_index,
            'capture_mode': capture_mode,
            'autowatch_rules': autowatch_rules
        }
        if shortcut_window_x is not None: config_data['shortcut_window_x'] = shortcut_window_x
        if shortcut_window_y is not None: config_data['shortcut_window_y'] = shortcut_window_y
        if projects_path is not None: config_data['projects_path'] = projects_path
        with open('config.json', 'w') as f: json.dump(config_data, f, indent=4)
    except Exception: pass

def process_gui_queue():
    try:
        task_info = gui_queue.get_nowait()
        func = task_info[0]
        args = task_info[1:]
        func(*args)
    except queue.Empty:
        pass
    except Exception as e:
        print(f"--- UNHANDLED EXCEPTION IN GUI THREAD ---")
        traceback.print_exc()
        print(f"-----------------------------------------")
    root_for_windows.after(100, process_gui_queue)

def periodic_gui_update():
    update_aw_indicator_gui()
    root_for_windows.after(250, periodic_gui_update)

def main():
    global root_for_windows, frames_buffer, icon, capture_mode, current_record_duration
    load_config()
    
    if capture_mode == 'autowatch':
        capture_mode = 'replay'
        current_record_duration = DEFAULT_RECORD_DURATION

    frames_buffer = deque(maxlen=int(current_record_duration * FPS))
    cleanup_old_gifs()
    root_for_windows = tk.Tk()
    root_for_windows.attributes('-toolwindow', True)
    root_for_windows.withdraw()
    gui_queue.put((display_splash_screen_gui,))
    setup_dxcam()
    threading.Thread(target=record_screen, daemon=True).start()
    threading.Thread(target=hotkey_listener_thread, daemon=True).start()
    threading.Thread(target=autowatch_thread_func, daemon=True).start()
    threading.Thread(target=monitor_input_events, daemon=True).start()
    icon = setup_tray_icon()
    threading.Thread(target=icon.run, daemon=True).start()
    process_gui_queue()
    gui_queue.put((show_shortcut_window_gui,))
    periodic_gui_update()
    root_for_windows.mainloop()
    print("Mainloop finished. Exiting.")

if __name__ == "__main__":
    main()
