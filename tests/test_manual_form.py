import copy
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from coeficientes_core import AnalysisError, build_families, calculate, export_report, load_database, measures
from tendencia_manual_core import (calculate_generic_parameter_trend, calculate_manual_trend, clipboard_coefficients,
    coefficient_text, reference_rows, remap_coefficients, result_clipboard, series_from_sinapi)


def refs_with(dims, units='MM', manual=False):
    return reference_rows([{'code': f'R{i+1}', 'dims': d, 'row_id': i+1} for i, d in enumerate(dims)], units, manual)


class ManualFormCoreTests(unittest.TestCase):
    def test_only_dimension_one_and_empty_optional_fields(self):
        refs = refs_with([['10', '', ''], ['20', '', '']])
        result = calculate_manual_trend(refs, [{'coefficients': [1, 3]}], ['15', '', ''])
        self.assertEqual(result['target_dims'], [15])
        self.assertEqual(result['rows'][0]['coefficient'], 2)
        self.assertEqual(result['rows'][0]['description'], 'Item 1')

    def test_two_dimensional_rms_by_independent_calculation(self):
        refs = refs_with([[20, 10, ''], [40, 30, '']])
        result = calculate_manual_trend(refs, [{'coefficients': [1, 3]}], [30, 20, ''])
        x1, x2, xt = [math.sqrt((a*a+b*b)/2) for a, b in ((20, 10), (40, 30), (30, 20))]
        self.assertAlmostEqual(result['rows'][0]['coefficient'], 1+2*(xt-x1)/(x2-x1))
        self.assertEqual(result['family']['dimension_count'], 2)
        self.assertIn('RMS', result['justification'])

    def test_three_dimensions_all_affect_result(self):
        refs = refs_with([[32, 32, 25], [50, 50, 32], [75, 75, 50]])
        rows = [{'coefficients': [.1, .3, .8]}]
        a = calculate_manual_trend(refs, rows, [60, 60, 40])
        b = calculate_manual_trend(refs, rows, [60, 60, 45])
        self.assertNotEqual(a['rows'][0]['coefficient'], b['rows'][0]['coefficient'])
        self.assertIn('60 MM × 60 MM × 40 MM', a['target_dimension_text'])
        self.assertIn('PCHIP', a['method'])

    def test_two_three_four_five_references_supported_six_rejected(self):
        for n in range(2, 6):
            with self.subTest(n=n):
                refs = refs_with([[10*(i+1)] for i in range(n)])
                result = calculate_manual_trend(refs, [{'coefficients': [i+1 for i in range(n)]}], 15)
                self.assertAlmostEqual(result['rows'][0]['coefficient'], 1.5)
        with self.assertRaises(AnalysisError):
            refs_with([[10*(i+1)] for i in range(6)])

    def test_optional_reference_codes_in_full_manual_mode(self):
        refs = reference_rows([{'dims': [10, '', '']}, {'dims': [20, '', '']}], manual=True)
        self.assertEqual([r['code'] for r in refs], ['REF_1', 'REF_2'])
        result = calculate_manual_trend(refs, [{'coefficients': [1, 3]}, {'coefficients': [0, 0]}], 15)
        self.assertEqual([r['description'] for r in result['rows']], ['Item 1', 'Item 2'])
        self.assertEqual(result_clipboard(result), '2\r\n0')

    def test_sinapi_mode_requires_codes_but_ignores_empty_extra_row(self):
        with self.assertRaises(AnalysisError):
            reference_rows([{'dims': [10]}, {'code': 'A', 'dims': [20]}])
        rows = [{'code': 'A', 'dims': [10]}, {'code': 'B', 'dims': [20]}, {'code': '', 'dims': ['', '', '']}]
        self.assertEqual(len(reference_rows(rows)), 2)

    def test_optional_dimensions_not_silently_inferred(self):
        for dims in ([[10], [20, 20]], [[10, '', 10], [20, 20, 20]], [['', 10], [20, 20]]):
            with self.subTest(dims=dims), self.assertRaises(AnalysisError):
                refs_with(dims)

    def test_units_mixed_length_convert_rms_and_fraction_display(self):
        refs = refs_with([[25, '1/2'], [50, '1']], ['MM', 'POL'])
        self.assertAlmostEqual(refs[0]['x'], math.hypot(25, 12.7)/math.sqrt(2))
        result = calculate_manual_trend(refs, [{'coefficients': [1, 3]}], [40, '3/4'])
        self.assertEqual(result['target_dimension_text'], '40 MM × 3/4"')
        with self.assertRaises(AnalysisError):
            refs_with([[10, 20], [20, 30]], ['M2', 'MM'])
        with self.assertRaises(AnalysisError):
            refs_with([['1 pol'], ['2 pol']], 'MM')

    def test_same_rms_different_geometry_does_not_claim_exact_reference(self):
        refs = refs_with([[3, 4], [6, 8]])
        result = calculate_manual_trend(refs, [{'coefficients': [1, 2]}], [4, 3])
        self.assertIsNone(result['target_reference'])
        self.assertEqual(result['rows'][0]['coefficient'], 1)
        self.assertIn('geometria diferente', ' '.join(result['warnings']))
        with self.assertRaises(AnalysisError):
            refs_with([[3, 4], [4, 3]])

    def test_target_dimension_count_must_match_reference(self):
        refs = refs_with([[10], [20]])
        with self.assertRaises(AnalysisError):
            calculate_manual_trend(refs, [{'coefficients': [1, 2]}], ['15 mm', '20 mm', ''])

    def test_paste_numeric_excel_matrix_zero_decimal_and_fractions_not_coefficients(self):
        matrix = clipboard_coefficients('0,15\t0,3\t0,5\r\n0\t1\t1\r\n', 3)
        self.assertEqual(matrix, [[.15, .3, .5], [0, 1, 1]])
        for text in ('a\tb', '1\t', '1\t2\t3', '-1\t2', '1/2\t2'):
            with self.subTest(text=text), self.assertRaises(AnalysisError):
                clipboard_coefficients(text, 2)

    def test_reference_add_remove_preserves_associated_manual_values(self):
        old = refs_with([[10], [20], [30]])
        new = [old[0], old[2], {'row_id': 4, 'code': 'R4', 'dims': [40], 'units': ['MM'], 'x': 40}]
        values = remap_coefficients([{'coefficients': ['1', '2', '3']}], old, new)
        self.assertEqual(values[0]['coefficients'], ['1', '3', ''])

    def test_copy_table_selected_values_and_small_number_precision(self):
        refs = refs_with([[10], [20]])
        result = calculate_manual_trend(refs, [{'coefficients': [0, 0]}, {'coefficients': [1e-14, 1e-14]}], 15)
        self.assertEqual(result_clipboard(result, indices=[0]), '0')
        self.assertEqual(coefficient_text(1e-14), '0,00000000000001')
        table = result_clipboard(result, table=True)
        self.assertEqual(len(table.splitlines()), 3)
        self.assertIn('Novo coeficiente', table.splitlines()[0])

    def test_copy_partial_does_not_drop_rows_or_insert_zero(self):
        refs = refs_with([[10], [20]])
        result = calculate_manual_trend(refs, [{'coefficients': [3, 1]}, {'coefficients': [2, 2]}], 40,
                                        allow_extrapolation=True)
        with self.assertRaises(AnalysisError):
            result_clipboard(result)
        table = result_clipboard(result, table=True).splitlines()
        self.assertEqual(len(table), 3)
        self.assertEqual(table[1].split('\t')[5], '')
        self.assertIn('não estimado', table[1])
        self.assertEqual(result_clipboard(result, indices=[1]), '2')

    def test_copy_table_escapes_formula_like_label(self):
        refs = refs_with([[10], [20]])
        result = calculate_manual_trend(refs, [{'description': '=1+1', 'coefficients': [1, 2]}], 15)
        self.assertIn("'=1+1", result_clipboard(result, table=True))

    def test_export_preserves_three_dimensions_and_anonymous_items(self):
        from openpyxl import load_workbook
        refs = refs_with([[32, 32, 25], [50, 50, 32]])
        result = calculate_manual_trend(refs, [{'coefficients': [.1, .3]}], [40, 40, 30])
        with tempfile.TemporaryDirectory() as directory:
            book = load_workbook(export_report(result, Path(directory)/'manual.xlsx'))
            self.assertIn('32 MM × 32 MM × 25 MM', book['Composições de referência']['B2'].value)
            self.assertEqual(book['Composições de referência']['C2'].value, 3)
            self.assertEqual(book['Coeficientes']['C2'].value, 'Item 1')
            book.close()


