import subprocess
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from PIL import Image, ImageTk, ImageDraw, ImageFont
import imageio.v2 as imageio
import os
import sys
import win32clipboard
import win32con
import tempfile
import time
import struct
import numpy as np
import shutil

class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event):
        if self.tooltip_window or not self.text:
            return
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 20
        y += self.widget.winfo_rooty() + 20
        
        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_geometry(f"+{x}+{y}")
        
        label = tk.Label(self.tooltip_window, text=self.text, justify=tk.LEFT,
                         background="#FFFFE0", relief=tk.SOLID, borderwidth=1,
                         font=("tahoma", "8", "normal"))
        label.pack(ipadx=1)

    def hide_tooltip(self, event):
        if self.tooltip_window:
            self.tooltip_window.destroy()
        self.tooltip_window = None

FPS = 20
NUM_FRAMES_TO_CUT = 3
EDITOR_WIDTH = 1000
EDITOR_HEIGHT = 800
BLANK_CANVAS_COLOR = "#1E1E1E"
ANNOTATION_COLOR = "#FFA500"

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)

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

def copy_file_to_clipboard(file_path):
    try:
        abs_path = os.path.abspath(file_path)
        file_path_bytes = (abs_path + '\0\0').encode('utf-16-le')
        drop_files_struct = struct.pack('<IIIII', 20, 0, 0, 0, 1)
        clipboard_data = drop_files_struct + file_path_bytes
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_HDROP, clipboard_data)
        win32clipboard.CloseClipboard()
    except Exception as e: 
        print(f"Error copying file to clipboard: {e}")



