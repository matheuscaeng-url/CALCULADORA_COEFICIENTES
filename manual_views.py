"""Layout compartilhado das calculadoras manuais SINAPI e genérica."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from manual_workspace import ManualWorkspace, ScrollArea


def build_manual_view(panel, *, generic, make_table, enable_cell_selection, units):
    ttk.Style(panel).configure('ManualCompact.TButton', padding=(7, 5))
    panel.columnconfigure(0, weight=1)
    panel.rowconfigure(0, weight=1)
    panel.workspace = ManualWorkspace(panel)
    panel.workspace.grid(row=0, column=0, sticky='nsew')
    references, editing, results = (panel.workspace.references, panel.workspace.edit,
                                     panel.workspace.results)

    # Etapa 1: campos com rolagem própria e ações fora da área rolada.
    ref_header = ttk.Frame(references)
    ref_header.grid(row=0, column=0, sticky='ew', pady=(0, 6))
    ttk.Label(ref_header, text='Referências genéricas' if generic else 'Referências SINAPI',
              style='Title.TLabel').pack(anchor='w')
    panel.mode_hint = ttk.Label(ref_header, style='Muted.TLabel', wraplength=850,
        text=(('Informe pelo menos duas referências e seus parâmetros. Prepare a tabela para preencher os coeficientes ao lado.'
               if generic else 'Informe 2 a 5 códigos. Preencha somente as dimensões que se aplicam a cada composição.')
              + ' A unidade POL indica polegadas para todas as medidas, sejam inteiras, decimais ou fracionárias.'))
    panel.mode_hint.pack(anchor='w', pady=(3, 0))
    ref_header.bind('<Configure>', lambda event: panel.mode_hint.configure(wraplength=max(200, event.width-12)))
    if generic:
        metadata = ttk.Frame(ref_header)
        metadata.pack(fill='x', pady=(8, 2))
        metadata.columnconfigure(0, weight=1)
        metadata.columnconfigure(1, weight=1)
        ttk.Label(metadata, text='Banco').grid(row=0, column=0, sticky='w')
        ttk.Label(metadata, text='Data do banco').grid(row=0, column=1, sticky='w', padx=(8, 0))
        panel.bank_entry = ttk.Entry(metadata, textvariable=panel.bank, width=18)
        panel.bank_entry.grid(row=1, column=0, sticky='ew')
        panel.period_entry = ttk.Entry(metadata, textvariable=panel.period, width=18)
        panel.period_entry.grid(row=1, column=1, sticky='ew', padx=(8, 0))
    panel.reference_scroll = ScrollArea(references)
    panel.reference_scroll.grid(row=1, column=0, sticky='nsew')
    panel.form = panel.reference_scroll.body
    actions = ttk.Frame(references)
    actions.grid(row=2, column=0, sticky='ew', pady=(8, 0))
    actions.columnconfigure(0, weight=1)
    toolbar = ttk.Frame(actions)
    toolbar.grid(row=0, column=0, sticky='w')
    panel.plus = ttk.Button(toolbar, text='+ Composição', command=panel.add_reference, style='ManualCompact.TButton')
    panel.plus.pack(side='left')
    if generic:
        panel.add_parameter_button = ttk.Button(toolbar, text='+ Parâmetro', command=panel.add_parameter, style='ManualCompact.TButton')
        panel.add_parameter_button.pack(side='left', padx=6)
        panel.remove_parameter_button = ttk.Button(toolbar, text='− Último parâmetro', command=panel.remove_parameter, style='ManualCompact.TButton')
        panel.remove_parameter_button.pack(side='left')
        panel.unit_boxes = []
    else:
        panel.mode = tk.StringVar(value='sinapi')
        panel.code_heading = ttk.Label(panel.form, text='Código SINAPI *')
        panel.code_heading.grid(row=0, column=0, sticky='w', padx=(0, 8))
        panel.units, panel.unit_boxes = [], []
        panel.base_axis_units = list(units)
        for i in range(3):
            ttk.Label(panel.form, text=f'Dimensão {i+1}' + (' *' if i == 0 else ' (opcional)')).grid(
                row=0, column=i+1, sticky='w', padx=5)
            unit = tk.StringVar(value='MM')
            box = ttk.Combobox(panel.form, textvariable=unit, width=13, values=units)
            box.grid(row=1, column=i+1, sticky='ew', padx=5, pady=(3, 5))
            unit.trace_add('write', panel.references_changed)
            panel.units.append(unit); panel.unit_boxes.append(box)
        ttk.Label(panel.form, text='Unidade por coluna →', style='Muted.TLabel').grid(
            row=1, column=0, sticky='e', padx=8)
    panel.prepare_button = ttk.Button(actions,
        text='Carregar SINAPI' if not generic else 'Preparar / atualizar tabela',
        style='Accent.TButton', command=panel.prepare)
    panel.prepare_button.grid(row=1, column=0, sticky='ew', pady=(5, 0))
    panel.ref_status = ttk.Label(actions, text='Preencha ao menos duas referências.', style='Muted.TLabel')
    panel.ref_status.grid(row=2, column=0, sticky='w', pady=(5, 0))
    actions.bind('<Configure>', lambda event: panel.ref_status.configure(wraplength=max(200, event.width-12)))

    # A matriz fica ao lado das referências; o alvo ocupa a base da aba inteira.
    edit_header = ttk.Frame(editing)
    edit_header.grid(row=0, column=0, sticky='ew', pady=(0, 5))
    edit_header.columnconfigure(0, weight=1)
    panel.edit_summary = ttk.Label(edit_header, text='Coeficientes por referência', style='Title.TLabel')
    panel.edit_summary.grid(row=0, column=0, sticky='w')
    panel.editor_hint = ttk.Label(edit_header, style='Muted.TLabel', wraplength=850,
        text='Uma linha por recurso; uma coluna por composição de referência.')
    panel.editor_hint.grid(row=1, column=0, columnspan=2, sticky='w', pady=(3, 0))
    edit_header.bind('<Configure>', lambda event: panel.editor_hint.configure(wraplength=max(200, event.width-12)))
    panel.editor_scroll = ScrollArea(editing)
    panel.editor_scroll.grid(row=1, column=0, sticky='nsew')
    panel.editor_host = panel.editor_scroll
    panel.editor_canvas, panel.editor = panel.editor_scroll.canvas, panel.editor_scroll.body

    calculation = panel.workspace.calculation
    calculation.columnconfigure(0, weight=1)
    # Ações dos componentes ficam imediatamente abaixo da matriz à direita.
    commands = ttk.Frame(editing if generic else calculation)
    commands.grid(row=2 if generic else 0, column=0, columnspan=1 if generic else 2,
                  sticky='ew', pady=(6, 3))
    panel.add_item_button = ttk.Button(commands, text='+ Componente', command=panel.add_component)
    panel.paste_button = ttk.Button(commands, text='Colar coeficientes do Excel', command=panel.paste_coefficients)
    if generic:
        panel.add_item_button.pack(side='left')
        panel.paste_button.pack(side='left', padx=6)
    else:
        panel.descriptions_button = ttk.Button(commands, text='Ver descrições das referências', command=panel.show_references)
        panel.descriptions_button.pack(side='left')
    panel.target_scroll = ScrollArea(calculation, height=72, fit_height=True)
    panel.target_scroll.grid(row=1, column=0, sticky='ew')
    panel.target_area = panel.target_scroll.body
    panel.source = tk.StringVar()
    panel.source_box = ttk.Combobox(panel.target_area, textvariable=panel.source, state='readonly', width=14)
    ttk.Label(panel.target_area, text='Referência de origem').grid(row=0, column=0, sticky='w', padx=(0, 8))
    panel.source_box.grid(row=1, column=0, sticky='w', padx=(0, 8))
    panel.targets, panel.target_entries, panel.target_labels = [], [], []
    panel.service_unit = tk.StringVar(value='UN')
    panel.extrapolate = tk.BooleanVar(value=False)
    panel.calc = ttk.Button(calculation, text='Calcular →', command=panel.run, style='Accent.TButton', state='disabled')
    panel.calc.grid(row=1, column=1, sticky='e', padx=(12, 0))
    options = ttk.Frame(calculation)
    options.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(2, 0))
    panel.allow_check = ttk.Checkbutton(options, text='Permitir extrapolação', variable=panel.extrapolate)
    panel.allow_check.pack(side='left')
    if not generic:
        for i in range(3):
            target = tk.StringVar()
            label = ttk.Label(panel.target_area, text=f'Alvo D{i+1}')
            label.grid(row=0, column=i+1, sticky='w', padx=5)
            entry = ttk.Entry(panel.target_area, textvariable=target, width=10)
            entry.grid(row=1, column=i+1, sticky='w', padx=5)
            entry.bind('<Return>', lambda event: panel.run())
            target.trace_add('write', panel.clear_output)
            panel.targets.append(target); panel.target_entries.append(entry); panel.target_labels.append(label)
        ttk.Label(panel.target_area, text='Un. do serviço').grid(row=0, column=4, sticky='w', padx=6)
        panel.service_entry = ttk.Entry(panel.target_area, textvariable=panel.service_unit, width=7, state='readonly')
        panel.service_entry.grid(row=1, column=4, sticky='w', padx=6)
        panel.agreed = tk.BooleanVar(value=False)
        ttk.Checkbutton(options, text='Confirmo a equivalência técnica das referências.', variable=panel.agreed).pack(
            side='left', padx=(14, 0))
        panel.agreed.trace_add('write', panel.clear_output)
        panel.buttons.extend([panel.plus, panel.prepare_button, panel.descriptions_button,
                              panel.calc, panel.add_item_button, panel.paste_button])
    for variable in (panel.source, panel.service_unit, panel.extrapolate):
        variable.trace_add('write', panel.clear_output)

    # Resultado em aba independente da altura das referências ou do editor.
    result_header = ttk.Frame(results)
    result_header.grid(row=0, column=0, sticky='ew', pady=(0, 5))
    result_header.columnconfigure(0, weight=1)
    panel.method = ttk.Label(result_header, text='Resultado', style='Title.TLabel')
    panel.method.grid(row=0, column=0, sticky='w')
    ttk.Button(result_header, text='← Voltar à edição', command=panel.workspace.show_editor).grid(
        row=0, column=1, sticky='e')
    tabs = ttk.Notebook(results, height=1, width=1)
    tabs.grid(row=1, column=0, sticky='nsew')
    result_tab, memo_tab = ttk.Frame(tabs), ttk.Frame(tabs)
    tabs.add(result_tab, text='Novos coeficientes')
    tabs.add(memo_tab, text='Memória e referências')
    frame, panel.output = make_table(result_tab,
        ['Item', 'Código/Ref. origem' if generic else 'Código na origem', 'Identificação',
         'Un.', 'Coef. origem', 'Novo coeficiente', 'Situação'],
        [50, 130, 300, 55, 115, 145, 180], height=12)
    frame.pack(fill='both', expand=True)
    enable_cell_selection(panel.output, {5})
    panel.output.bind('<Control-c>', lambda event: panel.copy_numbers(selected=True))
    panel.output.bind('<Control-C>', lambda event: panel.copy_numbers(selected=True))
    panel.memo = tk.Text(memo_tab, height=1, wrap='word', state='disabled', padx=12, pady=10)
    scroll = ttk.Scrollbar(memo_tab, command=panel.memo.yview)
    panel.memo.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right', fill='y'); panel.memo.pack(fill='both', expand=True)
    copy_actions = ttk.Frame(results)
    copy_actions.grid(row=2, column=0, sticky='ew', pady=(7, 0))
    panel.copy_values_button = ttk.Button(copy_actions, text='Copiar coeficientes', command=panel.copy_numbers,
                                         style='Accent.TButton', state='disabled')
    panel.copy_values_button.pack(side='left')
    panel.copy_table_button = ttk.Button(copy_actions, text='Copiar tabela', command=panel.copy_table, state='disabled')
    panel.copy_table_button.pack(side='left', padx=6)
    if generic:
        panel.copy_justification_button = ttk.Button(copy_actions, text='Copiar justificativa',
            command=panel.copy_justification, state='disabled')
        panel.copy_justification_button.pack(side='right')
    else:
        panel.make_actions(copy_actions)
    hint = ttk.Label(results, text='Clique em um novo coeficiente para selecionar e copiar. Ctrl+C copia a seleção.',
                     style='Muted.TLabel', wraplength=850)
    hint.grid(row=3, column=0, sticky='w', pady=(4, 0))
    results.bind('<Configure>', lambda event: hint.configure(wraplength=max(200, event.width-20)))

    panel.add_reference(); panel.add_reference()
    panel._building = False
    if generic:
        panel.render_reference_form(); panel.render_target_area(); panel.render_editor(); panel.state_controls()
    else:
        panel.mode_changed()