class GenericParameterTrendTests(unittest.TestCase):
    def test_two_references_interpolate_each_coefficient_independently(self):
        refs = [
            {'code': 'BANCO-A-01', 'parameter': '20', 'coefficients': ['1', '10', '0,5']},
            {'code': 'BANCO-A-02', 'parameter': '40', 'coefficients': ['3', '14', '1,5']},
        ]
        result = calculate_generic_parameter_trend(refs, '30')
        self.assertEqual(result['method'], 'Interpolação linear')
        self.assertEqual(result['coefficients'], [2.0, 12.0, 1.0])
        self.assertIn('Técnica: Interpolação linear por coeficiente', result['justification'])

    def test_three_references_use_pchip_for_every_coefficient(self):
        refs = [
            {'code': 'R1', 'parameter': 10, 'coefficients': [1, 10, 100]},
            {'code': 'R2', 'parameter': 20, 'coefficients': [2, 20, 200]},
            {'code': 'R3', 'parameter': 30, 'coefficients': [4, 40, 400]},
        ]
        result = calculate_generic_parameter_trend(refs, 25)
        self.assertEqual(result['method'], 'Interpolação PCHIP')
        self.assertEqual(len(result['coefficients']), 3)
        self.assertIn('PCHIP', result['justification'])

    def test_more_than_three_coefficients_are_supported(self):
        refs = [
            {'code': 'R1', 'parameter': 10, 'coefficients': [1, 2, 3, 4, 5]},
            {'code': 'R2', 'parameter': 20, 'coefficients': [2, 4, 6, 8, 10]},
        ]
        result = calculate_generic_parameter_trend(refs, 15)
        self.assertEqual(result['coefficients'], [1.5, 3.0, 4.5, 6.0, 7.5])

    def test_extrapolation_requires_explicit_permission(self):
        refs = [
            {'code': 'R1', 'parameter': 20, 'coefficients': [2]},
            {'code': 'R2', 'parameter': 40, 'coefficients': [4]},
        ]
        with self.assertRaises(AnalysisError):
            calculate_generic_parameter_trend(refs, 10)
        result = calculate_generic_parameter_trend(refs, 10, allow_extrapolation=True)
        self.assertEqual(result['method'], 'Extrapolação linear')
        self.assertAlmostEqual(result['coefficients'][0], 1.0)

    def test_multiple_parameters_use_rms_and_each_coefficient_remains_independent(self):
        refs = [
            {'code': 'R1', 'parameters': [20, 20], 'coefficients': [1, 10, 100]},
            {'code': 'R2', 'parameters': [40, 40], 'coefficients': [3, 14, 200]},
        ]
        result = calculate_generic_parameter_trend(refs, [30, 30])
        self.assertEqual(result['parameter_count'], 2)
        self.assertAlmostEqual(result['target_parameter'], 30.0)
        self.assertEqual(result['coefficients'], [2.0, 12.0, 150.0])
        self.assertIn('índice RMS', result['justification'])
        self.assertIn('30 × 30', result['justification'])

    def test_three_parameters_support_reducing_tee_geometry(self):
        refs = [
            {'code': 'TEE-A', 'parameters': [25, 25, 20], 'coefficients': [0.10, 0.20]},
            {'code': 'TEE-B', 'parameters': [50, 50, 32], 'coefficients': [0.30, 0.50]},
            {'code': 'TEE-C', 'parameters': [75, 75, 50], 'coefficients': [0.60, 0.80]},
        ]
        result = calculate_generic_parameter_trend(refs, [40, 40, 25])
        self.assertEqual(result['parameter_count'], 3)
        self.assertEqual(result['method'], 'Interpolação PCHIP')
        self.assertEqual(len(result['coefficients']), 2)

    def test_multiple_parameter_count_must_match(self):
        refs = [
            {'code': 'R1', 'parameters': [20, 20], 'coefficients': [1]},
            {'code': 'R2', 'parameters': [40], 'coefficients': [2]},
        ]
        with self.assertRaises(AnalysisError):
            calculate_generic_parameter_trend(refs, [30, 30])

    def test_arbitrary_parameter_count_is_supported(self):
        # A interface pode crescer além de três dimensões; o núcleo não impõe teto.
        refs = [
            {'code': 'R1', 'parameters': [10, 20, 30, 40, 50, 60, 70], 'coefficients': [1, 10]},
            {'code': 'R2', 'parameters': [20, 40, 60, 80, 100, 120, 140], 'coefficients': [3, 30]},
        ]
        target = [15, 30, 45, 60, 75, 90, 105]
        result = calculate_generic_parameter_trend(refs, target)
        self.assertEqual(result['parameter_count'], 7)
        self.assertAlmostEqual(result['coefficients'][0], 2.0)
        self.assertAlmostEqual(result['coefficients'][1], 20.0)


class ManualSINAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = load_database(APP/'data/sinapi_base.json.gz')
        cls.full = load_database(APP/'data/sinapi_completa.json.gz')

    def test_three_dimensional_tee_matches_existing_calculator(self):
        family = next(f for f in build_families(self.db) if any(r['code']=='89624' for r in f['refs']))
        chosen = family['refs'][:5]
        refs = reference_rows([{'code': r['code'], 'dims': r['dims']} for r in chosen])
        series, unit, _ = series_from_sinapi(self.full, refs)
        target = [42, 42, 35]
        manual_result = calculate_manual_trend(refs, series, target, service_unit=unit)
        short_family = {**family, 'refs': chosen}
        automatic = calculate(self.db, short_family, chosen[0]['code'], target)
        for a, b in zip(manual_result['rows'], automatic['rows']):
            self.assertEqual(a['source_resource'], b['source_resource'])
            self.assertAlmostEqual(a['coefficient'], b['coefficient'], places=11)

    def test_selected_source_order_controls_copy_order(self):
        db = copy.deepcopy(self.full)
        db['compositions']['94463']['components'].reverse()
        refs = reference_rows([{'code':'94462','dims':[50]}, {'code':'94463','dims':[65]}])
        series, unit, _ = series_from_sinapi(db, refs)
        result = calculate_manual_trend(refs, series, 60, source_code='94463', service_unit=unit)
        self.assertEqual([r['source_resource'] for r in result['rows']],
                         [r['code'] for r in db['compositions']['94463']['components']])
        self.assertEqual(result_clipboard(result).splitlines(),
                         [coefficient_text(r['coefficient']) for r in result['rows']])


