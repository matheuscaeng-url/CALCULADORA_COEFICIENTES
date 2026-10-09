"""Abas independentes: referência única e tendência genérica."""
from __future__ import annotations

import copy
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from celulas_copiaveis import enable_tree_cell_selection
from manual_views import build_manual_view

from coeficientes_core import (AnalysisError, export_report, format_dimension_input,
    format_reference_dimensions, norm)
from regra_tres_core import (calculate_generic_rule_of_three, calculate_rule_of_three, default_scaled_indices,
    proportional_factor, single_reference_families)
from tendencia_manual_core import (calculate_generic_parameter_trend, calculate_manual_trend, clipboard_coefficients, coefficient_text,
    geometry_text, reference_rows, remap_coefficients, result_clipboard, series_from_sinapi)


DEFAULT_AXIS_UNITS = [
    'MM', 'CM', 'M', 'POL', 'MM2', 'CM2', 'M2', 'MM3', 'CM3', 'M3',
    'W', 'KW', 'VA', 'KVA', 'V', 'A', 'MA', 'CV', 'HP', 'HZ',
    'BTU/H', 'KG', 'G', 'T', 'L', 'ML', 'BAR', 'MCA', 'PA', 'MPA', 'RPM', '°C',
]


def available_dimension_units(database):
    """Unidades disponíveis na Tendência manual.

    Mantém grandezas técnicas úteis para representar a dimensão/capacidade e
    acrescenta dinamicamente TODAS as unidades de composição da referência
    SINAPI carregada (UN, H, CHI, CHP, KGXKM etc.).
    """
    composition_units = sorted({str(item.get('unit') or '').strip().upper()
                                for item in (database or {}).get('compositions', {}).values()
                                if str(item.get('unit') or '').strip()})
    result = []
    for value in [*DEFAULT_AXIS_UNITS, *composition_units]:
        if value and value not in result:
            result.append(value)
    return result


def fmt(value, digits=8):
    return '—' if value is None else f'{value:.{digits}g}'.replace('.', ',')


def make_table(parent, columns, widths, height=7):
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=list(range(len(columns))), show='headings', height=height)
    for i, (title, width) in enumerate(zip(columns, widths)):
        tree.heading(i, text=title)
        tree.column(i, width=width, minwidth=55, stretch=(i == 1))
    vs = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
    hs = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
    tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
    tree.grid(row=0, column=0, sticky='nsew')
    vs.grid(row=0, column=1, sticky='ns')
    hs.grid(row=1, column=0, sticky='ew')
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    return frame, tree


def make_splitter(parent, orient='horizontal'):
    """PanedWindow visível e fácil de arrastar para redimensionar áreas/tabelas."""
    return tk.PanedWindow(
        parent, orient=orient, sashwidth=9, sashrelief='raised', showhandle=True,
        opaqueresize=True, bd=0, relief='flat', background='#d3ddd9')


def bind_initial_sash(paned, orient='horizontal', ratio=0.5, min_first=220, min_second=220):
    """Posiciona a divisória uma única vez quando a aba realmente estiver visível.

    Abas dentro de Notebook muitas vezes têm largura/altura 1 no primeiro idle. Por
    isso a posição inicial é aplicada no primeiro <Map>/<Configure> com tamanho útil,
    sem voltar a mexer depois que o usuário arrastar a divisória.
    """
    state = {'done': False}

    def place(*_):
        if state['done']:
            return
        try:
            total = paned.winfo_width() if orient == 'horizontal' else paned.winfo_height()
            if total <= min_first + min_second + 20:
                return
            pos = int(total * ratio)
            pos = max(min_first, min(pos, total - min_second))
            if orient == 'horizontal':
                paned.sash_place(0, pos, 0)
            else:
                paned.sash_place(0, 0, pos)
            state['done'] = True
        except (tk.TclError, IndexError):
            return

    def schedule(_event=None):
        try:
            paned.after_idle(place)
        except tk.TclError:
            pass

    paned.bind('<Map>', schedule, add='+')
    paned.bind('<Configure>', schedule, add='+')
    schedule()
    return state


class OutputPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app, self.result, self.buttons = app, None, []

    def make_actions(self, parent):
        self.copy_button = ttk.Button(parent, text='Copiar justificativa', command=self.copy, state='disabled')
        self.export_button = ttk.Button(parent, text='Exportar Excel', command=self.export, state='disabled')
        self.export_button.pack(side='right')
        self.copy_button.pack(side='right', padx=6)

    def clear_output(self, *_):
        self.result = None
        if hasattr(self, 'copy_button'):
            self.copy_button.configure(state='disabled')
            self.export_button.configure(state='disabled')
        if hasattr(self, 'memo'):
            self.app.text_into(self.memo, '')

    def set_busy(self, busy):
        for button in self.buttons:
            button.configure(state='disabled' if busy else 'normal')
        self.copy_button.configure(state='normal' if self.result and not busy else 'disabled')
        self.export_button.configure(state='normal' if self.result and not busy else 'disabled')

    def copy(self):
        if self.result and not self.app.working:
            self.app.clipboard_clear()
            self.app.clipboard_append(self.result['justification'])
            self.app.update_idletasks()
            self.app.status.set('Justificativa copiada.')

    def export(self):
        if not self.result or self.app.working:
            return
        result = copy.deepcopy(self.result)
        source_name = re.sub(r'[^\w. -]', '_', str(result['source_code']))[:80]
        path = filedialog.asksaveasfilename(parent=self.app, title='Salvar memória de cálculo',
            defaultextension='.xlsx', initialfile=f'{result["calculation_type"]}_{source_name}.xlsx',
            filetypes=[('Excel', '*.xlsx')])
        if path:
            self.app.start_job(lambda: export_report(result, path),
                               lambda saved: self.app.status.set(f'Relatório salvo: {saved}'), 'Salvando relatório…')

    def show_memo(self):
        result = self.result
        text = (f'{result["mode"]}\nMétodo: {result["method"]}\nOrigem: {result["source_code"]}\n'
                f'{result["source_dimension_text"]} → {result["target_dimension_text"]}\n'
                f'{result.get("factor_formula", "")}\n\nJUSTIFICATIVA\n{result["justification"]}\n\n')
        text += '\n\n'.join(result['warnings'])
        for row in result['rows']:
            text += f'\n\n{row["description"]}\n{row.get("calculation", row["status"])}'
            text += f'\nCoeficiente: {fmt(row["source_coefficient"])} → {fmt(row["coefficient"])} {row["unit"]}/{result["family"]["service_unit"]}'
            text += f'\nAlvo: {row["target_resource"]} — {row["target_description"]}\n{row["supply_status"]}'
            for supply in row['supply_matches']:
                text += f'\n{supply["code"]} — PE: {fmt(supply.get("PE"))}; SP: {fmt(supply.get("SP"))}'
        self.app.text_into(self.memo, text)
        self.copy_button.configure(state='normal')
        self.export_button.configure(state='normal')


