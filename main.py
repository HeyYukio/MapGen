import cv2
import numpy as np
import json
import os
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
from tkinter import ttk
from ttkthemes import ThemedTk
from PIL import Image, ImageTk, ImageDraw, ImageFont
import random

class PolygonEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("Polygon Editor")

        self.style = ttk.Style()
        self.style.theme_use('clam')

        self.canvas = tk.Canvas(root, width=800, height=600)
        self.canvas.pack()

        self.polygons = []
        self.current_polygon = []
        self.drawing = False
        self.moving_point = False
        self.selected_point_index = -1
        self.selected_polygon_index = -1

        self.action_history = []

        # Lista de cores válidas
        self.colors = [
            'red', 'blue', 'green', 'yellow', 'purple', 'orange',
            'cyan', 'magenta', 'lime', 'pink', 'teal', 'lavender',
            'brown', 'beige', 'maroon', 'olive', 'coral', 'navy', 'grey'
        ]
        random.shuffle(self.colors)

        self.load_image()

        self.canvas.bind("<Button-1>", self.on_left_click)
        self.canvas.bind("<B3-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-3>", self.on_right_release)
        self.root.bind("<Control-z>", self.undo_action)
        self.root.bind("<Return>", self.on_enter)
        self.root.bind("<Control-s>", self.save_and_restart)

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

        if not os.path.exists(self.filepath):
            messagebox.showerror("Error", f"File not found: {self.filepath}")
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
        self.tk_image = ImageTk.PhotoImage(self.display_image)
        self.canvas.config(width=self.width, height=self.height)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)

    def redraw(self):
        self.canvas.delete("all")
        self.tk_image = ImageTk.PhotoImage(self.display_image)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)

        for i, polygon in enumerate(self.polygons):
            points = polygon['points']
            color = self.colors[i % len(self.colors)]
            if len(points) > 1:
                self.canvas.create_polygon(points, outline=color, fill='', width=3)
            for point in points:
                self.canvas.create_oval(point[0]-3, point[1]-3, point[0]+3, point[1]+3, fill=color)
            label_pos = self.get_non_overlapping_label_position(points, i)
            self.canvas.create_text(label_pos[0], label_pos[1], text=f"{polygon['label']} ({polygon['id']})", fill=color, font=("Arial", 14, "bold"))

        if self.drawing and len(self.current_polygon) > 0:
            points = self.current_polygon
            color = 'blue'
            if len(points) > 1:
                self.canvas.create_line(points, fill=color, width=3)
            for point in points:
                self.canvas.create_oval(point[0]-3, point[1]-3, point[0]+3, point[1]+3, fill=color)

    def on_left_click(self, event):
        if event.x < 0 or event.x > self.width or event.y < 0 or event.y > self.height:
            return
        if not self.drawing:
            self.drawing = True
            self.current_polygon = [(event.x, event.y)]
            self.action_history.append(('start_polygon', self.current_polygon.copy()))
        else:
            for point in self.current_polygon:
                if abs(point[0] - event.x) < 5 and abs(point[1] - event.y) < 5:
                    if len(self.current_polygon) > 2:
                        self.drawing = False
                        self.add_polygon()
                    self.redraw()
                    return
            self.current_polygon.append((event.x, event.y))
            self.action_history.append(('add_point', (event.x, event.y)))
        self.redraw()

    def on_mouse_drag(self, event):
        if event.x < 0 or event.x > self.width or event.y < 0 or event.y > self.height:
            return
        if not self.moving_point:
            for i, polygon in enumerate(self.polygons):
                for j, point in enumerate(polygon['points']):
                    if abs(point[0] - event.x) < 5 and abs(point[1] - event.y) < 5:
                        self.moving_point = True
                        self.selected_point_index = j
                        self.selected_polygon_index = i
                        self.action_history.append(('move_start', self.selected_polygon_index, self.selected_point_index, point))
                        return
            for j, point in enumerate(self.current_polygon):
                if abs(point[0] - event.x) < 5 and abs(point[1] - event.y) < 5:
                    self.moving_point = True
                    self.selected_point_index = j
                    self.selected_polygon_index = -1
                    self.action_history.append(('move_start', self.selected_polygon_index, self.selected_point_index, point))
                    return
        if self.moving_point:
            if self.selected_polygon_index == -1:
                old_point = self.current_polygon[self.selected_point_index]
                self.current_polygon[self.selected_point_index] = (event.x, event.y)
            else:
                old_point = self.polygons[self.selected_polygon_index]['points'][self.selected_point_index]
                self.polygons[self.selected_polygon_index]['points'][self.selected_point_index] = (event.x, event.y)
            self.action_history.append(('move_point', self.selected_polygon_index, self.selected_point_index, old_point))
            self.redraw()

    def on_right_release(self, event):
        if self.moving_point:
            self.moving_point = False

    def on_enter(self, event):
        if self.drawing and len(self.current_polygon) > 2:
            self.drawing = False
            self.add_polygon()
        self.redraw()

    def add_polygon(self):
        label = simpledialog.askstring("Input", "Enter label for this polygon:")
        if label:
            try:
                id = int(simpledialog.askstring("Input", "Enter identifier for this polygon:"))
                self.polygons.append({
                    'label': label,
                    'id': id,
                    'points': self.current_polygon
                })
                self.action_history.append(('add_polygon', self.polygons[-1]))
            except ValueError:
                messagebox.showerror("Invalid input", "Identifier must be a number.")
        self.current_polygon = []

    def undo_action(self, event):
        if not self.action_history:
            return

        action = self.action_history.pop()

        if action[0] == 'start_polygon':
            self.current_polygon = []
            self.drawing = False
        elif action[0] == 'add_point':
            self.current_polygon.pop()
        elif action[0] == 'add_polygon':
            self.polygons.pop()
        elif action[0] == 'move_start':
            if action[1] == -1:
                self.current_polygon[action[2]] = action[3]
            else:
                self.polygons[action[1]]['points'][action[2]] = action[3]
        elif action[0] == 'move_point':
            if action[1] == -1:
                self.current_polygon[action[2]] = action[3]
            else:
                self.polygons[action[1]]['points'][action[2]] = action[3]

        self.redraw()

    def save_and_restart(self, event):
        self.save_polygons()
        self.polygons = []
        self.current_polygon = []
        self.drawing = False
        self.moving_point = False
        self.selected_point_index = -1
        self.selected_polygon_index = -1
        self.action_history = []
        self.load_image()

    def save_polygons(self):
        output_filepath = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
            initialfile="polygons"
        )
        if not output_filepath:
            messagebox.showerror("Error", "No file selected for saving.")
            return

        output_data = {
            'frame_size': {
                'width': self.width,
                'height': self.height
            },
            'polygons': self.polygons
        }
        with open(output_filepath, 'w') as f:
            json.dump(output_data, f, indent=4)
        self.save_annotated_image(output_filepath)
        messagebox.showinfo("Success", f"Polygons saved to {output_filepath}")

    def save_annotated_image(self, json_filepath):
        annotated_image = self.display_image.copy()
        draw = ImageDraw.Draw(annotated_image)
        font = ImageFont.truetype("arial.ttf", 20)  # Change the font size to make annotations more visible

        for i, polygon in enumerate(self.polygons):
            points = polygon['points']
            color = self.colors[i % len(self.colors)]
            draw.polygon(points, outline=color, width=3)
            label_pos = self.get_non_overlapping_label_position(points, i)
            draw.text(label_pos, f"{polygon['label']} ({polygon['id']})", fill=color, font=font)
        annotated_image_filepath = json_filepath.replace('.json', '.png')
        annotated_image.save(annotated_image_filepath)

    def get_non_overlapping_label_position(self, points, polygon_index):
        offset = 10
        x, y = points[0]
        positions = [
            (x, y - 30), (x + offset, y - 30), (x - offset, y - 30),
            (x, y + offset), (x + offset, y + offset), (x - offset, y + offset),
            (x, y + 30), (x + offset, y + 30), (x - offset, y + 30)
        ]

        for px, py in points:
            for pos in positions:
                if abs(px - pos[0]) < offset and abs(py - pos[1]) < offset:
                    positions.remove(pos)

        for pos in positions:
            if 0 <= pos[0] <= self.width and 0 <= pos[1] <= self.height:
                return pos

        return x, y - 30

    def on_close(self):
        self.save_polygons()
        self.root.destroy()

if __name__ == "__main__":
    root = ThemedTk(theme="arc")
    app = PolygonEditor(root)
    root.mainloop()
