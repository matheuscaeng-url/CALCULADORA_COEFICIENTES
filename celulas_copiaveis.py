"""Seleção de números em tabelas sem permitir edição dos resultados."""
from __future__ import annotations

import tkinter as tk


def enable_tree_cell_selection(tree, columns):
    allowed = set(columns)
    holder = {'entry': None, 'menu': None, 'anchor': 0, 'start_x': 0, 'cell_x': 0}

    def close(*_):
        for name in ('menu', 'entry'):
            widget = holder[name]
            holder[name] = None
            if widget is not None:
                try:
                    widget.destroy()
                except tk.TclError:
                    pass

    def select_all(event):
        event.widget.selection_range(0, 'end')
        return 'break'

    def popup(event):
        entry = event.widget
        menu = tk.Menu(entry, tearoff=0)
        menu.add_command(label='Copiar', command=lambda: entry.event_generate('<<Copy>>'))
        menu.add_command(label='Selecionar tudo', command=lambda: entry.selection_range(0, 'end'))
        holder['menu'] = menu
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return 'break'

    def show(event):
        if tree.identify_region(event.x, event.y) != 'cell':
            close()
            return
        row, column = tree.identify_row(event.y), tree.identify_column(event.x)
        if not row or not column.startswith('#'):
            close()
            return
        index = int(column[1:]) - 1
        values = tree.item(row, 'values')
        bbox = tree.bbox(row, column)
        if index not in allowed or index >= len(values) or not bbox:
            close()
            return
        close()
        tree.selection_set(row)
        tree.focus(row)
        x, y, width, height = bbox
        entry = tk.Entry(tree, relief='solid', borderwidth=1, background='white',
                         readonlybackground='white', foreground='black', cursor='xterm',
                         font=('Segoe UI', 9), exportselection=False)
        entry.insert(0, str(values[index]))
        entry.configure(state='readonly')
        entry.place(x=x, y=y, width=width, height=height)
        entry.update_idletasks()
        holder.update(entry=entry, anchor=entry.index(f'@{event.x-x}'),
                      start_x=event.x, cell_x=x)
        entry.focus_set()
        entry.selection_range(0, 'end')
        for sequence in ('<Control-a>', '<Control-A>'):
            entry.bind(sequence, select_all)
        entry.bind('<Button-3>', popup)
        entry.bind('<Escape>', lambda event: (close(), 'break')[1])
        entry.bind('<Return>', lambda event: (close(), 'break')[1])
        # readonly bloqueia digitação, Delete, recortar e colar inclusive via
        # eventos virtuais e botão do meio; a seleção nativa permanece ativa.
        return 'break'

    def drag(event):
        entry = holder['entry']
        if entry is None or abs(event.x - holder['start_x']) < 3:
            return
        end = entry.index(f'@{event.x-holder["cell_x"]}')
        entry.selection_range(min(holder['anchor'], end), max(holder['anchor'], end))
        return 'break'

    tree.bind('<Button-1>', show, add='+')
    tree.bind('<B1-Motion>', drag, add='+')
    for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>', '<Configure>'):
        tree.bind(sequence, close, add='+')
    # As barras de rolagem também devem fechar a célula sobreposta.
    positions = {'xscrollcommand': tuple(tree.xview()), 'yscrollcommand': tuple(tree.yview())}
    for option in ('xscrollcommand', 'yscrollcommand'):
        original = tree.cget(option)
        def scrolled(first, last, command=original, axis=option):
            position = (float(first), float(last))
            if positions[axis] != position:
                close()
                positions[axis] = position
            if command:
                tree.tk.call(*tree.tk.splitlist(command), first, last)
        tree.configure(**{option: scrolled})
    tree._selectable_cell_close = close
    tree._selectable_cell_state = holder