class ManualUIFlowTests(unittest.TestCase):
    """Exercita ações reais com variáveis Tcl, sem depender de um display."""
    def panel(self, mode='manual'):
        import tkinter as tk
        from calculadoras_extras import SinapiManualTrendTab
        self.tcl = tk.Tcl()
        p = object.__new__(SinapiManualTrendTab)
        p.app = Mock(working=False)
        p._building, p._loading, p.dirty = False, False, True
        p.db = None
        p.refs, p.series, p.loaded_meta, p.editor_rows = [], [], None, []
        p.next_item = 1
        p.mode = tk.StringVar(self.tcl, value=mode)
        p.units = [tk.StringVar(self.tcl, value='MM') for _ in range(3)]
        p.service_unit = tk.StringVar(self.tcl, value='UN')
        p.source = tk.StringVar(self.tcl)
        p.targets = [tk.StringVar(self.tcl, value='15'), tk.StringVar(self.tcl), tk.StringVar(self.tcl)]
        p.agreed = tk.BooleanVar(self.tcl, value=False)
        p.extrapolate = tk.BooleanVar(self.tcl, value=False)
        p.ref_rows = [{'id': i+1, 'code': tk.StringVar(self.tcl),
                       'dims': [tk.StringVar(self.tcl, value=str(x)), tk.StringVar(self.tcl), tk.StringVar(self.tcl)]}
                      for i, x in enumerate([10,20])]
        for name in ('source_box','ref_status','editor_hint','output','memo','copy_button','export_button',
                     'copy_values_button','copy_table_button','method'):
            setattr(p,name,Mock())
        p.output.selection.return_value=()
        p.output.get_children.return_value=()
        p.target_entries, p.target_labels = [Mock() for _ in range(3)], [Mock() for _ in range(3)]
        p.render_editor, p.state_controls = Mock(), Mock()
        p.result = None
        return p

    def test_manual_prepare_run_and_copy_without_sinapi_or_descriptions(self):
        p = self.panel()
        with patch('calculadoras_extras.series_from_sinapi', side_effect=AssertionError('Não pode consultar SINAPI')), \
             patch('calculadoras_extras.messagebox.showinfo') as warning:
            p.prepare()
            self.assertFalse(p.dirty)
            self.assertEqual([r['code'] for r in p.refs], ['REF_1','REF_2'])
            self.assertEqual(p.target_entries[1].configure.call_args.kwargs['state'], 'disabled')
            p.series=[{'coefficients':[1,3]}]
            p.agreed.set(True)
            p.run()
            self.assertEqual(p.result['rows'][0]['coefficient'], 2)
            p.copy_numbers()
            p.app.clipboard_append.assert_called_with('2')
            warning.assert_not_called()

    def test_edit_references_and_target_invalidates_copy_results(self):
        p = self.panel()
        p.result={'fake':True}
        p.references_changed()
        self.assertTrue(p.dirty)
        self.assertIsNone(p.result)
        p.copy_values_button.configure.assert_called_with(state='disabled')
        p.result={'fake':True}
        p.clear_output()
        self.assertIsNone(p.result)

    def test_prepare_after_adding_reference_retains_existing_coefficients(self):
        import tkinter as tk
        p = self.panel()
        p.prepare()
        p.series=[{'coefficients':['1','3']}]
        p.ref_rows.append({'id':3,'code':tk.StringVar(self.tcl),
            'dims':[tk.StringVar(self.tcl,value='30'),tk.StringVar(self.tcl),tk.StringVar(self.tcl)]})
        p.references_changed()
        p.prepare()
        self.assertEqual(p.series[0]['coefficients'], ['1','3',''])