class SinapiRuleOfThreeTab(OutputPanel):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.db, self.families, self.family, self.scaled = None, [], None, set()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.main_splitter = make_splitter(self, 'horizontal')
        self.main_splitter.grid(row=0, column=0, sticky='nsew')
        left = ttk.Frame(self.main_splitter, padding=(0, 0, 12, 0))
        right = ttk.Frame(self.main_splitter, padding=(8, 0, 0, 0))
        self.main_splitter.add(left, minsize=260, stretch='always')
        self.main_splitter.add(right, minsize=560, stretch='always')
        bind_initial_sash(self.main_splitter, 'horizontal', ratio=0.28, min_first=260, min_second=560)
        left.rowconfigure(4, weight=1)
        left.columnconfigure(0, weight=1)
        ttk.Label(left, text='Somente 1 referência', style='Title.TLabel').grid(row=0, column=0, sticky='w')
        self.query = tk.StringVar()
        ttk.Entry(left, textvariable=self.query, width=30).grid(row=1, column=0, sticky='ew', pady=8)
        ttk.Label(left, text='Pesquise código, material ou serviço.', style='Muted.TLabel').grid(row=2, column=0, sticky='w')
        self.count = ttk.Label(left, text='', style='Muted.TLabel')
        self.count.grid(row=3, column=0, sticky='w', pady=6)
        frame, self.list = make_table(left, ['Código', 'Composição'], [75, 235])
        frame.grid(row=4, column=0, sticky='nsew')
        self.list.bind('<<TreeviewSelect>>', self.select)
        self.query.trace_add('write', self.filter)

        right.columnconfigure(0, weight=1)
        right.rowconfigure(6, weight=1)
        self.title = ttk.Label(right, text='Selecione uma composição.', style='Title.TLabel', wraplength=780)
        self.title.grid(row=0, column=0, sticky='ew')
        right.bind('<Configure>', lambda e: self.title.configure(wraplength=max(350, e.width-10)))
        self.origin = ttk.Label(right, text='Dimensão original:', style='Muted.TLabel')
        self.origin.grid(row=1, column=0, sticky='w', pady=(5, 8))
        form = ttk.Frame(right)
        form.grid(row=2, column=0, sticky='ew')
        self.targets, self.labels, self.entries = [], [], []
        for i in range(3):
            variable = tk.StringVar()
            label = ttk.Label(form, text=f'Boca {i+1}')
            entry = ttk.Entry(form, width=12, textvariable=variable)
            label.grid(row=0, column=i, sticky='w', padx=(0, 8))
            entry.grid(row=1, column=i, sticky='w', padx=(0, 8))
            variable.trace_add('write', self.invalidate)
            self.targets.append(variable); self.labels.append(label); self.entries.append(entry)
        self.calc = ttk.Button(form, text='Calcular regra de 3', style='Accent.TButton', command=self.run)
        self.calc.grid(row=1, column=3, sticky='e', padx=10)
        self.buttons.append(self.calc)
        self.formula = ttk.Label(right, text='Coeficiente alvo = coeficiente original × fator.', wraplength=750)
        self.formula.grid(row=3, column=0, sticky='ew', pady=8)
        self.agreed = tk.BooleanVar(value=False)
        ttk.Checkbutton(right, text='Ciente: proporcionalidade assumida, sem tendência validada; revisão obrigatória.',
                        variable=self.agreed).grid(row=4, column=0, sticky='w')
        self.agreed.trace_add('write', self.invalidate)
        actions = ttk.Frame(right)
        actions.grid(row=5, column=0, sticky='ew', pady=6)
        toggle = ttk.Button(actions, text='Aplicar / manter selecionado', command=self.toggle)
        toggle.pack(side='left'); self.buttons.append(toggle)
        self.make_actions(actions)
        tabs = ttk.Notebook(right)
        tabs.grid(row=6, column=0, sticky='nsew')
        table_tab, memo_tab = ttk.Frame(tabs), ttk.Frame(tabs)
        tabs.add(table_tab, text='Coeficientes — duplo clique para aplicar/manter')
        tabs.add(memo_tab, text='Memória e preços')
        frame, self.components = make_table(table_tab,
            ['Aplicar fator?', 'Componente de origem', 'Un.', 'Coef. origem', 'Coef. alvo', 'Código no alvo', 'Descrição no alvo', 'Situação'],
            [100, 290, 60, 105, 105, 170, 350, 270])
        frame.pack(fill='both', expand=True)
        enable_tree_cell_selection(self.components, {4})
        self.components.bind('<Double-1>', lambda e: self.toggle())
        self.memo = tk.Text(memo_tab, wrap='word', height=10, state='disabled', padx=10, pady=8)
        scroll = ttk.Scrollbar(memo_tab, command=self.memo.yview)
        self.memo.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y'); self.memo.pack(fill='both', expand=True)

    def set_database(self, db, families):
        self.db, self.families, self.family = db, single_reference_families(families), None
        self.scaled = set(); self.agreed.set(False); self.clear_output()
        self.components.delete(*self.components.get_children())
        self.title.configure(text='Selecione uma composição.'); self.origin.configure(text='Dimensão original:')
        self.query.set(''); self.filter()

    def filter(self, *_):
        tokens = norm(self.query.get()).split()
        self.visible = {}
        self.list.delete(*self.list.get_children())
        for family in self.families:
            ref = family['refs'][0]
            haystack = norm(ref['code'] + ' ' + family['title'])
            if all(token in haystack for token in tokens):
                self.visible[family['id']] = family
                self.list.insert('', 'end', iid=family['id'], values=(ref['code'], family['title']))
        self.count.configure(text=f'{len(self.visible)} composições com 1 referência')

    def select(self, *_):
        if self.app.working:
            return
        selected = self.list.selection()
        if selected and selected[0] in self.visible:
            self.activate(self.visible[selected[0]])

    def activate(self, family):
        self.family = family
        ref = family['refs'][0]
        self.scaled = default_scaled_indices(self.db, family)
        self.agreed.set(False)
        self.title.configure(text=self.db['compositions'][ref['code']]['description'])
        self.origin.configure(text=f'Origem SINAPI {ref["code"]} · {format_reference_dimensions(ref)} · {len(family["refs"])} referência')
        for i, (variable, label, entry) in enumerate(zip(self.targets, self.labels, self.entries)):
            if i < family['dimension_count']:
                label.configure(text=f'{"Dimensão alvo" if family["dimension_count"] == 1 else f"Boca {i+1}"} ({ref["units"][i].lower()})')
                label.grid(); entry.grid()
                variable.set(format_dimension_input(ref['dims'][i], ref['units'][i]))
            else:
                label.grid_remove(); entry.grid_remove(); variable.set('')
        self.invalidate()

    def target_value(self):
        values = [variable.get() for variable in self.targets[:self.family['dimension_count']]]
        return values[0] if len(values) == 1 else values

    def invalidate(self, *_):
        self.clear_output()
        if not self.family or not hasattr(self, 'components'):
            return
        try:
            _, _, origin, target, factor = proportional_factor(self.family, self.target_value())
            suffix = ' · razão dos índices RMS das bocas' if self.family['dimension_count'] > 1 else ''
            self.formula.configure(text=f'Fator = {fmt(target)} / {fmt(origin)} = {fmt(factor)}{suffix}\nCoef. alvo = coef. origem × fator (somente nos recursos marcados).')
        except (ValueError, OverflowError, ZeroDivisionError):
            self.formula.configure(text='Informe todas as dimensões positivas nas unidades indicadas.')
        self.render_components()

    def render_components(self):
        selection = self.components.selection()
        self.components.delete(*self.components.get_children())
        if not self.family:
            return
        for i, component in enumerate(self.db['compositions'][self.family['refs'][0]['code']]['components']):
            row = self.result['rows'][i] if self.result else None
            self.components.insert('', 'end', iid=str(i), values=(
                'SIM' if i in self.scaled else 'MANTER', component['description'], component['unit'], fmt(component['coefficient']),
                fmt(row['coefficient']) if row else '—', row['target_resource'] if row else '—',
                row['target_description'] if row else '—', row['status'] if row else 'Aguardando cálculo'))
        if selection and self.components.exists(selection[0]):
            self.components.selection_set(selection[0])

    def toggle(self):
        if self.app.working or not self.family:
            return
        selected = self.components.selection()
        if selected:
            index = int(selected[0])
            self.scaled.symmetric_difference_update({index})
            self.invalidate()

    def run(self):
        if self.app.working:
            return
        try:
            if not self.family:
                raise AnalysisError('Selecione uma composição com apenas uma referência.')
            if not self.agreed.get():
                raise AnalysisError('Confirme a ciência de que a proporcionalidade é uma hipótese sem tendência validada.')
            self.result = calculate_rule_of_three(self.db, self.family, self.target_value(), self.scaled)
        except (ValueError, OverflowError) as exc:
            self.invalidate()
            messagebox.showinfo('Confira os dados', str(exc), parent=self.app)
            return
        self.render_components(); self.show_memo()
        self.app.status.set('Regra de 3 concluída. Revise os recursos mantidos, os estimados e os códigos do alvo.')


