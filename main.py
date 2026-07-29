"""
Map Editor – Ferramenta para demarcar linhas de referência, polígonos e recortes.
Salva automaticamente em ./maps/<nome_da_pasta>/lines.json + lines.png
Com indicadores de direção (IN/OUT) para uso com YOLO.
Lida com imagens pequenas, preview de linha, edição fluida e PNG com setas, cores e
textos sem sobreposição.
"""

import cv2
import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from tkinter import ttk
from ttkthemes import ThemedTk
from PIL import Image, ImageTk, ImageDraw, ImageFont
import numpy as np
from typing import List, Tuple, Optional, Dict, Any, Deque
from collections import deque
import colorsys
import math


class CollisionAvoidance:
    """Gerenciador simples para evitar sobreposição de textos no PNG."""
    def __init__(self):
        self.occupied = []  # lista de (x1, y1, x2, y2)

    def is_free(self, bbox):
        """Retorna True se a área não colide com nenhuma já ocupada."""
        ax1, ay1, ax2, ay2 = bbox
        for (bx1, by1, bx2, by2) in self.occupied:
            if not (ax2 < bx1 or ax1 > bx2 or ay2 < by1 or ay1 > by2):
                return False
        return True

    def add(self, bbox):
        self.occupied.append(bbox)

    def find_free_y(self, x_center, desired_y, width, height, step=20, max_shift=200):
        """Tenta posicionar um texto centralizado em x_center, desired_y ajustando y para baixo e para cima."""
        bbox = (x_center - width//2, desired_y - height//2,
                x_center + width//2, desired_y + height//2)
        if self.is_free(bbox):
            self.add(bbox)
            return desired_y
        # tentar para baixo
        for shift in range(step, max_shift+1, step):
            y_test = desired_y + shift
            bbox = (x_center - width//2, y_test - height//2,
                    x_center + width//2, y_test + height//2)
            if self.is_free(bbox):
                self.add(bbox)
                return y_test
        # tentar para cima
        for shift in range(step, max_shift+1, step):
            y_test = desired_y - shift
            bbox = (x_center - width//2, y_test - height//2,
                    x_center + width//2, y_test + height//2)
            if self.is_free(bbox):
                self.add(bbox)
                return y_test
        # se não achou, usa a posição original mesmo sobrepondo
        self.add(bbox)
        return desired_y


class ImageEditor:
    def __init__(self, root: ThemedTk):
        self.root = root
        self.root.title("Map Editor")
        self.style = ttk.Style()

        try:
            self.style.theme_use('arc')
        except:
            self.style.theme_use('clam')

        # -------------------------------------------------------
        # MELHORIAS DE VISIBILIDADE GLOBAL
        # -------------------------------------------------------
        self.root.option_add('*Listbox.selectForeground', 'black')
        self.root.option_add('*Listbox.selectBackground', '#c0c0ff')
        self.root.option_add('*Entry.foreground', 'black')
        self.root.option_add('*Entry.background', 'white')
        self.root.option_add('*TCombobox*Listbox.selectForeground', 'black')
        self.root.option_add('*TCombobox*Listbox.selectBackground', '#c0c0ff')
        self.style.configure('.', foreground='black', background='#f0f0f0')
        self.style.configure('TLabel', foreground='black', background='#f0f0f0')
        self.style.configure('TButton', foreground='black', background='#e0e0e0')
        self.style.map('TButton', background=[('active', '#c0c0c0')])
        self.style.configure('TFrame', background='#f0f0f0')
        self.style.configure('TCheckbutton', foreground='black', background='#f0f0f0')
        self.style.configure('Visible.TEntry', foreground='black', background='white', fieldbackground='white')
        self.root.configure(bg='#f0f0f0')

        # Canvas com scrollbars
        self.frame = ttk.Frame(root)
        self.frame.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(self.frame, width=1200, height=800, bg="#e0e0e0")
        self.h_scroll = ttk.Scrollbar(self.frame, orient="horizontal", command=self.canvas.xview)
        self.v_scroll = ttk.Scrollbar(self.frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self.h_scroll.set, yscrollcommand=self.v_scroll.set)
        self.h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Overlay de zoom (mantido)
        self.overlay = tk.Canvas(root, width=200, height=200, bg="white", bd=2, relief="solid")
        self.overlay.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=10)
        self.overlay.place_forget()

        # -------------------------------------------------------
        # Variáveis de estado
        # -------------------------------------------------------
        self.mode = None
        self.original_image: Optional[np.ndarray] = None
        self.display_image: Optional[Image.Image] = None
        self.filepath: Optional[str] = None
        self.polygons: List[Dict] = []
        self.lines: List[Dict] = []
        self.current_polygon: List[Tuple[float, float]] = []
        self.current_line_start: Optional[Tuple[float, float]] = None
        self.preview_line: Optional[Dict] = None
        self.crop_rect: Optional[Tuple[float, float, float, float]] = None
        self.crop_start_point: Optional[Tuple[float, float]] = None
        self.rect_moving = False
        self.keep_aspect_ratio = tk.BooleanVar(value=True)
        self.initial_load = True
        self.rect_move_offset = (0, 0)
        self.scale_factor = 1.0
        self.zoom_state = False
        self.pan_start = None
        self.aspect_ratio = 1.0
        self.temp_line_id = None
        self.action_history: Deque = deque(maxlen=50)

        self.dragging_polygon = None
        self.dragging_point = None
        self.dragging_line_index = None
        self.dragging_line_point_index = None
        self.drag_offset = (0, 0)

        self.next_polygon_id = 1
        self.next_line_id = 1
        self.next_color_index = 0

        self.selected_polygon_index = None
        self.selected_line_index = None

        self.view_mode = tk.BooleanVar(value=False)
        self.edit_mode = False

        # Cache de itens do canvas para performance
        self.canvas_items = {'polygons': {}, 'lines': {}, 'current_polygon': []}

        self.frames_dir = "./frames"
        self.maps_dir = "./maps"
        os.makedirs(self.frames_dir, exist_ok=True)
        os.makedirs(self.maps_dir, exist_ok=True)

        self.setup_ui()
        self.setup_bindings()
        self.show_welcome_message()
        self.root.after(100, self.load_image)

    # ============================================================
    # Geração de cores
    # ============================================================
    def generate_distinct_color(self):
        hue = self.next_color_index * 0.618033988749895
        hue %= 1.0
        r, g, b = colorsys.hls_to_rgb(hue, 0.5, 0.9)
        self.next_color_index += 1
        return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"

    # ============================================================
    # UI
    # ============================================================
    def show_welcome_message(self):
        self.canvas.delete("all")
        self.canvas.create_text(400, 300, text="Map Editor",
                                font=("Arial", 24, "bold"), fill="navy")
        self.canvas.create_text(400, 350, text="Selecione uma imagem para começar",
                                font=("Arial", 14), fill="gray")
        self.canvas.create_text(400, 400, text="Use Ctrl+O para abrir uma imagem",
                                font=("Arial", 12), fill="gray")
        self.update_status("Pronto")

    def setup_ui(self):
        self.status_bar = ttk.Label(self.root, text="Ready", anchor=tk.W,
                                    relief=tk.SUNKEN, padding=4)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.toolbar = ttk.Frame(self.root, padding=4)
        self.toolbar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(self.toolbar, text="Abrir Imagem", command=self.load_image, width=12).pack(side=tk.LEFT, padx=3)
        ttk.Button(self.toolbar, text="Zoom", command=self.toggle_zoom, width=8).pack(side=tk.LEFT, padx=3)
        self.aspect_check = ttk.Checkbutton(self.toolbar, text="Proporção", variable=self.keep_aspect_ratio)
        ttk.Button(self.toolbar, text="Desfazer", command=self.undo_action, width=10).pack(side=tk.LEFT, padx=3)
        ttk.Button(self.toolbar, text="Limpar Tudo", command=self.reset_annotations, width=10).pack(side=tk.LEFT, padx=3)
        ttk.Button(self.toolbar, text="Exportar Imagem", command=self.export_clean_image, width=14).pack(side=tk.LEFT, padx=3)
        self.view_check = ttk.Checkbutton(self.toolbar, text="Visualização", variable=self.view_mode, command=self.toggle_view_mode)
        self.view_check.pack(side=tk.LEFT, padx=3)
        self.edit_mode_button = ttk.Button(self.toolbar, text="Editar Pontos", command=self.toggle_edit_mode, width=12)
        self.edit_mode_button.pack(side=tk.LEFT, padx=3)
        self.save_lines_btn = ttk.Button(self.toolbar, text="Salvar Linhas", command=self.save_lines, width=12)
        self.mode_indicator = ttk.Label(self.toolbar, text="Modo: Nenhum", foreground="blue", font=("Arial", 10, "bold"))
        self.mode_indicator.pack(side=tk.RIGHT, padx=10)

    def update_status(self, message: str):
        mode_text = f"Modo: {self.mode.capitalize()}" if self.mode else "Nenhum"
        img_text = f"Imagem: {os.path.basename(self.filepath)}" if self.filepath else "Nenhuma"
        view_text = "Visualização" if self.view_mode.get() else "Edição"
        edit_text = " | Editando" if self.edit_mode else ""
        scale_text = f" | Escala: {self.scale_factor:.2f}" if self.scale_factor != 1.0 else ""
        self.status_bar.config(text=f"{message} | {mode_text} | {img_text} | {view_text}{edit_text}{scale_text}")

    def set_window_title(self):
        if self.filepath:
            self.root.title(f"Map Editor – {os.path.basename(self.filepath)}")
        else:
            self.root.title("Map Editor")

    # ============================================================
    # Bindings
    # ============================================================
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
            self.edit_mode_button.config(text="Editando...")
        else:
            self.edit_mode_button.config(text="Editar Pontos")
            self.dragging_point = None
            self.dragging_polygon = None
            self.dragging_line_index = None
            self.dragging_line_point_index = None
        self.redraw()

    def toggle_view_mode(self):
        self.redraw()

    def toggle_view_mode_key(self, event=None):
        self.view_mode.set(not self.view_mode.get())
        self.toggle_view_mode()

    def toggle_edit_mode_key(self, event=None):
        self.toggle_edit_mode()

    # ============================================================
    # Zoom e Pan
    # ============================================================
    def toggle_zoom(self):
        if self.mode in ('polygon', 'ref_line'):
            self.update_status("Zoom não disponível no modo atual")
            return
        self.zoom_state = not self.zoom_state
        if self.zoom_state:
            self.overlay.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=10)
        else:
            self.overlay.place_forget()
        self.update_status(f"Zoom {'ON' if self.zoom_state else 'OFF'}")

    def on_mouse_wheel(self, event):
        if not self.zoom_state or self.mode in ('polygon', 'ref_line'):
            return
        scale_factor = 1.1 if event.delta > 0 else 0.9
        self.scale_factor *= scale_factor
        self.scale_factor = max(0.1, min(self.scale_factor, 10.0))
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        self.canvas.scale("all", x, y, scale_factor, scale_factor)
        self.update_status(f"Zoom: {self.scale_factor*100:.1f}%")

    def show_zoom_preview(self, event):
        pass

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

    # ============================================================
    # Carregamento e ajuste de escala
    # ============================================================
    def load_image(self, event=None):
        initialdir = self.frames_dir if os.path.isdir(self.frames_dir) else os.getcwd()
        filepath = filedialog.askopenfilename(
            initialdir=initialdir,
            title="Selecionar imagem",
            filetypes=[("Imagens", "*.png *.jpg *.jpeg *.bmp *.tiff"), ("Todos", "*.*")]
        )
        if not filepath:
            if self.initial_load:
                self.update_status("Nenhuma imagem selecionada")
            return
        self.filepath = filepath
        self.initial_load = False
        self.set_window_title()
        img = cv2.imread(filepath)
        if img is None:
            messagebox.showerror("Erro", f"Não foi possível ler: {filepath}")
            return
        self.original_image = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        self.height, self.width, _ = self.original_image.shape
        self.display_image = Image.fromarray(self.original_image)
        self.fit_image_to_canvas()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.show_mode_selection()
        self.update_status(f"Carregado: {os.path.basename(filepath)}")

    def fit_image_to_canvas(self):
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        if canvas_width <= 1 or canvas_height <= 1:
            canvas_width, canvas_height = 1200, 800
        scale_w = canvas_width / self.width
        scale_h = canvas_height / self.height
        self.scale_factor = min(scale_w, scale_h)
        self.scale_factor = max(0.1, min(self.scale_factor, 10.0))

    def show_mode_selection(self):
        win = tk.Toplevel(self.root)
        win.title("Modo")
        win.geometry("280x220")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        ttk.Label(win, text="Selecione o modo:", font=("Arial", 12)).pack(pady=15)
        ttk.Button(win, text="Polígono", command=lambda: self.set_mode('polygon', win)).pack(pady=5, fill=tk.X, padx=40)
        ttk.Button(win, text="Recorte", command=lambda: self.set_mode('crop', win)).pack(pady=5, fill=tk.X, padx=40)
        ttk.Button(win, text="Linha de Referência", command=lambda: self.set_mode('ref_line', win)).pack(pady=5, fill=tk.X, padx=40)
        ttk.Button(win, text="Cancelar", command=win.destroy).pack(pady=10)

    def set_mode(self, mode: str, window: tk.Toplevel):
        self.mode = mode
        window.destroy()
        self.reset_annotations()
        self.mode_indicator.config(text=f"Modo: {mode.capitalize()}")
        if mode == 'crop':
            self.ask_for_aspect_ratio()
            self.aspect_check.pack(side=tk.LEFT, padx=3, before=self.view_check)
        else:
            self.aspect_check.pack_forget()
        if mode == 'ref_line':
            self.save_lines_btn.pack(side=tk.LEFT, padx=3, before=self.edit_mode_button)
        else:
            self.save_lines_btn.pack_forget()
        self.redraw()

    def ask_for_aspect_ratio(self):
        if not self.keep_aspect_ratio.get():
            self.keep_aspect_ratio.set(
                messagebox.askyesno("Manter Proporção", "Manter a proporção original?", parent=self.root)
            )

    # ============================================================
    # Histórico
    # ============================================================
    def reset_annotations(self):
        self.save_state_to_history()
        self.polygons = []
        self.lines = []
        self.current_polygon = []
        self.current_line_start = None
        self.preview_line = None
        self.crop_rect = None
        self.temp_line_id = None
        self.dragging_point = None
        self.dragging_polygon = None
        self.dragging_line_index = None
        self.dragging_line_point_index = None
        self.selected_polygon_index = None
        self.selected_line_index = None
        self.edit_mode = False
        self.edit_mode_button.config(text="Editar Pontos")
        self.redraw()
        self.update_status("Limpo")

    def save_state_to_history(self):
        state = {
            'polygons': [p.copy() for p in self.polygons],
            'lines': [l.copy() for l in self.lines],
            'current_polygon': self.current_polygon.copy(),
            'current_line_start': self.current_line_start,
            'preview_line': self.preview_line,
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
        self.preview_line = prev.get('preview_line')
        self.crop_rect = prev['crop_rect']
        self.next_polygon_id = prev['next_polygon_id']
        self.next_line_id = prev['next_line_id']
        self.next_color_index = prev['next_color_index']
        self.selected_polygon_index = prev['selected_polygon_index']
        self.selected_line_index = prev['selected_line_index']
        self.redraw()
        self.update_status("Desfeito")

    def cancel_operation(self, event=None):
        self.save_state_to_history()
        if self.mode == 'polygon' and self.current_polygon:
            self.current_polygon = []
            self.redraw()
        elif self.mode == 'ref_line' and self.current_line_start:
            self.current_line_start = None
            self.preview_line = None
            self.redraw()
        elif self.mode == 'crop' and self.crop_rect:
            self.crop_rect = None
            self.redraw()

    # ============================================================
    # Desenho no canvas (com armazenamento de IDs para edição rápida)
    # ============================================================
    def redraw(self):
        self.canvas.delete("all")
        self.display_image_on_canvas()
        self.draw_polygons()
        self.draw_lines()
        self.draw_crop_rectangle()
        self.update_temp_line_visibility()

    def display_image_on_canvas(self):
        if self.display_image is None:
            return
        w = int(self.width * self.scale_factor)
        h = int(self.height * self.scale_factor)
        img = self.display_image.resize((w, h), Image.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(img)
        self.canvas.config(scrollregion=(0, 0, w, h))
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image, tags="bg_image")

    def scale_point(self, x, y):
        return x * self.scale_factor, y * self.scale_factor

    def unscale_point(self, cx, cy):
        return cx / self.scale_factor, cy / self.scale_factor

    def draw_polygons(self):
        self.canvas_items['polygons'].clear()
        for idx, poly_data in enumerate(self.polygons):
            pts = [self.scale_point(x, y) for x, y in poly_data['points']]
            outline = "#FFFF00" if (idx == self.selected_polygon_index and not self.view_mode.get()) else poly_data['color']
            w = 4 if idx == self.selected_polygon_index else 3
            pid = self.canvas.create_polygon(pts, outline=outline, fill='', width=w)
            items = {'outline': pid, 'points': []}
            if not self.view_mode.get():
                for i, (sx, sy) in enumerate(pts):
                    fill = "red" if i == 0 else poly_data['color']
                    oid = self.canvas.create_oval(sx-4, sy-4, sx+4, sy+4, fill=fill, outline="white", width=1)
                    items['points'].append(oid)
            if pts:
                cx = sum(p[0] for p in pts) / len(pts)
                cy = sum(p[1] for p in pts) / len(pts)
                txt = f"{poly_data['label']} ({poly_data['id']})"
                tw = len(txt) * 7
                bg = self.canvas.create_rectangle(cx-tw/2-4, cy-12, cx+tw/2+4, cy+4, fill="black", outline="white")
                text = self.canvas.create_text(cx, cy-4, text=txt, fill="white", font=("Arial", 10, "bold"))
                items['label_bg'] = bg
                items['label_text'] = text
            self.canvas_items['polygons'][idx] = items

        self.canvas_items['current_polygon'].clear()
        if self.current_polygon and not self.view_mode.get():
            pts = [self.scale_point(x, y) for x, y in self.current_polygon]
            if len(pts) > 1:
                for i in range(1, len(pts)):
                    self.canvas.create_line(pts[i-1][0], pts[i-1][1], pts[i][0], pts[i][1], fill="#FF0000", width=2)
            for x, y in pts:
                oid = self.canvas.create_oval(x-4, y-4, x+4, y+4, fill="red", outline="white")
                self.canvas_items['current_polygon'].append(oid)

    def draw_lines(self):
        self.canvas_items['lines'].clear()
        for idx, line_data in enumerate(self.lines):
            self._draw_one_line(idx, line_data, is_preview=False)
        if self.preview_line:
            self._draw_one_line(-1, self.preview_line, is_preview=True)

    def _draw_one_line(self, idx, line_data, is_preview=False):
        pt1 = self.scale_point(*line_data['points'][0])
        pt2 = self.scale_point(*line_data['points'][1])

        if is_preview:
            color = "#AAAAAA"
            width = 3
        else:
            color = "#FFFF00" if (idx == self.selected_line_index and not self.view_mode.get()) else line_data['color']
            width = 4 if idx == self.selected_line_index else 3

        lid = self.canvas.create_line(pt1[0], pt1[1], pt2[0], pt2[1], fill=color, width=width)

        if not is_preview:
            items = {'line': lid, 'pt0': None, 'pt1': None}
            if not self.view_mode.get():
                o0 = self.canvas.create_oval(pt1[0]-4, pt1[1]-4, pt1[0]+4, pt1[1]+4, fill="green", outline="white")
                o1 = self.canvas.create_oval(pt2[0]-4, pt2[1]-4, pt2[0]+4, pt2[1]+4, fill="blue", outline="white")
                items['pt0'] = o0
                items['pt1'] = o1
            if not self.view_mode.get():
                arrow_ids = self._create_direction_indicators(pt1, pt2, color)
                items.update(arrow_ids)
            mx = (pt1[0] + pt2[0]) / 2
            my = (pt1[1] + pt2[1]) / 2
            txt = f"{line_data['label']} ({line_data['id']})"
            tw = len(txt) * 7
            bg = self.canvas.create_rectangle(mx-tw/2-4, my-12, mx+tw/2+4, my+4, fill="black", outline="white")
            text = self.canvas.create_text(mx, my-4, text=txt, fill="white", font=("Arial", 10, "bold"))
            items['label_bg'] = bg
            items['label_text'] = text
            self.canvas_items['lines'][idx] = items
        else:
            if not self.view_mode.get():
                self.canvas.create_oval(pt1[0]-4, pt1[1]-4, pt1[0]+4, pt1[1]+4, fill="gray", outline="white")
                self.canvas.create_oval(pt2[0]-4, pt2[1]-4, pt2[0]+4, pt2[1]+4, fill="gray", outline="white")
            mx = (pt1[0] + pt2[0]) / 2
            my = (pt1[1] + pt2[1]) / 2
            self.canvas.create_rectangle(mx-30, my-12, mx+30, my+4, fill="black", outline="white")
            self.canvas.create_text(mx, my-4, text="preview", fill="white", font=("Arial", 10, "bold"))

    def _create_direction_indicators(self, pt1, pt2, color):
        dx = pt2[0] - pt1[0]
        dy = pt2[1] - pt1[1]
        length = (dx*dx + dy*dy) ** 0.5
        if length == 0:
            return {}
        perp_x = -dy / length
        perp_y =  dx / length
        mx = (pt1[0] + pt2[0]) / 2
        my = (pt1[1] + pt2[1]) / 2
        arrow_len = 40 * self.scale_factor
        in_x = mx + perp_x * arrow_len
        in_y = my + perp_y * arrow_len
        in_arrow = self.canvas.create_line(mx, my, in_x, in_y, arrow=tk.LAST, fill=color, width=2)
        in_text = self.canvas.create_text(in_x + perp_x*8, in_y + perp_y*8, text="IN", fill=color, font=("Arial", 9, "bold"))
        out_x = mx - perp_x * arrow_len
        out_y = my - perp_y * arrow_len
        out_arrow = self.canvas.create_line(mx, my, out_x, out_y, arrow=tk.LAST, fill=color, width=2)
        out_text = self.canvas.create_text(out_x - perp_x*8, out_y - perp_y*8, text="OUT", fill=color, font=("Arial", 9, "bold"))
        return {
            'in_arrow': in_arrow,
            'in_text': in_text,
            'out_arrow': out_arrow,
            'out_text': out_text
        }

    def draw_crop_rectangle(self):
        if self.mode == 'crop' and self.crop_rect:
            x1, y1, x2, y2 = self.crop_rect
            sx1, sy1 = self.scale_point(x1, y1)
            sx2, sy2 = self.scale_point(x2, y2)
            self.canvas.create_rectangle(sx1, sy1, sx2, sy2, outline="#00FF00", width=3, dash=(4,2), tags="crop_rect")
            handles = [
                (sx1, sy1), (sx2, sy1), (sx2, sy2), (sx1, sy2),
                ((sx1+sx2)//2, sy1), ((sx1+sx2)//2, sy2),
                (sx1, (sy1+sy2)//2), (sx2, (sy1+sy2)//2)
            ]
            for hx, hy in handles:
                self.canvas.create_rectangle(hx-5, hy-5, hx+5, hy+5, fill="#00FF00", outline="white", tags="resize_handle")

    def update_temp_line_visibility(self):
        if self.temp_line_id:
            self.canvas.delete(self.temp_line_id)
            self.temp_line_id = None
        if self.mode == 'polygon' and self.current_polygon and hasattr(self, 'temp_coords'):
            last = self.scale_point(*self.current_polygon[-1])
            self.temp_line_id = self.canvas.create_line(last[0], last[1], *self.temp_coords, fill="#FF0000", width=2, dash=(4,2))
        elif self.mode == 'ref_line' and self.current_line_start and hasattr(self, 'temp_coords'):
            start = self.scale_point(*self.current_line_start)
            self.temp_line_id = self.canvas.create_line(start[0], start[1], *self.temp_coords, fill="#00AAFF", width=2, dash=(4,2))

    # ============================================================
    # Eventos de mouse
    # ============================================================
    def is_inside_image(self, orig_x, orig_y):
        return 0 <= orig_x <= self.width and 0 <= orig_y <= self.height

    def on_left_click(self, event):
        orig_x, orig_y = self.unscale_point(event.x, event.y)
        if not self.is_inside_image(orig_x, orig_y):
            self.update_status("Clique fora da imagem ignorado")
            return
        if self.mode == 'polygon':
            self.handle_polygon_click(orig_x, orig_y)
        elif self.mode == 'ref_line':
            self.handle_line_click(orig_x, orig_y, event)
        elif self.mode == 'crop':
            self.handle_crop_click(orig_x, orig_y, event)

    def handle_polygon_click(self, ox, oy):
        if self.edit_mode:
            idx, pt = self.find_polygon_point(ox, oy)
            if idx is not None:
                self.save_state_to_history()
                self.dragging_polygon = idx
                self.dragging_point = pt
                p = self.polygons[idx]['points'][pt]
                self.drag_offset = (ox - p[0], oy - p[1])
                return
        if len(self.current_polygon) > 2 and self.close_to_first_point(ox, oy):
            self.finalize_polygon()
            return
        self.save_state_to_history()
        self.current_polygon.append((ox, oy))
        self.redraw_current_polygon()
        self.update_status(f"Ponto adicionado: ({ox:.1f}, {oy:.1f})")

    def handle_line_click(self, ox, oy, event=None):
        if self.edit_mode:
            li, pi = self.find_line_point(ox, oy)
            if li is not None:
                self.save_state_to_history()
                self.dragging_line_index = li
                self.dragging_line_point_index = pi
                p = self.lines[li]['points'][pi]
                self.drag_offset = (ox - p[0], oy - p[1])
                self.selected_line_index = li
                self.redraw()
                return
        li = self.find_line_at_position(ox, oy)
        if li is not None:
            self.selected_line_index = li
            self.redraw()
            return
        if self.current_line_start is None:
            self.save_state_to_history()
            self.current_line_start = (ox, oy)
            self.redraw()
            self.update_status("Clique no segundo ponto")
        else:
            if ((ox-self.current_line_start[0])**2 + (oy-self.current_line_start[1])**2) < 4:
                return
            self.save_state_to_history()
            self.preview_line = {
                'points': [self.current_line_start, (ox, oy)],
                'label': '', 'id': 0, 'color': '#AAAAAA'
            }
            self.redraw()
            info = self.ask_shape_info("Linha")
            if not info["label"]:
                self.preview_line = None
                self.current_line_start = None
                self.redraw()
                self.update_status("Criação cancelada")
                return
            self.preview_line = None
            self.lines.append({
                'points': [self.current_line_start, (ox, oy)],
                'label': info["label"],
                'id': info["id"],
                'color': self.generate_distinct_color()
            })
            self.current_line_start = None
            self.selected_line_index = len(self.lines) - 1
            self.redraw()
            self.update_status(f"Linha '{info['label']}' criada")

    def handle_crop_click(self, ox, oy, event):
        self.save_state_to_history()
        handles = self.canvas.find_withtag("resize_handle")
        for handle in handles:
            x1, y1, x2, y2 = self.canvas.coords(handle)
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self.selected_handle = handle
                self.crop_start_point = (ox, oy)
                self.original_crop_rect = self.crop_rect
                return
        if not self.crop_rect:
            self.crop_start_point = (ox, oy)
        else:
            x1, y1, x2, y2 = self.crop_rect
            if x1 <= ox <= x2 and y1 <= oy <= y2:
                self.rect_moving = True
                self.rect_move_offset = (ox - x1, oy - y1)

    def on_mouse_drag(self, event):
        ox, oy = self.unscale_point(event.x, event.y)
        if self.dragging_point is not None:
            ox = max(0, min(self.width, ox))
            oy = max(0, min(self.height, oy))
            if self.dragging_polygon is not None:
                self.polygons[self.dragging_polygon]['points'][self.dragging_point] = (ox, oy)
                self.update_polygon_canvas(self.dragging_polygon)
            else:
                self.current_polygon[self.dragging_point] = (ox, oy)
                self.redraw_current_polygon()
            return
        if self.dragging_line_index is not None:
            ox = max(0, min(self.width, ox))
            oy = max(0, min(self.height, oy))
            self.lines[self.dragging_line_index]['points'][self.dragging_line_point_index] = (ox, oy)
            self.update_line_canvas(self.dragging_line_index)
            return
        if self.mode == 'crop' and self.crop_start_point:
            if hasattr(self, 'selected_handle'):
                self.resize_crop_rectangle(event)
            else:
                self.update_crop_rectangle(ox, oy)
            self.redraw()
        elif self.mode == 'polygon' and self.current_polygon:
            self.temp_coords = (event.x, event.y)
            self.update_temp_line_visibility()
        elif self.mode == 'ref_line' and self.current_line_start:
            self.temp_coords = (event.x, event.y)
            self.update_temp_line_visibility()

    def on_mouse_release(self, event):
        if self.mode == 'crop' and self.crop_rect:
            self.finalize_crop_rectangle()
            if hasattr(self, 'selected_handle'):
                del self.selected_handle
        if self.dragging_point is not None or self.dragging_line_index is not None:
            self.dragging_point = None
            self.dragging_polygon = None
            self.dragging_line_index = None
            self.dragging_line_point_index = None
            self.save_state_to_history()
        self.temp_coords = None
        self.update_temp_line_visibility()

    def on_mouse_move(self, event):
        ox, oy = self.unscale_point(event.x, event.y)
        self.update_status(f"Img: ({ox:.1f}, {oy:.1f})")
        if self.mode in ('polygon', 'ref_line'):
            if (self.mode == 'polygon' and self.current_polygon) or (self.mode == 'ref_line' and self.current_line_start):
                self.temp_coords = (event.x, event.y)
                self.update_temp_line_visibility()

    # ============================================================
    # Recorte
    # ============================================================
    def resize_crop_rectangle(self, event):
        ox, oy = self.unscale_point(event.x, event.y)
        x1, y1, x2, y2 = self.original_crop_rect
        hx1, hy1, hx2, hy2 = self.canvas.coords(self.selected_handle)
        hcx = (hx1 + hx2) / 2
        hcy = (hy1 + hy2) / 2
        hox, hoy = self.unscale_point(hcx, hcy)
        eps = 5 / self.scale_factor
        left = abs(hox - x1) < eps
        right = abs(hox - x2) < eps
        top = abs(hoy - y1) < eps
        bottom = abs(hoy - y2) < eps
        if left and top: x1, y1 = ox, oy
        elif right and top: x2, y1 = ox, oy
        elif right and bottom: x2, y2 = ox, oy
        elif left and bottom: x1, y2 = ox, oy
        elif top: y1 = oy
        elif bottom: y2 = oy
        elif left: x1 = ox
        elif right: x2 = ox
        else: return
        self.crop_rect = (min(x1,x2), min(y1,y2), max(x1,x2), max(y1,y2))

    def update_crop_rectangle(self, ox, oy):
        if not self.crop_start_point:
            return
        x1, y1 = self.crop_start_point
        x2, y2 = ox, oy
        if self.keep_aspect_ratio.get():
            dx = x2 - x1
            dy = y2 - y1
            if abs(dx) > abs(dy):
                y2 = y1 + dx / self.aspect_ratio
            else:
                x2 = x1 + dy * self.aspect_ratio
        self.crop_rect = (min(x1,x2), min(y1,y2), max(x1,x2), max(y1,y2))

    def finalize_crop_rectangle(self):
        x1, y1, x2, y2 = self.crop_rect
        self.crop_rect = (
            max(0, min(x1, x2)),
            max(0, min(y1, y2)),
            min(self.width, max(x1, x2)),
            min(self.height, max(y1, y2))
        )

    def on_right_click(self, event):
        if self.mode == 'crop' and self.crop_rect:
            self.save_state_to_history()
            ox, oy = self.unscale_point(event.x, event.y)
            x1, y1, x2, y2 = self.crop_rect
            if x1 <= ox <= x2 and y1 <= oy <= y2:
                self.rect_moving = True
                self.rect_move_offset = (ox - x1, oy - y1)

    def on_right_drag(self, event):
        if self.mode == 'crop' and self.rect_moving:
            ox, oy = self.unscale_point(event.x, event.y)
            self.move_crop_rectangle(ox, oy)

    def move_crop_rectangle(self, ox, oy):
        offset_x, offset_y = self.rect_move_offset
        w = self.crop_rect[2] - self.crop_rect[0]
        h = self.crop_rect[3] - self.crop_rect[1]
        x1 = max(0, min(ox - offset_x, self.width - w))
        y1 = max(0, min(oy - offset_y, self.height - h))
        x2 = x1 + w
        y2 = y1 + h
        self.crop_rect = (x1, y1, x2, y2)
        self.redraw()

    def on_right_release(self, event):
        self.rect_moving = False

    # ============================================================
    # Atualização incremental (sem redraw, para edição fluida)
    # ============================================================
    def update_polygon_canvas(self, idx):
        items = self.canvas_items['polygons'].get(idx)
        if not items:
            return
        pts = [self.scale_point(x, y) for x, y in self.polygons[idx]['points']]
        self.canvas.coords(items['outline'], *sum(pts, ()))
        for i, (sx, sy) in enumerate(pts):
            if i < len(items['points']):
                self.canvas.coords(items['points'][i], sx-4, sy-4, sx+4, sy+4)
        if pts:
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            txt = f"{self.polygons[idx]['label']} ({self.polygons[idx]['id']})"
            tw = len(txt) * 7
            self.canvas.coords(items['label_bg'], cx-tw/2-4, cy-12, cx+tw/2+4, cy+4)
            self.canvas.coords(items['label_text'], cx, cy-4)
            self.canvas.itemconfig(items['label_text'], text=txt)

    def update_line_canvas(self, idx):
        items = self.canvas_items['lines'].get(idx)
        if not items:
            return
        pt1 = self.scale_point(*self.lines[idx]['points'][0])
        pt2 = self.scale_point(*self.lines[idx]['points'][1])
        self.canvas.coords(items['line'], pt1[0], pt1[1], pt2[0], pt2[1])
        if items['pt0']:
            self.canvas.coords(items['pt0'], pt1[0]-4, pt1[1]-4, pt1[0]+4, pt1[1]+4)
        if items['pt1']:
            self.canvas.coords(items['pt1'], pt2[0]-4, pt2[1]-4, pt2[0]+4, pt2[1]+4)
        mx = (pt1[0] + pt2[0]) / 2
        my = (pt1[1] + pt2[1]) / 2
        txt = f"{self.lines[idx]['label']} ({self.lines[idx]['id']})"
        tw = len(txt) * 7
        self.canvas.coords(items['label_bg'], mx-tw/2-4, my-12, mx+tw/2+4, my+4)
        self.canvas.coords(items['label_text'], mx, my-4)
        self.canvas.itemconfig(items['label_text'], text=txt)
        dx = pt2[0] - pt1[0]
        dy = pt2[1] - pt1[1]
        length = (dx*dx + dy*dy) ** 0.5
        if length > 0:
            perp_x = -dy / length
            perp_y =  dx / length
            arrow_len = 40 * self.scale_factor
            in_x = mx + perp_x * arrow_len
            in_y = my + perp_y * arrow_len
            out_x = mx - perp_x * arrow_len
            out_y = my - perp_y * arrow_len
            self.canvas.coords(items['in_arrow'], mx, my, in_x, in_y)
            self.canvas.coords(items['in_text'], in_x + perp_x*8, in_y + perp_y*8)
            self.canvas.coords(items['out_arrow'], mx, my, out_x, out_y)
            self.canvas.coords(items['out_text'], out_x - perp_x*8, out_y - perp_y*8)

    def redraw_current_polygon(self):
        for oid in self.canvas_items['current_polygon']:
            self.canvas.delete(oid)
        self.canvas_items['current_polygon'].clear()
        if not self.current_polygon or self.view_mode.get():
            return
        pts = [self.scale_point(x, y) for x, y in self.current_polygon]
        if len(pts) > 1:
            for i in range(1, len(pts)):
                self.canvas.create_line(pts[i-1][0], pts[i-1][1], pts[i][0], pts[i][1], fill="#FF0000", width=2)
        for x, y in pts:
            oid = self.canvas.create_oval(x-4, y-4, x+4, y+4, fill="red", outline="white")
            self.canvas_items['current_polygon'].append(oid)

    # ============================================================
    # Detecção
    # ============================================================
    def find_polygon_point(self, ox, oy):
        for idx, poly in enumerate(self.polygons):
            for i, (px, py) in enumerate(poly['points']):
                if ((px-ox)**2 + (py-oy)**2)**0.5 < 8 / self.scale_factor:
                    return idx, i
        for i, (px, py) in enumerate(self.current_polygon):
            if ((px-ox)**2 + (py-oy)**2)**0.5 < 8 / self.scale_factor:
                return None, i
        return None, None

    def find_line_point(self, ox, oy):
        for idx, line in enumerate(self.lines):
            for i, (px, py) in enumerate(line['points']):
                if ((px-ox)**2 + (py-oy)**2)**0.5 < 8 / self.scale_factor:
                    return idx, i
        return None, None

    def find_line_at_position(self, ox, oy):
        for idx, line in enumerate(self.lines):
            pt1, pt2 = line['points']
            dist = self.point_to_segment_dist(ox, oy, pt1[0], pt1[1], pt2[0], pt2[1])
            if dist < 5 / self.scale_factor:
                return idx
        return None

    @staticmethod
    def point_to_segment_dist(px, py, x1, y1, x2, y2):
        dx, dy = x2-x1, y2-y1
        if dx==0 and dy==0:
            return ((px-x1)**2 + (py-y1)**2)**0.5
        t = ((px-x1)*dx + (py-y1)*dy) / (dx*dx + dy*dy)
        t = max(0, min(1, t))
        proj_x = x1 + t*dx
        proj_y = y1 + t*dy
        return ((px-proj_x)**2 + (py-proj_y)**2)**0.5

    def close_to_first_point(self, ox, oy):
        if not self.current_polygon:
            return False
        fx, fy = self.current_polygon[0]
        return ((ox-fx)**2 + (oy-fy)**2)**0.5 < 10 / self.scale_factor

    def finalize_polygon(self):
        if len(self.current_polygon) < 3:
            return
        info = self.ask_shape_info("Polígono")
        if not info["label"]:
            return
        self.save_state_to_history()
        self.polygons.append({
            'points': self.current_polygon.copy(),
            'label': info["label"],
            'id': info["id"],
            'color': self.generate_distinct_color()
        })
        self.current_polygon = []
        self.redraw()
        self.update_status(f"Polígono '{info['label']}' finalizado")

    def delete_selected(self, event=None):
        self.save_state_to_history()
        if self.mode == 'polygon':
            if self.selected_polygon_index is not None:
                del self.polygons[self.selected_polygon_index]
                self.selected_polygon_index = None
                self.redraw()
            elif self.current_polygon:
                self.current_polygon = []
                self.redraw()
        elif self.mode == 'ref_line':
            if self.selected_line_index is not None:
                del self.lines[self.selected_line_index]
                self.selected_line_index = None
                self.redraw()
            elif self.current_line_start:
                self.current_line_start = None
                self.preview_line = None
                self.redraw()

    # ============================================================
    # Diálogo de nome/ID
    # ============================================================
    def ask_shape_info(self, shape_type="Polígono"):
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Informações da {shape_type}")
        dialog.geometry("300x180")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.configure(bg='#f0f0f0')
        tk.Label(dialog, text="Nome / Label:", bg='#f0f0f0', font=("Arial", 10)).pack(pady=(15,0))
        label_entry = ttk.Entry(dialog, font=("Arial", 10))
        label_entry.pack(pady=5, padx=20, fill=tk.X)
        label_entry.configure(style='Visible.TEntry')
        default_label = f"{shape_type} {self.next_polygon_id if shape_type=='Polígono' else self.next_line_id}"
        label_entry.insert(0, default_label)
        label_entry.focus_set()
        tk.Label(dialog, text="ID:", bg='#f0f0f0', font=("Arial", 10)).pack(pady=(5,0))
        id_entry = ttk.Entry(dialog, font=("Arial", 10))
        id_entry.pack(pady=5, padx=20, fill=tk.X)
        id_entry.configure(style='Visible.TEntry')
        default_id = str(self.next_polygon_id if shape_type=='Polígono' else self.next_line_id)
        id_entry.insert(0, default_id)
        self.shape_info_result = {"label": "", "id": ""}
        def on_ok():
            label = label_entry.get().strip()
            id_val = id_entry.get().strip()
            if not label:
                messagebox.showerror("Erro", "Label não pode ser vazio", parent=dialog)
                return
            try:
                pid = int(id_val)
                if pid <= 0:
                    messagebox.showerror("Erro", "ID deve ser positivo", parent=dialog)
                    return
            except ValueError:
                messagebox.showerror("Erro", "ID deve ser um número inteiro", parent=dialog)
                return
            self.shape_info_result = {"label": label, "id": pid}
            dialog.destroy()
        def on_cancel():
            self.shape_info_result = {"label": "", "id": ""}
            dialog.destroy()
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(btn_frame, text="Cancelar", command=on_cancel).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="OK", command=on_ok).pack(side=tk.RIGHT)
        dialog.protocol("WM_DELETE_WINDOW", on_cancel)
        dialog.update()
        dialog.wait_window()
        return self.shape_info_result

    # ============================================================
    # Salvamento de linhas (com setas reais, cores e anti‑sobreposição)
    # ============================================================
    def save_lines(self):
        if not self.lines:
            messagebox.showwarning("Aviso", "Nenhuma linha")
            return
        if not self.filepath:
            messagebox.showerror("Erro", "Nenhuma imagem base carregada")
            return
        default_name = os.path.splitext(os.path.basename(self.filepath))[0]
        folder_name = simpledialog.askstring("Nome da pasta",
                                             "Digite o nome da subpasta dentro de ./maps:",
                                             initialvalue=default_name,
                                             parent=self.root)
        if not folder_name:
            return
        folder_name = "".join(c for c in folder_name if c.isalnum() or c in (' ', '_', '-')).strip()
        if not folder_name:
            folder_name = default_name
        out_dir = os.path.join(self.maps_dir, folder_name)
        os.makedirs(out_dir, exist_ok=True)
        json_path = os.path.join(out_dir, "lines.json")
        img_path = os.path.join(out_dir, "lines.png")
        if os.path.exists(json_path) and not messagebox.askyesno("Sobrescrever", f"{json_path} já existe. Continuar?"):
            return
        norm_lines = []
        for l in self.lines:
            pt1, pt2 = l['points']
            norm_lines.append({
                'id': l['id'],
                'name': l['label'],
                'x1': pt1[0]/self.width, 'y1': pt1[1]/self.height,
                'x2': pt2[0]/self.width, 'y2': pt2[1]/self.height
            })
        metadata = {
            "frame_size": {"width": self.width, "height": self.height},
            "lines": norm_lines,
            "lines_absolute": [{
                "id": l['id'], "name": l['label'],
                "x1": l['points'][0][0], "y1": l['points'][0][1],
                "x2": l['points'][1][0], "y2": l['points'][1][1]
            } for l in self.lines]
        }
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=4)
        self.export_lines_image(img_path)
        messagebox.showinfo("Sucesso", f"Salvo em {out_dir}")
        self.reset_annotations()

    def _get_bold_font(self, size):
        font_paths = [
            "arialbd.ttf",
            "Arial Bold.ttf",
            "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/Arial Bold.ttf",
        ]
        for path in font_paths:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except:
                    continue
        return None

    def _draw_text_with_outline(self, draw, xy, text, font, text_color, outline_color="black", outline_width=2):
        x, y = xy
        for adj_x in range(-outline_width, outline_width+1):
            for adj_y in range(-outline_width, outline_width+1):
                if adj_x != 0 or adj_y != 0:
                    draw.text((x+adj_x, y+adj_y), text, font=font, fill=outline_color, anchor="mm")
        draw.text((x, y), text, font=font, fill=text_color, anchor="mm")

    def _draw_arrow(self, draw, start, end, fill, width=3, arrow_size=12):
        """Desenha uma linha com ponta de seta triangular."""
        draw.line([start, end], fill=fill, width=width)
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length == 0:
            return
        ux = dx / length
        uy = dy / length
        tip = end
        base = (tip[0] - ux * arrow_size, tip[1] - uy * arrow_size)
        px = -uy
        py = ux
        base_left = (base[0] + px * arrow_size * 0.5, base[1] + py * arrow_size * 0.5)
        base_right = (base[0] - px * arrow_size * 0.5, base[1] - py * arrow_size * 0.5)
        draw.polygon([tip, base_left, base_right], fill=fill)

    def export_lines_image(self, path):
        """Exporta PNG com setas reais, cores por linha e sem sobreposição de textos.
        Labels com 14pt, IN/OUT com 10pt."""
        if not self.display_image:
            return
        img = self.display_image.copy().convert("RGBA")
        overlay = Image.new("RGBA", img.size, (255,255,255,0))
        draw = ImageDraw.Draw(overlay)

        label_size = 14
        arrow_size = 10

        label_font_bold = self._get_bold_font(label_size)
        if label_font_bold is None:
            try:
                label_font_bold = ImageFont.truetype("arial.ttf", label_size)
            except:
                label_font_bold = ImageFont.load_default()

        arrow_font_bold = self._get_bold_font(arrow_size)
        if arrow_font_bold is None:
            try:
                arrow_font_bold = ImageFont.truetype("arial.ttf", arrow_size)
            except:
                arrow_font_bold = label_font_bold

        collision = CollisionAvoidance()
        texts_to_draw = []

        for l in self.lines:
            pt1, pt2 = l['points']
            color = l['color']
            rgb = tuple(int(color[i:i+2], 16) for i in (1,3,5))

            # Linha principal
            draw.line([pt1, pt2], fill=rgb, width=4)

            # Pontos extremos
            r = 6
            draw.ellipse([pt1[0]-r, pt1[1]-r, pt1[0]+r, pt1[1]+r], fill="green", outline="black", width=2)
            draw.ellipse([pt2[0]-r, pt2[1]-r, pt2[0]+r, pt2[1]+r], fill="blue", outline="black", width=2)

            # Direção com setas
            dx, dy = pt2[0]-pt1[0], pt2[1]-pt1[1]
            length = (dx**2+dy**2)**0.5
            if length > 0:
                perp_x, perp_y = -dy/length, dx/length
                mx, my = (pt1[0]+pt2[0])/2, (pt1[1]+pt2[1])/2
                arrow_len = 50
                text_offset = 20

                # IN
                in_x = mx + perp_x * arrow_len
                in_y = my + perp_y * arrow_len
                self._draw_arrow(draw, (mx, my), (in_x, in_y), fill=rgb, width=3, arrow_size=12)
                in_text_x = mx + perp_x * (arrow_len + text_offset)
                in_text_y = my + perp_y * (arrow_len + text_offset)
                texts_to_draw.append((in_text_x, in_text_y, "IN", arrow_font_bold, rgb, "direction"))

                # OUT
                out_x = mx - perp_x * arrow_len
                out_y = my - perp_y * arrow_len
                self._draw_arrow(draw, (mx, my), (out_x, out_y), fill=rgb, width=3, arrow_size=12)
                out_text_x = mx - perp_x * (arrow_len + text_offset)
                out_text_y = my - perp_y * (arrow_len + text_offset)
                texts_to_draw.append((out_text_x, out_text_y, "OUT", arrow_font_bold, rgb, "direction"))

            # Label da linha
            mx, my = (pt1[0]+pt2[0])/2, (pt1[1]+pt2[1])/2
            text = f"{l['label']} ({l['id']})"
            texts_to_draw.append((mx, my, text, label_font_bold, rgb, "label"))

        # Desenha textos com anti‑colisão
        for (cx, cy, text, font, color, typ) in texts_to_draw:
            bbox_text = draw.textbbox((0, 0), text, font=font, anchor="mm")
            text_width = bbox_text[2] - bbox_text[0]
            text_height = bbox_text[3] - bbox_text[1]
            margin = 6
            box_width = text_width + 2 * margin
            box_height = text_height + 8

            final_y = collision.find_free_y(cx, cy, box_width, box_height)
            draw.rectangle([cx - box_width//2, final_y - box_height//2,
                            cx + box_width//2, final_y + box_height//2],
                           fill=(0,0,0,255))
            self._draw_text_with_outline(draw, (cx, final_y), text, font, color, "black", 2)

        out = Image.alpha_composite(img, overlay)
        out.save(path)

    # ============================================================
    # Demais métodos de salvamento/exportação (mantidos)
    # ============================================================
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
        normalized = []
        for p in self.polygons:
            norm_pts = [(x/self.width, y/self.height) for x, y in p['points']]
            normalized.append({'points': norm_pts, 'label': p['label'], 'id': p['id']})
        metadata = {
            "frame_size": {"width": self.width, "height": self.height},
            "polygons": [{'label': p['label'], 'id': p['id'], 'points': p['points']} for p in self.polygons],
            "polygons_normalized": normalized
        }
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)
        messagebox.showinfo("Sucesso", f"Polígonos salvos: {save_path}")
        self.reset_annotations()

    def save_crop(self):
        if not self.crop_rect:
            messagebox.showwarning("Aviso", "Nenhuma área de recorte definida")
            return
        x1, y1, x2, y2 = self.crop_rect
        cropped = self.display_image.crop((int(x1), int(y1), int(x2), int(y2)))
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
        w = x2_rel - x1_rel
        h = y2_rel - y1_rel
        metadata = {
            "original_size": {"width": self.width, "height": self.height},
            "crop_coordinates_relative": {"x1": x1_rel, "y1": y1_rel, "x2": x2_rel, "y2": y2_rel},
            "crop_coordinates_absolute": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
            "yolo_format": {"center_x": center_x, "center_y": center_y, "width": w, "height": h}
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
        base = self.display_image.copy()
        draw = ImageDraw.Draw(base)
        for p in self.polygons:
            pts = p['points']
            color = p['color']
            rgb = tuple(int(color[i:i+2], 16) for i in (1,3,5))
            draw.polygon(pts, outline=rgb, width=3)
            if pts:
                cx = sum(x for x, y in pts) / len(pts)
                cy = sum(y for x, y in pts) / len(pts)
                try:
                    font = ImageFont.truetype("arial.ttf", 16)
                except:
                    font = ImageFont.load_default()
                txt = f"{p['label']} ({p['id']})"
                bbox = draw.textbbox((cx, cy), txt, font=font)
                draw.rectangle([bbox[0]-2, bbox[1]-2, bbox[2]+2, bbox[3]+2], fill=(0,0,0,128))
                draw.text((cx, cy), txt, font=font, fill=(255,255,255))
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
        if messagebox.askokcancel("Sair", "Deseja sair?"):
            self.root.destroy()

if __name__ == "__main__":
    root = ThemedTk(theme="arc")
    app = ImageEditor(root)
    root.mainloop()