if __name__ == '__main__':
    unittest.main(verbosity=2)

class ManualCodeRecognitionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.full = load_database(APP/'data/sinapi_completa.json.gz')


    def test_btu_plural_measure_is_recognized_and_canonicalized(self):
        axes = measures('AR-CONDICIONADO SPLIT DUTO, 24000 BTUS/H, CICLO QUENTE/FRIO')
        self.assertEqual(len(axes), 1)
        self.assertEqual(axes[0]['value'], 24000)
        self.assertEqual(axes[0]['unit'], 'BTU/H')

    def test_air_conditioning_codes_103280_103281_align_by_capacity(self):
        refs = reference_rows([
            {'code': '103280', 'dims': [24000]},
            {'code': '103281', 'dims': [36000]},
        ], 'BTU/H')
        series, unit, descriptions = series_from_sinapi(self.full, refs, 'BTU/H')
        self.assertEqual(unit, 'UN')
        self.assertEqual(len(descriptions), 2)
        self.assertEqual(len(series), 12)
        varying = [row for row in series if row['codes'] == ['44404', '44405']]
        self.assertEqual(len(varying), 1)
        self.assertEqual(varying[0]['coefficients'], [1.0, 1.0])


    def test_three_air_conditioning_compositions_align_without_duplicate_error(self):
        refs = reference_rows([
            {'code': '103279', 'dims': [18000]},
            {'code': '103280', 'dims': [24000]},
            {'code': '103281', 'dims': [36000]},
        ], 'BTU/H')
        series, unit, _ = series_from_sinapi(self.full, refs, 'BTU/H')
        self.assertEqual(unit, 'UN')
        self.assertEqual(len(series), 12)
        self.assertTrue(all(row.get('alignment_complete') for row in series))
        self.assertIn(['44411', '44412', '44412'], [row['codes'] for row in series])
        self.assertIn(['44409', '44410', '44410'], [row['codes'] for row in series])

    def test_pead_codes_103380_103381_align_even_with_wall_thickness_change(self):
        refs = reference_rows([
            {'code': '103380', 'dims': [225]},
            {'code': '103381', 'dims': [250]},
        ], 'MM')
        series, unit, _ = series_from_sinapi(self.full, refs, 'MM')
        self.assertEqual(unit, 'M')
        self.assertEqual(len(series), 3)
        self.assertTrue(all(row.get('alignment_complete') for row in series))
        tube = next(row for row in series if row['codes'] == ['44433', '44434'])
        self.assertEqual(tube['coefficients'], [1.0, 1.0])

    def test_code_formats_resolve_to_same_sinapi_composition(self):
        refs = reference_rows([
            {'code': "'94462", 'dims': [50]},
            {'code': '94463.0', 'dims': [65]},
        ])
        series, unit, descriptions = series_from_sinapi(self.full, refs, 'MM')
        self.assertTrue(series)
        self.assertEqual(len(descriptions), 2)
        self.assertTrue(unit)

