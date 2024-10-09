import cv2
import numpy as np
import json
import os
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
from tkinter import ttk
from ttkthemes import ThemedTk
from PIL import Image, ImageTk, ImageDraw, ImageFont

class ImageEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("Image Editor")
        self.style = ttk.Style()
        self.style.theme_use('clam')

        self.canvas = tk.Canvas(root, width=800, height=600)
        self.canvas.pack()

        self.mode = None  # Mode: 'polygon' or 'crop'
        self.image = None
        self.display_image = None
        self.filepath = None

        self.polygons = []
        self.current_polygon = []
        self.drawing = False

        self.crop_rect = None
        self.crop_start_point = None
        self.crop_dragging = False
        self.rect_moving = False
        self.keep_aspect_ratio = tk.BooleanVar()

        self.load_image()

        self.canvas.bind("<Button-1>", self.on_left_click)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_release)

        self.canvas.bind("<Button-3>", self.on_right_click)  # For moving the crop rect
        self.canvas.bind("<B3-Motion>", self.on_right_drag)  # For dragging with right-click
        self.canvas.bind("<ButtonRelease-3>", self.on_right_release)

        self.root.bind("<Control-s>", self.save_and_restart)  # Ctrl+S for saving
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def load_image(self):
        initialdir = os.getcwd()
        self.filepath = filedialog.askopenfilename(
            initialdir=initialdir,
            filetypes=[("Image files", "*.png *.jpg *.jpeg")]
        )
        if not self.filepath:
            messagebox.showerror("Error", "No file selected.")
            self.root.destroy()
            return

        self.image = cv2.imread(self.filepath)
        if self.image is None:
            messagebox.showerror("Error", f"Could not read the file: {self.filepath}")
            self.root.destroy()
            return

        self.image = cv2.cvtColor(self.image, cv2.COLOR_BGR2RGB)
        self.height, self.width, _ = self.image.shape
        self.display_image = Image.fromarray(self.image)

        # Show mode selection window
        self.show_mode_selection()

    def show_mode_selection(self):
        # Create a new window for mode selection
        mode_selection_window = tk.Toplevel(self.root)
        mode_selection_window.title("Select Mode")
        mode_selection_window.geometry("300x150")

        label = tk.Label(mode_selection_window, text="Select Mode", font=("Arial", 14))
        label.pack(pady=20)

        # Add buttons for 'Polygon' and 'Crop' modes
        polygon_button = tk.Button(
            mode_selection_window, text="Polygon Mode", command=lambda: self.set_mode('polygon', mode_selection_window)
        )
        polygon_button.pack(pady=5)

        crop_button = tk.Button(
            mode_selection_window, text="Crop Mode", command=lambda: self.set_mode('crop', mode_selection_window)
        )
        crop_button.pack(pady=5)

    def set_mode(self, mode, window):
        self.mode = mode
        window.destroy()  # Close the mode selection window
        self.redraw()

        if self.mode == 'crop':
            self.ask_for_aspect_ratio()

    def ask_for_aspect_ratio(self):
        response = messagebox.askyesno("Keep Aspect Ratio", "Do you want to maintain the aspect ratio?")
        self.keep_aspect_ratio.set(response)

    def display_image_on_canvas(self):
        self.tk_image = ImageTk.PhotoImage(self.display_image)
        self.canvas.config(width=self.width, height=self.height)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)

    def redraw(self):
        self.canvas.delete("all")
        self.display_image_on_canvas()

        if self.mode == 'polygon':
            for polygon in self.polygons:
                self.canvas.create_polygon(polygon, outline='blue', fill='', width=3)

        elif self.mode == 'crop' and self.crop_rect:
            x1, y1, x2, y2 = self.crop_rect
            self.canvas.create_rectangle(x1, y1, x2, y2, outline="red", width=3)

    def on_left_click(self, event):
        if self.mode == 'polygon':
            self.current_polygon.append((event.x, event.y))
            if len(self.current_polygon) > 1:
                self.canvas.create_line(self.current_polygon[-2], self.current_polygon[-1], fill='blue', width=3)

        elif self.mode == 'crop':
            self.crop_start_point = (event.x, event.y)

    def on_mouse_drag(self, event):
        if self.mode == 'crop' and self.crop_start_point:
            x1, y1 = self.crop_start_point
            x2, y2 = event.x, event.y

            if self.keep_aspect_ratio.get():
                aspect_ratio = self.width / self.height
                new_width = abs(x2 - x1)
                new_height = int(new_width / aspect_ratio)

                if y2 < y1:
                    y2 = y1 - new_height
                else:
                    y2 = y1 + new_height

            self.crop_rect = (x1, y1, x2, y2)
            self.redraw()

    def on_mouse_release(self, event):
        if self.mode == 'crop' and self.crop_rect:
            self.crop_dragging = False  # Finish dragging

    def on_right_click(self, event):
        # If in crop mode, check if the click is inside the crop rect
        if self.mode == 'crop' and self.crop_rect:
            x1, y1, x2, y2 = self.crop_rect
            if x1 < event.x < x2 and y1 < event.y < y2:  # Check if right-click is inside the rectangle
                self.rect_moving = True
                self.rect_move_offset = (event.x - x1, event.y - y1)  # Store offset for dragging

    def on_right_drag(self, event):
        if self.mode == 'crop' and self.rect_moving:
            # Calculate new position based on the drag offset
            offset_x, offset_y = self.rect_move_offset
            x1 = event.x - offset_x
            y1 = event.y - offset_y
            x2 = x1 + (self.crop_rect[2] - self.crop_rect[0])
            y2 = y1 + (self.crop_rect[3] - self.crop_rect[1])

            # Ensure the rectangle stays within image bounds
            if x1 < 0:
                x1, x2 = 0, x2 - x1
            if y1 < 0:
                y1, y2 = 0, y2 - y1
            if x2 > self.width:
                x1, x2 = self.width - (x2 - x1), self.width
            if y2 > self.height:
                y1, y2 = self.height - (y2 - y1), self.height

            self.crop_rect = (x1, y1, x2, y2)
            self.redraw()

    def on_right_release(self, event):
        if self.mode == 'crop':
            self.rect_moving = False  # Stop moving the rectangle

    def save_crop(self):
        if self.crop_rect:
            x1, y1, x2, y2 = self.crop_rect

            # Ensure coordinates are in the correct order
            x1, x2 = sorted([x1, x2])
            y1, y2 = sorted([y1, y2])

            # Crop image
            cropped_image = self.display_image.crop((x1, y1, x2, y2))
            cropped_filepath = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG files", "*.png")])

            if cropped_filepath:
                cropped_image.save(cropped_filepath)

                # Save JSON with original dimensions and crop coordinates
                json_filepath = cropped_filepath.replace('.png', '.json')
                crop_data = {
                    "original_size": {"width": self.width, "height": self.height},
                    "crop_coordinates": {
                        "x1": x1, "y1": y1,
                        "x2": x2, "y2": y2
                    }
                }

                with open(json_filepath, 'w') as f:
                    json.dump(crop_data, f, indent=4)

                messagebox.showinfo("Crop Saved", f"Cropped image saved at {cropped_filepath} and JSON saved at {json_filepath}")

            # Reset crop
            self.crop_rect = None
            self.redraw()

    def save_and_restart(self, event=None):
        if self.mode == 'crop':
            self.save_crop()
        elif self.mode == 'polygon':
            json_filepath = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON files", "*.json")])
            if json_filepath:
                with open(json_filepath, 'w') as f:
                    json.dump(self.polygons, f, indent=4)
                messagebox.showinfo("Polygons Saved", f"Polygons saved at {json_filepath}")

        # Reset the editor state
        self.polygons = []
        self.current_polygon = []
        self.drawing = False
        self.crop_rect = None
        self.load_image()

    def on_close(self):
        try:
            self.root.destroy()  # Ensures graceful shutdown without errors
        except Exception as e:
            print(f"Error closing application: {e}")
            self.root.quit()

if __name__ == "__main__":
    root = ThemedTk(theme="clam")
    editor = ImageEditor(root)
    root.mainloop()