class GenericRuleOfThreeTab(ttk.Frame):
    """Regra de 3 genérica: soma de 1 a 3 dimensões, sem depender do SINAPI."""
    def __init__(self, parent, app):
        super().__init__(parent, padding=12)
        self.app, self.result = app, None
        self.columnconfigure(0, weight=1)

        ttk.Label(self, text='Regra de 3 genérica', style='Title.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(self,
            text='Coef. desejado = Coef. referência × (soma das dimensões desejadas / soma das dimensões da referência). '
                 'Use D1 e, quando necessário, D2 e D3; deixe as demais vazias.',
            style='Muted.TLabel', wraplength=980).grid(row=1, column=0, sticky='ew', pady=(3, 12))

        meta = ttk.LabelFrame(self, text='Identificação da referência', padding=10)
        meta.grid(row=2, column=0, sticky='ew')
        meta.columnconfigure(0, weight=2); meta.columnconfigure(1, weight=2); meta.columnconfigure(2, weight=1)
        self.reference_code = tk.StringVar()
        self.bank = tk.StringVar()
        self.period = tk.StringVar()
        for col, (label, var) in enumerate((('Código da referência *', self.reference_code),
                                            ('Banco *', self.bank),
                                            ('Data / competência *', self.period))):
            ttk.Label(meta, text=label).grid(row=0, column=col, sticky='w', padx=(0, 8))
            ttk.Entry(meta, textvariable=var).grid(row=1, column=col, sticky='ew', padx=(0, 8))
            var.trace_add('write', self.invalidate)

        calc = ttk.LabelFrame(self, text='Dimensões e coeficiente', padding=10)
        calc.grid(row=3, column=0, sticky='ew', pady=12)
        for col in range(1, 6):
            calc.columnconfigure(col, weight=1)
        headers = ['', 'D1', 'D2', 'D3', 'D.SOMA', 'COEF.']
        for col, title in enumerate(headers):
            ttk.Label(calc, text=title, style='Title.TLabel').grid(row=0, column=col, sticky='ew', padx=4, pady=(0, 5))

        self.reference_dims = [tk.StringVar() for _ in range(3)]
        self.target_dims = [tk.StringVar() for _ in range(3)]
        self.reference_coefficient = tk.StringVar()
        self.target_coefficient = tk.StringVar()
        self.reference_sum = tk.StringVar(value='—')
        self.target_sum = tk.StringVar(value='—')
        ttk.Label(calc, text='Peça de Referência').grid(row=1, column=0, sticky='w', padx=4, pady=4)
        ttk.Label(calc, text='Peça Desejada').grid(row=2, column=0, sticky='w', padx=4, pady=4)
        for i in range(3):
            ttk.Entry(calc, textvariable=self.reference_dims[i], width=12).grid(row=1, column=i+1, sticky='ew', padx=4, pady=4)
            ttk.Entry(calc, textvariable=self.target_dims[i], width=12).grid(row=2, column=i+1, sticky='ew', padx=4, pady=4)
            self.reference_dims[i].trace_add('write', self.invalidate)
            self.target_dims[i].trace_add('write', self.invalidate)
        ttk.Entry(calc, textvariable=self.reference_sum, width=12, state='readonly').grid(row=1, column=4, sticky='ew', padx=4)
        ttk.Entry(calc, textvariable=self.target_sum, width=12, state='readonly').grid(row=2, column=4, sticky='ew', padx=4)
        ttk.Entry(calc, textvariable=self.reference_coefficient, width=14).grid(row=1, column=5, sticky='ew', padx=4)
        ttk.Entry(calc, textvariable=self.target_coefficient, width=14, state='readonly').grid(row=2, column=5, sticky='ew', padx=4)
        self.reference_coefficient.trace_add('write', self.invalidate)

        actions = ttk.Frame(self)
        actions.grid(row=4, column=0, sticky='ew')
        self.calculate_button = ttk.Button(actions, text='Calcular', style='Accent.TButton', command=self.run)
        self.calculate_button.pack(side='left')
        self.copy_coefficient_button = ttk.Button(actions, text='Copiar coeficiente', command=self.copy_coefficient, state='disabled')
        self.copy_coefficient_button.pack(side='left', padx=6)
        self.copy_button = ttk.Button(actions, text='Copiar justificativa', command=self.copy_justification, state='disabled')
        self.copy_button.pack(side='left')

        self.formula = ttk.Label(self, text='Preencha a referência, o coeficiente e as dimensões.', wraplength=980)
        self.formula.grid(row=5, column=0, sticky='ew', pady=(10, 0))
        self.invalidate()

    @staticmethod
    def _fmt(value):
        return f'{value:.12g}'.replace('.', ',')

    def _live_sum(self, variables):
        values = []
        for var in variables:
            text = var.get().strip()
            if not text:
                continue
            try:
                from coeficientes_core import number
                values.append(number(text))
            except ValueError:
                return '—'
        return self._fmt(sum(values)) if values else '—'

    def invalidate(self, *_):
        self.result = None
        if not hasattr(self, 'reference_sum'):
            return
        self.reference_sum.set(self._live_sum(self.reference_dims))
        self.target_sum.set(self._live_sum(self.target_dims))
        self.target_coefficient.set('')
        self.copy_button.configure(state='disabled')
        self.copy_coefficient_button.configure(state='disabled')
        self.formula.configure(text='Coef. desejado = Coef. referência × (D.SOMA desejada / D.SOMA referência).')

    def run(self):
        if self.app.working:
            return
        try:
            self.result = calculate_generic_rule_of_three(
                [v.get() for v in self.reference_dims], [v.get() for v in self.target_dims],
                self.reference_coefficient.get(), self.reference_code.get(), self.bank.get(), self.period.get())
        except (ValueError, OverflowError) as exc:
            self.result = None
            messagebox.showinfo('Confira os dados', str(exc), parent=self.app)
            return
        self.reference_sum.set(self._fmt(self.result['reference_sum']))
        self.target_sum.set(self._fmt(self.result['target_sum']))
        self.target_coefficient.set(self._fmt(self.result['coefficient']))
        self.formula.configure(text=(
            f'Fator = {self._fmt(self.result["target_sum"])} / {self._fmt(self.result["reference_sum"])} = '
            f'{self._fmt(self.result["factor"])}   |   Coeficiente = {self._fmt(self.result["reference_coefficient"])} × '
            f'{self._fmt(self.result["factor"])} = {self._fmt(self.result["coefficient"])}'))
        self.copy_button.configure(state='normal')
        self.copy_coefficient_button.configure(state='normal')
        self.app.status.set('Regra de 3 genérica calculada.')

    def copy_coefficient(self):
        if not self.result or self.app.working:
            return
        self.app.clipboard_clear(); self.app.clipboard_append(self._fmt(self.result['coefficient']))
        self.app.update_idletasks(); self.app.status.set('Coeficiente copiado.')

    def copy_justification(self):
        if not self.result or self.app.working:
            return
        self.app.clipboard_clear(); self.app.clipboard_append(self.result['justification'])
        self.app.update_idletasks(); self.app.status.set('Justificativa copiada.')

    def set_busy(self, busy):
        state = 'disabled' if busy else 'normal'
        self.calculate_button.configure(state=state)
        self.copy_button.configure(state='normal' if self.result and not busy else 'disabled')
        self.copy_coefficient_button.configure(state='normal' if self.result and not busy else 'disabled')


