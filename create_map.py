import cv2
import numpy as np
import json
import os
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
from tkinter import ttk
from ttkthemes import ThemedTk
from PIL import Image, ImageTk

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

        self.load_image()

        self.canvas.bind("<Button-1>", self.on_left_click)
        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_release)
        self.root.bind("<Control-z>", self.undo_action)
        self.root.bind("<Return>", self.on_enter)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def load_image(self):
        initialdir = os.getcwd()  # Inicializa no diretório atual
        self.filepath = filedialog.askopenfilename(
            initialdir=initialdir,
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.gif")]
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

        for polygon in self.polygons:
            points = polygon['points']
            if len(points) > 1:
                self.canvas.create_polygon(points, outline='green', fill='', width=2)
            for point in points:
                self.canvas.create_oval(point[0]-3, point[1]-3, point[0]+3, point[1]+3, fill='red')

        if self.drawing and len(self.current_polygon) > 0:
            points = self.current_polygon
            if len(points) > 1:
                self.canvas.create_line(points, fill='blue', width=2)
            for point in points:
                self.canvas.create_oval(point[0]-3, point[1]-3, point[0]+3, point[1]+3, fill='red')

    def on_left_click(self, event):
        if not self.drawing:
            for i, polygon in enumerate(self.polygons):
                for j, point in enumerate(polygon['points']):
                    if abs(point[0] - event.x) < 5 and abs(point[1] - event.y) < 5:
                        self.moving_point = True
                        self.selected_point_index = j
                        self.selected_polygon_index = i
                        self.action_history.append(('move_start', self.selected_polygon_index, self.selected_point_index, point))
                        return
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

    def on_mouse_move(self, event):
        if self.moving_point:
            old_point = self.polygons[self.selected_polygon_index]['points'][self.selected_point_index]
            self.polygons[self.selected_polygon_index]['points'][self.selected_point_index] = (event.x, event.y)
            self.action_history.append(('move_point', self.selected_polygon_index, self.selected_point_index, old_point))
        self.redraw()

    def on_left_release(self, event):
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
                identifier = int(simpledialog.askstring("Input", "Enter identifier for this polygon:"))
                self.polygons.append({
                    'label': label,
                    'identifier': identifier,
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
            self.polygons[action[1]]['points'][action[2]] = action[3]
        elif action[0] == 'move_point':
            self.polygons[action[1]]['points'][action[2]] = action[3]

        self.redraw()

    def on_close(self):
        output_data = {
            'frame_size': {
                'width': self.width,
                'height': self.height
            },
            'polygons': self.polygons
        }
        with open('polygons.json', 'w') as f:
            json.dump(output_data, f, indent=4)
        self.root.destroy()

if __name__ == "__main__":
    root = ThemedTk(theme="arc")
    app = PolygonEditor(root)
    root.mainloop()
