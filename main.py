import cv2
import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from tkinter import ttk
from ttkthemes import ThemedTk
from PIL import Image, ImageTk, ImageOps
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
        
        # Canvas com fundo branco
        self.canvas = tk.Canvas(self.frame, width=1200, height=800, bg="white")
        self.h_scroll = ttk.Scrollbar(self.frame, orient="horizontal", command=self.canvas.xview)
        self.v_scroll = ttk.Scrollbar(self.frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self.h_scroll.set, yscrollcommand=self.v_scroll.set)
        
        self.h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Configuração do overlay para zoom
        self.overlay = tk.Canvas(root, width=200, height=200, bg="white", bd=2, relief="solid")
        self.overlay.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=10)
        self.overlay.place_forget()  # Inicialmente oculto
        self.overlay_visible = False

        # Estados e variáveis de controle
        self.mode = None
        self.original_image: Optional[np.ndarray] = None
        self.display_image: Optional[Image.Image] = None
        self.filepath: Optional[str] = None
        self.polygons: List[Dict] = []  # Armazena dicionários com 'points', 'label', 'id' e 'color'
        self.current_polygon: List[Tuple[int, int]] = []
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
        self.action_history: Deque = deque(maxlen=50)  # Histórico de ações para Ctrl+Z
        self.dragging_point = None  # Ponto sendo arrastado (polygon_index, point_index)
        self.dragging_polygon = None  # Polígono sendo arrastado (polygon_index)
        self.drag_offset = (0, 0)  # Offset para arrastar polígono
        self.next_polygon_id = 1  # Contador para IDs de polígonos
        self.next_color_index = 0  # Índice para cores de polígonos
        self.selected_polygon_index = None  # Polígono selecionado para remoção

        self.setup_ui()
        self.setup_bindings()
        
        # Mostrar mensagem de boas-vindas
        self.show_welcome_message()
        
        # Agendar carregamento da imagem para depois da UI estar pronta
        self.root.after(100, self.load_image)

    def generate_distinct_color(self):
        """Gera uma cor distinta para cada polígono usando HSL"""
        hue = self.next_color_index * 0.618033988749895  # Ângulo dourado
        hue = hue % 1.0
        r, g, b = colorsys.hls_to_rgb(hue, 0.5, 0.9)
        self.next_color_index += 1
        return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"

    def show_welcome_message(self):
        """Exibe uma mensagem de boas-vindas no canvas"""
        self.canvas.delete("all")
        self.canvas.create_text(400, 300, text="Map Editor", 
                              font=("Arial", 24), fill="navy")
        self.canvas.create_text(400, 350, text="Selecione uma imagem para começar", 
                              font=("Arial", 14), fill="gray")
        self.canvas.create_text(400, 400, text="Use Ctrl+O para abrir uma imagem", 
                              font=("Arial", 12), fill="gray")
        self.update_status("Pronto para carregar uma imagem")

    def setup_ui(self):
        """Configura elementos de UI adicionais"""
        # Barra de status
        self.status_bar = ttk.Label(self.root, text="Ready | Mode: None | Image: None", anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Barra de ferramentas
        self.toolbar = ttk.Frame(self.root)
        self.toolbar.pack(side=tk.TOP, fill=tk.X)
        
        # Botões da barra de ferramentas
        ttk.Button(
            self.toolbar, 
            text="Abrir Imagem", 
            command=self.load_image,
            width=12
        ).pack(side=tk.LEFT, padx=5, pady=2)
        
        ttk.Button(
            self.toolbar, 
            text="Zoom", 
            command=self.toggle_zoom,
            width=8
        ).pack(side=tk.LEFT, padx=5, pady=2)
        
        # Checkbutton só aparece no modo recorte
        self.aspect_check = ttk.Checkbutton(
            self.toolbar,
            text="Manter Proporção",
            variable=self.keep_aspect_ratio
        )
        
        ttk.Button(
            self.toolbar,
            text="Desfazer (Ctrl+Z)",
            command=self.undo_action,
            width=15
        ).pack(side=tk.LEFT, padx=5, pady=2)
        
        ttk.Button(
            self.toolbar,
            text="Limpar Tudo",
            command=self.reset_annotations,
            width=10
        ).pack(side=tk.LEFT, padx=5, pady=2)
        
        # Indicador de modo
        self.mode_indicator = ttk.Label(
            self.toolbar, 
            text="Modo Atual: Nenhum", 
            foreground="blue",
            font=("Arial", 10, "bold")
        )
        self.mode_indicator.pack(side=tk.RIGHT, padx=10)

    def setup_bindings(self):
        """Configura todos os bindings de eventos"""
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
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.canvas.bind("<Button-2>", self.start_pan)  # Botão do meio do mouse
        self.canvas.bind("<B2-Motion>", self.on_pan)

    def update_status(self, message: str):
        """Atualiza a barra de status"""
        mode_text = f"Modo: {self.mode.capitalize()}" if self.mode else "Modo: Nenhum"
        img_text = f"Imagem: {os.path.basename(self.filepath)}" if self.filepath else "Imagem: Nenhuma"
        self.status_bar.config(text=f"{message} | {mode_text} | {img_text}")

    def toggle_zoom(self):
        """Ativa/desativa o modo zoom"""
        # Desativa zoom no modo polígono
        if self.mode == 'polygon':
            self.update_status("Zoom não disponível no modo polígono")
            return
            
        self.zoom_state = not self.zoom_state
        if self.zoom_state:
            self.overlay.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=10)  # Mostra
        else:
            self.overlay.place_forget()  # Oculta
        self.update_status("Zoom: ON" if self.zoom_state else "Zoom: OFF")

    def set_custom_aspect_ratio(self):
        """Define uma proporção de aspecto personalizada"""
        ratio = simpledialog.askstring(
            "Proporção Personalizada",
            "Digite a proporção (largura:altura):",
            initialvalue="16:9"
        )
        
        if ratio:
            try:
                w, h = map(float, ratio.split(':'))
                self.aspect_ratio = w / h
                self.keep_aspect_ratio.set(True)
                self.update_status(f"Proporção definida: {w}:{h}")
            except (ValueError, ZeroDivisionError):
                messagebox.showerror("Erro", "Formato de proporção inválido. Use 'largura:altura'")

    def update_aspect_ratio(self):
        """Atualiza a proporção de aspecto quando a imagem é carregada"""
        if self.original_image is not None:
            self.height, self.width, _ = self.original_image.shape
            self.aspect_ratio = self.width / self.height

    def load_image(self, event=None):
        """Carrega uma imagem do sistema de arquivos"""
        initialdir = self.last_save_dir if hasattr(self, 'last_save_dir') else os.getcwd()
        filepath = filedialog.askopenfilename(
            initialdir=initialdir,
            filetypes=[
                ("Arquivos de imagem", "*.png *.jpg *.jpeg *.bmp *.tiff"),
                ("Todos os arquivos", "*.*")
            ]
        )
        
        if not filepath:
            if self.initial_load:
                # Não fechar o programa se nenhuma imagem for selecionada
                self.update_status("Nenhuma imagem selecionada")
            return

        self.filepath = filepath
        self.last_save_dir = os.path.dirname(filepath)
        self.initial_load = False
        self.original_image = cv2.imread(self.filepath)
        
        if self.original_image is None:
            messagebox.showerror("Erro", f"Não foi possível ler o arquivo: {self.filepath}")
            return

        self.original_image = cv2.cvtColor(self.original_image, cv2.COLOR_BGR2RGB)
        self.height, self.width, _ = self.original_image.shape
        self.display_image = Image.fromarray(self.original_image)
        
        # Resetar estado de zoom e pan
        self.scale_factor = 1.0
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        
        self.update_aspect_ratio()
        self.show_mode_selection()
        self.update_status(f"Carregado: {os.path.basename(self.filepath)}")

    def show_mode_selection(self):
        """Mostra a janela de seleção de modo de operação"""
        mode_window = tk.Toplevel(self.root)
        mode_window.title("Selecionar Modo")
        mode_window.geometry("300x200")
        mode_window.resizable(False, False)
        mode_window.transient(self.root)
        
        # Garantir que a janela esteja visível antes de capturar foco
        mode_window.update_idletasks()
        mode_window.wait_visibility()
        mode_window.grab_set()
        
        mode_window.focus_set()

        label = tk.Label(mode_window, text="Selecione o Modo de Operação", font=("Arial", 14))
        label.pack(pady=20)

        ttk.Button(
            mode_window,
            text="Anotação de Polígono",
            command=lambda: self.set_mode('polygon', mode_window),
            width=20
        ).pack(pady=5, padx=50, fill=tk.X)

        ttk.Button(
            mode_window,
            text="Recorte de Imagem",
            command=lambda: self.set_mode('crop', mode_window),
            width=20
        ).pack(pady=5, padx=50, fill=tk.X)

        ttk.Button(
            mode_window,
            text="Cancelar",
            command=mode_window.destroy,
            width=10
        ).pack(pady=10)

    def set_mode(self, mode: str, window: tk.Toplevel):
        """Define o modo de operação e fecha a janela de seleção"""
        self.mode = mode
        window.destroy()
        self.reset_annotations()
        self.mode_indicator.config(text=f"Modo Atual: {mode.capitalize()}")
        self.update_status(f"Modo definido para: {mode}")
        
        # Mostrar/ocultar controles de proporção conforme o modo
        if mode == 'crop':
            self.ask_for_aspect_ratio()
            self.aspect_check.pack(side=tk.LEFT, padx=5, pady=2)
        else:
            self.aspect_check.pack_forget()

    def ask_for_aspect_ratio(self):
        """Pergunta se deve manter a proporção no modo de recorte"""
        if not self.keep_aspect_ratio.get():
            self.keep_aspect_ratio.set(
                messagebox.askyesno(
                    "Manter Proporção", 
                    "Manter a proporção original?",
                    parent=self.root
                )
            )

    def reset_annotations(self):
        """Reseta todas as anotações e redesenha a imagem"""
        # Salvar estado atual no histórico
        self.save_state_to_history()
        
        self.polygons = []
        self.current_polygon = []
        self.crop_rect = None
        self.temp_line = None
        self.dragging_point = None
        self.dragging_polygon = None
        self.selected_polygon_index = None
        self.next_polygon_id = 1
        self.next_color_index = 0
        self.redraw()
        self.update_status("Anotações limpas")

    def save_state_to_history(self):
        """Salva o estado atual no histórico para desfazer"""
        state = {
            'polygons': [poly.copy() for poly in self.polygons],
            'current_polygon': self.current_polygon.copy(),
            'crop_rect': self.crop_rect,
            'mode': self.mode,
            'next_polygon_id': self.next_polygon_id,
            'next_color_index': self.next_color_index,
            'selected_polygon_index': self.selected_polygon_index
        }
        self.action_history.append(state)

    def undo_action(self, event=None):
        """Desfaz a última ação"""
        if not self.action_history:
            self.update_status("Nada para desfazer")
            return
            
        # Restaura o estado anterior
        previous_state = self.action_history.pop()
        
        self.polygons = previous_state['polygons']
        self.current_polygon = previous_state['current_polygon']
        self.crop_rect = previous_state['crop_rect']
        self.next_polygon_id = previous_state['next_polygon_id']
        self.next_color_index = previous_state['next_color_index']
        self.selected_polygon_index = previous_state['selected_polygon_index']
        
        self.redraw()
        self.update_status("Ação desfeita")

    def cancel_operation(self, event=None):
        """Cancela a operação atual"""
        # Salvar estado atual no histórico
        self.save_state_to_history()
        
        if self.mode == 'polygon' and self.current_polygon:
            self.current_polygon = []
            self.redraw()
            self.update_status("Polígono cancelado")
        elif self.mode == 'crop' and self.crop_rect:
            self.crop_rect = None
            self.redraw()
            self.update_status("Recorte cancelado")

    def display_image_on_canvas(self):
        """Exibe a imagem atual no canvas com suporte a zoom"""
        if self.display_image is None:
            return
            
        # Aplica zoom se necessário
        if self.scale_factor != 1.0:
            img = self.display_image.copy()
            new_size = (int(img.width * self.scale_factor), int(img.height * self.scale_factor))
            resized_img = img.resize(new_size, Image.LANCZOS)
            self.tk_image = ImageTk.PhotoImage(resized_img)
        else:
            self.tk_image = ImageTk.PhotoImage(self.display_image)
        
        # Configura a região de rolagem
        self.canvas.config(scrollregion=(0, 0, self.tk_image.width(), self.tk_image.height()))
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)

    def redraw(self):
        """Redesenha todos os elementos na interface"""
        self.canvas.delete("all")
        self.display_image_on_canvas()
        self.draw_polygons()
        self.draw_crop_rectangle()
        self.draw_temp_line()

    def draw_temp_line(self):
        """Desenha uma linha temporária para o próximo ponto do polígono"""
        if self.mode == 'polygon' and self.current_polygon and self.temp_line:
            x1, y1 = self.current_polygon[-1]
            x2, y2 = self.temp_line
            self.canvas.create_line(x1, y1, x2, y2, fill="#FF0000", width=2, dash=(4, 2))

    def draw_polygons(self):
        """Desenha todos os polígonos armazenados com cores distintas"""
        # Desenha polígonos completos
        for idx, polygon_data in enumerate(self.polygons):
            points = polygon_data['points']
            label = polygon_data['label']
            poly_id = polygon_data['id']
            color = polygon_data['color']
            
            # Destaca o polígono selecionado
            outline_width = 4 if idx == self.selected_polygon_index else 2
            outline_color = "#FFFF00" if idx == self.selected_polygon_index else color
            
            # Desenha o polígono
            self.canvas.create_polygon(
                points, 
                outline=outline_color, 
                fill='', 
                width=outline_width,
                tags=f"polygon_{idx}"
            )
            
            # Desenha os pontos de controle
            for p_idx, (x, y) in enumerate(points):
                fill_color = "red" if p_idx == 0 and self.current_polygon and len(self.current_polygon) > 2 else color
                point = self.canvas.create_oval(
                    x-5, y-5, x+5, y+5,
                    fill=fill_color,
                    outline="white",
                    tags=f"poly_{idx}_point_{p_idx}"
                )
                # Armazena dados do ponto para manipulação
                self.canvas.itemconfig(point, tags=(f"poly_{idx}_point_{p_idx}", "control_point"))
            
            # Desenha o label no centro do polígono
            if points:
                center_x = sum(p[0] for p in points) / len(points)
                center_y = sum(p[1] for p in points) / len(points)
                self.canvas.create_text(
                    center_x, center_y, 
                    text=f"{label} ({poly_id})", 
                    fill="white",
                    font=("Arial", 10, "bold"),
                    tags="polygon_label"
                )
        
        # Desenha polígono atual em construção
        if self.current_polygon:
            # Desenha linhas entre pontos
            if len(self.current_polygon) > 1:
                for i in range(1, len(self.current_polygon)):
                    self.canvas.create_line(
                        self.current_polygon[i-1][0], self.current_polygon[i-1][1],
                        self.current_polygon[i][0], self.current_polygon[i][1],
                        fill="#FF0000",
                        width=2,
                        tags="current_polygon"
                    )
            
            # Desenha pontos de controle
            for p_idx, (x, y) in enumerate(self.current_polygon):
                fill_color = "red" if p_idx == 0 and len(self.current_polygon) > 2 else "#FF0000"
                self.canvas.create_oval(
                    x-5, y-5, x+5, y+5,
                    fill=fill_color,
                    outline="white",
                    tags=f"current_point_{p_idx}"
                )
                
                # Conectar ao primeiro ponto se estiver próximo
                if p_idx == 0 and len(self.current_polygon) > 2:
                    # Desenha linha de conexão ao primeiro ponto
                    self.canvas.create_line(
                        self.current_polygon[-1][0], self.current_polygon[-1][1],
                        x, y,
                        fill="#FF0000",
                        width=2,
                        dash=(4, 2),
                        tags="closing_line"
                    )

    def draw_crop_rectangle(self):
        """Desenha o retângulo de recorte se existir"""
        if self.mode == 'crop' and self.crop_rect:
            x1, y1, x2, y2 = self.crop_rect
            self.canvas.create_rectangle(
                x1, y1, x2, y2, 
                outline="#00FF00", 
                width=3,
                dash=(4, 2) if self.rect_moving else None,
                tags="crop_rect"
            )
            
            # Desenha alças de redimensionamento
            handles = [
                (x1, y1), (x2, y1), (x2, y2), (x1, y2),          # Cantos
                ((x1+x2)//2, y1), ((x1+x2)//2, y2),               # Topo e fundo
                (x1, (y1+y2)//2), (x2, (y1+y2)//2)                # Laterais
            ]
            
            for hx, hy in handles:
                self.canvas.create_rectangle(
                    hx-5, hy-5, hx+5, hy+5,
                    fill="#00FF00",
                    outline="white",
                    tags="resize_handle"
                )

    def on_left_click(self, event):
        """Manipula cliques do botão esquerdo do mouse"""
        if self.zoom_state and self.mode != 'polygon':
            self.show_zoom_preview(event)
            return
            
        if self.mode == 'polygon':
            # Verificar se clicou em um ponto existente para finalizar
            if self.check_close_to_first_point(event):
                self.finalize_polygon()
                return
                
            # Verificar se clicou em um ponto para mover
            if self.handle_point_drag_start(event):
                return
                
            # Selecionar polígono existente
            if self.select_polygon(event):
                return
                
            # Adicionar novo ponto
            self.save_state_to_history()
            self.handle_polygon_click(event)
            
        elif self.mode == 'crop':
            self.handle_crop_click(event)

    def select_polygon(self, event):
        """Seleciona um polígono existente ao clicar nele"""
        # Verificar se clicou em um polígono existente
        items = self.canvas.find_overlapping(event.x-5, event.y-5, event.x+5, event.y+5)
        for item in items:
            tags = self.canvas.gettags(item)
            # Verificação segura para tags vazias
            if tags:  # Verifica se há tags
                # Verificar se alguma tag começa com "polygon_"
                for tag in tags:
                    if tag.startswith("polygon_"):
                        try:
                            idx = int(tag.split("_")[1])
                            self.selected_polygon_index = idx
                            self.redraw()
                            self.update_status(f"Polígono {idx} selecionado")
                            return True
                        except (IndexError, ValueError):
                            continue
        return False

    def check_close_to_first_point(self, event):
        """Verifica se o clique está próximo do primeiro ponto para finalizar o polígono"""
        if len(self.current_polygon) > 2:
            first_x, first_y = self.current_polygon[0]
            distance = ((event.x - first_x) ** 2 + (event.y - first_y) ** 2) ** 0.5
            if distance < 10:  # 10 pixels de tolerância
                return True
        return False

    def handle_point_drag_start(self, event):
        """Inicia o arraste de um ponto existente"""
        # Verificar se clicou em um ponto de controle de polígono existente
        items = self.canvas.find_overlapping(event.x-5, event.y-5, event.x+5, event.y+5)
        for item in items:
            tags = self.canvas.gettags(item)
            if "control_point" in tags:
                # Encontrar qual ponto de qual polígono
                for tag in tags:
                    if tag.startswith("poly_"):
                        parts = tag.split("_")
                        poly_idx = int(parts[1])
                        point_idx = int(parts[3])
                        
                        # Se for um polígono já finalizado
                        if parts[0] == "poly" and poly_idx < len(self.polygons):
                            self.dragging_polygon = poly_idx
                            self.dragging_point = point_idx
                            self.drag_offset = (event.x - self.polygons[poly_idx]['points'][point_idx][0], 
                                              event.y - self.polygons[poly_idx]['points'][point_idx][1])
                            return True
                        # Se for o polígono atual em construção
                        elif tag.startswith("current_point"):
                            point_idx = int(tag.split("_")[-1])
                            self.dragging_point = point_idx
                            self.drag_offset = (event.x - self.current_polygon[point_idx][0], 
                                              event.y - self.current_polygon[point_idx][1])
                            return True
        return False

    def handle_polygon_click(self, event):
        """Adiciona ponto ao polígono atual"""
        self.current_polygon.append((event.x, event.y))
        self.redraw()
        self.update_status(f"Ponto adicionado: ({event.x}, {event.y})")

    def handle_crop_click(self, event):
        """Inicia a criação ou seleção do retângulo de recorte"""
        # Salvar estado antes da modificação
        self.save_state_to_history()
        
        # Verifica se clicou em uma alça de redimensionamento
        handles = self.canvas.find_withtag("resize_handle")
        for handle in handles:
            x1, y1, x2, y2 = self.canvas.coords(handle)
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self.selected_handle = handle
                self.crop_start_point = (event.x, event.y)
                self.original_crop_rect = self.crop_rect
                return
        
        # Se não clicou em uma alça, inicia novo recorte
        if not self.crop_rect:
            self.crop_start_point = (event.x, event.y)
        else:
            # Verifica se clicou dentro do retângulo existente
            x1, y1, x2, y2 = self.crop_rect
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self.rect_moving = True
                self.rect_move_offset = (event.x - x1, event.y - y1)

    def on_mouse_drag(self, event):
        """Manipula arrastar do mouse"""
        if self.zoom_state and self.mode != 'polygon':
            return
            
        # Arrastar ponto de polígono
        if self.dragging_point is not None:
            if self.dragging_polygon is not None:
                # Arrastando ponto de polígono existente
                poly = self.polygons[self.dragging_polygon]
                new_x = event.x - self.drag_offset[0]
                new_y = event.y - self.drag_offset[1]
                poly['points'][self.dragging_point] = (new_x, new_y)
                self.redraw()
            elif self.dragging_point is not None and self.current_polygon:
                # Arrastando ponto do polígono atual
                new_x = event.x - self.drag_offset[0]
                new_y = event.y - self.drag_offset[1]
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

    def resize_crop_rectangle(self, event):
        """Redimensiona o retângulo de recorte usando as alças"""
        x1, y1, x2, y2 = self.original_crop_rect
        handle_idx = self.canvas.gettags(self.selected_handle)[1]  # Obtém o índice da alça
        
        # Mapeia as alças para suas posições no retângulo
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
            
            # Mantém a proporção
            if abs(dx) > abs(dy):
                dy = dx / self.aspect_ratio
            else:
                dx = dy * self.aspect_ratio
                
            new_x = self.crop_start_point[0] + dx
            new_y = self.crop_start_point[1] + dy
        
        # Atualiza as coordenadas baseadas na alça selecionada
        if hx == 0:   # Lado esquerdo
            x1 = min(new_x, x2)
        elif hx == 1: # Lado direito
            x2 = max(new_x, x1)
        elif hx == 0.5: # Centro horizontal
            pass
        
        if hy == 0:   # Topo
            y1 = min(new_y, y2)
        elif hy == 1: # Fundo
            y2 = max(new_y, y1)
        elif hy == 0.5: # Centro vertical
            pass
            
        self.crop_rect = (x1, y1, x2, y2)
        self.redraw()

    def update_crop_rectangle(self, event):
        """Atualiza o retângulo de recorte durante o arraste"""
        x1, y1 = self.crop_start_point
        x2, y2 = event.x, event.y

        if self.keep_aspect_ratio.get():
            dx = x2 - x1
            dy = y2 - y1
            
            # Mantém a proporção
            if abs(dx) > abs(dy):
                y2 = y1 + dx / self.aspect_ratio
            else:
                x2 = x1 + dy * self.aspect_ratio

        self.crop_rect = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        self.redraw()

    def on_mouse_release(self, event):
        """Finaliza a interação ao soltar o botão do mouse"""
        if self.mode == 'crop' and self.crop_rect:
            self.finalize_crop_rectangle()
            if hasattr(self, 'selected_handle'):
                del self.selected_handle
                
        # Finalizar arraste de ponto
        if self.dragging_point is not None:
            self.dragging_point = None
            self.dragging_polygon = None
            self.save_state_to_history()
            self.update_status("Ponto movido")
            
        self.temp_line = None
        self.redraw()

    def finalize_crop_rectangle(self):
        """Ajusta coordenadas finais do recorte"""
        x1, y1, x2, y2 = self.crop_rect
        self.crop_rect = (
            max(0, min(x1, x2)),
            max(0, min(y1, y2)),
            min(self.width, max(x1, x2)),
            min(self.height, max(y1, y2))
        )
        self.update_status(f"Área de recorte definida: {self.crop_rect}")

    def on_right_click(self, event):
        """Inicia movimento do retângulo de recorte"""
        if self.mode == 'crop' and self.crop_rect:
            # Salvar estado antes da modificação
            self.save_state_to_history()
            
            x1, y1, x2, y2 = self.crop_rect
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self.rect_moving = True
                self.rect_move_offset = (event.x - x1, event.y - y1)

    def on_right_drag(self, event):
        """Move o retângulo de recorte durante o arraste"""
        if self.mode == 'crop' and self.rect_moving:
            self.move_crop_rectangle(event)

    def move_crop_rectangle(self, event):
        """Calcula nova posição do retângulo de recorte"""
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
        """Finaliza o movimento do retângulo de recorte"""
        self.rect_moving = False

    def on_mouse_wheel(self, event):
        """Manipula o zoom com a roda do mouse"""
        if not self.zoom_state or self.mode == 'polygon':
            return
            
        scale_factor = 1.1 if event.delta > 0 else 0.9
        self.scale_factor *= scale_factor
        
        # Limita o zoom entre 10% e 1000%
        self.scale_factor = max(0.1, min(self.scale_factor, 10.0))
        
        # Atualiza a posição de visualização
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        
        self.redraw()
        self.canvas.scale("all", x, y, scale_factor, scale_factor)
        self.update_status(f"Zoom: {self.scale_factor*100:.1f}%")

    def on_mouse_move(self, event):
        """Atualiza a linha temporária e mostra coordenadas"""
        self.update_status(f"Posição: ({event.x}, {event.y})")
        
        if self.mode == 'polygon' and self.current_polygon:
            self.temp_line = (event.x, event.y)
            self.redraw()
        
        if self.zoom_state and self.mode != 'polygon':
            self.show_zoom_preview(event)

    def show_zoom_preview(self, event):
        """Mostra uma prévia ampliada sob o cursor"""
        if self.display_image is None or not self.zoom_state or self.mode == 'polygon':
            return
            
        # Calcula a região de zoom
        zoom_size = 100
        zoom_factor = 2.0
        
        # Obtém as coordenadas reais da imagem
        img_x = int(event.x / self.scale_factor)
        img_y = int(event.y / self.scale_factor)
        
        # Garante coordenadas válidas
        x1 = max(0, min(img_x, self.width - 1))
        y1 = max(0, min(img_y, self.height - 1))
        
        # Define a área para ampliar (garantindo ordem correta)
        left = max(0, x1 - zoom_size//2)
        top = max(0, y1 - zoom_size//2)
        right = min(self.width, left + zoom_size)
        bottom = min(self.height, top + zoom_size)
        
        # Verifica se a região é válida
        if right <= left or bottom <= top:
            return
            
        # Recorta e amplia a região
        zoom_region = self.display_image.crop((left, top, right, bottom))
        
        # Corrigido: cálculo correto do novo tamanho
        new_width = int(zoom_region.width * zoom_factor)
        new_height = int(zoom_region.height * zoom_factor)
        zoom_region = zoom_region.resize((new_width, new_height), Image.LANCZOS)
        
        # Atualiza o overlay
        self.overlay.delete("all")
        zoom_tk = ImageTk.PhotoImage(zoom_region)
        self.overlay.image = zoom_tk  # Mantém referência
        self.overlay.create_image(0, 0, anchor=tk.NW, image=zoom_tk)
        
        # Desenha cruz indicadora
        cross_x = zoom_region.width // 2
        cross_y = zoom_region.height // 2
        self.overlay.create_line(cross_x, 0, cross_x, zoom_region.height, fill="red", width=1)
        self.overlay.create_line(0, cross_y, zoom_region.width, cross_y, fill="red", width=1)

    def start_pan(self, event):
        """Inicia o pan da imagem"""
        self.pan_start = (event.x, event.y)
        self.canvas.config(cursor="fleur")

    def on_pan(self, event):
        """Executa o pan da imagem"""
        if self.pan_start:
            dx = event.x - self.pan_start[0]
            dy = event.y - self.pan_start[1]
            self.canvas.xview_scroll(-dx, "units")
            self.canvas.yview_scroll(-dy, "units")
            self.pan_start = (event.x, event.y)

    def ask_polygon_info(self):
        """Pergunta o label e ID para um novo polígono"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Informações do Polígono")
        dialog.geometry("300x180")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        
        # Garante que a janela esteja visível antes de capturar foco
        dialog.update_idletasks()
        dialog.wait_visibility()
        dialog.grab_set()
        
        tk.Label(dialog, text="Label do polígono:").pack(pady=(10, 0))
        label_entry = ttk.Entry(dialog)
        label_entry.pack(pady=5, padx=20, fill=tk.X)
        label_entry.insert(0, f"Objeto {self.next_polygon_id}")
        label_entry.focus_set()
        
        tk.Label(dialog, text="ID do polígono:").pack()
        id_entry = ttk.Entry(dialog)
        id_entry.pack(pady=5, padx=20, fill=tk.X)
        id_entry.insert(0, str(self.next_polygon_id))
        
        # Variável para armazenar o resultado
        self.polygon_info_result = {"label": "", "id": ""}
        
        def on_ok():
            label = label_entry.get().strip()
            id_val = id_entry.get().strip()
            
            if not label:
                messagebox.showerror("Erro", "O label não pode estar vazio", parent=dialog)
                return
                
            if not id_val:
                messagebox.showerror("Erro", "O ID não pode estar vazio", parent=dialog)
                return
                
            try:
                poly_id = int(id_val)
                if poly_id <= 0:
                    messagebox.showerror("Erro", "ID deve ser um número positivo", parent=dialog)
                    return
            except ValueError:
                messagebox.showerror("Erro", "ID deve ser um número inteiro", parent=dialog)
                return
                
            self.polygon_info_result = {"label": label, "id": poly_id}
            dialog.destroy()
            
        def on_cancel():
            self.polygon_info_result = {"label": "", "id": ""}
            dialog.destroy()
            
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(button_frame, text="Cancelar", command=on_cancel).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="OK", command=on_ok).pack(side=tk.RIGHT)
        
        dialog.protocol("WM_DELETE_WINDOW", on_cancel)
        dialog.wait_window()
        
        return self.polygon_info_result

    def finalize_polygon(self, event=None):
        """Finaliza o polígono atual e pergunta pelo label e ID"""
        if self.mode == 'polygon' and len(self.current_polygon) >= 3:
            # Perguntar pelo label e ID
            info = self.ask_polygon_info()
            if not info["label"] or not info["id"]:
                self.update_status("Criação de polígono cancelada")
                return
                
            # Salvar estado antes da modificação
            self.save_state_to_history()
            
            # Adiciona o polígono com informações
            self.polygons.append({
                'points': self.current_polygon.copy(),
                'label': info["label"],
                'id': info["id"],
                'color': self.generate_distinct_color()
            })
            
            self.current_polygon = []
            self.next_polygon_id = info["id"] + 1
            self.selected_polygon_index = len(self.polygons) - 1  # Seleciona o novo polígono
            self.redraw()
            self.update_status(f"Polígono '{info['label']}' (ID: {info['id']}) finalizado")
        elif self.mode == 'polygon':
            messagebox.showwarning("Aviso", "Um polígono precisa de pelo menos 3 pontos")

    def delete_selected(self, event=None):
        """Deleta o polígono selecionado ou o recorte atual"""
        # Salvar estado antes da modificação
        self.save_state_to_history()
        
        if self.mode == 'polygon':
            if self.selected_polygon_index is not None and self.selected_polygon_index < len(self.polygons):
                deleted = self.polygons.pop(self.selected_polygon_index)
                self.selected_polygon_index = None
                self.redraw()
                self.update_status(f"Polígono '{deleted['label']}' deletado")
            elif self.current_polygon:
                # Cancela o polígono em construção
                self.current_polygon = []
                self.redraw()
                self.update_status("Polígono em construção cancelado")
            elif self.polygons:
                # Remove o último polígono se nenhum estiver selecionado
                deleted = self.polygons.pop()
                self.redraw()
                self.update_status(f"Polígono '{deleted['label']}' deletado")
            else:
                self.update_status("Nenhum polígono para deletar")
        elif self.mode == 'crop' and self.crop_rect:
            self.crop_rect = None
            self.redraw()
            self.update_status("Recorte deletado")

    def save_crop(self):
        """Salva a área recortada e seus metadados"""
        if not self.crop_rect:
            messagebox.showwarning("Aviso", "Nenhuma área de recorte definida")
            return

        x1, y1, x2, y2 = self.crop_rect
        cropped_image = self.display_image.crop((x1, y1, x2, y2))
        
        save_path = filedialog.asksaveasfilename(
            initialdir=self.last_save_dir,
            defaultextension=".png",
            filetypes=[
                ("PNG files", "*.png"),
                ("JPEG files", "*.jpg;*.jpeg"),
                ("Todos os arquivos", "*.*")
            ]
        )
        
        if not save_path:
            return

        # Atualiza o último diretório usado
        self.last_save_dir = os.path.dirname(save_path)
        
        # Salva a imagem no formato apropriado
        if save_path.lower().endswith(('.jpg', '.jpeg')):
            cropped_image.save(save_path, "JPEG", quality=95)
        else:
            cropped_image.save(save_path)
            
        self.save_crop_metadata(save_path, x1, y1, x2, y2)
        messagebox.showinfo("Sucesso", f"Imagem salva: {save_path}")
        self.reset_annotations()

    def save_crop_metadata(self, path: str, x1: int, y1: int, x2: int, y2: int):
        """Salva metadados do recorte com coordenadas normalizadas"""
        json_path = os.path.splitext(path)[0] + ".json"
        
        # Calcula coordenadas relativas (0-1)
        x1_rel = x1 / self.width
        y1_rel = y1 / self.height
        x2_rel = x2 / self.width
        y2_rel = y2 / self.height
        
        # Calcula coordenadas do centro e tamanho (formato YOLO)
        center_x = (x1_rel + x2_rel) / 2
        center_y = (y1_rel + y2_rel) / 2
        width = x2_rel - x1_rel
        height = y2_rel - y1_rel
        
        metadata = {
            "original_size": {"width": self.width, "height": self.height},
            "crop_coordinates_relative": {
                "x1": x1_rel, "y1": y1_rel,
                "x2": x2_rel, "y2": y2_rel
            },
            "crop_coordinates_absolute": {
                "x1": x1, "y1": y1,
                "x2": x2, "y2": y2
            },
            "yolo_format": {
                "center_x": center_x,
                "center_y": center_y,
                "width": width,
                "height": height
            }
        }
        
        with open(json_path, 'w') as f:
            json.dump(metadata, f, indent=4)

    def save_polygons(self):
        """Salva polígonos em arquivo JSON com labels e IDs"""
        if not self.polygons:
            messagebox.showwarning("Aviso", "Nenhum polígono para salvar")
            return

        save_path = filedialog.asksaveasfilename(
            initialdir=self.last_save_dir,
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")]
        )
        
        if not save_path:
            return

        # Atualiza o último diretório usado
        self.last_save_dir = os.path.dirname(save_path)
        
        # Normaliza as coordenadas
        normalized_polygons = []
        for polygon_data in self.polygons:
            normalized = []
            for x, y in polygon_data['points']:
                normalized.append((x / self.width, y / self.height))
                
            normalized_polygons.append({
                'points': normalized,
                'label': polygon_data['label'],
                'id': polygon_data['id'],
                'color': polygon_data['color']
            })
        
        # Estrutura de metadados completa
        metadata = {
            "image_path": self.filepath,
            "image_size": {"width": self.width, "height": self.height},
            "polygons_absolute": self.polygons,
            "polygons_normalized": normalized_polygons
        }
        
        with open(save_path, 'w') as f:
            json.dump(metadata, f, indent=4)
        
        messagebox.showinfo("Sucesso", f"Polígonos salvos: {save_path}")
        self.reset_annotations()

    def save_and_restart(self, event=None):
        """Salva o trabalho atual e reinicia o editor"""
        if self.mode == 'crop':
            self.save_crop()
        elif self.mode == 'polygon' and (self.polygons or self.current_polygon):
            if self.current_polygon:
                self.finalize_polygon()
            else:
                self.save_polygons()
        else:
            self.update_status("Nada para salvar")
        
        self.load_image()

    def on_close(self):
        """Garante o fechamento seguro da aplicação"""
        if messagebox.askokcancel("Sair", "Tem certeza que deseja sair?"):
            try:
                self.root.destroy()
            except Exception:
                self.root.quit()

if __name__ == "__main__":
    root = ThemedTk(theme="clam")
    root.title("Map Editor")
    
    # Configuração multiplataforma para janela maximizada
    try:
        if os.name == 'nt':  # Windows
            root.state('zoomed')
        else:  # Linux/Mac
            # Tenta várias abordagens para diferentes ambientes
            try:
                root.attributes('-zoomed', True)
            except:
                try:
                    root.attributes('-fullscreen', True)
                except:
                    root.geometry("1200x800")
    except Exception as e:
        print(f"Could not maximize window: {e}")
        root.geometry("1200x800")
    
    # Configura tamanho mínimo
    root.minsize(800, 600)
    
    ImageEditor(root)
    root.mainloop()