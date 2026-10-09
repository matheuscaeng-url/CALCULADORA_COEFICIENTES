import copy
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from coeficientes_core import AnalysisError, build_families, export_report, load_database
from regra_tres_core import (calculate_generic_rule_of_three, calculate_rule_of_three, default_scaled_indices,
    proportional_factor, single_reference_families)
from tendencia_manual_core import (calculate_manual_trend, dimension_text,
    parse_references, series_from_sinapi)


def manual(values=(1, 3), xs=(10, 20), target=15, **kwargs):
    refs = [{'code': chr(65+i), 'x': x} for i, x in enumerate(xs)]
    rows = [{'description': 'Mão de obra', 'unit': 'H', 'coefficients': list(values)}]
    return calculate_manual_trend(refs, rows, target, **kwargs)


class ManualTests(unittest.TestCase):
    def test_two_points_linear_with_intercept_not_rule_three(self):
        result = manual()
        self.assertAlmostEqual(result['rows'][0]['coefficient'], 2)
        self.assertNotAlmostEqual(result['rows'][0]['coefficient'], 1.5)
        self.assertIn('linear', result['method'])
        self.assertIn('2 referências', ' '.join(result['warnings']))

    def test_three_points_pchip_against_independent_scipy(self):
        try:
            from scipy.interpolate import PchipInterpolator
        except ImportError:
            self.skipTest('SciPy usada somente para verificação independente')
        result = manual((1, 1.2, 3), (10, 20, 40), 25)
        self.assertAlmostEqual(result['rows'][0]['coefficient'],
                               float(PchipInterpolator([10, 20, 40], [1, 1.2, 3])(25)), places=12)
        self.assertIn('PCHIP', result['method'])
        self.assertEqual(result['rows'][0]['validation']['n'], 0)

    def test_unsorted_references_keep_coefficients_and_selected_source(self):
        a = manual((3, 1, 1.2), (40, 10, 20), 25, source_code='C')
        b = manual((1, 1.2, 3), (10, 20, 40), 25)
        self.assertEqual(a['rows'][0]['source_coefficient'], 1.2)
        self.assertAlmostEqual(a['rows'][0]['coefficient'], b['rows'][0]['coefficient'])
        self.assertIn('origem na referência C', a['justification'])
        self.assertIn('B (10 MM), C (20 MM), A (40 MM)', a['justification'])

    def test_four_points_have_internal_validation(self):
        result = manual((1, 2, 4, 8), (10, 20, 40, 80), 30)
        self.assertEqual(result['rows'][0]['validation']['n'], 2)

    def test_each_resource_has_own_curve(self):
        refs = parse_references('A;10\nB;20')
        rows = [{'description': 'A', 'unit': 'H', 'coefficients': [1, 3]},
                {'description': 'B', 'unit': 'UN', 'coefficients': [1, 1]}]
        result = calculate_manual_trend(refs, rows, 15)
        self.assertEqual([row['coefficient'] for row in result['rows']], [2, 1])

    def test_exact_point_is_not_new_official_code(self):
        result = manual(target=20)
        self.assertEqual(result['rows'][0]['coefficient'], 3)
        self.assertEqual(result['target_reference'], 'B')
        self.assertIsNone(result['target_code'])

    def test_extrapolation_requires_opt_in_no_percent_cap(self):
        with self.assertRaises(AnalysisError):
            manual(target=50)
        result = manual(target=50, allow_extrapolation=True)
        self.assertAlmostEqual(result['rows'][0]['coefficient'], 9)
        self.assertIn('extrapolação', result['mode'])

    def test_negative_prediction_is_partial_not_zero(self):
        result = manual((3, 1), (10, 20), 40, allow_extrapolation=True)
        self.assertIsNone(result['rows'][0]['coefficient'])
        self.assertIn('parcial', ' '.join(result['warnings']))

    def test_missing_negative_nan_infinite_coefficients_rejected(self):
        for value in ('', None, -1, float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                manual((value, 3))

    def test_zero_coefficient_is_valid(self):
        result = manual((0, 0))
        self.assertEqual(result['rows'][0]['coefficient'], 0)
        self.assertIsNone(result['rows'][0]['change_pct'])

    def test_parse_references_rejects_duplicates_invalid_and_one(self):
        for text in ('A;1', 'A;1\nA;2', 'A;1\nB;1', 'A;nan\nB;2',
                     'A;0\nB;2', 'A;-1\nB;2', 'A;1/0\nB;2', ';1\nB;2', 'A;1;2\nB;2'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_references(text)

    def test_fractional_inches_and_decimal_comma(self):
        refs = parse_references('A;1 1/4\nB;1,5')
        self.assertEqual([ref['x'] for ref in refs], [1.25, 1.5])
        self.assertEqual(dimension_text(1.25, 'POL'), '1 1/4"')
        result = calculate_manual_trend(refs, [{'description': 'Teste', 'unit': 'H', 'coefficients': [1, 2]}],
                                        '1 3/8', dimension_unit='POL')
        self.assertEqual(result['target_dimension_text'], '1 3/8"')

    def test_invalid_source_and_incomplete_series_rejected(self):
        with self.assertRaises(AnalysisError):
            manual(source_code='C')
        with self.assertRaises(AnalysisError):
            manual((1,))
        with self.assertRaises(AnalysisError):
            manual(dimension_unit='')

    def test_manual_report_has_references_no_official_claim_formula_safety(self):
        from openpyxl import load_workbook
        result = manual()
        result['rows'][0]['description'] = '=FORMULA()'
        with tempfile.TemporaryDirectory() as folder:
            path = export_report(result, Path(folder) / 'manual.xlsx')
            book = load_workbook(path)
            info = dict(book['Leia primeiro'].iter_rows(values_only=True))
            self.assertIn('Não atribuído', info['Código oficial da composição no alvo'])
            self.assertEqual(book['Coeficientes']['C2'].data_type, 's')
            self.assertEqual(book['Coeficientes']['H2'].value, 2)
            self.assertEqual(book['Composições de referência']['A2'].value, 'A')
            book.close()


class GenericRuleOfThreeTests(unittest.TestCase):
    def test_two_dimensions_matches_user_example(self):
        result = calculate_generic_rule_of_three([25, 20, ''], [75, 50, ''], 0.0844,
                                                 'REF-001', 'SINAPI', '08/2026')
        self.assertAlmostEqual(result['reference_sum'], 45)
        self.assertAlmostEqual(result['target_sum'], 125)
        self.assertAlmostEqual(result['coefficient'], 0.23444444444444446)
        self.assertIn('REF-001', result['justification'])
        self.assertIn('SINAPI', result['justification'])
        self.assertIn('08/2026', result['justification'])
        self.assertNotIn('revis', result['justification'].lower())

    def test_three_dimensions_matches_user_example(self):
        result = calculate_generic_rule_of_three([25, 25, 25], [32, 32, 32], 0.1395,
                                                 'ABC', 'ORSE', '09/2026')
        self.assertAlmostEqual(result['reference_sum'], 75)
        self.assertAlmostEqual(result['target_sum'], 96)
        self.assertAlmostEqual(result['coefficient'], 0.17856)

    def test_requires_same_dimension_pattern_and_metadata(self):
        with self.assertRaises(AnalysisError):
            calculate_generic_rule_of_three([25, 20, ''], [75, '', ''], 1, 'A', 'SINAPI', '08/2026')
        for code, bank, period in (('', 'SINAPI', '08/2026'), ('A', '', '08/2026'), ('A', 'SINAPI', '')):
            with self.subTest(code=code, bank=bank, period=period), self.assertRaises(AnalysisError):
                calculate_generic_rule_of_three([25, '', ''], [50, '', ''], 1, code, bank, period)


class RealNewModesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = load_database(APP / 'data' / 'sinapi_base.json.gz')
        cls.full = load_database(APP / 'data' / 'sinapi_completa.json.gz')
        cls.families = build_families(cls.db)
        cls.single = single_reference_families(cls.families)

    def family(self, code):
        return next(f for f in self.families if any(r['code'] == code for r in f['refs']))

    def test_single_reference_routing_all_materials(self):
        self.assertEqual(len(self.single), 191)
        self.assertEqual(sum(f['has_trend'] for f in self.families), 426)
        self.assertEqual(sum(f['has_trend'] for f in self.families if not f.get('cable_tray')), 418)
        self.assertIn(self.family('90734'), self.single)
        self.assertNotIn(self.family('89867'), self.single)
        self.assertEqual({r['code'] for r in self.family('89867')['refs']}, {'104318', '89867', '104320'})
        self.assertNotIn(self.family('94464'), self.single)
        self.assertTrue(all(len(f['refs']) == 1 for f in self.single))

    def test_proportional_single_reference_scales_components(self):
        family = self.family('90734')
        result = calculate_rule_of_three(self.db, family, 200)
        self.assertAlmostEqual(result['factor'], 200/150)
        for row in result['rows']:
            self.assertAlmostEqual(row['coefficient'], row['source_coefficient'] * result['factor'])
        self.assertIn('90734', result['justification'])
        self.assertIsNone(result['target_code'])

    def test_user_can_scale_every_component_or_none(self):
        family = self.family('90734')
        components = self.db['compositions']['90734']['components']
        for indices in (set(), set(range(len(components)))):
            result = calculate_rule_of_three(self.db, family, 200, indices)
            for i, row in enumerate(result['rows']):
                self.assertAlmostEqual(row['coefficient'], row['source_coefficient'] * (result['factor'] if i in indices else 1))

    def test_reference_only_rule_cannot_use_sliced_multi_reference_family(self):
        multiple = self.family('94464')
        with self.assertRaises(AnalysisError):
            calculate_rule_of_three(self.db, multiple, 100)
        forged = copy.deepcopy(multiple)
        forged['refs'] = forged['refs'][:1]
        with self.assertRaises(AnalysisError):
            calculate_rule_of_three(self.db, forged, 100)

    def test_reject_manual_family_invalid_index_and_invalid_target(self):
        family = self.family('90734')
        forged = {**family, 'manual': True}
        with self.assertRaises(AnalysisError):
            calculate_rule_of_three(self.db, forged, 200)
        with self.assertRaises(AnalysisError):
            calculate_rule_of_three(self.db, family, 200, {9999})
        for target in (0, -1, 'NaN', 'Inf', ''):
            with self.subTest(target=target), self.assertRaises(ValueError):
                calculate_rule_of_three(self.db, family, target)

    def test_same_dimension_is_consultation(self):
        result = calculate_rule_of_three(self.db, self.family('90734'), 150)
        self.assertEqual(result['target_code'], '90734')
        self.assertEqual(result['factor'], 1)
        self.assertIn('sem adaptação', result['justification'])

    def test_multiple_ports_use_explicit_rms_ratio(self):
        for n in (2, 3):
            family = next(f for f in self.single if f['dimension_count'] == n and f['unit'] == 'MM')
            origin = family['refs'][0]['dims']
            target = [d*1.5 if i == 0 else d for i, d in enumerate(origin)]
            _, _, _, _, factor = proportional_factor(family, target)
            self.assertAlmostEqual(factor, math.sqrt(sum(d*d for d in target)/sum(d*d for d in origin)))
            result = calculate_rule_of_three(self.db, family, target)
            self.assertIn('hipótese simplificadora', ' '.join(result['warnings']))

    def test_single_inches_show_fraction(self):
        family = next(f for f in self.single if f['dimension_count'] == 1 and f['unit'] == 'POL')
        result = calculate_rule_of_three(self.db, family, '1 1/2')
        self.assertEqual(result['target_dimension_text'], '1 1/2"')

    def test_missing_coefficient_stays_partial(self):
        db = copy.deepcopy(self.db)
        db['compositions']['90734']['components'][0]['coefficient'] = None
        result = calculate_rule_of_three(db, self.family('90734'), 200)
        self.assertIsNone(result['rows'][0]['coefficient'])
        self.assertIn('PARCIAL', ' '.join(result['warnings']))

    def test_rule_report_has_factors_and_no_statistical_validation_claim(self):
        from openpyxl import load_workbook
        result = calculate_rule_of_three(self.db, self.family('90734'), 200)
        with tempfile.TemporaryDirectory() as folder:
            book = load_workbook(export_report(result, Path(folder) / 'regra.xlsx'))
            info = dict(book['Leia primeiro'].iter_rows(values_only=True))
            self.assertIn('Não se aplica', info['Validação'])
            headers = [cell.value for cell in book['Coeficientes'][1]]
            self.assertIn('Fator aplicado', headers)
            self.assertIn('Aplicar fator?', headers)
            self.assertEqual(len(book.sheetnames), 5)
            book.close()

    def test_manual_dimension_selector_contains_every_composition_unit(self):
        from calculadoras_extras import available_dimension_units
        available = set(available_dimension_units(self.full))
        composition_units = {str(item.get('unit') or '').strip().upper()
                             for item in self.full['compositions'].values()
                             if str(item.get('unit') or '').strip()}
        self.assertTrue(composition_units.issubset(available))
        self.assertIn('UN', available)
        self.assertIn('CHI', available)
        self.assertIn('CHP', available)
        self.assertIn('MM2', available)
        self.assertIn('BTU/H', available)

    def test_full_base_same_reference_non_tubes_available_only_manual(self):
        self.assertEqual(self.full['meta']['sha256'], self.db['meta']['sha256'])
        self.assertEqual(len(self.full['compositions']), 10547)
        self.assertIn('91924', self.full['compositions'])
        self.assertNotIn('91924', self.db['compositions'])
        refs = parse_references('91924;1,5\n91926;2,5\n91928;4')
        series, unit, _ = series_from_sinapi(self.full, refs, 'MM2')
        result = calculate_manual_trend(refs, series, 3, dimension_unit='MM2', service_unit=unit)
        self.assertTrue(all(row['coefficient'] is not None for row in result['rows']))

    def test_incomplete_resources_load_with_blank_but_units_and_unknown_codes_are_rejected(self):
        refs = parse_references('94462;50\n94463;65')
        db = copy.deepcopy(self.full)
        db['compositions']['94463']['components'].pop()
        series, unit, _ = series_from_sinapi(db, refs, 'MM')
        self.assertEqual(unit, 'M')
        self.assertTrue(any(not row.get('alignment_complete', True) for row in series))
        self.assertTrue(any('' in row['coefficients'] for row in series))
        db['compositions']['94463']['unit'] = 'UN'
        with self.assertRaises(AnalysisError):
            series_from_sinapi(db, refs, 'MM')
        with self.assertRaises(AnalysisError):
            series_from_sinapi(self.full, parse_references('SEM_CODIGO;50\n94463;65'), 'MM')

    def test_manual_edited_values_are_marked(self):
        meta = {**self.full['meta'], 'manual_edited': True}
        self.assertIn('editada pelo usuário', ' '.join(manual(meta=meta)['warnings']))

    def test_manual_loaded_resource_descriptions_follow_selected_source_and_target(self):
        refs = parse_references('94462;50\n94463;65\n94464;80')
        series, unit, _ = series_from_sinapi(self.full, refs, 'MM')
        result = calculate_manual_trend(refs, series, 65, source_code='94464', service_unit=unit)
        row = next(row for row in result['rows'] if row['source_resource'] == '7694')
        self.assertIn('3"', row['description'])
        self.assertEqual(row['target_resource'], '7701')
        self.assertIn('2.1/2"', row['target_description'])

    def test_export_memo_callbacks_render_all_three_modes(self):
        from calculadoras_extras import OutputPanel
        results = [manual(), calculate_rule_of_three(self.db, self.family('90734'), 200)]
        for result in results:
            panel = Mock()
            panel.result = result
            OutputPanel.show_memo(panel)
            self.assertIn(result['justification'], panel.app.text_into.call_args.args[1])

    def test_filtering_full_base_and_matching_cache(self):
        from coeficientes_app import CalculatorApp
        data = CalculatorApp.tube_database(self.full)
        self.assertEqual(set(data['compositions']), set(self.db['compositions']))
        self.assertEqual(data['meta']['filtered_compositions'], 2300)
        with tempfile.TemporaryDirectory() as directory, patch('coeficientes_app.USER_DIR', Path(directory)):
            self.assertEqual(CalculatorApp.matching_full_database(self.db)['meta']['sha256'], self.db['meta']['sha256'])
            bad = copy.deepcopy(self.db)
            bad['meta']['period'] = '01/2000'
            self.assertIsNone(CalculatorApp.matching_full_database(bad))


if __name__ == '__main__':
    unittest.main(verbosity=2)