class TestManualJustificationV154(unittest.TestCase):
    def _series(self):
        return [{
            'description': 'Mão de obra', 'unit': 'H',
            'coefficients': [3.0709, 3.2942],
            'codes': ['100308', '100308'],
            'rows': ['1', '1'],
            'descriptions': ['MECÂNICO', 'MECÂNICO'],
            'orders': [0, 0],
        }]

    def test_justification_explains_two_point_method_without_review_wording(self):
        refs = [
            {'code': '103280', 'dims': [24000], 'units': ['BTU'], 'description': '24k'},
            {'code': '103281', 'dims': [36000], 'units': ['BTU'], 'description': '36k'},
        ]
        result = calculate_manual_trend(refs, self._series(), [18000], source_code='103280',
                                        dimension_unit='BTU', allow_extrapolation=True)
        text = result['justification'].lower()
        self.assertIn('técnica: extrapolação linear', text)
        self.assertNotIn('fator de correção', text)
        self.assertIn('extrapolação', text)
        self.assertNotIn('revis', text)
        self.assertNotIn('obrigat', text)

    def test_exact_point_justification_has_no_review_wording(self):
        refs = [
            {'code': '103280', 'dims': [24000], 'units': ['BTU'], 'description': '24k'},
            {'code': '103281', 'dims': [36000], 'units': ['BTU'], 'description': '36k'},
        ]
        result = calculate_manual_trend(refs, self._series(), [24000], source_code='103280',
                                        dimension_unit='BTU')
        text = result['justification'].lower()
        self.assertIn('técnica: consulta ao ponto informado', text)
        self.assertNotIn('revis', text)
        self.assertNotIn('obrigat', text)
