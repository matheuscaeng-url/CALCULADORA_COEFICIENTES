"""Interface desktop do Processo 3. Diálogos sempre na thread do Tk."""
from __future__ import annotations

import logging
import math
import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from celulas_copiaveis import enable_tree_cell_selection

from coeficientes_core import (VERSION, OFFICIAL_URL, AUTOMATIC_SCOPE, SCOPE_REVISION, AnalysisError, build_families, calculate,
    export_report, format_dimension_input, format_geometry, format_reference_dimensions,
    import_sinapi, is_automatic_scope, load_database,
    norm, pchip, save_database)
from calculadoras_extras import RuleOfThreeTab, ManualTrendTab, make_splitter, bind_initial_sash

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
USER_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "Processo3Coeficientes"
GREEN, INK, BG, MUTED, AMBER = "#155e50", "#183b35", "#f1f5f4", "#57716b", "#ae6417"


def formatted(value, digits=6):
    if value is None:
        return "—"
    if value and abs(value) < 10**(-digits):
        return f"{value:.5g}".replace(".", ",")
    return f"{value:.{digits}f}".rstrip("0").rstrip(".").replace(".", ",")


def table(parent, columns, widths, height=6):
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=list(range(len(columns))), show="headings", height=height, selectmode="browse")
    for i, (label, width) in enumerate(zip(columns, widths)):
        tree.heading(i, text=label)
        tree.column(i, width=width, minwidth=55, stretch=(i == 1))
    vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    tree.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    return frame, tree


class CalculatorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PROCESSO 3 · Calculadoras de coeficientes")
        width = min(1320, max(960, self.winfo_screenwidth()-64))
        height = min(850, max(620, self.winfo_screenheight()-100))
        self.geometry(f"{width}x{height}")
        self.minsize(960, 620)
        self.configure(background=BG)
        self.db, self.families, self.family, self.result = None, [], None, None
        self.full_db = None
        self.events, self.working = queue.Queue(), False
        self.search_job = None
        self.source_codes = []
        self.style_widgets()
        self.build_interface()
        self.report_callback_exception = self.callback_error
        self.after(100, self.poll)
        self.after(150, self.load_initial)

    def style_widgets(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background=BG, foreground=INK)
        style.configure("TButton", padding=(12, 8), borderwidth=0)
        style.configure("Accent.TButton", background=GREEN, foreground="white", font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#0f7561"), ("disabled", "#9eb6af")])
        style.configure("TEntry", fieldbackground="white", padding=6)
        style.configure("TCombobox", fieldbackground="white", padding=5)
        style.configure("Treeview", rowheight=27, background="white", fieldbackground="white", borderwidth=0)
        style.configure("Treeview.Heading", background="#e0ebe7", font=("Segoe UI", 9, "bold"), padding=7)
        style.map("Treeview", background=[("selected", GREEN)], foreground=[("selected", "white")])
        style.configure("TNotebook.Tab", padding=(16, 9))
        style.configure("Title.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("Muted.TLabel", foreground=MUTED)

    def build_interface(self):
        header = tk.Frame(self, bg=INK, padx=22, pady=15)
        header.pack(fill="x")
        tk.Label(header, text="CALCULADORAS DE COEFICIENTES", bg=INK, fg="white", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        tk.Label(header, text="PROCESSO 3  /  Tubos, conexões e eletrocalhas · Regra de 3 SINAPI e genérica · Tendência manual SINAPI e genérica", bg=INK, fg="#c3ddd5", font=("Segoe UI", 10)).pack(anchor="w", pady=(3, 0))
        strip = ttk.Frame(self, padding=(20, 8))
        strip.pack(fill="x")
        self.base_label = ttk.Label(strip, text="Carregando referência…", style="Title.TLabel")
        self.base_label.pack(side="left")
        ttk.Label(strip, text="v" + VERSION, style="Muted.TLabel").pack(side="right")

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=18)
        calc_tab = ttk.Frame(self.notebook, padding=10)
        self.rule_tab = RuleOfThreeTab(self.notebook, self)
        self.manual_tab = ManualTrendTab(self.notebook, self)
        base_tab = ttk.Frame(self.notebook, padding=20)
        self.notebook.add(calc_tab, text="Tendência (2+ referências)")
        self.notebook.add(self.rule_tab, text="Regra de 3")
        self.notebook.add(self.manual_tab, text="Tendência manual")
        self.notebook.add(base_tab, text="Base SINAPI e orientações")
        calc_tab.columnconfigure(0, weight=1)
        calc_tab.rowconfigure(0, weight=1)
        self.trend_main_splitter = make_splitter(calc_tab, 'horizontal')
        self.trend_main_splitter.grid(row=0, column=0, sticky='nsew')
        left = ttk.Frame(self.trend_main_splitter, padding=(0, 0, 15, 0), width=330)
        right = ttk.Frame(self.trend_main_splitter, padding=(8, 0, 0, 0))
        self.trend_main_splitter.add(left, minsize=280, stretch='always')
        self.trend_main_splitter.add(right, minsize=650, stretch='always')
        bind_initial_sash(self.trend_main_splitter, 'horizontal', ratio=0.27, min_first=280, min_second=650)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(5, weight=1)
        ttk.Label(left, text="1. Encontre o serviço", style="Title.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.query = tk.StringVar()
        ttk.Entry(left, textvariable=self.query, width=36).grid(row=1, column=0, sticky="ew")
        ttk.Label(left, text="Pesquise um código, material ou serviço.", style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(3, 10))
        self.discipline = tk.StringVar(value="Todas as disciplinas")
        self.discipline_box = ttk.Combobox(left, textvariable=self.discipline, state="readonly", values=["Todas as disciplinas"])
        self.discipline_box.grid(row=3, column=0, sticky="ew")
        self.count_label = ttk.Label(left, text="", style="Muted.TLabel")
        self.count_label.grid(row=4, column=0, sticky="w", pady=6)
        family_frame, self.family_tree = table(left, ["Família de composições", "Referências"], [270, 92], height=12)
        self.family_tree.column(0, stretch=True)
        self.family_tree.column(1, stretch=False)
        family_frame.grid(row=5, column=0, sticky="nsew")
        self.query.trace_add("write", self.queue_filter)
        self.discipline.trace_add("write", self.queue_filter)
        self.family_tree.bind("<<TreeviewSelect>>", self.select_family)

        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)
        self.family_title = ttk.Label(right, text="Selecione uma família à esquerda.", wraplength=780, style="Title.TLabel")
        self.family_title.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        right.bind("<Configure>", lambda e: self.family_title.configure(wraplength=max(380, e.width-10)))
        form = ttk.Frame(right)
        form.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        form.columnconfigure(0, weight=1)
        ttk.Label(form, text="2. Composição de origem").grid(row=0, column=0, sticky="w")
        self.source = tk.StringVar()
        self.source_box = ttk.Combobox(form, textvariable=self.source, state="readonly", width=29)
        self.source_box.grid(row=1, column=0, sticky="ew", padx=(0, 12))
        self.target_frame = ttk.Frame(form)
        self.target_frame.grid(row=0, column=1, rowspan=2, sticky="w", padx=(0, 10))
        self.targets, self.target_labels, self.target_entries = [], [], []
        for index in range(3):
            variable = tk.StringVar()
            label = ttk.Label(self.target_frame, text=f"Boca {index + 1}")
            entry = ttk.Entry(self.target_frame, textvariable=variable, width=10)
            label.grid(row=0, column=index, sticky="w", padx=(0, 6))
            entry.grid(row=1, column=index, sticky="w", padx=(0, 6))
            entry.bind("<Return>", lambda e: self.run_calculation())
            self.targets.append(variable)
            self.target_labels.append(label)
            self.target_entries.append(entry)
        self.calc_button = ttk.Button(form, text="Calcular tendência", style="Accent.TButton", command=self.run_calculation)
        self.calc_button.grid(row=1, column=2, sticky="e")
        self.extrapolate = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="Permitir extrapolação fora do intervalo observado (sem limite percentual; revisão obrigatória)", variable=self.extrapolate).grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        for variable in (self.source, *self.targets, self.extrapolate):
            variable.trace_add("write", self.invalidate)
        result_bar = ttk.Frame(right)
        result_bar.grid(row=2, column=0, sticky="ew", pady=(0, 5))
        self.result_label = ttk.Label(result_bar, text="Coeficientes por componente", style="Title.TLabel")
        self.result_label.pack(side="left")
        self.export_button = ttk.Button(result_bar, text="Exportar Excel", command=self.export, state="disabled")
        self.export_button.pack(side="right")
        self.copy_button = ttk.Button(result_bar, text="Copiar justificativa", command=self.copy_justification, state="disabled")
        self.copy_button.pack(side="right", padx=(0, 8))
        self.trend_vertical_splitter = make_splitter(right, 'vertical')
        self.trend_vertical_splitter.grid(row=3, column=0, sticky='nsew')
        result_panel = ttk.Frame(self.trend_vertical_splitter)
        detail_panel = ttk.Frame(self.trend_vertical_splitter)
        self.trend_vertical_splitter.add(result_panel, minsize=180, stretch='always')
        self.trend_vertical_splitter.add(detail_panel, minsize=180, stretch='always')
        bind_initial_sash(self.trend_vertical_splitter, 'vertical', ratio=0.48, min_first=180, min_second=180)
        result_panel.columnconfigure(0, weight=1)
        result_panel.rowconfigure(0, weight=1)
        detail_panel.columnconfigure(0, weight=1)
        detail_panel.rowconfigure(1, weight=1)

        result_frame, self.result_tree = table(result_panel,
            ["Tipo", "Descrição na composição de origem", "Descrição para a nova composição", "Un.",
             "Coef. origem", "Coef. alvo", "Variação %", "Código do insumo na nova composição", "Situação"],
            [120, 300, 300, 50, 95, 95, 90, 190, 260], height=6)
        result_frame.grid(row=0, column=0, sticky="nsew")
        enable_tree_cell_selection(self.result_tree, {5})
        self.result_tree.bind("<<TreeviewSelect>>", self.show_resource)
        self.method_label = ttk.Label(detail_panel, text="Selecione e calcule para visualizar os dados.", style="Muted.TLabel", wraplength=720)
        self.method_label.grid(row=0, column=0, sticky="ew", pady=6)
        self.details = ttk.Notebook(detail_panel)
        self.details.grid(row=1, column=0, sticky="nsew")
        chart_frame, points_frame, supply_frame, notes_frame = ttk.Frame(self.details), ttk.Frame(self.details), ttk.Frame(self.details), ttk.Frame(self.details)
        self.details.add(chart_frame, text="Curva do componente")
        self.details.add(points_frame, text="Pontos e mudanças")
        self.details.add(supply_frame, text="Insumo e preços PE/SP")
        self.details.add(notes_frame, text="Memória e observações")
        self.canvas = tk.Canvas(chart_frame, bg="white", highlightthickness=0, height=200)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.draw_chart())
        points_area, self.points_tree = table(points_frame, ["Composição", "Geometria", "Índice", "Coeficiente", "Δ %", "Inclinação", "Recurso", "Linha fonte"], [95, 190, 80, 110, 75, 110, 80, 90], height=5)
        points_area.pack(fill="both", expand=True)
        supply_area, self.supply_tree = table(supply_frame, ["Código", "Descrição", "Un.", "Preço PE", "Preço SP", "Origem", "Linha ISD"], [90, 470, 55, 90, 90, 70, 80], height=5)
        supply_area.pack(fill="both", expand=True)
        self.supply_label = ttk.Label(supply_frame, text="Selecione um componente calculado.", style="Muted.TLabel")
        self.supply_label.pack(fill="x", pady=5)
        self.notes = tk.Text(notes_frame, wrap="word", height=8, background="white", foreground=INK, font=("Segoe UI", 10), padx=12, pady=10, relief="flat", state="disabled")
        notes_scroll = ttk.Scrollbar(notes_frame, command=self.notes.yview)
        self.notes.configure(yscrollcommand=notes_scroll.set)
        notes_scroll.pack(side="right", fill="y")
        self.notes.pack(fill="both", expand=True)

        ttk.Label(base_tab, text="Referência ativa", style="Title.TLabel").pack(anchor="w")
        self.base_details = tk.Text(base_tab, height=7, wrap="word", font=("Segoe UI", 10), bg="white", fg=INK, relief="flat", padx=12, pady=12, state="disabled")
        self.base_details.pack(fill="x", pady=10)
        actions = ttk.Frame(base_tab)
        actions.pack(fill="x")
        self.import_button = ttk.Button(actions, text="Importar referência SINAPI (.xlsx ou .zip)", style="Accent.TButton", command=self.choose_database)
        self.import_button.pack(side="left", padx=(0, 10))
        ttk.Button(actions, text="Abrir downloads da CAIXA", command=lambda: webbrowser.open(OFFICIAL_URL)).pack(side="left")
        self.restore_button = ttk.Button(actions, text="Usar base incluída", command=self.restore_database)
        self.restore_button.pack(side="left", padx=10)
        help_text = (
            "ESCOPO\n"
            "As famílias automáticas incluem tubos, conexões de tubulação e eletrocalhas, suas conexões e suportes. "
            "A terceira aba permite referências manuais de qualquer categoria, sob confirmação de equivalência técnica.\n\n"
            "AS CALCULADORAS\n"
            "Tendência: famílias com 2 ou mais referências; mantém o método anterior por componente.\n"
            "Regra de 3: possui duas subabas. A primeira é exclusiva para famílias SINAPI com exatamente 1 referência; "
            "a segunda é uma Regra de 3 genérica baseada na soma de 1 a 3 dimensões e permite informar código, banco e data da referência. "
            "Na subaba SINAPI, coeficiente alvo = coeficiente original × dimensão alvo / dimensão original. Em conexões com várias bocas, "
            "a razão usa os índices RMS. Essa proporcionalidade é uma hipótese, sem validação de tendência. "
            "Confira os recursos marcados para aplicar o fator; o consumo do tubo/conexão principal é mantido por padrão, "
            "mas a seleção é editável. Nenhum preço é multiplicado pelo fator.\n"
            "Tendência manual: possui duas subabas. Na subaba SINAPI, carregue de 2 a 5 composições diretamente da referência ativa, "
            "informe as dimensões e calcule cada recurso separadamente. Na subaba Tendência genérica — manual, o fluxo replica a tela SINAPI: "
            "as duas subabas têm uma aba de entrada que reúne referências, coeficientes e alvo. Informe códigos e dimensões à esquerda, carregue a tabela e confira/preencha os coeficientes à direita. O alvo e o botão Calcular ficam na base da mesma aba. Resultados abre automaticamente em uma aba separada. Voltar à edição preserva os dados. Identificação e unidade de cada recurso genérico são opcionais. "
            "A quantidade de parâmetros pode ser aumentada ou reduzida livremente (mínimo de 1). Depois informe a dimensão/parâmetro alvo e calcule. Com mais de um parâmetro, o programa usa o índice RMS para formar o eixo da tendência; cada coeficiente é interpolado independentemente. "
            "Com duas referências usa reta entre os pontos; com três ou mais usa PCHIP. A extrapolação é opcional. As duas subabas possuem Copiar justificativa, Copiar coeficientes e seleção individual do Novo coeficiente com o mouse para Ctrl+C.\n\n"
            "COMO USAR\n"
            "1. Pesquise o código/material e selecione uma família tecnicamente compatível.\n"
            "2. Escolha a composição de origem e informe a dimensão desejada. Em conexões de tubulação, informe as bocas indicadas. "
            "Em eletrocalhas e conexões, informe largura e altura; em reduções, as duas larguras e a altura.\n"
            "3. Calcule. Clique em cada componente para ver a curva e as mudanças entre as referências.\n"
            "4. Confira o insumo correspondente e os preços PE/SP, copie a justificativa e exporte a memória em Excel.\n\n"
            "ELETROCALHAS — DISCIPLINA ELÉTRICA\n"
            "Na referência incluída, estão disponíveis eletrocalhas retas, emendas, reduções, cotovelos horizontais e retos, "
            "curvas horizontais, tês horizontais e suportes. Eletrocalhas e conexões permitem alterar largura e altura. "
            "O tê elétrico usa largura e altura; a regra das três bocas aplica-se somente à tubulação. Reduções usam "
            "largura maior, largura menor e altura no índice RMS. As referências incluídas possuem somente altura de 50 mm; "
            "para adaptar a 100 mm ou outra altura não observada, habilite a extrapolação. O cálculo usa uma hipótese "
            "dimensional RMS, sem tendência independente de altura, e exibe alerta de revisão. "
            "Nos suportes, largura atendida e comprimento do perfil variam juntos, com 50 mm de diferença. "
            "Confira a espessura da chapa e o suporte do alvo: a tendência não dimensiona esses elementos.\n\n"
            "REGRA DOS TÊS DE TUBULAÇÃO\n"
            "Descrições com uma dimensão são interpretadas como D × D × D. Descrições com duas, como D1 × D1 × D2. "
            "Descrições com três mantêm a ordem informada. O eixo da curva é o diâmetro equivalente RMS das três bocas; "
            "portanto, todas participam do cálculo. A descrição SINAPI original fica preservada para conferência.\n\n"
            "FAMÍLIAS DE REDUÇÃO E LATÃO/BRONZE\n"
            "Tês normais e tês de redução permanecem em famílias diferentes. Luvas, joelhos, curvas, buchas, uniões, "
            "nípeis, adaptadores, conectores e demais conexões de redução são agrupados com todas as combinações dimensionais "
            "tecnicamente equivalentes. Material, junta, aplicação e local de instalação continuam separados. Conexões em "
            "latão ou bronze também são incluídas. Medidas em polegadas são mostradas como frações, conforme a notação SINAPI.\n\n"
            "COMO A TENDÊNCIA É OBTIDA\n"
            "PCHIP é uma curva cúbica por trechos que passa pelos pontos observados. Cada componente tem sua própria curva; "
            "o programa não multiplica a CPU inteira pela razão entre diâmetros. Com dois pontos, o cálculo é linear e exibe "
            "um alerta de maior possibilidade de erro. "
            "Se o alvo já existir na família, os coeficientes são consultados diretamente na referência.\n\n"
            "COMPARABILIDADE E CONFIANÇA\n"
            "A seleção automática mantém grupo, unidade de serviço, descrição e demais especificações. Material, tipo de junta, "
            "classe de pressão, local de instalação e método executivo precisam continuar compatíveis. Famílias não reconhecidas "
            "podem ser informadas na aba Tendência manual; nessa opção você declara a comparabilidade técnica. Não existe garantia de que toda "
            "família SINAPI tenha pontos suficientes. Mudanças na lista de recursos limitam o trecho calculável.\n"
            "Com quatro ou mais pontos, a validação retira pontos internos e mede o erro de previsão. Esse erro não é uma probabilidade "
            "de acerto nem mede o erro de uma futura obra. A extrapolação pode ultrapassar 20%, mas sempre exige marcação "
            "explícita e revisão técnica obrigatória.\n\n"
            "ATUALIZAÇÃO DA BASE\n"
            "Baixe os relatórios XLSX oficiais na CAIXA e importe o ZIP ou a planilha SINAPI_Referência com a aba Analítico. "
            "Uma tabela apenas de preços ou uma curva ABC não contém os coeficientes necessários. Uma competência é usada por vez. "
            "O mês vem do cabeçalho; AF na descrição é a revisão da composição. A importação não altera o arquivo original.\n\n"
            "RESULTADO PARA ORÇAMENTO\n"
            "Estimativas são composições próprias a revisar, não novos coeficientes oficiais SINAPI. O programa procura, na aba ISD "
            "da mesma referência, um insumo do serviço com a geometria desejada e informa preços em PE e SP quando existentes. "
            "A análise usa a CPU de primeiro nível; composições auxiliares mantêm seu coeficiente, sem decomposição recursiva. "
            "O preço do insumo não altera os coeficientes; encargos, perdas adicionais e disponibilidade comercial não são calculados."
        )
        help_frame = ttk.Frame(base_tab)
        help_frame.pack(fill="both", expand=True, pady=(15, 0))
        help_widget = tk.Text(help_frame, wrap="word", font=("Segoe UI", 10), bg=BG, fg=INK, relief="flat", padx=3, pady=5)
        help_scroll = ttk.Scrollbar(help_frame, command=help_widget.yview)
        help_widget.configure(yscrollcommand=help_scroll.set)
        help_scroll.pack(side="right", fill="y")
        help_widget.pack(fill="both", expand=True)
        help_widget.insert("1.0", help_text)
        help_widget.configure(state="disabled")
        footer = ttk.Frame(self, padding=(20, 8))
        footer.pack(fill="x")
        self.status = tk.StringVar(value="Preparando base…")
        ttk.Label(footer, textvariable=self.status, style="Muted.TLabel").pack(side="left")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=160)
        self.progress.pack(side="right")

    @staticmethod
    def text_into(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def callback_error(self, exc, value, trace):
        logging.error("Falha na interface", exc_info=(exc, value, trace))
        messagebox.showerror("Processo 3", f"Não foi possível concluir a ação: {value}\n\nRegistro: {USER_DIR / 'processo3.log'}", parent=self)

    def start_job(self, worker, success, message):
        if self.working:
            return
        self.working = True
        self.status.set(message)
        self.progress.start(12)
        for button in (self.import_button, self.restore_button, self.calc_button, self.export_button, self.copy_button):
            button.configure(state="disabled")
        self.rule_tab.set_busy(True)
        self.manual_tab.set_busy(True)
        def run():
            try:
                result = worker()
                self.events.put(("done", success, result))
            except Exception as exc:
                logging.exception("Falha na operação")
                self.events.put(("error", None, str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, callback, value = self.events.get_nowait()
                if kind == "progress":
                    self.status.set(value)
                    continue
                self.working = False
                self.progress.stop()
                for button in (self.import_button, self.restore_button, self.calc_button):
                    button.configure(state="normal")
                self.export_button.configure(state="normal" if self.result else "disabled")
                self.copy_button.configure(state="normal" if self.result else "disabled")
                self.rule_tab.set_busy(False)
                self.manual_tab.set_busy(False)
                if kind == "error":
                    self.status.set("Operação interrompida. Confira a mensagem e tente novamente.")
                    messagebox.showerror("Processo 3", value, parent=self)
                else:
                    callback(value)
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def load_initial(self):
        def work():
            custom = USER_DIR / "base_ativa.json.gz"
            warning = ""
            try:
                data = load_database(custom if custom.exists() else ROOT / "data" / "sinapi_base.json.gz")
            except Exception:
                logging.exception("Base local indisponível, usando base incluída")
                data = load_database(ROOT / "data" / "sinapi_base.json.gz")
                save_database(data, custom)
                warning = "A base anterior era incompatível e foi substituída pela base incluída."
            full_data = self.matching_full_database(data)
            if full_data is None:
                warning += " Base completa correspondente indisponível: reimporte sua referência para incluir eletrocalhas e carregar códigos na Tendência manual."
            else:
                upgraded = self.upgrade_automatic_database(data, full_data)
                if upgraded != data:
                    data = upgraded
                    save_database(data, custom)
                if full_data["meta"].get("scope_revision", 0) >= SCOPE_REVISION:
                    save_database(full_data, USER_DIR / "base_completa.json.gz")
                else:
                    warning += " Eletrocalhas incluídas na sua competência; reimporte essa referência para completar os preços dos novos insumos."
            return data, build_families(data), warning, full_data
        self.start_job(work, self.set_database, "Carregando composições e identificando famílias…")

    @staticmethod
    def matching_full_database(data):
        matches = []
        for path in (USER_DIR / "base_completa.json.gz", ROOT / "data" / "sinapi_completa.json.gz"):
            if not path.exists():
                continue
            try:
                full = load_database(path)
                if all(full["meta"].get(key) == data["meta"].get(key) for key in ("period", "sha256")):
                    matches.append(full)
            except Exception:
                logging.exception("Base completa indisponível: %s", path)
        if not matches:
            return None
        full = matches[0]
        # Uma cópia antiga do mesmo XLSX pode ter as CPUs completas, mas apenas
        # os insumos de tubulação. Enriquece sem trocar competência nem valores
        # existentes na cópia do usuário.
        for newer in matches[1:]:
            if newer["meta"].get("scope_revision", 0) > full["meta"].get("scope_revision", 0):
                full = {**full, "meta": {**full["meta"], "scope_revision": newer["meta"]["scope_revision"]},
                        "compositions": {**newer["compositions"], **full["compositions"]},
                        "supplies": {**newer.get("supplies", {}), **full.get("supplies", {})}}
                full["meta"]["filtered_supplies"] = len(full["supplies"])
        return full

    @staticmethod
    def tube_database(full):
        """Nome mantido para compatibilidade; filtra todo o escopo automático."""
        data = dict(full)
        data["meta"] = dict(full["meta"])
        data["compositions"] = {code: item for code, item in full["compositions"].items()
                                if is_automatic_scope(item["description"])}
        data["meta"]["scope"] = AUTOMATIC_SCOPE
        data["meta"]["filtered_compositions"] = len(data["compositions"])
        return data

    @staticmethod
    def upgrade_automatic_database(data, full):
        """Acrescenta o novo escopo só quando competência e arquivo coincidem."""
        if not all(data["meta"].get(key) == full["meta"].get(key) for key in ("period", "sha256")):
            return data
        additions = CalculatorApp.tube_database(full)
        upgraded = {**data, "meta": dict(data["meta"]),
                    "compositions": {**additions["compositions"], **data["compositions"]},
                    "supplies": {**additions.get("supplies", {}), **data.get("supplies", {})}}
        upgraded["meta"].update(scope=AUTOMATIC_SCOPE,
                                scope_revision=full["meta"].get("scope_revision", 0),
                                filtered_compositions=len(upgraded["compositions"]),
                                filtered_supplies=len(upgraded["supplies"]))
        return upgraded

    def set_database(self, payload):
        self.db, all_families, warning, self.full_db = payload
        self.families = [family for family in all_families if len(family["refs"]) >= 2]
        self.rule_tab.set_database(self.db, all_families)
        self.manual_tab.set_database(self.full_db)
        self.family = None
        self.invalidate()
        meta = self.db["meta"]
        calculable = sum(bool(f.get("has_trend", True)) for f in self.families)
        self.base_label.configure(text=(f"SINAPI {meta['period']}  ·  {calculable} famílias com tendência  ·  "
                                        f"{len(self.rule_tab.families)} com referência única"))
        info = (f"Competência: {meta['period']}   |   Emissão: {meta.get('emission') or 'não informada'}\n"
            f"Arquivo: {meta['filename']}\nAba: {meta['sheet']}   |   Preços: {meta.get('price_sheet') or 'não encontrada'}\n"
            f"Escopo filtrado: {len(self.db['compositions']):,} composições e {len(self.db.get('supplies', {})):,} insumos — {AUTOMATIC_SCOPE}\n"
            f"SHA-256: {meta['sha256']}\n"
            "A competência acima é a utilizada nos cálculos. Consulte a CAIXA para verificar novas publicações.")
        self.text_into(self.base_details, info)
        self.discipline_box.configure(values=["Todas as disciplinas"] + sorted({f["discipline"] for f in self.families}))
        self.discipline.set("Todas as disciplinas")
        self.query.set("")
        self.filter_families()
        default = next((f for f in self.families if any(r["code"] == "94648" for r in f["refs"])), None)
        if default:
            self.family_tree.selection_set(default["id"])
            self.family_tree.see(default["id"])
            self.activate_family(default)
            self.targets[0].set("45")
        self.status.set(warning or "Base pronta. Selecione o serviço, confira a dimensão e calcule.")

    def choose_database(self):
        if self.working:
            return
        path = filedialog.askopenfilename(parent=self, title="Referência SINAPI completa", filetypes=[("Referência SINAPI", "*.xlsx *.zip"), ("Excel", "*.xlsx"), ("ZIP", "*.zip")])
        if not path:
            return
        def work():
            full_data = import_sinapi(path, lambda m: self.events.put(("progress", None, m)), include_all=True)
            data = self.tube_database(full_data)
            families = build_families(data)
            if not families:
                raise AnalysisError("Nenhuma família dimensional encontrada. A base anterior foi preservada.")
            save_database(data, USER_DIR / "base_ativa.json.gz")
            save_database(full_data, USER_DIR / "base_completa.json.gz")
            return data, families, "Referência importada. Todos os novos cálculos usarão essa competência.", full_data
        self.start_job(work, self.set_database, "Importando referência sem alterar o arquivo original…")

    def restore_database(self):
        if self.working:
            return
        def work():
            data = load_database(ROOT / "data" / "sinapi_base.json.gz")
            full_data = load_database(ROOT / "data" / "sinapi_completa.json.gz")
            families = build_families(data)
            save_database(data, USER_DIR / "base_ativa.json.gz")
            save_database(full_data, USER_DIR / "base_completa.json.gz")
            return data, families, "Base incluída restaurada.", full_data
        self.start_job(work, self.set_database, "Restaurando referência incluída…")

    def queue_filter(self, *_):
        if self.search_job:
            self.after_cancel(self.search_job)
        self.search_job = self.after(220, self.filter_families)

    def filter_families(self):
        self.search_job = None
        if not self.db:
            return
        tokens, category = norm(self.query.get()).split(), self.discipline.get()
        self.visible = {}
        self.family_tree.delete(*self.family_tree.get_children())
        for family in self.families:
            haystack = norm(family["title"] + " " + family["group"] + " " + " ".join(r["code"] for r in family["refs"]))
            if (category == "Todas as disciplinas" or family["discipline"] == category) and all(t in haystack for t in tokens):
                self.visible[family["id"]] = family
                count = str(len(family["refs"])) if family.get("has_trend", True) else f"{len(family['refs'])} · consulta"
                self.family_tree.insert("", "end", iid=family["id"], values=(family["title"], count))
        self.count_label.configure(text=f"{len(self.visible)} famílias encontradas")
        if self.family and self.family["id"] in self.visible:
            self.family_tree.selection_set(self.family["id"])

    def select_family(self, *_):
        selected = self.family_tree.selection()
        if selected and selected[0] in self.visible:
            family = self.visible[selected[0]]
            if self.family is not family:
                self.activate_family(family)

    def activate_family(self, family):
        self.family = family
        self.invalidate()
        self.family_title.configure(text=family["title"])
        self.source_codes = [r["code"] for r in family["refs"]]
        values = [f"{r['code']}  ·  {format_reference_dimensions(r)}" for r in family["refs"]]
        self.source_box.configure(values=values)
        self.source_box.current(0)
        for index, (label, entry, variable) in enumerate(zip(self.target_labels, self.target_entries, self.targets)):
            if index < family["dimension_count"]:
                unit = family["axis_units"][index]
                unit_label = 'pol' if unit == 'POL' else unit.lower()
                if family.get("axis_labels"):
                    label.configure(text=f"{'3. ' if index == 0 else ''}{family['axis_labels'][index]} ({unit_label})")
                else:
                    label.configure(text=(f"3. Dimensão desejada ({unit_label})" if family["dimension_count"] == 1
                                          else f"{'3. ' if index == 0 else ''}Boca {index + 1} ({unit_label})"))
                label.grid()
                entry.grid()
                variable.set(format_dimension_input(family["refs"][0]["dims"][index], unit))
            else:
                label.grid_remove()
                entry.grid_remove()
                variable.set("")
        if family.get("has_trend", True):
            self.status.set(f"{len(values)} referências · serviço em {family['service_unit']} · confira a especificação completa acima.")
        else:
            self.status.set("Consulta oficial disponível. Esta especificação possui menos de 2 geometrias compatíveis para estimar outro diâmetro.")

    def invalidate(self, *_):
        self.result = None
        if not hasattr(self, "result_tree"):
            return
        if hasattr(self.result_tree, '_selectable_cell_close'):
            self.result_tree._selectable_cell_close()
        self.result_tree.delete(*self.result_tree.get_children())
        self.points_tree.delete(*self.points_tree.get_children())
        self.supply_tree.delete(*self.supply_tree.get_children())
        self.supply_label.configure(text="Selecione um componente calculado.")
        self.canvas.delete("all")
        self.text_into(self.notes, "")
        self.export_button.configure(state="disabled")
        self.copy_button.configure(state="disabled")
        self.result_label.configure(text="Coeficientes por componente")
        self.method_label.configure(text="Informe o alvo e clique em Calcular tendência.")

    def run_calculation(self):
        if self.working:
            return
        if not self.family or not self.db:
            messagebox.showinfo("Processo 3", "Selecione uma família de composições.", parent=self)
            return
        try:
            index = self.source_box.current()
            if index < 0:
                raise AnalysisError("Selecione uma composição de origem.")
            target = (self.targets[0].get() if self.family["dimension_count"] == 1 else
                      [value.get() for value in self.targets[:self.family["dimension_count"]]])
            result = calculate(self.db, self.family, self.source_codes[index], target, self.extrapolate.get())
        except (AnalysisError, ValueError) as exc:
            self.invalidate()
            self.status.set("Cálculo não realizado: confira as referências e a dimensão.")
            messagebox.showinfo("Confira os dados", str(exc), parent=self)
            return
        self.result = result
        self.result_tree.delete(*self.result_tree.get_children())
        for index, row in enumerate(result["rows"]):
            self.result_tree.insert("", "end", iid=str(index), values=(row["kind"], row["description"],
                row["target_description"], row["unit"], formatted(row["source_coefficient"]),
                formatted(row["coefficient"]), formatted(row["change_pct"], 2),
                row["target_resource"], row["status"]))
        self.result_label.configure(text=(f"Composição SINAPI oficial {result['target_code']}" if result["target_code"]
                                         else "Estimativa para composição própria — sem código oficial"))
        self.method_label.configure(text=f"{result['method']} · {result['source_dimension_text']} → {result['target_dimension_text']} · selecione um componente")
        refs_text = "\n".join(f"{r['code']} | {r['dimension_text']} | linha {r['row']} | {r['description']}" for r in result["references"])
        memo = (f"{result['mode']}\nMétodo: {result['method']}\nCompetência: {result['meta']['period']}\n"
            f"Composição de origem: {result['source_code']}\n"
            f"Código oficial de composição no alvo: {result['target_code'] or 'não existe — estimativa para composição própria'}\n"
            "Os códigos exibidos na coluna 'Código do insumo na nova composição' são códigos de insumos/componentes "
            "a usar dentro da composição adaptada; não são novos códigos oficiais de composição.\n\n"
            f"JUSTIFICATIVA CURTA\n{result['justification']}\n\n")
        memo += "\n\n".join(result["warnings"]) + "\n\nCOMPOSIÇÕES DE REFERÊNCIA\n" + refs_text
        self.text_into(self.notes, memo)
        self.export_button.configure(state="normal")
        self.copy_button.configure(state="normal")
        if result["rows"]:
            self.result_tree.selection_set("0")
            self.show_resource()
        partial = any(r["coefficient"] is None for r in result["rows"])
        self.status.set("Resultado parcial: leia as observações antes de usar." if partial else "Cálculo concluído. Confira a curva e exporte a memória em Excel.")

    def selected_resource(self):
        selected = self.result_tree.selection()
        if not selected or not self.result:
            return None
        return self.result["rows"][int(selected[0])]

    def show_resource(self, *_):
        row = self.selected_resource()
        self.points_tree.delete(*self.points_tree.get_children())
        self.supply_tree.delete(*self.supply_tree.get_children())
        if not row:
            return
        previous = None
        for point in row["points"]:
            coefficient = point["coefficient"]
            valid = previous and previous["coefficient"] is not None and coefficient is not None
            change = (coefficient / previous["coefficient"] - 1) * 100 if valid and previous["coefficient"] else None
            slope = ((coefficient - previous["coefficient"]) / (point["x"] - previous["x"])
                     if valid and not math.isclose(point["x"], previous["x"]) else None)
            self.points_tree.insert("", "end", values=(point["composition"], point["dimension_text"], formatted(point["x"]), formatted(coefficient), formatted(change, 2), formatted(slope, 8), point["resource"], point["row"]))
            previous = point
        for item in row["supply_matches"]:
            self.supply_tree.insert("", "end", values=(item["code"], item["description"], item["unit"],
                formatted(item.get("PE"), 2), formatted(item.get("SP"), 2), item.get("origin"), item.get("row")))
        self.supply_label.configure(text=row["supply_status"])
        check = row["validation"]
        validation_text = f"Erro interno {formatted(check['nmae_pct'], 2)}% ({check['n']} pontos retirados)" if check["nmae_pct"] is not None else check["label"]
        if "DEFINIR" in row["target_resource"]:
            target_note = " · Insumo da nova composição a definir"
        elif row["target_resource"] and row["target_resource"] != row["source_resource"]:
            target_note = f" · Novo insumo na composição: {row['target_resource']} — {row['target_description']}"
        else:
            target_note = ""
        self.method_label.configure(text=f"{row['status']} · {validation_text}{target_note}")
        self.draw_chart()

    def draw_chart(self):
        self.canvas.delete("all")
        row = self.selected_resource()
        if not row:
            return
        raw_points = [p for p in row["points"] if p["coefficient"] is not None]
        grouped = {}
        for point in raw_points:
            grouped.setdefault(round(point["x"], 10), []).append(point["coefficient"])
        points = [{"x": x, "coefficient": sum(values) / len(values)} for x, values in sorted(grouped.items())]
        if not points:
            return
        width, height = max(320, self.canvas.winfo_width()), max(155, self.canvas.winfo_height())
        left, right, top, bottom = 75, width - 25, 35, height - 42
        xs = [p["x"] for p in points]
        ys = [p["coefficient"] for p in points]
        target, value = self.result["target"], row["coefficient"]
        xmin, xmax = min(xs + [target]), max(xs + [target])
        xmax = xmax if xmax > xmin else xmin + 1
        ymin, ymax = min(ys + ([value] if value is not None else [])), max(ys + ([value] if value is not None else []))
        margin = (ymax - ymin) * .12 or max(abs(ymax) * .08, .001)
        ymin, ymax = max(0, ymin-margin), ymax+margin
        px = lambda x: left + (x-xmin)/(xmax-xmin)*(right-left)
        py = lambda y: bottom - (y-ymin)/(ymax-ymin)*(bottom-top)
        for i in range(4):
            y = ymin + i * (ymax-ymin)/3
            yy = py(y)
            self.canvas.create_line(left, yy, right, yy, fill="#e3ece8")
            self.canvas.create_text(left-8, yy, text=formatted(y, 5), anchor="e", fill=MUTED, font=("Segoe UI", 8))
        self.canvas.create_line(left, top, left, bottom, right, bottom, fill="#849d94")
        if len(xs) >= 2:
            line = []
            for i in range(161):
                x = xs[0] + (xs[-1]-xs[0])*i/160
                line.extend((px(x), py(pchip(xs, ys, x))))
            self.canvas.create_line(*line, fill=GREEN, width=2)
        for i, (x, y) in enumerate(zip(xs, ys)):
            self.canvas.create_oval(px(x)-3, py(y)-3, px(x)+3, py(y)+3, fill=GREEN, outline="white")
            if len(xs) <= 10 or i in (0, len(xs)-1):
                self.canvas.create_text(px(x), bottom+14, text=formatted(x, 2), fill=MUTED, font=("Segoe UI", 8))
        if value is not None:
            self.canvas.create_line(px(target), top, px(target), bottom, fill=AMBER, dash=(4, 4))
            self.canvas.create_oval(px(target)-5, py(value)-5, px(target)+5, py(value)+5, fill=AMBER, outline="white", width=2)
        self.canvas.create_text(left, 16, text=f"Coeficiente ({row['unit']} / {self.result['family']['service_unit']})", anchor="w", fill=INK, font=("Segoe UI", 9, "bold"))
        self.canvas.create_text(right, 16, text="● Referências    ● Alvo", anchor="e", fill=MUTED, font=("Segoe UI", 8))
        self.canvas.create_text((left+right)/2, height-9, text=self.result["family"]["curve_label"], fill=MUTED, font=("Segoe UI", 8))

    def copy_justification(self):
        if not self.result:
            return
        self.clipboard_clear()
        self.clipboard_append(self.result["justification"])
        self.update_idletasks()
        self.status.set("Justificativa curta copiada para a área de transferência.")

    def export(self):
        if self.working or not self.result:
            return
        result = self.result
        target_name = "x".join(formatted(value, 2).replace(",", "_") for value in result["target_dims"])
        path = filedialog.asksaveasfilename(parent=self, title="Salvar memória do cálculo", defaultextension=".xlsx", initialfile=f"Coeficientes_{result['source_code']}_{target_name}.xlsx", filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        def completed(saved):
            self.status.set(f"Relatório salvo: {saved}")
            messagebox.showinfo("Relatório salvo", f"Memória do cálculo salva em:\n{saved}", parent=self)
        self.start_job(lambda: export_report(result, path), completed, "Gravando relatório Excel…")


def main():
    USER_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=USER_DIR / "processo3.log", level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    app = CalculatorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