class RuleOfThreeTab(ttk.Frame):
    """Contêiner da regra de 3: SINAPI com 1 referência + cálculo genérico."""
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.columnconfigure(0, weight=1); self.rowconfigure(0, weight=1)
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=0, column=0, sticky='nsew')
        self.sinapi = SinapiRuleOfThreeTab(self.notebook, app)
        self.generic = GenericRuleOfThreeTab(self.notebook, app)
        self.notebook.add(self.sinapi, text='SINAPI — 1 referência')
        self.notebook.add(self.generic, text='Regra de 3 genérica')
        self.families = []

    def set_database(self, db, families):
        self.sinapi.set_database(db, families)
        self.families = self.sinapi.families

    def set_busy(self, busy):
        self.sinapi.set_busy(busy)
        self.generic.set_busy(busy)


class SinapiManualTrendTab(OutputPanel):
    """Tendência manual com referências carregadas da base SINAPI."""
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.db, self.refs, self.series, self.loaded_meta = None, [], [], None
        self.ref_rows, self.editor_rows = [], []
        self.next_ref_id, self.next_item, self.dirty = 0, 1, True
        self._building, self._loading = True, False
        build_manual_view(self, generic=False, make_table=make_table,
                          enable_cell_selection=enable_tree_cell_selection, units=DEFAULT_AXIS_UNITS)

    def add_reference(self):
        if len(self.ref_rows) >= 5 or (self.app.working and not self._building):
            return
        self.next_ref_id += 1
        row = {'id': self.next_ref_id, 'code': tk.StringVar(), 'dims': [tk.StringVar() for _ in range(3)], 'widgets': []}
        for col, var in enumerate([row['code'], *row['dims']]):
            entry = ttk.Entry(self.form, textvariable=var, width=12 if col == 0 else 15)
            row['widgets'].append(entry)
            var.trace_add('write', self.references_changed)
        remove = ttk.Button(self.form, text='Remover', command=lambda identifier=row['id']: self.remove_reference(identifier))
        row['remove'] = remove
        self.ref_rows.append(row)
        self.layout_references()
        self.references_changed()

    def remove_reference(self, identifier):
        if self.app.working or len(self.ref_rows) <= 2:
            return
        row = next(row for row in self.ref_rows if row['id'] == identifier)
        for widget in [*row['widgets'], row['remove']]:
            widget.destroy()
        self.ref_rows.remove(row)
        self.layout_references()
        self.references_changed()

    def layout_references(self):
        for i, row in enumerate(self.ref_rows):
            for col, widget in enumerate(row['widgets']):
                widget.grid(row=i+2, column=col, sticky='w', padx=(0, 8) if col == 0 else 5, pady=2)
            row['remove'].grid(row=i+2, column=5, sticky='w', padx=5)
            row['remove'].configure(state='normal' if len(self.ref_rows) > 2 and not self.app.working else 'disabled')
        self.plus.configure(state='normal' if len(self.ref_rows) < 5 and not self.app.working else 'disabled')

    def mode_changed(self):
        if self._building:
            return
        self.refs, self.series, self.loaded_meta = [], [], None
        self.next_item = 1
        self.dirty = True
        manual = self.mode.get() == 'manual'
        self.code_heading.configure(text='Código / nome (opcional)' if manual else 'Código SINAPI *')
        self.mode_hint.configure(text=(('Modo totalmente manual: sem consulta ao SINAPI. Códigos e descrições dos componentes são opcionais.'
                                        if manual else 'Informe 2 a 5 códigos e suas dimensões. Deixe as dimensões 2 e 3 vazias quando não se aplicarem.')
                                       + ' A unidade POL indica polegadas para todas as medidas, sejam inteiras, decimais ou fracionárias.'))
        self.prepare_button.configure(text='Preparar / atualizar tabela' if manual else 'Carregar SINAPI')
        self.service_entry.configure(state='normal' if manual else 'readonly')
        self.source_box.configure(values=[])
        self.source.set('')
        self.clear_output()
        self.render_editor()
        self.references_changed()

    def set_database(self, db):
        self.db = db
        # A lista acompanha a referência selecionada e inclui todas as unidades
        # de composição presentes nela, além das grandezas técnicas de dimensão.
        axis_units = available_dimension_units(db)
        for box in self.unit_boxes:
            box.configure(values=axis_units)
        # Uma troca de base não apaga dados inteiramente manuais.
        if self.mode.get() == 'sinapi':
            self.mode_changed()

    def set_busy(self, busy):
        super().set_busy(busy)
        self.state_controls()

    def state_controls(self):
        if self._building:
            return
        busy = self.app.working
        ready = bool(self.refs) and not self.dirty and not busy
        if hasattr(self, 'workspace'):
            self.workspace.sync(ready=bool(self.refs) and not self.dirty, has_result=bool(self.result))
        for button in (self.copy_values_button, self.copy_table_button, self.copy_button, self.export_button):
            button.configure(state='normal' if self.result and not busy else 'disabled')
        self.calc.configure(state='normal' if ready else 'disabled')
        self.descriptions_button.configure(state='normal' if self.refs and not self.dirty and not busy else 'disabled')
        editing = ready and self.mode.get() == 'manual'
        self.add_item_button.configure(state='normal' if editing else 'disabled')
        self.paste_button.configure(state='normal' if editing else 'disabled')
        self.layout_references()

    def clear_output(self, *_):
        super().clear_output()
        if hasattr(self, 'output'):
            if hasattr(self.output, '_selectable_cell_close'):
                self.output._selectable_cell_close()
            self.output.delete(*self.output.get_children())
        if hasattr(self, 'copy_values_button'):
            self.copy_values_button.configure(state='disabled')
            self.copy_table_button.configure(state='disabled')
        if hasattr(self, 'workspace'):
            self.workspace.sync(ready=bool(self.refs) and not self.dirty, has_result=False)

    def references_changed(self, *_):
        if self._building or self._loading:
            return
        self.dirty = True
        self.clear_output()
        self.ref_status.configure(text='Atualize a tabela após preencher ou alterar as referências.')
        self.state_controls()

    def _form_references(self):
        return reference_rows([{'row_id': row['id'], 'code': row['code'].get(),
                                'dims': [value.get() for value in row['dims']]} for row in self.ref_rows],
                              [unit.get() for unit in self.units], manual=self.mode.get() == 'manual')

    def _read_components(self):
        if not self.editor_rows:
            return copy.deepcopy(self.series)
        result = []
        for editor_row in self.editor_rows:
            component = copy.deepcopy(editor_row['data'])
            description = editor_row['description'].get().strip()
            if description != component.get('description', ''):
                component.pop('descriptions', None)
            component['description'] = description
            component['unit'] = editor_row['unit'].get().strip()
            component['coefficients'] = [variable.get() for variable in editor_row['values']]
            result.append(component)
        return result

    def prepare(self):
        if self.app.working:
            return
        try:
            new_refs = self._form_references()
            old_series = self._read_components()
            if self.mode.get() == 'sinapi':
                if not self.db:
                    raise AnalysisError('A base completa não está disponível. Importe ou restaure uma referência SINAPI.')
                series, service_unit, descriptions = series_from_sinapi(self.db, new_refs)
                for ref, description in zip(new_refs, descriptions):
                    ref['description'] = description
                meta = dict(self.db['meta'])
            else:
                series = remap_coefficients(old_series, self.refs, new_refs) if self.refs else []
                if not series:
                    series = [{'description': 'Item 1', 'unit': '', 'coefficients': [''] * len(new_refs)}]
                    self.next_item = 2
                service_unit, meta = self.service_unit.get(), None
            self._loading = True
            current_source = self.source.get()
            self.refs, self.series, self.loaded_meta = new_refs, series, meta
            self.service_unit.set(service_unit)
            codes = [ref['code'] for ref in self.refs]
            self.source_box.configure(values=codes)
            self.source.set(current_source if current_source in codes else codes[0])
            count = len(self.refs[0]['dims'])
            for i, (entry, label, target) in enumerate(zip(self.target_entries, self.target_labels, self.targets)):
                entry.configure(state='normal' if i < count else 'disabled')
                label.configure(text=(f'Alvo D{i+1} ({self.refs[0]["units"][i]})' if i < count else f'Dimensão {i+1}: não usada'))
                if i >= count:
                    target.set('')
            self.dirty = False
            self.agreed.set(False)
            self.clear_output()
            self.render_editor()
            suffix = 'dimensão 1' if count == 1 else f'{count} dimensões · índice RMS'
            self.ref_status.configure(text=f'{len(self.refs)} referências · {suffix}')
            if self.mode.get() == 'manual':
                hint = 'Identificação opcional: pode manter Item 1, Item 2…'
            else:
                incomplete = sum(1 for component in self.series if not component.get('alignment_complete', True))
                hint = ('Coeficientes carregados; confira os recursos equivalentes.' if not incomplete else
                        f'Coeficientes carregados. {incomplete} linha(s) não têm correspondente em todas as referências; confira/preencha as células vazias.')
            self.editor_hint.configure(text=hint)
            self.app.status.set('Tabela pronta. Preencha/confira os coeficientes e informe o alvo.')
        except (ValueError, OverflowError) as exc:
            self.dirty = True
            self.clear_output()
            messagebox.showinfo('Confira as referências', str(exc), parent=self.app)
        finally:
            self._loading = False
            self.state_controls()
        if not self.dirty and hasattr(self, 'workspace'):
            self.edit_summary.configure(text=f'{len(self.refs)} referências · {len(self.series)} componentes')
            self.workspace.show_editor()

    def render_editor(self):
        self.editor_rows = []
        for widget in self.editor.winfo_children():
            widget.destroy()
        if not self.refs:
            ttk.Label(self.editor, text='Preencha a etapa Referências e clique em Carregar para continuar.',
                      padding=12, wraplength=440).grid(row=0, column=0, sticky='w')
            return
        headers = ['Item', 'Identificação (opcional)', 'Un. (opc.)'] + [ref['code'] for ref in self.refs]
        for col, title in enumerate(headers):
            ttk.Label(self.editor, text=title, style='Title.TLabel').grid(row=0, column=col, sticky='w', padx=4, pady=5)
        for i, component in enumerate(self.series):
            description = tk.StringVar(value=component.get('description', ''))
            unit = tk.StringVar(value=component.get('unit', ''))
            values = [tk.StringVar(value=(coefficient_text(value) if isinstance(value, (float, int)) else str(value or '')))
                      for value in component['coefficients']]
            record = {'data': component, 'description': description, 'unit': unit, 'values': values}
            self.editor_rows.append(record)
            ttk.Label(self.editor, text=str(i+1)).grid(row=i+1, column=0, padx=6)
            for col, (var, width) in enumerate([(description, 28), (unit, 8), *[(value, 14) for value in values]], 1):
                entry = ttk.Entry(self.editor, textvariable=var, width=width)
                entry.grid(row=i+1, column=col, sticky='ew', padx=3, pady=3)
                entry.bind('<MouseWheel>', self.scroll_editor)
                var.trace_add('write', self.coefficients_changed)
            if self.mode.get() == 'manual':
                ttk.Button(self.editor, text='×', width=3, command=lambda index=i: self.remove_component(index)).grid(
                    row=i+1, column=len(headers), padx=3)
        self.editor_canvas.xview_moveto(0)

    def scroll_editor(self, event):
        self.editor_canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
        return 'break'

    def coefficients_changed(self, *_):
        if self._building or self._loading:
            return
        if self.loaded_meta:
            self.loaded_meta['manual_edited'] = True
        self.agreed.set(False)
        self.clear_output()

    def add_component(self):
        if self.app.working or self.dirty or self.mode.get() != 'manual':
            return
        self.series = self._read_components()
        self.series.append({'description': f'Item {self.next_item}', 'unit': '', 'coefficients': [''] * len(self.refs)})
        self.next_item += 1
        self.coefficients_changed()
        self.render_editor()
        self.editor.update_idletasks()
        self.editor_canvas.yview_moveto(1)

    def remove_component(self, index):
        if self.app.working or self.mode.get() != 'manual' or self.dirty:
            return
        self.series = self._read_components()
        del self.series[index]
        self.coefficients_changed()
        self.render_editor()

    def paste_coefficients(self):
        if self.app.working or self.dirty or self.mode.get() != 'manual':
            return
        try:
            matrix = clipboard_coefficients(self.app.clipboard_get(), len(self.refs))
            self.series = self._read_components()
            # Substitui apenas uma linha inicial ainda vazia; dados preenchidos
            # permanecem, e as novas linhas são acrescentadas ao fim.
            if len(self.series) == 1 and not any(str(v).strip() for v in self.series[0]['coefficients']):
                self.series = []
                self.next_item = 1
            for values in matrix:
                self.series.append({'description': f'Item {self.next_item}', 'unit': '', 'coefficients': values})
                self.next_item += 1
            self.coefficients_changed()
            self.render_editor()
            self.app.status.set(f'{len(matrix)} linhas de coeficientes coladas. Confira a ordem dos recursos.')
        except (tk.TclError, ValueError) as exc:
            messagebox.showinfo('Colar coeficientes', str(exc), parent=self.app)

    def show_references(self):
        if not self.refs or self.dirty:
            return
        dialog = tk.Toplevel(self.app)
        dialog.title('Referências utilizadas')
        dialog.geometry('820x430')
        dialog.transient(self.app)
        text = tk.Text(dialog, wrap='word', padx=15, pady=12, font=('Segoe UI', 11))
        scroll = ttk.Scrollbar(dialog, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        text.pack(fill='both', expand=True)
        content = '\n\n'.join(f'{ref["code"]} — {geometry_text(ref["dims"], ref["units"])}\n{ref.get("description", "Referência informada manualmente")}'
                              for ref in self.refs)
        if len(self.refs[0]['dims']) > 1:
            content += '\n\nAs dimensões participam pelo índice RMS, em mm, conforme o método de tubos e conexões.'
        self.app.text_into(text, content)

    def run(self):
        if self.app.working:
            return
        try:
            if self.dirty or not self.refs:
                raise AnalysisError('Carregue ou atualize a tabela de referências antes de calcular.')
            if not self.agreed.get():
                raise AnalysisError('Confirme a equivalência técnica dos recursos e das referências.')
            self.series = self._read_components()
            self.result = calculate_manual_trend(self.refs, self.series, [target.get() for target in self.targets],
                self.source.get(), [unit.get() for unit in self.units], self.service_unit.get(),
                self.extrapolate.get(), self.loaded_meta)
        except (ValueError, OverflowError) as exc:
            self.clear_output()
            messagebox.showinfo('Confira os dados', str(exc), parent=self.app)
            return
        self.output.delete(*self.output.get_children())
        for i, row in enumerate(self.result['rows']):
            self.output.insert('', 'end', iid=str(i), values=(row['item'], row['source_resource'],
                row['description'], row['unit'], coefficient_text(row['source_coefficient']),
                coefficient_text(row['coefficient']) if row['coefficient'] is not None else 'SEM RESULTADO', row['status']))
        label = 'Linear' if len(self.refs) == 2 else 'PCHIP'
        self.method.configure(text=f'Resultado · {label} · origem {self.source.get()}')
        self.show_memo()
        text = '\n\nREFERÊNCIAS INFORMADAS\n' + '\n'.join(
            f'{ref["code"]} | {ref["dimension_text"]} | índice {fmt(ref["x"])} | {ref["description"]}'
            for ref in self.result['references'])
        self.memo.configure(state='normal')
        self.memo.insert('end', text)
        self.memo.configure(state='disabled')
        self.state_controls()
        self.app.status.set('Calculado. Use Copiar coeficientes ou Copiar tabela para colar os resultados.')
        if hasattr(self, 'workspace'):
            self.workspace.show_results()

    def _copy_result(self, table=False, selected=False):
        if not self.result or self.app.working:
            return 'break'
        try:
            indices = sorted(int(item) for item in self.output.selection()) if selected and self.output.selection() else None
            text = result_clipboard(self.result, table=table, indices=indices)
            self.app.clipboard_clear()
            self.app.clipboard_append(text)
            self.app.update_idletasks()
            self.app.status.set('Tabela copiada para colar no Excel.' if table else 'Coeficientes copiados, um por linha, na ordem exibida.')
        except (ValueError, tk.TclError) as exc:
            messagebox.showinfo('Copiar resultado', str(exc), parent=self.app)
        return 'break'

    def copy_numbers(self, selected=False):
        return self._copy_result(selected=selected)

    def copy_table(self):
        return self._copy_result(table=True)


class GenericManualTrendTab(ttk.Frame):
    """Tendência genérica com o mesmo fluxo visual da subaba SINAPI."""
    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app, self.db, self.result = app, None, None
        self.refs, self.series, self.ref_rows, self.editor_rows = [], [], [], []
        self.parameter_count, self.next_ref_id, self.next_item = 1, 0, 1
        self.dirty, self._building, self._loading = True, True, False
        self.bank = tk.StringVar()
        self.period = tk.StringVar()
        for variable in (self.bank, self.period):
            variable.trace_add('write', self.clear_output)
        self.units = [tk.StringVar(value='MM')]
        self.units[0].trace_add('write', self.unit_changed)
        build_manual_view(self, generic=True, make_table=make_table,
                          enable_cell_selection=enable_tree_cell_selection, units=DEFAULT_AXIS_UNITS)

    def set_database(self, db):
        self.db = db
        axis_units = available_dimension_units(db)
        for box in self.unit_boxes:
            box.configure(values=axis_units)

    def _new_var(self, value=''):
        var = tk.StringVar(value=value)
        var.trace_add('write', self.references_changed)
        return var

    def add_reference(self):
        if self.app.working and not self._building:
            return
        self.next_ref_id += 1
        row = {'id': self.next_ref_id, 'code': self._new_var(),
               'params': [self._new_var() for _ in range(self.parameter_count)]}
        self.ref_rows.append(row)
        if not self._building:
            self.render_reference_form(); self.references_changed()

    def remove_reference(self, identifier):
        if self.app.working or len(self.ref_rows) <= 2:
            return
        self.ref_rows = [row for row in self.ref_rows if row['id'] != identifier]
        self.render_reference_form(); self.references_changed()

    def add_parameter(self):
        if self.app.working:
            return
        self.parameter_count += 1
        unit = tk.StringVar(value='MM')
        unit.trace_add('write', self.unit_changed)
        self.units.append(unit)
        for row in self.ref_rows:
            row['params'].append(self._new_var())
        self.render_reference_form(); self.render_target_area(); self.references_changed()

    def remove_parameter(self):
        if self.app.working or self.parameter_count <= 1:
            return
        self.parameter_count -= 1
        self.units.pop()
        for row in self.ref_rows:
            row['params'].pop()
        self.render_reference_form(); self.render_target_area(); self.references_changed()

    def render_reference_form(self):
        for widget in self.form.winfo_children():
            widget.destroy()
        self.unit_boxes = []
        ttk.Label(self.form, text='Código genérico *').grid(row=0, column=0, sticky='w', padx=(0, 8))
        ttk.Label(self.form, text='Unidade por coluna →', style='Muted.TLabel').grid(row=1, column=0, sticky='e', padx=8)
        axis_units = available_dimension_units(self.db)
        for i in range(self.parameter_count):
            ttk.Label(self.form, text=f'Parâmetro {i+1} *').grid(row=0, column=i+1, sticky='w', padx=5)
            box = ttk.Combobox(self.form, textvariable=self.units[i], width=13, values=axis_units)
            box.grid(row=1, column=i+1, sticky='ew', padx=5, pady=(2, 3))
            self.unit_boxes.append(box)
        for index, row in enumerate(self.ref_rows):
            ttk.Entry(self.form, textvariable=row['code'], width=12).grid(
                row=index+2, column=0, sticky='w', padx=(0, 8), pady=2)
            for column, variable in enumerate(row['params'], 1):
                ttk.Entry(self.form, textvariable=variable, width=15).grid(
                    row=index+2, column=column, sticky='ew', padx=5, pady=2)
            button = ttk.Button(self.form, text='Remover', command=lambda identifier=row['id']: self.remove_reference(identifier))
            button.grid(row=index+2, column=self.parameter_count+2, sticky='w', padx=5)
            button.configure(state='normal' if len(self.ref_rows) > 2 and not self.app.working else 'disabled')
        self.plus.configure(state='disabled' if self.app.working else 'normal')
        self.remove_parameter_button.configure(state='normal' if self.parameter_count > 1 and not self.app.working else 'disabled')

    def render_target_area(self):
        # Preserva origem, serviço e checkbox; reconstrói apenas as caixas de alvo.
        for widget in self.target_entries + self.target_labels:
            try: widget.destroy()
            except tk.TclError: pass
        self.target_entries = []
        self.target_labels = []
        old_values = [v.get() for v in self.targets]
        self.targets = []
        for i in range(self.parameter_count):
            target = tk.StringVar(value=old_values[i] if i < len(old_values) else '')
            target.trace_add('write', self.clear_output)
            label = ttk.Label(self.target_area, text=f'Alvo D{i+1} ({self.units[i].get()})')
            entry = ttk.Entry(self.target_area, textvariable=target, width=10)
            label.grid(row=0, column=i+1, sticky='w', padx=5)
            entry.grid(row=1, column=i+1, sticky='w', padx=5)
            entry.bind('<Return>', lambda event: self.run())
            self.targets.append(target); self.target_entries.append(entry); self.target_labels.append(label)
        offset = self.parameter_count + 1
        # Recria/posiciona estes widgets para permanecerem logo após o último alvo.
        for child in list(self.target_area.grid_slaves()):
            if getattr(child, '_generic_dynamic_aux', False):
                child.destroy()
        unit_label = ttk.Label(self.target_area, text='Un. do serviço'); unit_label._generic_dynamic_aux = True
        unit_entry = ttk.Entry(self.target_area, textvariable=self.service_unit, width=8); unit_entry._generic_dynamic_aux = True
        unit_label.grid(row=0, column=offset, sticky='w', padx=6)
        unit_entry.grid(row=1, column=offset, sticky='w', padx=6)
        self.service_entry = unit_entry


    def unit_changed(self, *_):
        if hasattr(self, 'target_labels'):
            for i, label in enumerate(self.target_labels):
                if i < len(self.units):
                    label.configure(text=f'Alvo D{i+1} ({self.units[i].get()})')
        self.references_changed()

    def references_changed(self, *_):
        if self._building or self._loading:
            return
        self.dirty = True
        self.clear_output()
        self.ref_status.configure(text='Atualize a tabela após preencher ou alterar as referências.')
        self.state_controls()

    def _form_refs(self):
        refs = []
        for i, row in enumerate(self.ref_rows, 1):
            code = row['code'].get().strip()
            params = [v.get().strip() for v in row['params']]
            populated = bool(code or any(params))
            if not populated:
                continue
            if not code:
                raise AnalysisError(f'Linha {i}: informe o código/identificação genérico.')
            if any(not value for value in params):
                raise AnalysisError(f'{code}: preencha todos os {self.parameter_count} parâmetro(s) ativos.')
            refs.append({'row_id': row['id'], 'code': code, 'parameters': params,
                         'units': [u.get().strip() or 'MM' for u in self.units]})
        if len(refs) < 2:
            raise AnalysisError('Informe pelo menos duas referências genéricas.')
        codes = [r['code'] for r in refs]
        if len(codes) != len(set(codes)):
            raise AnalysisError('Os códigos/identificações das referências não podem se repetir.')
        return refs

    def _read_components(self):
        if not self.editor_rows:
            return copy.deepcopy(self.series)
        result = []
        for record in self.editor_rows:
            result.append({
                'description': record['description'].get().strip(),
                'unit': record['unit'].get().strip(),
                'coefficients': [value.get() for value in record['values']],
            })
        return result

    def prepare(self):
        if self.app.working:
            return
        try:
            new_refs = self._form_refs()
            old_series = self._read_components()
            old_codes = [r['code'] for r in self.refs]
            new_codes = [r['code'] for r in new_refs]
            remapped = []
            if old_series and old_codes:
                positions = {code: i for i, code in enumerate(old_codes)}
                for component in old_series:
                    values = component.get('coefficients', [])
                    remapped.append({
                        'description': component.get('description', ''),
                        'unit': component.get('unit', ''),
                        'coefficients': [values[positions[c]] if c in positions and positions[c] < len(values) else '' for c in new_codes],
                    })
            if not remapped:
                remapped = [
                    {'description': '', 'unit': '', 'coefficients': [''] * len(new_refs)}
                    for _ in range(3)
                ]
                self.next_item = 4
            self._loading = True
            current_source = self.source.get()
            self.refs, self.series = new_refs, remapped
            self.source_box.configure(values=new_codes)
            self.source.set(current_source if current_source in new_codes else new_codes[0])
            self.dirty = False
            self.clear_output()
            self.render_editor()
            suffix = '1 parâmetro' if self.parameter_count == 1 else f'{self.parameter_count} parâmetros · índice RMS'
            self.ref_status.configure(text=f'{len(self.refs)} referências · {suffix}')
            self.app.status.set('Tabela genérica pronta. Preencha os coeficientes por coluna e informe o alvo.')
        except (ValueError, OverflowError) as exc:
            self.dirty = True
            self.clear_output()
            messagebox.showinfo('Confira as referências', str(exc), parent=self.app)
        finally:
            self._loading = False
            self.state_controls()
        if not self.dirty and hasattr(self, 'workspace'):
            self.edit_summary.configure(text=f'{len(self.refs)} referências · {len(self.series)} componentes')
            self.workspace.show_editor()

    def render_editor(self):
        self.editor_rows = []
        for widget in self.editor.winfo_children():
            widget.destroy()
        if not self.refs:
            ttk.Label(self.editor,
                      text='Preencha os códigos e parâmetros na etapa Referências e prepare a tabela.',
                      padding=12, wraplength=440).grid(row=0, column=0, sticky='w')
            return
        headers = ['Item', 'Identificação (opcional)', 'Un. (opc.)'] + [ref['code'] for ref in self.refs]
        for col, title in enumerate(headers):
            ttk.Label(self.editor, text=title, style='Title.TLabel').grid(row=0, column=col, sticky='w', padx=4, pady=5)
        for i, component in enumerate(self.series):
            description = tk.StringVar(value=component.get('description', ''))
            unit = tk.StringVar(value=component.get('unit', ''))
            values = [tk.StringVar(value=str(value or '')) for value in component.get('coefficients', [])]
            record = {'description': description, 'unit': unit, 'values': values}
            self.editor_rows.append(record)
            ttk.Label(self.editor, text=str(i+1)).grid(row=i+1, column=0, padx=6)
            for col, (var, width) in enumerate([(description, 28), (unit, 8), *[(value, 14) for value in values]], 1):
                entry = ttk.Entry(self.editor, textvariable=var, width=width)
                entry.grid(row=i+1, column=col, sticky='ew', padx=3, pady=3)
                entry.bind('<MouseWheel>', self.scroll_editor)
                var.trace_add('write', self.coefficients_changed)
            ttk.Button(self.editor, text='×', width=3, command=lambda index=i: self.remove_component(index)).grid(
                row=i+1, column=len(headers), padx=3)
        self.editor_canvas.xview_moveto(0)

    def scroll_editor(self, event):
        self.editor_canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
        return 'break'

    def coefficients_changed(self, *_):
        if self._building or self._loading:
            return
        self.clear_output()

    def add_component(self):
        if self.app.working or self.dirty or not self.refs:
            return
        self.series = self._read_components()
        self.series.append({'description': '', 'unit': '', 'coefficients': [''] * len(self.refs)})
        self.next_item += 1
        self.render_editor(); self.clear_output()
        self.editor.update_idletasks(); self.editor_canvas.yview_moveto(1)

    def remove_component(self, index):
        if self.app.working or self.dirty or len(self.series) <= 1:
            return
        self.series = self._read_components()
        del self.series[index]
        self.render_editor(); self.clear_output()

    def paste_coefficients(self):
        if self.app.working or self.dirty or not self.refs:
            return
        try:
            matrix = clipboard_coefficients(self.app.clipboard_get(), len(self.refs))
            self.series = self._read_components()
            if all(not any(str(v).strip() for v in row.get('coefficients', [])) and not row.get('description') and not row.get('unit') for row in self.series):
                self.series = []
            for values in matrix:
                self.series.append({'description': '', 'unit': '', 'coefficients': values})
            self.render_editor(); self.clear_output()
            self.app.status.set(f'{len(matrix)} linha(s) de coeficientes coladas.')
        except (tk.TclError, ValueError) as exc:
            messagebox.showinfo('Colar coeficientes', str(exc), parent=self.app)

    def _trend_data(self):
        series = self._read_components()
        if not series:
            raise AnalysisError('Adicione pelo menos um coeficiente.')
        references = []
        for ref_index, ref in enumerate(self.refs):
            references.append({
                'code': ref['code'],
                'parameters': ref['parameters'],
                'coefficients': [component['coefficients'][ref_index] for component in series],
            })
        return series, references

    def run(self):
        if self.app.working:
            return
        try:
            if self.dirty or not self.refs:
                raise AnalysisError('Prepare a tabela na etapa Referências antes de calcular.')
            series, references = self._trend_data()
            core = calculate_generic_parameter_trend(
                references, [target.get() for target in self.targets], self.extrapolate.get(),
                parameter_units=[unit.get().strip() or 'MM' for unit in self.units],
                bank=self.bank.get(), period=self.period.get())
            source_code = self.source.get() or self.refs[0]['code']
            source_ref = next((ref for ref in core['references'] if ref['code'] == source_code), None)
            if source_ref is None:
                raise AnalysisError('Escolha uma referência de origem válida.')
            rows = []
            status = 'Ponto informado' if core['exact'] else ('Extrapolado' if core['outside'] else 'Interpolado')
            for index, value in enumerate(core['coefficients']):
                description = series[index].get('description', '').strip() or f'Item {index+1}'
                unit = series[index].get('unit', '').strip()
                rows.append({
                    'item': index+1,
                    'source_resource': source_code,
                    'description': description,
                    'unit': unit,
                    'source_coefficient': source_ref['coefficients'][index],
                    'coefficient': value,
                    'status': status,
                })
            self.result = {**core, 'rows': rows, 'source_code': source_code,
                           'series': series, 'service_unit': self.service_unit.get().strip() or 'Não informada'}
        except (ValueError, OverflowError) as exc:
            self.clear_output()
            messagebox.showinfo('Confira os dados', str(exc), parent=self.app)
            return

        self.output.delete(*self.output.get_children())
        for i, row in enumerate(self.result['rows']):
            self.output.insert('', 'end', iid=str(i), values=(
                row['item'], row['source_resource'], row['description'], row['unit'],
                coefficient_text(row['source_coefficient']), coefficient_text(row['coefficient']), row['status']))
        label = 'Linear' if len(self.refs) == 2 else 'PCHIP'
        self.method.configure(text=f'Resultado · {label} · origem {source_code}')
        ref_lines = []
        for ref in self.result['references']:
            params = geometry_text(ref['parameters'], self.result['parameter_units'])
            ref_lines.append(f'{ref["code"]} | {params} | índice {fmt(ref["x"])}')
        memo_text = self.result['justification'] + '\n\nREFERÊNCIAS INFORMADAS\n' + '\n'.join(ref_lines)
        self.app.text_into(self.memo, memo_text)
        self.state_controls()
        self.app.status.set('Calculado. Clique em um Novo coeficiente para selecionar/copiar com o mouse ou use os botões de cópia.')
        if hasattr(self, 'workspace'):
            self.workspace.show_results()

    def copy_numbers(self, selected=False):
        if not self.result or self.app.working:
            return 'break'
        rows = self.result['rows']
        if selected and self.output.selection():
            rows = [self.result['rows'][int(i)] for i in sorted(self.output.selection(), key=int)]
        text = '\r\n'.join(coefficient_text(row['coefficient']) for row in rows)
        self.app.clipboard_clear(); self.app.clipboard_append(text); self.app.update_idletasks()
        self.app.status.set('Coeficientes copiados, um por linha.')
        return 'break'

    def copy_table(self):
        if not self.result or self.app.working:
            return
        lines = ['Item\tCódigo/Ref. origem\tIdentificação\tUnidade\tCoeficiente original\tNovo coeficiente\tSituação']
        for row in self.result['rows']:
            lines.append('\t'.join([
                str(row['item']), str(row['source_resource']), str(row['description']).replace('\t',' '),
                str(row['unit']).replace('\t',' '), coefficient_text(row['source_coefficient']),
                coefficient_text(row['coefficient']), str(row['status'])]))
        self.app.clipboard_clear(); self.app.clipboard_append('\r\n'.join(lines)); self.app.update_idletasks()
        self.app.status.set('Tabela copiada para colar no Excel.')

    def copy_justification(self):
        if not self.result or self.app.working:
            return
        self.app.clipboard_clear(); self.app.clipboard_append(self.result['justification']); self.app.update_idletasks()
        self.app.status.set('Justificativa copiada.')

    def clear_output(self, *_):
        self.result = None
        if hasattr(self, 'output'):
            if hasattr(self.output, '_selectable_cell_close'):
                self.output._selectable_cell_close()
            self.output.delete(*self.output.get_children())
        if hasattr(self, 'memo'):
            self.app.text_into(self.memo, '')
        if hasattr(self, 'copy_values_button'):
            self.copy_values_button.configure(state='disabled')
            self.copy_table_button.configure(state='disabled')
            self.copy_justification_button.configure(state='disabled')
        if hasattr(self, 'method'):
            self.method.configure(text='Resultado')
        if hasattr(self, 'workspace'):
            self.workspace.sync(ready=bool(self.refs) and not self.dirty, has_result=False)

    def state_controls(self):
        if self._building:
            return
        busy = self.app.working
        ready = bool(self.refs) and not self.dirty and not busy
        if hasattr(self, 'workspace'):
            self.workspace.sync(ready=bool(self.refs) and not self.dirty, has_result=bool(self.result))
        self.calc.configure(state='normal' if ready else 'disabled')
        self.add_item_button.configure(state='normal' if ready else 'disabled')
        self.paste_button.configure(state='normal' if ready else 'disabled')
        self.prepare_button.configure(state='disabled' if busy else 'normal')
        self.add_parameter_button.configure(state='disabled' if busy else 'normal')
        self.remove_parameter_button.configure(state='normal' if self.parameter_count > 1 and not busy else 'disabled')
        if hasattr(self, 'plus'):
            self.plus.configure(state='disabled' if busy else 'normal')
        if hasattr(self, 'copy_values_button'):
            state = 'normal' if self.result and not busy else 'disabled'
            self.copy_values_button.configure(state=state)
            self.copy_table_button.configure(state=state)
            self.copy_justification_button.configure(state=state)

    def set_busy(self, busy):
        self.state_controls()


class ManualTrendTab(ttk.Frame):
    """Contêiner: Tendência SINAPI existente + Tendência genérica digitada manualmente."""
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=0, column=0, sticky='nsew')
        self.sinapi = SinapiManualTrendTab(self.notebook, app)
        self.generic = GenericManualTrendTab(self.notebook, app)
        self.notebook.add(self.sinapi, text='Tendência itens SINAPI')
        self.notebook.add(self.generic, text='Tendência genérica — manual')

    def set_database(self, db):
        self.sinapi.set_database(db)
        self.generic.set_database(db)

    def set_busy(self, busy):
        self.sinapi.set_busy(busy)
        self.generic.set_busy(busy)
