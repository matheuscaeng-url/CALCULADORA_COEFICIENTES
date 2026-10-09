"""Tendência manual: entrada unificada e resultados em uma aba própria."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ScrollArea(ttk.Frame):
    """Rolagem local: tabelas grandes não empurram as ações para fora da tela."""
    def __init__(self, parent, *, height=180, fit_height=False):
        super().__init__(parent)
        self.fit_height = fit_height
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, width=1, height=height, highlightthickness=0,
                                background='white')
        self.canvas.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        horizontal = ttk.Scrollbar(self, orient='horizontal', command=self.canvas.xview)
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        self.canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.body = ttk.Frame(self.canvas, padding=6)
        self.canvas.create_window((0, 0), window=self.body, anchor='nw')
        self.body.bind('<Configure>', self._refresh, add='+')
        self.canvas.bind('<MouseWheel>', self._wheel)
        self.canvas.bind('<Button-4>', self._wheel)
        self.canvas.bind('<Button-5>', self._wheel)

    def _wheel(self, event):
        direction = -1 if getattr(event, 'num', None) == 4 or getattr(event, 'delta', 0) > 0 else 1
        if getattr(event, 'state', 0) & 1:
            self.canvas.xview_scroll(direction, 'units')
        else:
            self.canvas.yview_scroll(direction, 'units')
        return 'break'

    def _refresh(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        if self.fit_height:
            requested = min(180, self.body.winfo_reqheight())
            if int(self.canvas.cget('height')) != requested:
                self.canvas.configure(height=requested)
        self._bind_children(self.body)

    def _bind_children(self, parent):
        for child in parent.winfo_children():
            if not getattr(child, '_manual_scroll_bound', False):
                child._manual_scroll_bound = True
                child.bind('<MouseWheel>', self._wheel, add='+')
                child.bind('<Button-4>', self._wheel, add='+')
                child.bind('<Button-5>', self._wheel, add='+')
                child.bind('<FocusIn>', lambda event: self.reveal(event.widget), add='+')
            self._bind_children(child)

    def reveal(self, widget):
        """Tab e Shift+Tab trazem para a vista campos fora da área rolada."""
        self.canvas.update_idletasks()
        x = widget.winfo_rootx() - self.body.winfo_rootx()
        y = widget.winfo_rooty() - self.body.winfo_rooty()
        for start, size, visible, total, current, move in (
            (x, widget.winfo_width(), self.canvas.winfo_width(), self.body.winfo_width(),
             self.canvas.canvasx(0), self.canvas.xview_moveto),
            (y, widget.winfo_height(), self.canvas.winfo_height(), self.body.winfo_height(),
             self.canvas.canvasy(0), self.canvas.yview_moveto),
        ):
            if total <= visible or visible <= 1:
                continue
            if start < current:
                move(max(0, start-6) / total)
            elif start + size > current + visible:
                move(max(0, start + size-visible+6) / total)


class ManualWorkspace(ttk.Frame):
    """Referências e coeficientes lado a lado; alvo fixo na mesma aba."""
    def __init__(self, parent):
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.steps = ttk.Notebook(self, width=1, height=1)
        self.steps.grid(row=0, column=0, sticky='nsew')
        self.inputs = ttk.Frame(self.steps, padding=(8, 8))
        self.inputs.columnconfigure(0, weight=1)
        self.inputs.rowconfigure(0, weight=1)
        self.input_panes = tk.PanedWindow(self.inputs, orient='horizontal', sashwidth=7,
            sashrelief='flat', background='#d5e1dd', borderwidth=0, width=1, height=1)
        self.input_panes.grid(row=0, column=0, sticky='nsew')
        self.references = ttk.Frame(self.input_panes, padding=(0, 0, 8, 0))
        self.edit = ttk.Frame(self.input_panes, padding=(8, 0, 0, 0))
        self.input_panes.add(self.references, minsize=300, stretch='always')
        self.input_panes.add(self.edit, minsize=420, stretch='always')
        self.calculation = ttk.Frame(self.inputs)
        self.calculation.grid(row=1, column=0, sticky='ew', pady=(6, 0))
        self.results = ttk.Frame(self.steps, padding=(8, 8))
        for page in (self.references, self.edit, self.results):
            page.columnconfigure(0, weight=1)
            page.rowconfigure(1, weight=1)
        self.steps.add(self.inputs, text='1. Referências, coeficientes e alvo')
        self.steps.add(self.results, text='2. Resultados', state='disabled')
        self._sash_placed = False
        self.input_panes.bind('<Configure>', self._initial_sash, add='+')

    def _initial_sash(self, event):
        if not self._sash_placed and event.width > 720:
            self._sash_placed = True
            self.input_panes.sash_place(0, min(650, max(300, int(event.width * .36))), 0)

    def sync(self, *, ready, has_result):
        current = self.steps.index(self.steps.select())
        if current == 1 and not (ready and has_result):
            self.steps.select(0)
        self.steps.tab(1, state='normal' if ready and has_result else 'disabled')

    def show_references(self):
        self.steps.select(0)

    def show_editor(self):
        self.steps.select(0)

    def show_results(self):
        if self.steps.tab(1, 'state') != 'disabled':
            self.steps.select(1)