class GifEditorApp:
    def __init__(self, master):
        self.master = master
        master.title("Gif Editor")
        master.geometry(f"{EDITOR_WIDTH}x{EDITOR_HEIGHT}")
        master.config(bg="#2E2E2E")
        set_dark_title_bar(master)

        self.gif_frames, self.edit_events, self.redo_stack = [], [], []
        self.current_frame_index = 0
        self.photo_image, self.original_gif_path = None, None
        self.last_x, self.last_y, self.current_drawing_segments = None, None, None
        self.pencil_color = ANNOTATION_COLOR
        self.marker_positions = []
        self.redo_marker_positions = []
        self.crop_start_x, self.crop_start_y = 0, 0
        self.crop_rect_id = None
        self.crop_coords = None
        self.current_tool = None
        self.zoom_ratio = 1.0
        self.x_offset = 0
        self.y_offset = 0

        # Text tool state
        self.is_editing_text = False
        self.current_text_string = ""
        self.current_text_position = (0, 0)
        self.current_text_font_size = 20

        self.button_frame = None
        self.timeline_frame = None
        self.marker_canvas = None
        self.setup_buttons()
        self.setup_timeline()
        self.setup_canvas()

        self.status_label = tk.Label(master, text="Chargez un GIF...", bg="#2E2E2E", fg="white")
        self.status_label.pack(pady=5, side=tk.BOTTOM, fill=tk.X)

        self.master.after(100, self.load_gif_from_cli_or_clipboard)
        master.bind("<Control-z>", self.undo); master.bind("<Control-y>", self.redo)
        master.bind("<Escape>", self.handle_escape)
        self.master.bind("<Key>", self.handle_text_keypress)

    def setup_buttons(self):
        self.button_frame = tk.Frame(self.master, bg="#2E2E2E")
        self.button_frame.pack(pady=5, side=tk.TOP, fill=tk.X, padx=5)

        # Load icons
        self.icons = {}
        icon_folder = resource_path("icons")
        icon_files = {
            "validate": "Valider.png", "undo": "Undo.png", "redo": "Redo.png",
            "pencil": "Pencil.png", "text": "Text.png", "text_size": "TextSize.png",
            "color": "Color.png", "crop": "Crop.png", "duplicate": "Duplicate.png",
            "delete": "DeletPicture.png", "slowmo": "SlowMo.png",
            "trim_start": "TrimDebut.png", "trim_end": "TrimFin.png"
        }

        for name, filename in icon_files.items():
            try:
                path = os.path.join(icon_folder, filename)
                img = Image.open(path).resize((24, 24), Image.LANCZOS) # Resize to 24x24 for consistency
                self.icons[name] = ImageTk.PhotoImage(img)
            except Exception as e:
                print(f"Error loading icon {filename}: {e}")
                self.icons[name] = None # Placeholder

        # --- Right side buttons ---
        # Container for export buttons
        export_frame = tk.Frame(self.button_frame, bg="#2E2E2E")
        export_frame.pack(side=tk.RIGHT, padx=5)

        # WebM Button
        webm_btn = tk.Button(export_frame, text="WebM", image=self.icons.get("validate"), compound=tk.LEFT, relief=tk.FLAT, bg="#2E2E2E", fg="white", command=self.export_as_webm)
        webm_btn.pack(side=tk.RIGHT, padx=2)
        Tooltip(webm_btn, "Valider en WebM (Plus léger)")

        # GIF Button (formerly Validate)
        gif_btn = tk.Button(export_frame, text="GIF", image=self.icons.get("validate"), compound=tk.LEFT, relief=tk.FLAT, bg="#2E2E2E", fg="white", command=self.export_as_gif)
        gif_btn.pack(side=tk.RIGHT, padx=2)
        Tooltip(gif_btn, "Valider en GIF")

        # --- Left side buttons ---
        self.undo_button = tk.Button(self.button_frame, image=self.icons.get("undo"), relief=tk.FLAT, bg="#2E2E2E", command=self.undo, state=tk.DISABLED)
        self.undo_button.pack(side=tk.LEFT, padx=2)
        Tooltip(self.undo_button, "Annuler la dernière modification")

        self.redo_button = tk.Button(self.button_frame, image=self.icons.get("redo"), relief=tk.FLAT, bg="#2E2E2E", command=self.redo, state=tk.DISABLED)
        self.redo_button.pack(side=tk.LEFT, padx=2)
        Tooltip(self.redo_button, "Rétablire la dernière modification")

        pencil_btn = tk.Button(self.button_frame, image=self.icons.get("pencil"), relief=tk.FLAT, bg="#2E2E2E", command=self.activate_pencil_tool)
        pencil_btn.pack(side=tk.LEFT, padx=2)
        Tooltip(pencil_btn, "Dessiner au Crayon")

        text_btn = tk.Button(self.button_frame, image=self.icons.get("text"), relief=tk.FLAT, bg="#2E2E2E", command=self.activate_text_tool)
        text_btn.pack(side=tk.LEFT, padx=2)
        Tooltip(text_btn, "Ecrire un texte")
        
        text_size_btn = tk.Button(self.button_frame, image=self.icons.get("text_size"), relief=tk.FLAT, bg="#2E2E2E", command=self.choose_font_size)
        text_size_btn.pack(side=tk.LEFT, padx=2)
        Tooltip(text_size_btn, "Taille du texte")

        color_btn = tk.Button(self.button_frame, image=self.icons.get("color"), relief=tk.FLAT, bg="#2E2E2E", command=self.choose_pencil_color)
        color_btn.pack(side=tk.LEFT, padx=2)
        Tooltip(color_btn, "Changer la couleur du crayon ou du texte")

        crop_btn = tk.Button(self.button_frame, image=self.icons.get("crop"), relief=tk.FLAT, bg="#2E2E2E", command=self.enter_crop_mode)
        crop_btn.pack(side=tk.LEFT, padx=2)
        Tooltip(crop_btn, "Définir une nouvelle zone de selection de l'image")
        
        # Crop confirmation buttons (re-using validate icon)
        self.confirm_crop_button = tk.Button(self.button_frame, image=self.icons.get("validate"), relief=tk.FLAT, bg="#28a745", command=self.confirm_crop)
        Tooltip(self.confirm_crop_button, "Valider le Crop")
        self.cancel_crop_button = tk.Button(self.button_frame, text="Annuler Crop", fg="white", bg="#dc3545", relief=tk.FLAT, command=self.exit_crop_mode) # No icon for this one
        Tooltip(self.cancel_crop_button, "Annuler le Crop")

        duplicate_btn = tk.Button(self.button_frame, image=self.icons.get("duplicate"), relief=tk.FLAT, bg="#2E2E2E", command=self.duplicate_current_frame)
        duplicate_btn.pack(side=tk.LEFT, padx=2)
        Tooltip(duplicate_btn, "Duppliquer l'image en cours")

        delete_btn = tk.Button(self.button_frame, image=self.icons.get("delete"), relief=tk.FLAT, bg="#2E2E2E", command=self.delete_current_frame)
        delete_btn.pack(side=tk.LEFT, padx=2)
        Tooltip(delete_btn, "Supprimer l'Image en cours")

        slowmo_btn = tk.Button(self.button_frame, image=self.icons.get("slowmo"), relief=tk.FLAT, bg="#2E2E2E", command=self.apply_slowmo_effect)
        slowmo_btn.pack(side=tk.LEFT, padx=2)
        Tooltip(slowmo_btn, "Effectuer un Ralentis SlowMotion")

        trim_start_btn = tk.Button(self.button_frame, image=self.icons.get("trim_start"), relief=tk.FLAT, bg="#2E2E2E", command=self.delete_first_frames)
        trim_start_btn.pack(side=tk.LEFT, padx=2)
        Tooltip(trim_start_btn, "Supprimer les 3 premières images du début")

        trim_end_btn = tk.Button(self.button_frame, image=self.icons.get("trim_end"), relief=tk.FLAT, bg="#2E2E2E", command=self.delete_last_frames)
        trim_end_btn.pack(side=tk.LEFT, padx=2)
        Tooltip(trim_end_btn, "Supprimer les 3 dernières images de fin")

    def setup_timeline(self):
        self.timeline_frame = tk.Frame(self.master, bg="#2E2E2E")
        self.timeline_frame.pack(pady=5, side=tk.BOTTOM, fill=tk.X, padx=10)
        
        self.marker_canvas = tk.Canvas(self.timeline_frame, height=5, bg="#2E2E2E", highlightthickness=0)
        self.marker_canvas.pack(fill=tk.X, padx=10)

        self.timeline_label = tk.Label(self.timeline_frame, text="0.0s", bg="#2E2E2E", fg="white", width=6)
        self.timeline_label.pack(side=tk.LEFT)
        self.timeline_slider = tk.Scale(self.timeline_frame, from_=0, to=0, orient=tk.HORIZONTAL, command=self.on_slider_move, showvalue=0, bg="#2E2E2E", fg="white", troughcolor="#5E5E5E", highlightthickness=0)
        self.timeline_slider.pack(fill=tk.X, expand=True, side=tk.LEFT, padx=10)

    def setup_canvas(self):
        canvas_frame = tk.Frame(self.master, bg=BLANK_CANVAS_COLOR)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.h_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL)
        self.v_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL)

        self.canvas = tk.Canvas(canvas_frame, bg=BLANK_CANVAS_COLOR, highlightthickness=0,
                                xscrollcommand=self.h_scrollbar.set, yscrollcommand=self.v_scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.h_scrollbar.config(command=self.canvas.xview)
        self.v_scrollbar.config(command=self.canvas.yview)

        self.canvas.bind("<Button-1>", self.on_canvas_press)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)

    def canvas_to_image_coords(self, cx, cy):
        if self.zoom_ratio == 0: return cx, cy
        ix = (cx - self.x_offset) / self.zoom_ratio
        iy = (cy - self.y_offset) / self.zoom_ratio
        return ix, iy

    def image_to_canvas_coords(self, ix, iy):
        cx = ix * self.zoom_ratio + self.x_offset
        cy = iy * self.zoom_ratio + self.y_offset
        return cx, cy

    def load_gif_from_cli_or_clipboard(self):
        path_arg = sys.argv[1] if len(sys.argv) > 1 else self.get_clipboard_file_path()
        
        if not path_arg or not os.path.exists(path_arg):
            self.display_blank_canvas()
            return

        try:
            if os.path.isdir(path_arg):
                # It's a project folder, load JPGs
                self.original_gif_path = os.path.join(path_arg, 'edited.gif') # Tentative output path
                jpg_files = sorted([os.path.join(path_arg, f) for f in os.listdir(path_arg) if f.lower().endswith(".jpg")])
                if not jpg_files:
                    raise ValueError("No .jpg frames found in the project folder.")
                
                # Read images as numpy arrays
                self.gif_frames = [imageio.imread(f) for f in jpg_files]
                
                self.status_label.config(text=f"Projet {os.path.basename(path_arg)} - {len(self.gif_frames)} images")

            elif path_arg.lower().endswith('.gif'):
                # It's a GIF file
                self.original_gif_path = path_arg
                self.gif_frames = list(imageio.get_reader(path_arg, mode='I'))
                self.status_label.config(text=f"{os.path.basename(path_arg)} - {len(self.gif_frames)} images")

            else:
                self.status_label.config(text=f"Unsupported file or folder: {path_arg}")
                self.display_blank_canvas()
                return

            self.timeline_slider.config(to=len(self.gif_frames) - 1)
            self.on_slider_move(0)
            self.update_timeline_markers()

        except Exception as e:
            self.status_label.config(text=f"Erreur chargement: {e}")
            self.display_blank_canvas()

    def get_clipboard_file_path(self):
        try:
            win32clipboard.OpenClipboard()
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP): return win32clipboard.GetClipboardData(win32con.CF_HDROP)[0]
            win32clipboard.CloseClipboard()
        except Exception: return None

    def on_slider_move(self, value):
        self.current_frame_index = int(value)
        self.display_current_frame()
        duration_secs = self.current_frame_index / FPS
        self.timeline_label.config(text=f"{duration_secs:.1f}s")

    def display_current_frame(self):
        if not self.gif_frames: self.display_blank_canvas(); return
        frame_data = self.gif_frames[self.current_frame_index]
        pil_image = Image.fromarray(frame_data).convert("RGBA")

        # Pre-render committed annotations
        pil_image = self.draw_annotations_on_image(pil_image, self.current_frame_index)

        img_width, img_height = pil_image.size
        self.canvas.update_idletasks()
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()

        if img_width == 0 or img_height == 0: self.display_blank_canvas(); return

        self.zoom_ratio = min(canvas_width / img_width, canvas_height / img_height)
        display_width = int(img_width * self.zoom_ratio)
        display_height = int(img_height * self.zoom_ratio)

        self.display_image = pil_image.resize((display_width, display_height), Image.LANCZOS)
        self.photo_image = ImageTk.PhotoImage(self.display_image)
        
        self.x_offset = (canvas_width - display_width) / 2
        self.y_offset = (canvas_height - display_height) / 2

        self.canvas.delete("all")
        self.canvas.create_image(self.x_offset, self.y_offset, anchor=tk.NW, image=self.photo_image)
        self.canvas.config(scrollregion=(0, 0, canvas_width, canvas_height))
        
        self.h_scrollbar.pack_forget()
        self.v_scrollbar.pack_forget()

        self.draw_live_text()

    def draw_live_text(self):
        if self.is_editing_text:
            ix, iy = self.current_text_position
            cx, cy = self.image_to_canvas_coords(ix, iy)
            scaled_font_size = max(1, int(self.current_text_font_size * self.zoom_ratio))
            cursor = "|" if int(time.time() * 1.5) % 2 == 0 else ""
            self.canvas.create_text(cx, cy, text=self.current_text_string + cursor, fill=self.pencil_color, font=('Candara', scaled_font_size), anchor=tk.SW)

    def display_blank_canvas(self): self.canvas.delete("all"); self.canvas.config(bg=BLANK_CANVAS_COLOR)
    
    def handle_escape(self, event=None):
        if self.is_editing_text:
            self.cancel_text_entry()
        elif self.current_tool == 'crop':
            self.exit_crop_mode()

    def on_canvas_press(self, event):
        if self.current_tool == 'crop':
            self.crop_start_x = self.canvas.canvasx(event.x)
            self.crop_start_y = self.canvas.canvasy(event.y)
            if self.crop_rect_id:
                self.canvas.delete(self.crop_rect_id)
            self.crop_rect_id = self.canvas.create_rectangle(self.crop_start_x, self.crop_start_y, self.crop_start_x, self.crop_start_y, outline="red", width=2)
        elif self.current_tool == 'pencil':
            self.last_x = self.canvas.canvasx(event.x)
            self.last_y = self.canvas.canvasy(event.y)
            self.current_drawing_segments = []
        elif self.current_tool == 'text':
            self.start_text_entry(event)
        else:
            self.finalize_text_entry()

    def on_canvas_drag(self, event):
        if self.current_tool == 'crop':
            cur_x = self.canvas.canvasx(event.x)
            cur_y = self.canvas.canvasy(event.y)
            self.canvas.coords(self.crop_rect_id, self.crop_start_x, self.crop_start_y, cur_x, cur_y)
        elif self.current_tool == 'pencil' and self.last_x is not None:
            x_canvas, y_canvas = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
            self.canvas.create_line(self.last_x, self.last_y, x_canvas, y_canvas, fill=self.pencil_color, width=2, capstyle=tk.ROUND)
            self.current_drawing_segments.append((self.last_x, self.last_y, x_canvas, y_canvas))
            self.last_x, self.last_y = x_canvas, y_canvas

    def on_canvas_release(self, event):
        if self.current_tool == 'crop':
            if not self.gif_frames: return
            
            frame_data = self.gif_frames[self.current_frame_index]
            pil_image = Image.fromarray(frame_data)
            img_width, img_height = pil_image.size

            cx1_raw = self.crop_start_x
            cy1_raw = self.crop_start_y
            cx2_raw = self.canvas.canvasx(event.x)
            cy2_raw = self.canvas.canvasy(event.y)

            ix1_raw, iy1_raw = self.canvas_to_image_coords(min(cx1_raw, cx2_raw), min(cy1_raw, cy2_raw))
            ix2_raw, iy2_raw = self.canvas_to_image_coords(max(cx1_raw, cx2_raw), max(cy1_raw, cy2_raw))

            # Clamp coordinates to image boundaries
            x1 = max(0, min(round(ix1_raw), img_width))
            y1 = max(0, min(round(iy1_raw), img_height))
            x2 = max(0, min(round(ix2_raw), img_width))
            y2 = max(0, min(round(iy2_raw), img_height))
            
            if x1 >= x2: x2 = x1 + 1
            if y1 >= y2: y2 = y1 + 1

            self.crop_coords = (x1, y1, x2, y2)
            self.confirm_crop_button.pack(side=tk.LEFT, padx=5)
            self.cancel_crop_button.pack(side=tk.LEFT, padx=5)

        elif self.current_tool == 'pencil':
            self.last_x, self.last_y = None, None
            if self.current_drawing_segments:
                image_segments = []
                for cx1, cy1, cx2, cy2 in self.current_drawing_segments:
                    ix1, iy1 = self.canvas_to_image_coords(cx1, cy1)
                    ix2, iy2 = self.canvas_to_image_coords(cx2, cy2)
                    image_segments.append((ix1, iy1, ix2, iy2))
                
                self.edit_events.append({'type': 'pencil', 'segments': image_segments, 'start_frame': self.current_frame_index, 'end_frame': self.current_frame_index + int(FPS * 1), 'color': self.pencil_color, 'width': 5})
                self.redo_stack.clear()
                self.marker_positions.append(self.current_frame_index)
                self.redo_marker_positions.clear()
                self.update_undo_redo_state()
                self.update_timeline_markers()
            self.current_drawing_segments = None

    def enter_crop_mode(self):
        self.finalize_text_entry()
        self.current_tool = 'crop'
        self.master.config(cursor="cross")
        self.status_label.config(text="Mode Crop: Dessinez un rectangle et validez.")

    def exit_crop_mode(self):
        self.current_tool = None
        self.master.config(cursor="")
        if self.crop_rect_id:
            self.canvas.delete(self.crop_rect_id)
            self.crop_rect_id = None
        self.confirm_crop_button.pack_forget()
        self.cancel_crop_button.pack_forget()
        self.status_label.config(text=f"{os.path.basename(self.original_gif_path)} - {len(self.gif_frames)} images")

    def confirm_crop(self):
        if not self.crop_coords: return
        x1, y1, x2, y2 = self.crop_coords
        if x1 >= x2 or y1 >= y2: self.exit_crop_mode(); return

        new_frames = []
        for frame_data in self.gif_frames:
            new_frames.append(frame_data[y1:y2, x1:x2])
        self.gif_frames = new_frames

        for event in self.edit_events:
            if event.get('type', 'pencil') == 'pencil':
                new_segments = []
                for seg_x1, seg_y1, seg_x2, seg_y2 in event['segments']:
                    new_segments.append((seg_x1 - x1, seg_y1 - y1, seg_x2 - x1, seg_y2 - y1))
                event['segments'] = new_segments
            elif event.get('type') == 'text':
                event['pos'] = (event['pos'][0] - x1, event['pos'][1] - y1)

        self.exit_crop_mode()
        self.display_current_frame()
        self.update_timeline_markers()
        self.status_label.config(text=f"Crop appliqué. Nouvelle taille: {x2-x1}x{y2-y1}")

    def start_text_entry(self, event):
        if not self.gif_frames: return
        self.finalize_text_entry() # Finalize any previous entry
        
        self.is_editing_text = True
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        self.current_text_position = self.canvas_to_image_coords(cx, cy)
        self.current_text_string = ""
        
        self.canvas.focus_set()
        self.display_current_frame() # To draw the cursor

    def cancel_text_entry(self):
        if not self.is_editing_text: return
        self.is_editing_text = False
        self.current_text_string = ""
        self.display_current_frame()

    def finalize_text_entry(self):
        if not self.is_editing_text: return

        if self.current_text_string:
            text_event = {
                'type': 'text',
                'start_frame': self.current_frame_index,
                'end_frame': self.current_frame_index + int(FPS),
                'text': self.current_text_string,
                'font_size': self.current_text_font_size,
                'color': self.pencil_color,
                'pos': self.current_text_position
            }
            self.edit_events.append(text_event)
            self.redo_stack.clear()
            self.update_undo_redo_state()
        
        self.is_editing_text = False
        self.current_text_string = ""
        self.display_current_frame()

    def handle_text_keypress(self, event):
        if not self.is_editing_text: return

        if event.keysym == 'Return':
            self.finalize_text_entry()
        elif event.keysym == 'Escape':
            self.cancel_text_entry()
        elif event.keysym == 'BackSpace':
            self.current_text_string = self.current_text_string[:-1]
        elif event.char and event.char.isprintable():
            self.current_text_string += event.char
        
        self.display_current_frame()

    def activate_pencil_tool(self):
        self.finalize_text_entry()
        self.current_tool = 'pencil'
        self.master.config(cursor="")
        self.status_label.config(text="Mode Crayon: Dessinez sur l'image.")

    def activate_text_tool(self):
        self.current_tool = 'text'
        self.master.config(cursor="crosshair")
        self.status_label.config(text="Mode Texte: Cliquez pour ajouter du texte.")

    def undo(self, event=None):
        if self.edit_events: 
            self.redo_stack.append(self.edit_events.pop())
            if self.marker_positions:
                self.redo_marker_positions.append(self.marker_positions.pop())
            self.display_current_frame()
            self.update_undo_redo_state()
            self.update_timeline_markers()

    def redo(self, event=None):
        if self.redo_stack: 
            self.edit_events.append(self.redo_stack.pop())
            if self.redo_marker_positions:
                self.marker_positions.append(self.redo_marker_positions.pop())
            self.display_current_frame()
            self.update_undo_redo_state()
            self.update_timeline_markers()

    def update_timeline_markers(self):
        if not self.marker_canvas: return
        self.marker_canvas.delete("all")
        self.marker_canvas.update_idletasks()
        
        canvas_width = self.marker_canvas.winfo_width()
        num_frames = len(self.gif_frames)
        if num_frames < 2 or canvas_width == 1: return

        for frame_index in self.marker_positions:
            x_pos = (frame_index / (num_frames - 1)) * canvas_width
            self.marker_canvas.create_line(x_pos, 0, x_pos, 5, fill=ANNOTATION_COLOR, width=1)

    def update_undo_redo_state(self):
        self.undo_button.config(state=tk.NORMAL if self.edit_events else tk.DISABLED)
        self.redo_button.config(state=tk.NORMAL if self.redo_stack else tk.DISABLED)

    def delete_first_frames(self):
        if not self.gif_frames: return
        num_to_delete = NUM_FRAMES_TO_CUT
        if len(self.gif_frames) <= num_to_delete: self.gif_frames = []
        else: self.gif_frames = self.gif_frames[num_to_delete:]
        self.current_frame_index = max(0, self.current_frame_index - num_to_delete)
        if not self.gif_frames: self.timeline_slider.config(to=0); self.current_frame_index = 0
        else: self.timeline_slider.config(to=len(self.gif_frames) - 1)
        self.timeline_slider.set(self.current_frame_index)
        self.display_current_frame()
        self.status_label.config(text=f"Supprimé {num_to_delete} premières images. Reste {len(self.gif_frames)} images.")

    def delete_last_frames(self):
        if not self.gif_frames: return
        num_to_delete = NUM_FRAMES_TO_CUT
        if len(self.gif_frames) <= num_to_delete: self.gif_frames = []
        else: self.gif_frames = self.gif_frames[:-num_to_delete]
        self.current_frame_index = min(self.current_frame_index, len(self.gif_frames) - 1)
        if not self.gif_frames: self.timeline_slider.config(to=0); self.current_frame_index = 0
        else: self.timeline_slider.config(to=len(self.gif_frames) - 1)
        self.timeline_slider.set(self.current_frame_index)
        self.display_current_frame()
        self.status_label.config(text=f"Supprimé {num_to_delete} dernières images. Reste {len(self.gif_frames)} images.")

    def delete_current_frame(self):
        if not self.gif_frames or not (0 <= self.current_frame_index < len(self.gif_frames)): return
        self.gif_frames.pop(self.current_frame_index)
        if not self.gif_frames: self.current_frame_index = 0; self.timeline_slider.config(to=0)
        else:
            if self.current_frame_index >= len(self.gif_frames): self.current_frame_index = len(self.gif_frames) - 1
            self.timeline_slider.config(to=len(self.gif_frames) - 1)
        self.timeline_slider.set(self.current_frame_index)
        self.display_current_frame()
        self.status_label.config(text=f"Image supprimée. Reste {len(self.gif_frames)} images.")

    def duplicate_current_frame(self):
        if not self.gif_frames or not (0 <= self.current_frame_index < len(self.gif_frames)): return
        frame_to_duplicate = self.gif_frames[self.current_frame_index]
        self.gif_frames.insert(self.current_frame_index + 1, frame_to_duplicate)
        self.timeline_slider.config(to=len(self.gif_frames) - 1)
        self.current_frame_index += 1
        self.timeline_slider.set(self.current_frame_index)
        self.display_current_frame()
        self.status_label.config(text=f"Image dupliquée. Total {len(self.gif_frames)} images.")

    def apply_slowmo_effect(self):
        if not self.gif_frames: return
        C = self.current_frame_index
        num_frames = len(self.gif_frames)
        pyramid = [(-5, 1), (-4, 2), (-3, 3), (-2, 4), (-1, 5), (0, 10), (1, 5), (2, 4), (3, 3), (4, 2), (5, 1)]
        start_effect_idx, end_effect_idx = C - 5, C + 5
        new_frames = []
        new_frames.extend(self.gif_frames[:max(0, start_effect_idx)])
        for i in range(start_effect_idx, end_effect_idx + 1):
            if 0 <= i < num_frames:
                original_frame = self.gif_frames[i]
                new_frames.append(original_frame)
                repetitions = 0
                offset = i - C
                for p_offset, p_reps in pyramid:
                    if p_offset == offset: repetitions = p_reps; break
                for _ in range(repetitions): new_frames.append(original_frame)
        new_frames.extend(self.gif_frames[end_effect_idx + 1:])
        self.gif_frames = new_frames
        self.timeline_slider.config(to=len(self.gif_frames) - 1)
        self.display_current_frame()
        self.status_label.config(text=f"Effet SlowMo appliqué. Total {len(self.gif_frames)} images.")

    def choose_pencil_color(self):
        color_win = tk.Toplevel(self.master); color_win.title("Couleurs"); color_win.config(bg="#2E2E2E"); set_dark_title_bar(color_win); color_win.transient(self.master); color_win.grab_set()
        colors = {"Noir": "#000000", "Blanc": "#FFFFFF", "Bleu": "#0000FF", "Jaune": "#FFFF00", "Rouge": "#FF0000", "Vert": "#008000", "Violet": "#800080", "Orange": "#FFA500", "Rose": "#FFC0CB", "Gris": "#808080"}
        def set_color(color_hex): self.pencil_color = color_hex; color_win.destroy()
        row, col = 0, 0
        for name, hex_code in colors.items():
            b = tk.Button(color_win, text=name, bg=hex_code, fg=self.get_text_color(hex_code), command=lambda h=hex_code: set_color(h))
            b.grid(row=row, column=col, padx=5, pady=5, sticky="ew"); col += 1
            if col > 4: col = 0; row += 1
    
    def get_text_color(self, hex_code):
        hex_code = hex_code.lstrip('#')
        r, g, b = tuple(int(hex_code[i:i+2], 16) for i in (0, 2, 4))
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return "white" if luminance < 0.5 else "black"

    def draw_annotations_on_image(self, image, frame_index):
        fonts = {} # Cache fonts for performance
        draw = ImageDraw.Draw(image)

        for event in self.edit_events:
            event_type = event.get('type', 'pencil')
            if event.get('start_frame', 0) <= frame_index < event.get('end_frame', 0):
                if event_type == 'pencil':
                    for seg_x1, seg_y1, seg_x2, seg_y2 in event['segments']:
                        draw.line((seg_x1, seg_y1, seg_x2, seg_y2), fill=event['color'], width=event['width'])
                elif event_type == 'text':
                    font_size = event['font_size']
                    if font_size not in fonts:
                        try: fonts[font_size] = ImageFont.truetype("candara.ttf", font_size)
                        except IOError:
                            try: fonts[font_size] = ImageFont.truetype("arial.ttf", font_size)
                            except IOError: fonts[font_size] = ImageFont.load_default()
                    
                    draw.text(event['pos'], event['text'], fill=event['color'], font=fonts[font_size], anchor="ls")
        return image

    def choose_font_size(self):
        size_dialog = tk.Toplevel(self.master)
        size_dialog.title("Taille Police")
        size_dialog.config(bg="#2E2E2E")
        set_dark_title_bar(size_dialog)
        size_dialog.transient(self.master)
        size_dialog.grab_set()

        tk.Label(size_dialog, text="Choisir la taille de la police:", bg="#2E2E2E", fg="white").pack(padx=10, pady=10)

        size_spinbox = tk.Spinbox(size_dialog, from_=8, to=72, width=5)
        size_spinbox.pack(padx=10, pady=5)
        size_spinbox.delete(0, "end")
        size_spinbox.insert(0, str(self.current_text_font_size))
        size_spinbox.focus_set()

        def on_ok():
            new_size = size_spinbox.get()
            if new_size.isdigit():
                self.current_text_font_size = int(new_size)
            size_dialog.destroy()

        ok_button = tk.Button(size_dialog, text="OK", command=on_ok, fg="white", bg="#28a745", relief=tk.FLAT)
        ok_button.pack(pady=10)
        
        size_dialog.bind("<Return>", lambda e: on_ok())
        size_dialog.bind("<Escape>", lambda e: size_dialog.destroy())

    def _prepare_frames_for_export(self, title="Export en cours..."):
        if not self.gif_frames or not self.original_gif_path: return None, None

        progress_win = tk.Toplevel(self.master)
        progress_win.geometry("+5000+5000") # Move off-screen during setup
        progress_win.update_idletasks()
        progress_win.title(title)
        progress_win.config(bg="#2E2E2E")
        set_dark_title_bar(progress_win)
        progress_win.transient(self.master)
        progress_win.grab_set()
        
        # Center window
        width, height = 300, 100
        x, y = self.master.winfo_x() + (self.master.winfo_width() // 2) - (width // 2), self.master.winfo_y() + (self.master.winfo_height() // 2) - (height // 2)
        progress_win.geometry(f"{width}x{height}+{x}+{y}")
        progress_win.deiconify()

        progress_label = tk.Label(progress_win, text="Préparation des images...", bg="#2E2E2E", fg="white", padx=20, pady=10)
        progress_label.pack()
        progress_bar = ttk.Progressbar(progress_win, orient=tk.HORIZONTAL, length=260, mode='determinate')
        progress_bar.pack(padx=20, pady=(0, 20))
        progress_win.update_idletasks()
        
        try:
            pil_frames = [Image.fromarray(frame).convert("RGBA") for frame in self.gif_frames]
            
            progress_bar['maximum'] = len(pil_frames)
            for i, pil_frame in enumerate(pil_frames):
                pil_frames[i] = self.draw_annotations_on_image(pil_frame, i)
                
                progress_bar['value'] = i + 1
                progress_label.config(text=f"Préparation: {i+1}/{len(pil_frames)}")
                progress_win.update_idletasks()

            final_frames = []
            for frame in pil_frames:
                if frame.mode == 'RGBA':
                    rgb_frame = Image.new("RGB", frame.size, (255, 255, 255)); rgb_frame.paste(frame, (0, 0), frame)
                    final_frames.append(np.array(rgb_frame))
                else:
                    final_frames.append(np.array(frame.convert("RGB")))

            if not final_frames:
                raise ValueError("Aucune image à sauvegarder.")
                
            return final_frames, progress_win

        except Exception as e:
            if 'progress_win' in locals() and progress_win.winfo_exists():
                progress_win.destroy()
            messagebox.showerror("Erreur de Préparation", f"Une erreur est survenue: {e}")
            return None, None

    def export_as_gif(self):
        final_frames, progress_win = self._prepare_frames_for_export("Export GIF en cours...")
        if not final_frames: return

        try:
            # Retrieve progress widgets from the window
            progress_label = progress_win.winfo_children()[0]
            progress_bar = progress_win.winfo_children()[1]

            temp_dir = tempfile.gettempdir()
            temp_original_gif_path = os.path.join(temp_dir, f"temp_original_gif_{int(time.time())}.gif")

            progress_label.config(text="Sauvegarde du GIF...")
            progress_bar['value'] = 0
            progress_bar['maximum'] = len(final_frames)
            progress_win.update_idletasks()

            with imageio.get_writer(temp_original_gif_path, mode='I', fps=FPS, subrectangles=True) as writer:
                for i, frame in enumerate(final_frames):
                    writer.append_data(frame)
                    progress_bar['value'] = i + 1
                    progress_label.config(text=f"Sauvegarde: {i+1}/{len(final_frames)}")
                    progress_win.update_idletasks()
            
            progress_win.destroy()

            original_size_mb = os.path.getsize(temp_original_gif_path) / (1024 * 1024)
            estimated_compressed_size_mb = original_size_mb * 0.65
            self._show_compression_dialog(original_size_mb, estimated_compressed_size_mb, final_frames, temp_original_gif_path)

        except Exception as e:
            if 'progress_win' in locals() and progress_win.winfo_exists():
                progress_win.destroy()
            messagebox.showerror("Erreur de Sauvegarde GIF", f"Une erreur est survenue: {e}")
            if 'temp_original_gif_path' in locals() and os.path.exists(temp_original_gif_path):
                os.remove(temp_original_gif_path)

    def export_as_webm(self):
        final_frames, progress_win = self._prepare_frames_for_export("Export WebM en cours...")
        if not final_frames: return

        try:
            # Retrieve progress widgets from the window
            progress_label = progress_win.winfo_children()[0]
            progress_bar = progress_win.winfo_children()[1]

            # Construct WebM path (same location as original project if possible, or temp)
            # Using temp for consistency with GIF flow, but we could save directly.
            # Let's save to a temp file first to ensure success.
            temp_dir = tempfile.gettempdir()
            temp_webm_path = os.path.join(temp_dir, f"export_{int(time.time())}.webm")

            progress_label.config(text="Sauvegarde du WebM...")
            progress_bar['value'] = 0
            progress_bar['maximum'] = len(final_frames) # imageio writes all at once usually for video, but let's try to show progress if possible or just indeterminate
            progress_win.update_idletasks()

            # Ensure dimensions are divisible by 2 for video encoding
            first_frame = final_frames[0]
            height, width, _ = first_frame.shape
            new_width = width if width % 2 == 0 else width - 1
            new_height = height if height % 2 == 0 else height - 1
            
            if new_width != width or new_height != height:
                print(f"Resizing for WebM: {width}x{height} -> {new_width}x{new_height}")
                resized_frames = []
                for frame in final_frames:
                    img = Image.fromarray(frame)
                    img = img.resize((new_width, new_height), Image.LANCZOS)
                    resized_frames.append(np.array(img))
                final_frames = resized_frames

            # Writing video might take time and doesn't easily support frame-by-frame callback with imageio.mimsave easily for progress bar without more complex setup.
            # We will just use mimsave.
            progress_bar.config(mode='indeterminate')
            progress_bar.start()
            
            # Use libvpx-vp9 for better compression/quality, or libvpx. 
            # pixelformat yuv420p is widely supported.
            imageio.mimsave(temp_webm_path, final_frames, fps=FPS, format='WEBM', codec='libvpx', pixelformat='yuv420p')
            
            progress_win.destroy()
            
            copy_file_to_clipboard(temp_webm_path)
            messagebox.showinfo("Succès", f"Fichier WebM sauvegardé et copié dans le presse-papier !\n\n{temp_webm_path}")

        except Exception as e:
            if 'progress_win' in locals() and progress_win.winfo_exists():
                progress_win.destroy()
            messagebox.showerror("Erreur de Sauvegarde WebM", f"Une erreur est survenue: {e}\n\nAssurez-vous d'avoir les codecs nécessaires (ffmpeg).")
            if 'temp_webm_path' in locals() and os.path.exists(temp_webm_path):
                os.remove(temp_webm_path)

    def _show_compression_dialog(self, original_size_mb, estimated_compressed_size_mb, final_frames, temp_original_gif_path):
        dialog = tk.Toplevel(self.master); dialog.title("Options de Sauvegarde GIF"); set_dark_title_bar(dialog); dialog.transient(self.master); dialog.grab_set()
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._on_dialog_close(dialog, temp_original_gif_path))
        tk.Label(dialog, text=f"Le fichier final fera {original_size_mb:.1f} Mo si vous le gardez dans sa taille originale.", wraplength=300).pack(pady=10)
        tk.Label(dialog, text=f"Dans son état compressé, le fichier devrait faire environ : {estimated_compressed_size_mb:.1f} Mo", font=("", 8)).pack(pady=5)
        def save_original():
            self.status_label.config(text="Sauvegarde de la taille originale..."); self.master.update_idletasks()
            if os.path.exists(self.original_gif_path): os.remove(self.original_gif_path)
            shutil.move(temp_original_gif_path, self.original_gif_path)
            copy_file_to_clipboard(self.original_gif_path)
            dialog.destroy()
            self.status_label.config(text="Copié ! Fermeture dans 3s...")
            self.master.after(3000, self.master.destroy)
        def save_compressed():
            self.status_label.config(text="Compression et sauvegarde..."); self.master.update_idletasks()
            temp_compressed_gif_path_final = os.path.join(tempfile.gettempdir(), f"temp_compressed_gif_final_{int(time.time())}.gif")
            original_fps, target_fps = FPS, 15
            if target_fps < original_fps:
                reduced_frames = []
                num_original_frames, num_reduced_frames = len(final_frames), int(len(final_frames) * (target_fps / original_fps))
                if num_reduced_frames == 0 and num_original_frames > 0: num_reduced_frames = 1
                for i in range(num_reduced_frames):
                    original_index = int(i * (original_fps / target_fps))
                    if original_index < num_original_frames: reduced_frames.append(final_frames[original_index])
                print(f"DEBUG: Reduced frames from {num_original_frames} to {len(reduced_frames)} for {target_fps} FPS.")
                frames_to_save = reduced_frames
            else: frames_to_save = final_frames
            resized_frames = []
            if frames_to_save:
                first_frame_pil = Image.fromarray(frames_to_save[0])
                original_width, original_height = first_frame_pil.size
                new_width, new_height = int(original_width * 0.9), int(original_height * 0.9)
                print(f"DEBUG: Resizing frames from {original_width}x{original_height} to {new_width}x{new_height}")
                for frame_data in frames_to_save:
                    pil_image = Image.fromarray(frame_data)
                    resized_pil_image = pil_image.resize((new_width, new_height), Image.LANCZOS)
                    resized_frames.append(np.array(resized_pil_image))
                frames_to_save = resized_frames
            with imageio.get_writer(temp_compressed_gif_path_final, mode='I', fps=target_fps, subrectangles=True) as writer:
                for frame in frames_to_save:
                    writer.append_data(frame)
            if os.path.exists(self.original_gif_path): os.remove(self.original_gif_path)
            shutil.move(temp_compressed_gif_path_final, self.original_gif_path)
            copy_file_to_clipboard(self.original_gif_path)
            dialog.destroy()
            self.status_label.config(text="Copié ! Fermeture dans 3s...")
            self.master.after(3000, self.master.destroy)
        btn_frame = tk.Frame(dialog); btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Taille Originale", command=save_original).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Compresser...", command=save_compressed).pack(side=tk.LEFT, padx=5)
        dialog.update_idletasks()
        x, y = self.master.winfo_x() + (self.master.winfo_width() // 2) - (dialog.winfo_width() // 2), self.master.winfo_y() + (self.master.winfo_height() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        self.master.wait_window(dialog)

    def _on_dialog_close(self, dialog, temp_original_gif_path):
        if os.path.exists(temp_original_gif_path): os.remove(temp_original_gif_path)
        dialog.destroy(); self.master.destroy()

    

def main():
    root = tk.Tk()
    app = GifEditorApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()