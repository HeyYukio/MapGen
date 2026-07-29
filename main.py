"""
Map Editor – Ferramenta para demarcar linhas de referência, polígonos e recortes.
Salva automaticamente em ./maps/<nome_da_pasta>/lines.json + lines.png
Com indicadores de direção (IN/OUT) para uso com YOLO.
Lida corretamente com imagens pequenas: ajusta a visualização e restringe
marcações apenas à área da imagem, mantendo as coordenadas normalizadas.
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


class ImageEditor:
    def __init__(self, root: ThemedTk):
        self.root = root
        self.root.title("Map Editor")
        self.style = ttk.Style()

        # Tenta usar o tema 'arc' (moderno). Se não existir, usa 'clam'.
        try:
            self.style.theme_use('arc')
        except:
            self.style.theme_use('clam')

        # -------------------------------------------------------
        # CORREÇÃO VISUAL: garante texto legível nos diálogos de arquivo
        # -------------------------------------------------------
        self.root.option_add('*Listbox.selectForeground', 'black')
        self.root.option_add('*Listbox.selectBackground', '#c0c0ff')
        self.root.option_add('*Entry.foreground', 'black')
        self.root.option_add('*Entry.background', 'white')
        self.root.option_add('*TCombobox*Listbox.selectForeground', 'black')
        self.root.option_add('*TCombobox*Listbox.selectBackground', '#c0c0ff')

        # Canvas com barras de rolagem
        self.frame = ttk.Frame(root)
        self.frame.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(self.frame, width=1200, height=800, bg="#e0e0e0")
        self.h_scroll = ttk.Scrollbar(self.frame, orient="horizontal", command=self.canvas.xview)
        self.v_scroll = ttk.Scrollbar(self.frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self.h_scroll.set, yscrollcommand=self.v_scroll.set)
        self.h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Overlay para zoom (não usado atualmente, mas mantido)
        self.overlay = tk.Canvas(root, width=200, height=200, bg="white", bd=2, relief="solid")
        self.overlay.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=10)
        self.overlay.place_forget()
        self.overlay_visible = False

        # -------------------------------------------------------
        # Variáveis de estado
        # -------------------------------------------------------
        self.mode = None                     # 'polygon', 'crop' ou 'ref_line'
        self.original_image: Optional[np.ndarray] = None
        self.display_image: Optional[Image.Image] = None
        self.filepath: Optional[str] = None
        self.polygons: List[Dict] = []
        self.lines: List[Dict] = []
        self.current_polygon: List[Tuple[float, float]] = []  # armazenado em coordenadas originais
        self.current_line_start: Optional[Tuple[float, float]] = None
        self.crop_rect: Optional[Tuple[int, int, int, int]] = None  # em coordenadas do canvas? Melhor manter original
        self.crop_start_point: Optional[Tuple[int, int]] = None
        self.rect_moving = False
        self.keep_aspect_ratio = tk.BooleanVar(value=True)
        self.initial_load = True
        self.rect_move_offset = (0, 0)
        self.scale_factor = 1.0             # fator de escala atual
        self.zoom_state = False
        self.pan_start = None
        self.aspect_ratio = 1.0
        self.temp_line_id = None
        self.action_history: Deque = deque(maxlen=50)

        # Arraste de pontos
        self.dragging_polygon = None
        self.dragging_point = None
        self.dragging_line_index = None
        self.dragging_line_point_index = None
        self.drag_offset = (0, 0)

        # IDs automáticos
        self.next_polygon_id = 1
        self.next_line_id = 1
        self.next_color_index = 0

        # Seleção
        self.selected_polygon_index = None
        self.selected_line_index = None

        # Flags de modo
        self.view_mode = tk.BooleanVar(value=False)
        self.edit_mode = False

        # Cache de itens do canvas para performance
        self.canvas_items = {'polygons': {}, 'lines': {}, 'current_polygon': []}

        # Pastas padrão
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
        """Gera cores diferentes usando proporção áurea."""
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

        # Ajusta escala inicial para preencher o canvas
        self.fit_image_to_canvas()

        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.show_mode_selection()
        self.update_status(f"Carregado: {os.path.basename(filepath)}")

    def fit_image_to_canvas(self):
        """Ajusta self.scale_factor para que a imagem caiba no canvas mantendo a proporção."""
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        if canvas_width <= 1 or canvas_height <= 1:  # ainda não desenhado
            canvas_width, canvas_height = 1200, 800
        scale_w = canvas_width / self.width
        scale_h = canvas_height / self.height
        self.scale_factor = min(scale_w, scale_h)
        # Garante que não fique minúsculo (mínimo 0.1) nem gigante (máximo 10)
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
        self.update_status("Desfeito")

    def cancel_operation(self, event=None):
        self.save_state_to_history()
        if self.mode == 'polygon' and self.current_polygon:
            self.current_polygon = []
            self.redraw()
        elif self.mode == 'ref_line' and self.current_line_start:
            self.current_line_start = None
            self.redraw()
        elif self.mode == 'crop' and self.crop_rect:
            self.crop_rect = None
            self.redraw()

    # ============================================================
    # Desenho (coordenadas originais multiplicadas por scale_factor)
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
        # Redimensiona de acordo com scale_factor
        w = int(self.width * self.scale_factor)
        h = int(self.height * self.scale_factor)
        img = self.display_image.resize((w, h), Image.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(img)
        self.canvas.config(scrollregion=(0, 0, w, h))
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image, tags="bg_image")

    def scale_point(self, x, y):
        """Converte coordenadas da imagem original para coordenadas do canvas."""
        return x * self.scale_factor, y * self.scale_factor

    def unscale_point(self, cx, cy):
        """Converte coordenadas do canvas para coordenadas da imagem original."""
        return cx / self.scale_factor, cy / self.scale_factor

    def draw_polygons(self):
        self.canvas_items['polygons'].clear()
        for idx, poly_data in enumerate(self.polygons):
            # Pontos em coordenadas originais
            points = [self.scale_point(x, y) for x, y in poly_data['points']]
            outline_color = "#FFFF00" if (idx == self.selected_polygon_index and not self.view_mode.get()) else poly_data['color']
            width = 4 if idx == self.selected_polygon_index else 3
            pid = self.canvas.create_polygon(points, outline=outline_color, fill='', width=width)
            self.canvas_items['polygons'][idx] = {'outline': pid, 'points': []}
            if not self.view_mode.get():
                for i, (sx, sy) in enumerate(points):
                    fill = "red" if i == 0 else poly_data['color']
                    oid = self.canvas.create_oval(sx-4, sy-4, sx+4, sy+4, fill=fill, outline="white", width=1)
                    self.canvas_items['polygons'][idx]['points'].append(oid)
            if points:
                cx = sum(p[0] for p in points) / len(points)
                cy = sum(p[1] for p in points) / len(points)
                text = f"{poly_data['label']} ({poly_data['id']})"
                tw = len(text) * 7
                self.canvas.create_rectangle(cx - tw/2 - 4, cy - 12, cx + tw/2 + 4, cy + 4, fill="black", outline="white")
                self.canvas.create_text(cx, cy - 4, text=text, fill="white", font=("Arial", 10, "bold"))

        # Polígono atual
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
            pt1 = self.scale_point(*line_data['points'][0])
            pt2 = self.scale_point(*line_data['points'][1])
            color = "#FFFF00" if (idx == self.selected_line_index and not self.view_mode.get()) else line_data['color']
            width = 4 if idx == self.selected_line_index else 3
            lid = self.canvas.create_line(pt1[0], pt1[1], pt2[0], pt2[1], fill=color, width=width)
            self.canvas_items['lines'][idx] = {'line': lid, 'pt0': None, 'pt1': None}
            if not self.view_mode.get():
                o0 = self.canvas.create_oval(pt1[0]-4, pt1[1]-4, pt1[0]+4, pt1[1]+4, fill="green", outline="white")
                o1 = self.canvas.create_oval(pt2[0]-4, pt2[1]-4, pt2[0]+4, pt2[1]+4, fill="blue", outline="white")
                self.canvas_items['lines'][idx]['pt0'] = o0
                self.canvas_items['lines'][idx]['pt1'] = o1

            if not self.view_mode.get():
                self.draw_direction_indicators(pt1, pt2, color)

            mx = (pt1[0] + pt2[0]) / 2
            my = (pt1[1] + pt2[1]) / 2
            text = f"{line_data['label']} ({line_data['id']})"
            tw = len(text) * 7
            self.canvas.create_rectangle(mx - tw/2 - 4, my - 12, mx + tw/2 + 4, my + 4, fill="black", outline="white")
            self.canvas.create_text(mx, my - 4, text=text, fill="white", font=("Arial", 10, "bold"))

    def draw_direction_indicators(self, pt1, pt2, color):
        dx = pt2[0] - pt1[0]
        dy = pt2[1] - pt1[1]
        length = (dx**2 + dy**2) ** 0.5
        if length == 0:
            return
        perp_x = -dy / length
        perp_y = dx / length
        mid_x = (pt1[0] + pt2[0]) / 2
        mid_y = (pt1[1] + pt2[1]) / 2
        arrow_len = 40 * self.scale_factor  # ajusta tamanho da seta conforme escala
        in_x = mid_x + perp_x * arrow_len
        in_y = mid_y + perp_y * arrow_len
        self.canvas.create_line(mid_x, mid_y, in_x, in_y, arrow=tk.LAST, fill=color, width=2)
        self.canvas.create_text(in_x + perp_x*8, in_y + perp_y*8, text="IN", fill=color, font=("Arial", 9, "bold"))
        out_x = mid_x - perp_x * arrow_len
        out_y = mid_y - perp_y * arrow_len
        self.canvas.create_line(mid_x, mid_y, out_x, out_y, arrow=tk.LAST, fill=color, width=2)
        self.canvas.create_text(out_x - perp_x*8, out_y - perp_y*8, text="OUT", fill=color, font=("Arial", 9, "bold"))

    def draw_crop_rectangle(self):
        if self.mode == 'crop' and self.crop_rect:
            # crop_rect armazenado em coordenadas originais? No código anterior era em canvas.
            # Vamos padronizar: armazenar em coordenadas originais.
            x1, y1, x2, y2 = self.crop_rect
            sx1, sy1 = self.scale_point(x1, y1)
            sx2, sy2 = self.scale_point(x2, y2)
            self.canvas.create_rectangle(sx1, sy1, sx2, sy2, outline="#00FF00", width=3, dash=(4,2))

    def update_temp_line_visibility(self):
        if self.temp_line_id:
            self.canvas.delete(self.temp_line_id)
            self.temp_line_id = None
        if self.mode == 'polygon' and self.current_polygon and hasattr(self, 'temp_coords'):
            last_pt = self.scale_point(*self.current_polygon[-1])
            temp = self.temp_coords  # já está em canvas? Depende: vamos manter temp_coords em canvas
            self.temp_line_id = self.canvas.create_line(last_pt[0], last_pt[1], temp[0], temp[1], fill="#FF0000", width=2, dash=(4,2))
        elif self.mode == 'ref_line' and self.current_line_start and hasattr(self, 'temp_coords'):
            start = self.scale_point(*self.current_line_start)
            temp = self.temp_coords  # canvas
            self.temp_line_id = self.canvas.create_line(start[0], start[1], temp[0], temp[1], fill="#00AAFF", width=2, dash=(4,2))

    # ============================================================
    # Eventos de mouse (com validação de limites)
    # ============================================================
    def is_inside_image(self, orig_x, orig_y):
        """Verifica se as coordenadas originais estão dentro da imagem."""
        return 0 <= orig_x <= self.width and 0 <= orig_y <= self.height

    def on_left_click(self, event):
        # Converte para coordenadas originais
        orig_x, orig_y = self.unscale_point(event.x, event.y)
        if not self.is_inside_image(orig_x, orig_y):
            self.update_status("Clique fora da imagem ignorado")
            return
        if self.mode == 'polygon':
            self.handle_polygon_click(orig_x, orig_y)
        elif self.mode == 'ref_line':
            self.handle_line_click(orig_x, orig_y)
        elif self.mode == 'crop':
            self.handle_crop_click(orig_x, orig_y)

    def handle_polygon_click(self, orig_x, orig_y):
        if self.edit_mode:
            poly_idx, pt_idx = self.find_polygon_point(orig_x, orig_y)
            if poly_idx is not None:
                self.save_state_to_history()
                self.dragging_polygon = poly_idx
                self.dragging_point = pt_idx
                point = self.polygons[poly_idx]['points'][pt_idx]
                self.drag_offset = (orig_x - point[0], orig_y - point[1])
                return
        if len(self.current_polygon) > 2 and self.close_to_first_point(orig_x, orig_y):
            self.finalize_polygon()
            return
        self.save_state_to_history()
        self.current_polygon.append((orig_x, orig_y))
        self.redraw_current_polygon()
        self.update_status(f"Ponto adicionado: ({orig_x:.1f}, {orig_y:.1f})")

    def handle_line_click(self, orig_x, orig_y):
        if self.edit_mode:
            line_idx, pt_idx = self.find_line_point(orig_x, orig_y)
            if line_idx is not None:
                self.save_state_to_history()
                self.dragging_line_index = line_idx
                self.dragging_line_point_index = pt_idx
                point = self.lines[line_idx]['points'][pt_idx]
                self.drag_offset = (orig_x - point[0], orig_y - point[1])
                self.selected_line_index = line_idx
                self.redraw()
                return
        line_idx = self.find_line_at_position(orig_x, orig_y)
        if line_idx is not None:
            self.selected_line_index = line_idx
            self.redraw()
            return
        if self.current_line_start is None:
            self.save_state_to_history()
            self.current_line_start = (orig_x, orig_y)
            self.redraw()
            self.update_status("Clique no segundo ponto")
        else:
            # Verifica distância mínima
            if ((orig_x - self.current_line_start[0])**2 + (orig_y - self.current_line_start[1])**2) < 4:
                return
            info = self.ask_shape_info("Linha")
            if not info["label"]:
                self.current_line_start = None
                self.redraw()
                return
            self.save_state_to_history()
            self.lines.append({
                'points': [self.current_line_start, (orig_x, orig_y)],
                'label': info["label"],
                'id': info["id"],
                'color': self.generate_distinct_color()
            })
            self.current_line_start = None
            self.selected_line_index = len(self.lines) - 1
            self.redraw()
            self.update_status(f"Linha '{info['label']}' criada")

    def handle_crop_click(self, orig_x, orig_y):
        # crop_rect em coordenadas originais
        self.save_state_to_history()
        # Verifica handles de redimensionamento (feito no canvas)
        # Necessário adaptar: converter handles para originais? Melhor manter crop_rect em originais e manipular no canvas.
        # Para simplificar, vamos manter crop_rect em coordenadas originais.
        if not self.crop_rect:
            self.crop_start_point = (orig_x, orig_y)
        else:
            x1, y1, x2, y2 = self.crop_rect
            if x1 <= orig_x <= x2 and y1 <= orig_y <= y2:
                self.rect_moving = True
                self.rect_move_offset = (orig_x - x1, orig_y - y1)

    def on_mouse_drag(self, event):
        orig_x, orig_y = self.unscale_point(event.x, event.y)
        # Se estiver arrastando ponto, permite sair um pouco? Melhor manter dentro.
        if self.dragging_point is not None:
            # Mantém dentro dos limites
            orig_x = max(0, min(self.width, orig_x))
            orig_y = max(0, min(self.height, orig_y))
            if self.dragging_polygon is not None:
                self.polygons[self.dragging_polygon]['points'][self.dragging_point] = (orig_x, orig_y)
                self.update_polygon_canvas(self.dragging_polygon)
            else:
                self.current_polygon[self.dragging_point] = (orig_x, orig_y)
                self.redraw_current_polygon()
            return
        if self.dragging_line_index is not None:
            orig_x = max(0, min(self.width, orig_x))
            orig_y = max(0, min(self.height, orig_y))
            self.lines[self.dragging_line_index]['points'][self.dragging_line_point_index] = (orig_x, orig_y)
            self.update_line_canvas(self.dragging_line_index)
            return
        if self.mode == 'crop' and self.crop_start_point:
            # Lógica de recorte usando coordenadas originais
            if hasattr(self, 'selected_handle'):
                self.resize_crop_rectangle(event)
            else:
                self.update_crop_rectangle(orig_x, orig_y)
            self.redraw()
        elif self.mode == 'polygon' and self.current_polygon:
            self.temp_coords = (event.x, event.y)  # mantido em canvas para linha temporária
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
        orig_x, orig_y = self.unscale_point(event.x, event.y)
        self.update_status(f"Img: ({orig_x:.1f}, {orig_y:.1f})")
        if self.mode in ('polygon', 'ref_line'):
            if (self.mode == 'polygon' and self.current_polygon) or (self.mode == 'ref_line' and self.current_line_start):
                self.temp_coords = (event.x, event.y)
                self.update_temp_line_visibility()

    # ============================================================
    # Atualização incremental
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
        self.redraw()

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
        self.redraw()

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
    # Funções de detecção (trabalham com coordenadas originais)
    # ============================================================
    def find_polygon_point(self, orig_x, orig_y):
        for idx, poly in enumerate(self.polygons):
            for i, (px, py) in enumerate(poly['points']):
                if ((px - orig_x)**2 + (py - orig_y)**2)**0.5 < 8 / self.scale_factor:
                    return idx, i
        for i, (px, py) in enumerate(self.current_polygon):
            if ((px - orig_x)**2 + (py - orig_y)**2)**0.5 < 8 / self.scale_factor:
                return None, i
        return None, None

    def find_line_point(self, orig_x, orig_y):
        for idx, line in enumerate(self.lines):
            for i, (px, py) in enumerate(line['points']):
                if ((px - orig_x)**2 + (py - orig_y)**2)**0.5 < 8 / self.scale_factor:
                    return idx, i
        return None, None

    def find_line_at_position(self, orig_x, orig_y):
        for idx, line in enumerate(self.lines):
            pt1, pt2 = line['points']
            dist = self.point_to_segment_dist(orig_x, orig_y, pt1[0], pt1[1], pt2[0], pt2[1])
            if dist < 5 / self.scale_factor:
                return idx
        return None

    @staticmethod
    def point_to_segment_dist(px, py, x1, y1, x2, y2):
        dx = x2 - x1
        dy = y2 - y1
        if dx == 0 and dy == 0:
            return ((px-x1)**2 + (py-y1)**2) ** 0.5
        t = ((px-x1)*dx + (py-y1)*dy) / (dx*dx + dy*dy)
        t = max(0, min(1, t))
        projx = x1 + t*dx
        projy = y1 + t*dy
        return ((px-projx)**2 + (py-projy)**2) ** 0.5

    def close_to_first_point(self, orig_x, orig_y):
        if not self.current_polygon:
            return False
        fx, fy = self.current_polygon[0]
        return ((orig_x - fx)**2 + (orig_y - fy)**2)**0.5 < 10 / self.scale_factor

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

    # ============================================================
    # Salvamento
    # ============================================================
    def save_lines(self):
        if not self.lines:
            messagebox.showwarning("Aviso", "Nenhuma linha")
            return
        if not self.filepath:
            messagebox.showerror("Erro", "Nenhuma imagem base carregada")
            return
        default_name = os.path.splitext(os.path.basename(self.filepath))[0]
        folder_name = simpledialog.askstring(
            "Nome da pasta",
            "Digite o nome da subpasta dentro de ./maps:",
            initialvalue=default_name,
            parent=self.root
        )
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
        # Normalização
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

    def export_lines_image(self, path):
        if not self.display_image:
            return
        img = self.display_image.copy()
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 16)
        except:
            font = ImageFont.load_default()
        for l in self.lines:
            pt1, pt2 = l['points']  # originais
            color = l['color']
            rgb = tuple(int(color[i:i+2], 16) for i in (1,3,5))
            draw.line([pt1, pt2], fill=rgb, width=4)
            r = 4
            draw.ellipse([pt1[0]-r, pt1[1]-r, pt1[0]+r, pt1[1]+r], fill="green")
            draw.ellipse([pt2[0]-r, pt2[1]-r, pt2[0]+r, pt2[1]+r], fill="blue")
            dx, dy = pt2[0]-pt1[0], pt2[1]-pt1[1]
            length = (dx**2+dy**2)**0.5
            if length:
                perp_x, perp_y = -dy/length, dx/length
                mx, my = (pt1[0]+pt2[0])/2, (pt1[1]+pt2[1])/2
                in_x, in_y = mx+perp_x*40, my+perp_y*40
                out_x, out_y = mx-perp_x*40, my-perp_y*40
                draw.line([mx, my, in_x, in_y], fill=rgb, width=2)
                draw.line([mx, my, out_x, out_y], fill=rgb, width=2)
                draw.text((in_x+perp_x*8, in_y+perp_y*8), "IN", fill=rgb, font=font)
                draw.text((out_x-perp_x*8, out_y-perp_y*8), "OUT", fill=rgb, font=font)
            text = f"{l['label']} ({l['id']})"
            draw.text((mx, my-12), text, fill=rgb, font=font)
        img.save(path)

    # Métodos de recorte e exportação mantidos (adaptados para coordenadas originais)
    def resize_crop_rectangle(self, event):
        # Implementar conforme necessidade, usando unscale_point
        pass

    def update_crop_rectangle(self, orig_x, orig_y):
        if not self.crop_start_point:
            return
        x1, y1 = self.crop_start_point
        x2, y2 = orig_x, orig_y
        if self.keep_aspect_ratio.get():
            dx = x2 - x1
            dy = y2 - y1
            if abs(dx) > abs(dy):
                y2 = y1 + dx / self.aspect_ratio
            else:
                x2 = x1 + dy * self.aspect_ratio
        self.crop_rect = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

    def finalize_crop_rectangle(self):
        x1, y1, x2, y2 = self.crop_rect
        self.crop_rect = (
            max(0, min(x1, x2)),
            max(0, min(y1, y2)),
            min(self.width, max(x1, x2)),
            min(self.height, max(y1, y2))
        )

    def on_right_click(self, event):
        orig_x, orig_y = self.unscale_point(event.x, event.y)
        if self.mode == 'crop' and self.crop_rect:
            self.save_state_to_history()
            x1, y1, x2, y2 = self.crop_rect
            if x1 <= orig_x <= x2 and y1 <= orig_y <= y2:
                self.rect_moving = True
                self.rect_move_offset = (orig_x - x1, orig_y - y1)

    def on_right_drag(self, event):
        if self.mode == 'crop' and self.rect_moving:
            orig_x, orig_y = self.unscale_point(event.x, event.y)
            self.move_crop_rectangle(orig_x, orig_y)

    def move_crop_rectangle(self, orig_x, orig_y):
        offset_x, offset_y = self.rect_move_offset
        rect_width = self.crop_rect[2] - self.crop_rect[0]
        rect_height = self.crop_rect[3] - self.crop_rect[1]
        x1 = max(0, min(orig_x - offset_x, self.width - rect_width))
        y1 = max(0, min(orig_y - offset_y, self.height - rect_height))
        x2 = x1 + rect_width
        y2 = y1 + rect_height
        self.crop_rect = (x1, y1, x2, y2)
        self.redraw()

    def on_right_release(self, event):
        self.rect_moving = False

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
        base = self.display_image.copy()
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
        if messagebox.askokcancel("Sair", "Deseja sair?"):
            self.root.destroy()

if __name__ == "__main__":
    root = ThemedTk(theme="arc")
    app = ImageEditor(root)
    root.mainloop()