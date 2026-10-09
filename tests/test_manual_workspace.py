"""Fluxo das telas manuais, sem depender de servidor gráfico no teste."""
import sys
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from manual_workspace import ManualWorkspace
from calculadoras_extras import GenericManualTrendTab, SinapiManualTrendTab
from coeficientes_core import load_database


class NotebookModel:
    def __init__(self):
        self.current = 0
        self.states = ['normal', 'disabled']

    def select(self, index=None):
        if index is not None:
            if self.states[index] == 'disabled':
                raise AssertionError('Tentativa de abrir etapa desabilitada')
            self.current = index
        return self.current

    def index(self, tab):
        return int(tab)

    def tab(self, index, option=None, **kwargs):
        if 'state' in kwargs:
            self.states[index] = kwargs['state']
        return self.states[index]


def workspace():
    panel = object.__new__(ManualWorkspace)
    panel.steps = NotebookModel()
    return panel


class WorkspaceNavigationTests(unittest.TestCase):
    def test_prepare_calculate_and_return_preserve_navigation(self):
        w = workspace()
        w.sync(ready=False, has_result=False)
        w.show_results()
        self.assertEqual(w.steps.current, 0)
        w.sync(ready=True, has_result=False)
        w.show_editor()
        self.assertEqual(w.steps.current, 0)
        w.sync(ready=True, has_result=True)
        w.show_results()
        self.assertEqual(w.steps.current, 1)
        w.show_editor()
        self.assertEqual(w.steps.current, 0)
        self.assertEqual(w.steps.states[1], 'normal')

    def test_changing_target_invalidates_result_but_keeps_editor(self):
        w = workspace()
        w.sync(ready=True, has_result=True); w.show_results()
        w.sync(ready=True, has_result=False)
        self.assertEqual(w.steps.current, 0)
        self.assertEqual(w.steps.states, ['normal', 'disabled'])

    def test_changing_references_returns_to_reference_form(self):
        w = workspace()
        w.sync(ready=True, has_result=True); w.show_results()
        w.sync(ready=False, has_result=False)
        self.assertEqual(w.steps.current, 0)
        self.assertEqual(w.steps.states, ['normal', 'disabled'])


class ManualFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tcl = tk.Tcl()
        cls.database = load_database(APP/'data/sinapi_completa.json.gz')

    def variable(self, value=''):
        return tk.StringVar(self.tcl, value=value)

    def panel(self, generic):
        p = object.__new__(GenericManualTrendTab if generic else SinapiManualTrendTab)
        p.app = Mock(working=False)
        p.db, p.refs, p.series, p.editor_rows = self.database, [], [], []
        p._building, p._loading, p.dirty, p.result = False, False, True, None
        p.workspace = workspace()
        p.source = self.variable()
        p.bank = self.variable('ORSE')
        p.period = self.variable('07/26')
        for variable in (p.bank, p.period):
            variable.trace_add('write', p.clear_output)
        p.service_unit = self.variable('UN')
        p.extrapolate = tk.BooleanVar(self.tcl, False)
        p.agreed = tk.BooleanVar(self.tcl, True)
        p.units = [self.variable('MM')] if generic else [self.variable('MM') for _ in range(3)]
        p.targets = [self.variable('30')] if generic else [self.variable('28'), self.variable(), self.variable()]
        p.target_entries = [Mock() for _ in p.targets]
        p.target_labels = [Mock() for _ in p.targets]
        for name in ('output', 'memo', 'calc', 'method', 'source_box', 'editor_hint', 'ref_status',
                     'copy_values_button', 'copy_table_button', 'copy_button', 'export_button',
                     'copy_justification_button', 'edit_summary', 'add_item_button', 'paste_button',
                     'descriptions_button', 'prepare_button', 'add_parameter_button',
                     'remove_parameter_button', 'plus'):
            setattr(p, name, Mock())
        p.output.get_children.return_value = ()
        p.output.selection.return_value = ()
        p.render_editor = Mock()
        p.next_item, p.next_ref_id = 1, 2
        if generic:
            p.parameter_count = 1
            p.ref_rows = [dict(id=i, code=self.variable(f'R{i}'), params=[self.variable(str(d))])
                          for i, d in ((1, 20), (2, 40))]
        else:
            p.mode = self.variable('sinapi')
            p.loaded_meta = None
            p.layout_references = Mock()
            p.ref_rows = [dict(id=i, code=self.variable(c),
                dims=[self.variable(str(d)), self.variable(), self.variable()])
                for i, (c, d) in enumerate((('104318', 20), ('89867', 25), ('104320', 32)), 1)]
        return p

    def test_generic_prepare_calculate_copy_and_return_without_losing_data(self):
        p = self.panel(True)
        p.prepare()
        self.assertEqual(p.workspace.steps.current, 0)
        p.series = [{'description': 'Recurso', 'unit': 'H', 'coefficients': ['1', '3']}]
        p.run()
        self.assertEqual(p.workspace.steps.current, 1)
        self.assertEqual(p.result['rows'][0]['coefficient'], 2)
        p.copy_numbers()
        p.app.clipboard_append.assert_called_with('2')
        p.workspace.show_editor()
        self.assertEqual(p.targets[0].get(), '30')
        self.assertEqual(p.series[0]['coefficients'], ['1', '3'])
        self.assertEqual(p.result['rows'][0]['coefficient'], 2)

    def test_sinapi_prepare_calculate_and_all_actions_enabled(self):
        p = self.panel(False)
        p.prepare()
        self.assertEqual(p.workspace.steps.current, 0)
        p.agreed.set(True)
        p.run()
        self.assertEqual(p.workspace.steps.current, 1)
        self.assertTrue(p.result['rows'])
        for button in (p.copy_values_button, p.copy_table_button, p.copy_button, p.export_button):
            button.configure.assert_called_with(state='normal')
        p.copy_numbers()
        self.assertEqual(len(p.app.clipboard_append.call_args.args[0].splitlines()), len(p.result['rows']))

    def test_generic_bank_and_period_reach_clipboard_and_changes_invalidate_result(self):
        p = self.panel(True)
        p.prepare()
        p.series = [{'description': '', 'unit': 'H', 'coefficients': ['0,1', '0,3']}]
        p.run()
        p.copy_justification()
        text = p.app.clipboard_append.call_args.args[0]
        self.assertTrue(text.startswith('Banco: ORSE. Data do banco: 07/26.'))
        p.bank.set('SEINFRA')
        self.assertIsNone(p.result)
        self.assertFalse(p.dirty)
        self.assertEqual(p.series[0]['coefficients'], ['0,1', '0,3'])
        p.period.set('09/2026')
        p.run()
        self.assertTrue(p.result['justification'].startswith('Banco: SEINFRA. Data do banco: 09/2026.'))

    def test_generic_fraction_inputs_calculate_and_copy_without_retyping_decimals(self):
        p = self.panel(True)
        p.units[0].set('POL')
        for row, value in zip(p.ref_rows, ('1/2', '1')):
            row['params'][0].set(value)
        p.targets[0].set('3/4')
        with patch('calculadoras_extras.messagebox.showinfo') as alert:
            p.prepare()
            p.series = [{'description': '', 'unit': 'H', 'coefficients': ['0,1', '0,3']}]
            p.run()
        alert.assert_not_called()
        self.assertEqual(p.workspace.steps.current, 1)
        self.assertAlmostEqual(p.result['rows'][0]['coefficient'], .2)
        p.copy_numbers()
        p.app.clipboard_append.assert_called_with('0,2')
        p.copy_justification()
        self.assertIn('3/4"', p.app.clipboard_append.call_args.args[0])
        self.assertIn('1/2"', p.app.text_into.call_args.args[1])
        self.assertEqual(p.targets[0].get(), '3/4')
        self.assertEqual(p.ref_rows[0]['params'][0].get(), '1/2')

    def test_sinapi_fraction_inputs_load_actual_compositions_and_calculate(self):
        p = self.panel(False)
        p.units[0].set('POL')
        p.ref_rows = [dict(id=i, code=self.variable(code),
                          dims=[self.variable(d), self.variable(), self.variable()])
                      for i, (code, d) in enumerate((('106044', '1 1/8'), ('106045', '1 5/8')))]
        p.targets[0].set('1 1/2')
        with patch('calculadoras_extras.messagebox.showinfo') as alert:
            p.prepare()
            p.agreed.set(True)
            p.run()
        alert.assert_not_called()
        self.assertEqual(p.workspace.steps.current, 1)
        self.assertTrue(p.result['rows'])
        self.assertEqual(p.result['target_dimension_text'], '1 1/2"')
        p.copy()
        self.assertIn('1 1/2"', p.app.clipboard_append.call_args.args[0])
        self.assertEqual(p.targets[0].get(), '1 1/2')

    def test_invalid_calculation_stays_in_editor_and_does_not_show_old_result(self):
        p = self.panel(True)
        p.prepare()
        with patch('calculadoras_extras.messagebox.showinfo') as alert:
            p.run()  # coeficientes ainda vazios
        alert.assert_called_once()
        self.assertIsNone(p.result)
        self.assertEqual(p.workspace.steps.current, 0)
        self.assertEqual(p.workspace.steps.states[1], 'disabled')

    def test_reference_changes_disable_old_results_and_copy_actions(self):
        for generic in (True, False):
            with self.subTest(generic=generic):
                p = self.panel(generic)
                p.prepare()
                if generic:
                    p.series = [{'description': '', 'unit': '', 'coefficients': ['1', '3']}]
                else:
                    p.agreed.set(True)
                p.run()
                p.references_changed()
                self.assertTrue(p.dirty)
                self.assertIsNone(p.result)
                self.assertEqual(p.workspace.steps.current, 0)
                p.copy_values_button.configure.assert_called_with(state='disabled')
                p.output._selectable_cell_close.assert_called()


if __name__ == '__main__':
    unittest.main()
