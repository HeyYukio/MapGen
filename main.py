import cv2
import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from tkinter import ttk
from ttkthemes import ThemedTk
from PIL import Image, ImageTk, ImageOps, ImageDraw, ImageFont
import numpy as np
from typing import List, Tuple, Optional, Dict, Any, Deque
from collections import deque
import colorsys

class ImageEditor:
    def __init__(self, root: ThemedTk):
        self.root = root
        self.root.title("Map Editor")
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # Configuração do canvas principal com scrollbars
        self.frame = ttk.Frame(root)
        self.frame.pack(fill=tk.BOTH, expand=True)
        
        self.canvas = tk.Canvas(self.frame, width=1200, height=800, bg="white")
        self.h_scroll = ttk.Scrollbar(self.frame, orient="horizontal", command=self.canvas.xview)
        self.v_scroll = ttk.Scrollbar(self.frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self.h_scroll.set, yscrollcommand=self.v_scroll.set)
        
        self.h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.overlay = tk.Canvas(root, width=200, height=200, bg="white", bd=2, relief="solid")
        self.overlay.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=10)
        self.overlay.place_forget()
        self.overlay_visible = False

        self.mode = None
        self.original_image: Optional[np.ndarray] = None
        self.display_image: Optional[Image.Image] = None
        self.filepath: Optional[str] = None
        self.polygons: List[Dict] = []
        self.lines: List[Dict] = []
        self.current_polygon: List[Tuple[int, int]] = []
        self.current_line_start: Optional[Tuple[int, int]] = None
        self.crop_rect: Optional[Tuple[int, int, int, int]] = None
        self.crop_start_point: Optional[Tuple[int, int]] = None
        self.rect_moving = False
        self.keep_aspect_ratio = tk.BooleanVar(value=True)
        self.initial_load = True
        self.rect_move_offset = (0, 0)
        self.scale_factor = 1.0
        self.zoom_state = False
        self.pan_start = None
        self.last_save_dir = os.getcwd()
        self.aspect_ratio = 1.0
        self.temp_line = None
        self.action_history: Deque = deque(maxlen=50)
        self.dragging_point = None
        self.dragging_polygon = None
        self.drag_offset = (0, 0)
        self.next_polygon_id = 1
        self.next_line_id = 1
        self.next_color_index = 0
        self.selected_polygon_index = None
        self.selected_line_index = None
        self.view_mode = tk.BooleanVar(value=False)
        self.edit_mode = False

        self.setup_ui()
        self.setup_bindings()
        self.show_welcome_message()
        self.root.after(100, self.load_image)

    # ------------------------------------------------------------
    # Geração de cores
    # ------------------------------------------------------------
    def generate_distinct_color(self):
        hue = self.next_color_index * 0.618033988749895
        hue = hue % 1.0
        r, g, b = colorsys.hls_to_rgb(hue, 0.5, 0.9)
        self.next_color_index += 1
        return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"

    # ------------------------------------------------------------
    # UI
    # ------------------------------------------------------------
    def show_welcome_message(self):
        self.canvas.delete("all")
        self.canvas.create_text(400, 300, text="Map Editor",
                                font=("Arial", 24), fill="navy")
        self.canvas.create_text(400, 350, text="Selecione uma imagem para começar",
                                font=("Arial", 14), fill="gray")
        self.canvas.create_text(400, 400, text="Use Ctrl+O para abrir uma imagem",
                                font=("Arial", 12), fill="gray")
        self.update_status("Pronto para carregar uma imagem")

    def setup_ui(self):
        self.status_bar = ttk.Label(self.root, text="Ready | Mode: None | Image: None", anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.toolbar = ttk.Frame(self.root)
        self.toolbar.pack(side=tk.TOP, fill=tk.X)
        
        ttk.Button(self.toolbar, text="Abrir Imagem", command=self.load_image, width=12).pack(side=tk.LEFT, padx=5, pady=2)
        ttk.Button(self.toolbar, text="Zoom", command=self.toggle_zoom, width=8).pack(side=tk.LEFT, padx=5, pady=2)
        self.aspect_check = ttk.Checkbutton(self.toolbar, text="Manter Proporção", variable=self.keep_aspect_ratio)
        ttk.Button(self.toolbar, text="Desfazer (Ctrl+Z)", command=self.undo_action, width=15).pack(side=tk.LEFT, padx=5, pady=2)
        ttk.Button(self.toolbar, text="Limpar Tudo", command=self.reset_annotations, width=10).pack(side=tk.LEFT, padx=5, pady=2)
        ttk.Button(self.toolbar, text="Exportar Imagem", command=self.export_clean_image, width=12).pack(side=tk.LEFT, padx=5, pady=2)
        ttk.Checkbutton(self.toolbar, text="Modo Visualização", variable=self.view_mode, command=self.toggle_view_mode).pack(side=tk.LEFT, padx=5, pady=2)
        self.edit_mode_button = ttk.Button(self.toolbar, text="Editar Polígonos", command=self.toggle_edit_mode, width=15)
        self.edit_mode_button.pack(side=tk.LEFT, padx=5, pady=2)
        
        self.save_lines_btn = ttk.Button(self.toolbar, text="Salvar Linhas", command=self.save_lines, width=12)
        
        self.mode_indicator = ttk.Label(self.toolbar, text="Modo Atual: Nenhum", foreground="blue", font=("Arial", 10, "bold"))
        self.mode_indicator.pack(side=tk.RIGHT, padx=10)

    # ------------------------------------------------------------
    # Bindings
    # ------------------------------------------------------------
    def setup_bindings(self):
        self.canvas.bind("<Button-1>", self.on_left_click)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_release)
        self.canvas.bind("<Button-3>", self.on_right_click)
        self.canvas.bind("<B3-Motion>", self.on_right_drag)
        self.canvas.bind("<ButtonRelease-3>", self.on_right_release)
        self.root.bind("<Control-s>", self.save_and_restart)
        self.root.bind("<Escape>", self.cancel_operation)
        self.root.bind("<Return>", self.finalize_polygon)
        self.root.bind("<Delete>", self.delete_selected)
        self.root.bind("<Control-z>", self.undo_action)
        self.root.bind("<Control-o>", self.load_image)
        self.root.bind("<KeyPress-v>", self.toggle_view_mode_key)
        self.root.bind("<KeyPress-e>", self.toggle_edit_mode_key)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.canvas.bind("<Button-2>", self.start_pan)
        self.canvas.bind("<B2-Motion>", self.on_pan)

    def toggle_edit_mode(self):
        self.edit_mode = not self.edit_mode
        if self.edit_mode:
            self.edit_mode_button.config(style="Accent.TButton")
            self.update_status("Modo edição: arraste pontos para mover")
        else:
            self.edit_mode_button.config(style="TButton")
            self.dragging_point = None
            self.dragging_polygon = None
            self.update_status("Modo edição desativado")
        self.redraw()

    def toggle_view_mode(self):
        self.redraw()
        self.update_status("Modo visualização" if self.view_mode.get() else "Modo edição")

    def toggle_view_mode_key(self, event=None):
        self.view_mode.set(not self.view_mode.get())
        self.toggle_view_mode()

    def toggle_edit_mode_key(self, event=None):
        self.toggle_edit_mode()

    def update_status(self, message: str):
        mode_text = f"Modo: {self.mode.capitalize()}" if self.mode else "Modo: Nenhum"
        img_text = f"Imagem: {os.path.basename(self.filepath)}" if self.filepath else "Imagem: Nenhuma"
        view_text = "Visualização" if self.view_mode.get() else "Edição"
        edit_text = " | Editando" if self.edit_mode else ""
        self.status_bar.config(text=f"{message} | {mode_text} | {img_text} | {view_text}{edit_text}")

    # ------------------------------------------------------------
    # Zoom e Pan
    # ------------------------------------------------------------
    def toggle_zoom(self):
        if self.mode in ('polygon', 'ref_line'):
            self.update_status("Zoom não disponível no modo atual")
            return
        self.zoom_state = not self.zoom_state
        if self.zoom_state:
            self.overlay.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=10)
        else:
            self.overlay.place_forget()
        self.update_status("Zoom: ON" if self.zoom_state else "Zoom: OFF")

    def on_mouse_wheel(self, event):
        if not self.zoom_state or self.mode in ('polygon', 'ref_line'):
            return
        scale_factor = 1.1 if event.delta > 0 else 0.9
        self.scale_factor *= scale_factor
        self.scale_factor = max(0.1, min(self.scale_factor, 10.0))
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        self.redraw()
        self.canvas.scale("all", x, y, scale_factor, scale_factor)
        self.update_status(f"Zoom: {self.scale_factor*100:.1f}%")

    def show_zoom_preview(self, event):
        if self.display_image is None or not self.zoom_state or self.mode in ('polygon', 'ref_line'):
            return
        zoom_size = 100
        zoom_factor = 2.0
        img_x = int(event.x / self.scale_factor)
        img_y = int(event.y / self.scale_factor)
        left = max(0, img_x - zoom_size//2)
        top = max(0, img_y - zoom_size//2)
        right = min(self.width, left + zoom_size)
        bottom = min(self.height, top + zoom_size)
        if right <= left or bottom <= top:
            return
        zoom_region = self.display_image.crop((left, top, right, bottom))
        new_width = int(zoom_region.width * zoom_factor)
        new_height = int(zoom_region.height * zoom_factor)
        zoom_region = zoom_region.resize((new_width, new_height), Image.LANCZOS)
        self.overlay.delete("all")
        zoom_tk = ImageTk.PhotoImage(zoom_region)
        self.overlay.image = zoom_tk
        self.overlay.create_image(0, 0, anchor=tk.NW, image=zoom_tk)
        cross_x = zoom_region.width // 2
        cross_y = zoom_region.height // 2
        self.overlay.create_line(cross_x, 0, cross_x, zoom_region.height, fill="red", width=1)
        self.overlay.create_line(0, cross_y, zoom_region.width, cross_y, fill="red", width=1)

    def start_pan(self, event):
        self.pan_start = (event.x, event.y)
        self.canvas.config(cursor="fleur")

    def on_pan(self, event):
        if self.pan_start:
            dx = event.x - self.pan_start[0]
            dy = event.y - self.pan_start[1]
            self.canvas.xview_scroll(-dx, "units")
            self.canvas.yview_scroll(-dy, "units")
            self.pan_start = (event.x, event.y)

    # ------------------------------------------------------------
    # Carregamento de imagem e seleção de modo
    # ------------------------------------------------------------
    def load_image(self, event=None):
        initialdir = self.last_save_dir if hasattr(self, 'last_save_dir') else os.getcwd()
        filepath = filedialog.askopenfilename(
            initialdir=initialdir,
            filetypes=[("Arquivos de imagem", "*.png *.jpg *.jpeg *.bmp *.tiff"), ("Todos", "*.*")]
        )
        if not filepath:
            if self.initial_load:
                self.update_status("Nenhuma imagem selecionada")
            return
        self.filepath = filepath
        self.last_save_dir = os.path.dirname(filepath)
        self.initial_load = False
        self.original_image = cv2.imread(self.filepath)
        if self.original_image is None:
            messagebox.showerror("Erro", f"Não foi possível ler: {self.filepath}")
            return
        self.original_image = cv2.cvtColor(self.original_image, cv2.COLOR_BGR2RGB)
        self.height, self.width, _ = self.original_image.shape
        self.display_image = Image.fromarray(self.original_image)
        self.scale_factor = 1.0
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.update_aspect_ratio()
        self.show_mode_selection()
        self.update_status(f"Carregado: {os.path.basename(self.filepath)}")

    def show_mode_selection(self):
        mode_window = tk.Toplevel(self.root)
        mode_window.title("Selecionar Modo")
        mode_window.geometry("300x250")
        mode_window.resizable(False, False)
        mode_window.transient(self.root)
        mode_window.update_idletasks()
        mode_window.wait_visibility()
        mode_window.grab_set()
        mode_window.focus_set()

        tk.Label(mode_window, text="Selecione o Modo", font=("Arial", 14)).pack(pady=20)
        ttk.Button(mode_window, text="Anotação de Polígono", command=lambda: self.set_mode('polygon', mode_window), width=20).pack(pady=5, padx=50, fill=tk.X)
        ttk.Button(mode_window, text="Recorte de Imagem", command=lambda: self.set_mode('crop', mode_window), width=20).pack(pady=5, padx=50, fill=tk.X)
        ttk.Button(mode_window, text="Linha de Referência", command=lambda: self.set_mode('ref_line', mode_window), width=20).pack(pady=5, padx=50, fill=tk.X)
        ttk.Button(mode_window, text="Cancelar", command=mode_window.destroy, width=10).pack(pady=10)

    def set_mode(self, mode: str, window: tk.Toplevel):
        self.mode = mode
        window.destroy()
        self.reset_annotations()
        self.mode_indicator.config(text=f"Modo Atual: {mode.capitalize()}")
        self.update_status(f"Modo: {mode}")
        
        if mode == 'crop':
            self.ask_for_aspect_ratio()
            self.aspect_check.pack(side=tk.LEFT, padx=5, pady=2)
        else:
            self.aspect_check.pack_forget()
        
        if mode == 'ref_line':
            self.save_lines_btn.pack(side=tk.LEFT, padx=5, pady=2, after=self.edit_mode_button)
        else:
            self.save_lines_btn.pack_forget()

    def ask_for_aspect_ratio(self):
        if not self.keep_aspect_ratio.get():
            self.keep_aspect_ratio.set(
                messagebox.askyesno("Manter Proporção", "Manter a proporção original?", parent=self.root)
            )

    def update_aspect_ratio(self):
        if self.original_image is not None:
            self.height, self.width, _ = self.original_image.shape
            self.aspect_ratio = self.width / self.height

    # ------------------------------------------------------------
    # Histórico e desfazer
    # ------------------------------------------------------------
    def reset_annotations(self):
        self.save_state_to_history()
        self.polygons = []
        self.lines = []
        self.current_polygon = []
        self.current_line_start = None
        self.crop_rect = None
        self.temp_line = None
        self.dragging_point = None
        self.dragging_polygon = None
        self.selected_polygon_index = None
        self.selected_line_index = None
        self.next_polygon_id = 1
        self.next_line_id = 1
        self.next_color_index = 0
        self.edit_mode = False
        self.redraw()
        self.update_status("Anotações limpas")

    def save_state_to_history(self):
        state = {
            'polygons': [p.copy() for p in self.polygons],
            'lines': [l.copy() for l in self.lines],
            'current_polygon': self.current_polygon.copy(),
            'current_line_start': self.current_line_start,
            'crop_rect': self.crop_rect,
            'mode': self.mode,
            'next_polygon_id': self.next_polygon_id,
            'next_line_id': self.next_line_id,
            'next_color_index': self.next_color_index,
            'selected_polygon_index': self.selected_polygon_index,
            'selected_line_index': self.selected_line_index,
        }
        self.action_history.append(state)

    def undo_action(self, event=None):
        if not self.action_history:
            self.update_status("Nada para desfazer")
            return
        prev = self.action_history.pop()
        self.polygons = prev['polygons']
        self.lines = prev['lines']
        self.current_polygon = prev['current_polygon']
        self.current_line_start = prev['current_line_start']
        self.crop_rect = prev['crop_rect']
        self.next_polygon_id = prev['next_polygon_id']
        self.next_line_id = prev['next_line_id']
        self.next_color_index = prev['next_color_index']
        self.selected_polygon_index = prev['selected_polygon_index']
        self.selected_line_index = prev['selected_line_index']
        self.redraw()
        self.update_status("Ação desfeita")

    def cancel_operation(self, event=None):
        self.save_state_to_history()
        if self.mode == 'polygon' and self.current_polygon:
            self.current_polygon = []
            self.redraw()
            self.update_status("Polígono cancelado")
        elif self.mode == 'ref_line' and self.current_line_start:
            self.current_line_start = None
            self.redraw()
            self.update_status("Linha cancelada")
        elif self.mode == 'crop' and self.crop_rect:
            self.crop_rect = None
            self.redraw()
            self.update_status("Recorte cancelado")

    # ------------------------------------------------------------
    # Desenho
    # ------------------------------------------------------------
    def display_image_on_canvas(self):
        if self.display_image is None:
            return
        if self.scale_factor != 1.0:
            img = self.display_image.copy()
            new_size = (int(img.width * self.scale_factor), int(img.height * self.scale_factor))
            resized_img = img.resize(new_size, Image.LANCZOS)
            self.tk_image = ImageTk.PhotoImage(resized_img)
        else:
            self.tk_image = ImageTk.PhotoImage(self.display_image)
        self.canvas.config(scrollregion=(0, 0, self.tk_image.width(), self.tk_image.height()))
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)

    def redraw(self):
        self.canvas.delete("all")
        self.display_image_on_canvas()
        self.draw_polygons()
        self.draw_lines()
        self.draw_crop_rectangle()
        self.draw_temp_line()

    def draw_temp_line(self):
        if self.mode == 'polygon' and self.current_polygon and self.temp_line:
            x1, y1 = self.current_polygon[-1]
            x2, y2 = self.temp_line
            self.canvas.create_line(x1, y1, x2, y2, fill="#FF0000", width=2, dash=(4, 2))
        if self.mode == 'ref_line' and self.current_line_start and self.temp_line:
            sx, sy = self.current_line_start
            ex, ey = self.temp_line
            self.canvas.create_line(sx, sy, ex, ey, fill="#00AAFF", width=2, dash=(4, 2))

    def draw_polygons(self):
        for idx, poly_data in enumerate(self.polygons):
            points = poly_data['points']
            if self.scale_factor != 1.0:
                points = [(x * self.scale_factor, y * self.scale_factor) for x, y in points]
            outline_color = "#FFFF00" if (idx == self.selected_polygon_index and not self.view_mode.get()) else poly_data['color']
            outline_width = 4 if idx == self.selected_polygon_index else 3
            self.canvas.create_polygon(points, outline=outline_color, fill='', width=outline_width, tags=f"polygon_{idx}")
            if not self.view_mode.get():
                for p_idx, (x, y) in enumerate(points):
                    fill_color = "red" if p_idx == 0 else poly_data['color']
                    self.canvas.create_oval(x-4, y-4, x+4, y+4, fill=fill_color, outline="white", width=1, tags=f"poly_{idx}_point_{p_idx}")
            if points:
                center_x = sum(p[0] for p in points) / len(points)
                center_y = sum(p[1] for p in points) / len(points)
                text = f"{poly_data['label']} ({poly_data['id']})"
                tw = len(text) * 7
                th = 16
                self.canvas.create_rectangle(center_x - tw/2 - 4, center_y - th/2 - 2,
                                             center_x + tw/2 + 4, center_y + th/2 + 2,
                                             fill="black", outline="white", tags="polygon_label_bg")
                self.canvas.create_text(center_x, center_y, text=text, fill="white", font=("Arial", 10, "bold"), tags="polygon_label")
        if self.current_polygon and not self.view_mode.get():
            self.draw_current_polygon()

    def draw_current_polygon(self):
        points = self.current_polygon
        if self.scale_factor != 1.0:
            points = [(x * self.scale_factor, y * self.scale_factor) for x, y in points]
        if len(points) > 1:
            for i in range(1, len(points)):
                self.canvas.create_line(points[i-1][0], points[i-1][1], points[i][0], points[i][1], fill="#FF0000", width=2, tags="current_polygon")
        for p_idx, (x, y) in enumerate(points):
            fill_color = "red" if p_idx == 0 else "#FF0000"
            self.canvas.create_oval(x-4, y-4, x+4, y+4, fill=fill_color, outline="white", width=1, tags=f"current_point_{p_idx}")

    def draw_lines(self):
        for idx, line_data in enumerate(self.lines):
            pt1, pt2 = line_data['points']
            if self.scale_factor != 1.0:
                pt1 = (pt1[0] * self.scale_factor, pt1[1] * self.scale_factor)
                pt2 = (pt2[0] * self.scale_factor, pt2[1] * self.scale_factor)
            outline_color = "#FFFF00" if (idx == self.selected_line_index and not self.view_mode.get()) else line_data['color']
            outline_width = 4 if idx == self.selected_line_index else 3
            self.canvas.create_line(pt1[0], pt1[1], pt2[0], pt2[1], fill=outline_color, width=outline_width, tags=f"line_{idx}")
            if not self.view_mode.get():
                self.canvas.create_oval(pt1[0]-4, pt1[1]-4, pt1[0]+4, pt1[1]+4, fill="green", outline="white", width=1)
                self.canvas.create_oval(pt2[0]-4, pt2[1]-4, pt2[0]+4, pt2[1]+4, fill="blue", outline="white", width=1)
            mx = (pt1[0] + pt2[0]) / 2
            my = (pt1[1] + pt2[1]) / 2
            text = f"{line_data['label']} ({line_data['id']})"
            tw = len(text) * 7
            th = 16
            self.canvas.create_rectangle(mx - tw/2 - 4, my - th/2 - 2, mx + tw/2 + 4, my + th/2 + 2,
                                         fill="black", outline="white", tags="line_label_bg")
            self.canvas.create_text(mx, my, text=text, fill="white", font=("Arial", 10, "bold"), tags="line_label")

    def draw_crop_rectangle(self):
        if self.mode == 'crop' and self.crop_rect:
            x1, y1, x2, y2 = self.crop_rect
            self.canvas.create_rectangle(x1, y1, x2, y2, outline="#00FF00", width=3, dash=(4, 2), tags="crop_rect")
            handles = [(x1,y1),(x2,y1),(x2,y2),(x1,y2),((x1+x2)//2,y1),((x1+x2)//2,y2),(x1,(y1+y2)//2),(x2,(y1+y2)//2)]
            for hx, hy in handles:
                self.canvas.create_rectangle(hx-5, hy-5, hx+5, hy+5, fill="#00FF00", outline="white", tags="resize_handle")

    # ------------------------------------------------------------
    # Detecção de pontos e linhas
    # ------------------------------------------------------------
    def find_point_at_position(self, x, y, tolerance=6):
        for p_idx, (px, py) in enumerate(self.current_polygon):
            if ((px - x) ** 2 + (py - y) ** 2) ** 0.5 <= tolerance:
                return (None, p_idx)
        for poly_idx, poly_data in enumerate(self.polygons):
            for p_idx, (px, py) in enumerate(poly_data['points']):
                if ((px - x) ** 2 + (py - y) ** 2) ** 0.5 <= tolerance:
                    return (poly_idx, p_idx)
        return (None, None)

    def find_line_at_position(self, x, y, tolerance=5):
        for idx, line_data in enumerate(self.lines):
            pt1, pt2 = line_data['points']
            dist = self.point_to_segment_dist(x, y, pt1[0], pt1[1], pt2[0], pt2[1])
            if dist <= tolerance:
                return idx
        return None

    @staticmethod
    def point_to_segment_dist(px, py, x1, y1, x2, y2):
        dx = x2 - x1
        dy = y2 - y1
        if dx == 0 and dy == 0:
            return ((px - x1)**2 + (py - y1)**2) ** 0.5
        t = ((px - x1)*dx + (py - y1)*dy) / (dx*dx + dy*dy)
        t = max(0.0, min(1.0, t))
        projx = x1 + t*dx
        projy = y1 + t*dy
        return ((px - projx)**2 + (py - projy)**2) ** 0.5

    # ------------------------------------------------------------
    # Cliques do mouse
    # ------------------------------------------------------------
    def on_left_click(self, event):
        if self.zoom_state and self.mode not in ('polygon', 'ref_line'):
            self.show_zoom_preview(event)
            return
        if self.mode == 'polygon':
            self.handle_polygon_left_click(event)
        elif self.mode == 'ref_line':
            self.handle_line_left_click(event)
        elif self.mode == 'crop':
            self.handle_crop_click(event)

    def handle_polygon_left_click(self, event):
        if self.edit_mode:
            self.dragging_polygon, self.dragging_point = self.find_point_at_position(event.x, event.y)
            if self.dragging_polygon is not None or self.dragging_point is not None:
                self.save_state_to_history()
                poly_points = self.polygons[self.dragging_polygon]['points'] if self.dragging_polygon is not None else self.current_polygon
                point_x, point_y = poly_points[self.dragging_point]
                self.drag_offset = (event.x - point_x, event.y - point_y)
                self.redraw()
                return
        if len(self.current_polygon) > 2 and self.check_close_to_first_point(event):
            self.finalize_polygon()
            return
        if self.select_polygon(event):
            return
        self.save_state_to_history()
        self.current_polygon.append((event.x, event.y))
        self.redraw()
        self.update_status(f"Ponto adicionado: ({event.x}, {event.y})")

    def handle_line_left_click(self, event):
        line_idx = self.find_line_at_position(event.x, event.y, tolerance=8)
        if line_idx is not None:
            self.selected_line_index = line_idx
            self.selected_polygon_index = None
            self.redraw()
            self.update_status(f"Linha {line_idx} selecionada")
            return
        if self.current_line_start is None:
            self.save_state_to_history()
            self.current_line_start = (event.x, event.y)
            self.selected_line_index = None
            self.redraw()
            self.update_status("Primeiro ponto da linha definido. Clique no segundo ponto.")
        else:
            end_point = (event.x, event.y)
            if ((end_point[0] - self.current_line_start[0])**2 + (end_point[1] - self.current_line_start[1])**2) < 4:
                return
            info = self.ask_shape_info("Linha")
            if not info["label"] or not info["id"]:
                self.current_line_start = None
                self.redraw()
                self.update_status("Criação de linha cancelada")
                return
            self.save_state_to_history()
            self.lines.append({
                'points': [self.current_line_start, end_point],
                'label': info["label"],
                'id': info["id"],
                'color': self.generate_distinct_color()
            })
            self.current_line_start = None
            self.selected_line_index = len(self.lines) - 1
            self.redraw()
            self.update_status(f"Linha '{info['label']}' (ID: {info['id']}) criada")

    def check_close_to_first_point(self, event):
        if len(self.current_polygon) < 3:
            return False
        first_x, first_y = self.current_polygon[0]
        return ((event.x - first_x)**2 + (event.y - first_y)**2)**0.5 < 10

    def select_polygon(self, event):
        items = self.canvas.find_overlapping(event.x-5, event.y-5, event.x+5, event.y+5)
        for item in items:
            tags = self.canvas.gettags(item)
            for tag in tags:
                if tag.startswith("polygon_"):
                    try:
                        idx = int(tag.split("_")[1])
                        self.selected_polygon_index = idx
                        self.selected_line_index = None
                        self.redraw()
                        self.update_status(f"Polígono {idx} selecionado")
                        return True
                    except:
                        pass
        return False

    def on_mouse_drag(self, event):
        if self.zoom_state and self.mode not in ('polygon', 'ref_line'):
            return
        if self.dragging_point is not None:
            new_x = event.x - self.drag_offset[0]
            new_y = event.y - self.drag_offset[1]
            if self.dragging_polygon is not None:
                self.polygons[self.dragging_polygon]['points'][self.dragging_point] = (new_x, new_y)
            else:
                self.current_polygon[self.dragging_point] = (new_x, new_y)
            self.redraw()
            return
        if self.mode == 'crop' and self.crop_start_point:
            if hasattr(self, 'selected_handle'):
                self.resize_crop_rectangle(event)
            else:
                self.update_crop_rectangle(event)
        elif self.mode == 'polygon' and self.current_polygon:
            self.temp_line = (event.x, event.y)
            self.redraw()
        elif self.mode == 'ref_line' and self.current_line_start:
            self.temp_line = (event.x, event.y)
            self.redraw()

    def on_mouse_release(self, event):
        if self.mode == 'crop' and self.crop_rect:
            self.finalize_crop_rectangle()
            if hasattr(self, 'selected_handle'):
                del self.selected_handle
        if self.dragging_point is not None:
            self.dragging_point = None
            self.dragging_polygon = None
            self.save_state_to_history()
            self.update_status("Ponto movido")
        self.temp_line = None
        self.rect_moving = False
        self.redraw()

    # ------------------------------------------------------------
    # Movimento do mouse
    # ------------------------------------------------------------
    def on_mouse_move(self, event):
        self.update_status(f"Posição: ({event.x}, {event.y})")
        if self.mode == 'polygon' and self.current_polygon:
            self.temp_line = (event.x, event.y)
            self.redraw()
        elif self.mode == 'ref_line' and self.current_line_start:
            self.temp_line = (event.x, event.y)
            self.redraw()
        if self.zoom_state and self.mode not in ('polygon', 'ref_line'):
            self.show_zoom_preview(event)

    # ------------------------------------------------------------
    # Recorte (crop)
    # ------------------------------------------------------------
    def handle_crop_click(self, event):
        self.save_state_to_history()
        handles = self.canvas.find_withtag("resize_handle")
        for handle in handles:
            x1, y1, x2, y2 = self.canvas.coords(handle)
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self.selected_handle = handle
                self.crop_start_point = (event.x, event.y)
                self.original_crop_rect = self.crop_rect
                return
        if not self.crop_rect:
            self.crop_start_point = (event.x, event.y)
        else:
            x1, y1, x2, y2 = self.crop_rect
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self.rect_moving = True
                self.rect_move_offset = (event.x - x1, event.y - y1)

    def resize_crop_rectangle(self, event):
        x1, y1, x2, y2 = self.original_crop_rect
        handle_idx = self.canvas.gettags(self.selected_handle)[1]
        handles = {
            'nw': (0, 0), 'ne': (1, 0), 'se': (1, 1), 'sw': (0, 1),
            'n': (0.5, 0), 's': (0.5, 1), 'e': (1, 0.5), 'w': (0, 0.5)
        }
        hx, hy = handles.get(handle_idx, (0, 0))
        new_x = event.x
        new_y = event.y
        if self.keep_aspect_ratio.get():
            dx = event.x - self.crop_start_point[0]
            dy = event.y - self.crop_start_point[1]
            if abs(dx) > abs(dy):
                dy = dx / self.aspect_ratio
            else:
                dx = dy * self.aspect_ratio
            new_x = self.crop_start_point[0] + dx
            new_y = self.crop_start_point[1] + dy
        if hx == 0:
            x1 = min(new_x, x2)
        elif hx == 1:
            x2 = max(new_x, x1)
        if hy == 0:
            y1 = min(new_y, y2)
        elif hy == 1:
            y2 = max(new_y, y1)
        self.crop_rect = (x1, y1, x2, y2)
        self.redraw()

    def update_crop_rectangle(self, event):
        x1, y1 = self.crop_start_point
        x2, y2 = event.x, event.y
        if self.keep_aspect_ratio.get():
            dx = x2 - x1
            dy = y2 - y1
            if abs(dx) > abs(dy):
                y2 = y1 + dx / self.aspect_ratio
            else:
                x2 = x1 + dy * self.aspect_ratio
        self.crop_rect = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        self.redraw()

    def finalize_crop_rectangle(self):
        x1, y1, x2, y2 = self.crop_rect
        self.crop_rect = (
            max(0, min(x1, x2)),
            max(0, min(y1, y2)),
            min(self.width, max(x1, x2)),
            min(self.height, max(y1, y2))
        )
        self.update_status(f"Área de recorte definida: {self.crop_rect}")

    def on_right_click(self, event):
        if self.mode == 'crop' and self.crop_rect:
            self.save_state_to_history()
            x1, y1, x2, y2 = self.crop_rect
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self.rect_moving = True
                self.rect_move_offset = (event.x - x1, event.y - y1)

    def on_right_drag(self, event):
        if self.mode == 'crop' and self.rect_moving:
            self.move_crop_rectangle(event)

    def move_crop_rectangle(self, event):
        offset_x, offset_y = self.rect_move_offset
        rect_width = self.crop_rect[2] - self.crop_rect[0]
        rect_height = self.crop_rect[3] - self.crop_rect[1]
        x1 = max(0, min(event.x - offset_x, self.width - rect_width))
        y1 = max(0, min(event.y - offset_y, self.height - rect_height))
        x2 = x1 + rect_width
        y2 = y1 + rect_height
        self.crop_rect = (x1, y1, x2, y2)
        self.redraw()

    def on_right_release(self, event):
        self.rect_moving = False

    # ------------------------------------------------------------
    # Diálogo de nome/ID
    # ------------------------------------------------------------
    def ask_shape_info(self, shape_type="Polígono"):
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Informações da {shape_type}")
        dialog.geometry("300x180")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.update_idletasks()
        dialog.wait_visibility()
        dialog.grab_set()
        tk.Label(dialog, text="Nome / Label:").pack(pady=(10,0))
        label_entry = ttk.Entry(dialog)
        label_entry.pack(pady=5, padx=20, fill=tk.X)
        default_label = f"{shape_type} {self.next_polygon_id if shape_type=='Polígono' else self.next_line_id}"
        label_entry.insert(0, default_label)
        label_entry.focus_set()
        tk.Label(dialog, text="ID:").pack()
        id_entry = ttk.Entry(dialog)
        id_entry.pack(pady=5, padx=20, fill=tk.X)
        default_id = self.next_polygon_id if shape_type=='Polígono' else self.next_line_id
        id_entry.insert(0, str(default_id))
        self.shape_info_result = {"label": "", "id": ""}
        def on_ok():
            label = label_entry.get().strip()
            id_val = id_entry.get().strip()
            if not label:
                messagebox.showerror("Erro", "Label não pode ser vazio", parent=dialog)
                return
            try:
                poly_id = int(id_val)
                if poly_id <= 0:
                    messagebox.showerror("Erro", "ID deve ser positivo", parent=dialog)
                    return
            except ValueError:
                messagebox.showerror("Erro", "ID deve ser um número inteiro", parent=dialog)
                return
            self.shape_info_result = {"label": label, "id": poly_id}
            dialog.destroy()
        def on_cancel():
            self.shape_info_result = {"label": "", "id": ""}
            dialog.destroy()
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(btn_frame, text="Cancelar", command=on_cancel).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="OK", command=on_ok).pack(side=tk.RIGHT)
        dialog.protocol("WM_DELETE_WINDOW", on_cancel)
        dialog.wait_window()
        return self.shape_info_result

    # ------------------------------------------------------------
    # Finalização e deleção
    # ------------------------------------------------------------
    def finalize_polygon(self, event=None):
        if self.mode == 'polygon' and len(self.current_polygon) >= 3:
            info = self.ask_shape_info("Polígono")
            if not info["label"] or not info["id"]:
                self.update_status("Polígono cancelado")
                return
            self.save_state_to_history()
            self.polygons.append({
                'points': self.current_polygon.copy(),
                'label': info["label"],
                'id': info["id"],
                'color': self.generate_distinct_color()
            })
            self.current_polygon = []
            self.next_polygon_id = info["id"] + 1
            self.selected_polygon_index = len(self.polygons) - 1
            self.selected_line_index = None
            self.redraw()
            self.update_status(f"Polígono '{info['label']}' finalizado")

    def delete_selected(self, event=None):
        self.save_state_to_history()
        if self.mode == 'polygon':
            if self.selected_polygon_index is not None and self.selected_polygon_index < len(self.polygons):
                deleted = self.polygons.pop(self.selected_polygon_index)
                self.selected_polygon_index = None
                self.redraw()
                self.update_status(f"Polígono '{deleted['label']}' deletado")
            elif self.current_polygon:
                self.current_polygon = []
                self.redraw()
            else:
                self.update_status("Nada para deletar")
        elif self.mode == 'ref_line':
            if self.selected_line_index is not None and self.selected_line_index < len(self.lines):
                deleted = self.lines.pop(self.selected_line_index)
                self.selected_line_index = None
                self.redraw()
                self.update_status(f"Linha '{deleted['label']}' deletada")
            elif self.current_line_start:
                self.current_line_start = None
                self.redraw()
            else:
                self.update_status("Nada para deletar")
        elif self.mode == 'crop' and self.crop_rect:
            self.crop_rect = None
            self.redraw()
            self.update_status("Recorte deletado")

    # ------------------------------------------------------------
    # Salvamento (polígonos, linhas, crop)
    # ------------------------------------------------------------
    def save_polygons(self):
        if not self.polygons:
            messagebox.showwarning("Aviso", "Nenhum polígono para salvar")
            return
        save_path = filedialog.asksaveasfilename(
            initialdir=self.last_save_dir, defaultextension=".json",
            filetypes=[("JSON files", "*.json")]
        )
        if not save_path:
            return
        self.last_save_dir = os.path.dirname(save_path)
        normalized_polygons = []
        for poly in self.polygons:
            norm = []
            for x, y in poly['points']:
                norm.append((x/self.width, y/self.height))
            normalized_polygons.append({'points': norm, 'label': poly['label'], 'id': poly['id']})
        metadata = {
            "frame_size": {"width": self.width, "height": self.height},
            "polygons": [{'label': p['label'], 'id': p['id'], 'points': p['points']} for p in self.polygons],
            "polygons_normalized": [{'label': p['label'], 'id': p['id'], 'points': p['points']} for p in normalized_polygons]
        }
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)
        messagebox.showinfo("Sucesso", f"Polígonos salvos: {save_path}")
        self.reset_annotations()

    def save_lines(self):
        if not self.lines:
            messagebox.showwarning("Aviso", "Nenhuma linha para salvar")
            return
        save_path = filedialog.asksaveasfilename(
            initialdir=self.last_save_dir, defaultextension=".json",
            filetypes=[("JSON files", "*.json")]
        )
        if not save_path:
            return
        self.last_save_dir = os.path.dirname(save_path)
        norm_lines = []
        for line_data in self.lines:
            pt1, pt2 = line_data['points']
            x1_rel = pt1[0] / self.width
            y1_rel = pt1[1] / self.height
            x2_rel = pt2[0] / self.width
            y2_rel = pt2[1] / self.height
            norm_lines.append({
                'id': line_data['id'],
                'name': line_data['label'],
                'x1': x1_rel, 'y1': y1_rel,
                'x2': x2_rel, 'y2': y2_rel
            })
        metadata = {
            "frame_size": {"width": self.width, "height": self.height},
            "lines": [{
                "id": line['id'],
                "name": line['name'],
                "x1": line['x1'], "y1": line['y1'],
                "x2": line['x2'], "y2": line['y2']
            } for line in norm_lines],
            "lines_absolute": [{
                "id": line['id'],
                "name": line['label'],
                "x1": line['points'][0][0], "y1": line['points'][0][1],
                "x2": line['points'][1][0], "y2": line['points'][1][1]
            } for line in self.lines]
        }
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)
        if messagebox.askyesno("Exportar imagem", "Deseja exportar a imagem com as linhas?"):
            img_path = os.path.splitext(save_path)[0] + "_lines.png"
            self.export_lines_image(img_path)
        messagebox.showinfo("Sucesso", f"Linhas salvas: {save_path}")
        self.reset_annotations()

    def export_lines_image(self, save_path):
        if self.display_image is None:
            return
        base_image = self.display_image.copy()
        draw = ImageDraw.Draw(base_image)
        for line_data in self.lines:
            pt1, pt2 = line_data['points']
            color = line_data['color']
            rgb = tuple(int(color[i:i+2], 16) for i in (1, 3, 5))
            draw.line([pt1, pt2], fill=rgb, width=4)
            r = 4
            draw.ellipse((pt1[0]-r, pt1[1]-r, pt1[0]+r, pt1[1]+r), fill="green")
            draw.ellipse((pt2[0]-r, pt2[1]-r, pt2[0]+r, pt2[1]+r), fill="blue")
            mx = (pt1[0] + pt2[0]) // 2
            my = (pt1[1] + pt2[1]) // 2
            try:
                font = ImageFont.truetype("arial.ttf", 16)
            except:
                font = ImageFont.load_default()
            text = f"{line_data['label']} ({line_data['id']})"
            bbox = draw.textbbox((mx, my), text, font=font)
            draw.rectangle([bbox[0]-2, bbox[1]-2, bbox[2]+2, bbox[3]+2], fill=(0,0,0))
            draw.text((mx, my), text, font=font, fill=(255,255,255))
        base_image.save(save_path)

    def save_crop(self):
        if not self.crop_rect:
            messagebox.showwarning("Aviso", "Nenhuma área de recorte definida")
            return
        x1, y1, x2, y2 = self.crop_rect
        cropped = self.display_image.crop((x1, y1, x2, y2))
        save_path = filedialog.asksaveasfilename(
            initialdir=self.last_save_dir, defaultextension=".png",
            filetypes=[("PNG files", "*.png"), ("JPEG files", "*.jpg;*.jpeg")]
        )
        if not save_path:
            return
        self.last_save_dir = os.path.dirname(save_path)
        if save_path.lower().endswith(('.jpg', '.jpeg')):
            cropped.save(save_path, "JPEG", quality=95)
        else:
            cropped.save(save_path)
        self.save_crop_metadata(save_path, x1, y1, x2, y2)
        messagebox.showinfo("Sucesso", f"Imagem salva: {save_path}")
        self.reset_annotations()

    def save_crop_metadata(self, path, x1, y1, x2, y2):
        json_path = os.path.splitext(path)[0] + ".json"
        x1_rel = x1 / self.width
        y1_rel = y1 / self.height
        x2_rel = x2 / self.width
        y2_rel = y2 / self.height
        center_x = (x1_rel + x2_rel) / 2
        center_y = (y1_rel + y2_rel) / 2
        width = x2_rel - x1_rel
        height = y2_rel - y1_rel
        metadata = {
            "original_size": {"width": self.width, "height": self.height},
            "crop_coordinates_relative": {"x1": x1_rel, "y1": y1_rel, "x2": x2_rel, "y2": y2_rel},
            "crop_coordinates_absolute": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
            "yolo_format": {"center_x": center_x, "center_y": center_y, "width": width, "height": height}
        }
        with open(json_path, 'w') as f:
            json.dump(metadata, f, indent=4)

    def export_clean_image(self, event=None):
        if not self.polygons and not self.current_polygon:
            messagebox.showwarning("Aviso", "Nenhum polígono para exportar")
            return
        save_path = filedialog.asksaveasfilename(
            initialdir=self.last_save_dir, defaultextension=".png",
            filetypes=[("PNG files", "*.png"), ("JPEG files", "*.jpg;*.jpeg")]
        )
        if not save_path:
            return
        base = self.display_image.resize((self.width, self.height), Image.LANCZOS) if self.scale_factor != 1.0 else self.display_image.copy()
        draw = ImageDraw.Draw(base)
        for poly_data in self.polygons:
            points = poly_data['points']
            color = poly_data['color']
            rgb = tuple(int(color[i:i+2], 16) for i in (1, 3, 5))
            draw.polygon(points, outline=rgb, width=3)
            if points:
                cx = sum(p[0] for p in points) / len(points)
                cy = sum(p[1] for p in points) / len(points)
                try:
                    font = ImageFont.truetype("arial.ttf", 16)
                except:
                    font = ImageFont.load_default()
                text = f"{poly_data['label']} ({poly_data['id']})"
                bbox = draw.textbbox((cx, cy), text, font=font)
                draw.rectangle([bbox[0]-2, bbox[1]-2, bbox[2]+2, bbox[3]+2], fill=(0,0,0,128))
                draw.text((cx, cy), text, font=font, fill=(255,255,255))
        base.save(save_path)
        self.update_status(f"Imagem exportada: {save_path}")

    def save_and_restart(self, event=None):
        if self.mode == 'crop':
            self.save_crop()
        elif self.mode == 'polygon':
            if self.current_polygon:
                self.finalize_polygon()
            else:
                self.save_polygons()
        elif self.mode == 'ref_line':
            if self.current_line_start:
                self.update_status("Finalize a linha antes de salvar")
            else:
                self.save_lines()
        else:
            self.update_status("Nada para salvar")
        self.load_image()

    def on_close(self):
        if messagebox.askokcancel("Sair", "Tem certeza que deseja sair?"):
            try:
                self.root.destroy()
            except:
                self.root.quit()

if __name__ == "__main__":
    root = ThemedTk(theme="clam")
    root.title("Map Editor")
    try:
        if os.name == 'nt':
            root.state('zoomed')
        else:
            try:
                root.attributes('-zoomed', True)
            except:
                root.geometry("1200x800")
    except:
        root.geometry("1200x800")
    root.minsize(800, 600)
    ImageEditor(root)
    root.mainloop()