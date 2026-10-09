"""Regressão: frações de polegada nas referências e nos alvos manuais."""
import math
import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from coeficientes_core import AnalysisError, dimension_number
from tendencia_manual_core import (
    calculate_generic_parameter_trend, calculate_manual_trend, reference_rows,
)


def generic_refs(values):
    return [dict(code=f'R{i+1}', parameters=v if isinstance(v, list) else [v],
                 coefficients=[c, 2*c])
            for i, (v, c) in enumerate(zip(values, (0.1, 0.3, 0.7)))]


class FractionalDimensionTests(unittest.TestCase):
    def test_fraction_notations_have_correct_numeric_value(self):
        cases = {'3/4': .75, '3 / 4': .75, '3⁄4': .75, '¾': .75,
                 '1 1/2': 1.5, '1½': 1.5, '1\u00a01/2': 1.5,
                 '1-1/2': 1.5, '1.1/2': 1.5, '2 1/2 pol': 2.5,
                 '3/4"': .75, '3/4″': .75, '3/4”': .75,
                 '3/4 POLEGADAS': .75, '0,75': .75, '40 mm': 40,
                 '1.000,5': 1000.5, '-1 1/2': -1.5}
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(dimension_number(raw), expected)

    def test_invalid_fractions_are_not_silently_interpreted(self):
        for raw in ('3/0', '1/2/3', 'abc', '', None, True, 'nan', 'inf', '1 2 3/4'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                dimension_number(raw)

    def test_generic_two_references_and_target_accept_fractions(self):
        result = calculate_generic_parameter_trend(generic_refs(['1/2', '1']), '3/4',
                                                   parameter_units=['POL'])
        self.assertEqual(result['target_parameters'], [.75])
        self.assertAlmostEqual(result['coefficients'][0], .2)
        self.assertAlmostEqual(result['coefficients'][1], .4)
        self.assertEqual(result['method'], 'Interpolação linear')
        for text in ('R1 (1/2")', 'R2 (1")', '3/4"'):
            self.assertIn(text, result['justification'])

    def test_generic_three_references_match_decimal_pchip(self):
        fractional = calculate_generic_parameter_trend(
            generic_refs(['1/2', '1', '1 1/2']), '1 1/4', parameter_units='POL')
        decimal = calculate_generic_parameter_trend(generic_refs([.5, 1, 1.5]), 1.25)
        self.assertEqual(fractional['method'], 'Interpolação PCHIP')
        self.assertEqual(fractional['coefficients'], decimal['coefficients'])
        self.assertIn('1 1/2"', fractional['justification'])
        self.assertIn('1 1/4"', fractional['justification'])

    def test_generic_three_parameters_match_decimal_rms(self):
        fractional = calculate_generic_parameter_trend(
            generic_refs([['1/2', '1/2', '1/4'], ['1', '1', '1/2']]),
            ['3/4', '3/4', '3/8'], parameter_units=['POL']*3)
        decimal = calculate_generic_parameter_trend(
            generic_refs([[.5, .5, .25], [1, 1, .5]]), [.75, .75, .375])
        self.assertEqual(fractional['coefficients'], decimal['coefficients'])
        self.assertIn('3/4" × 3/4" × 3/8"', fractional['justification'])

    def test_generic_units_check_suffix_without_converting_existing_axis(self):
        refs = generic_refs([['25', '1/2'], ['50', '1']])
        result = calculate_generic_parameter_trend(refs, ['40', '3/4″'],
                                                   parameter_units=['MM', 'POL'])
        self.assertAlmostEqual(result['target_parameter'], math.hypot(40, .75)/math.sqrt(2))
        with self.assertRaisesRegex(AnalysisError, 'coluna está em MM'):
            calculate_generic_parameter_trend(generic_refs(['1/2', '1']), '3/4"',
                                              parameter_units=['MM'])

    def test_generic_invalid_reference_and_target_are_rejected(self):
        for value in ('3/0', 'x/y', '', '-1 1/2', '0/4'):
            with self.subTest(value=value, field='target'), self.assertRaises(AnalysisError):
                calculate_generic_parameter_trend(generic_refs(['1/2', '1']), value)
            with self.subTest(value=value, field='reference'), self.assertRaises(AnalysisError):
                calculate_generic_parameter_trend(generic_refs([value, '1']), '3/4')

    def test_fractions_are_dimensions_not_coefficient_values(self):
        refs = generic_refs(['1/2', '1'])
        refs[0]['coefficients'][0] = '1/2'
        with self.assertRaisesRegex(AnalysisError, 'coeficiente 1 inválido'):
            calculate_generic_parameter_trend(refs, '3/4')

    def test_sinapi_fraction_references_and_target_with_optional_dims(self):
        refs = reference_rows([{'code': 'R1', 'dims': ['1/2"', '', '']},
                               {'code': 'R2', 'dims': ['1″', '', '']}], ['POL', 'MM', 'MM'])
        result = calculate_manual_trend(refs, [{'coefficients': [.1, .3]}], ['3 / 4″', '', ''])
        self.assertEqual(result['target_dims'], [.75])
        self.assertAlmostEqual(result['rows'][0]['coefficient'], .2)
        self.assertEqual(result['target_dimension_text'], '3/4"')

    def test_sinapi_mixed_fraction_pchip_matches_decimal(self):
        refs = reference_rows([{'code': f'R{i}', 'dims': [d]} for i, d in
                               enumerate(('1/2', '1', '1½'))], 'POL')
        series = [{'coefficients': [.1, .3, .7]}]
        result = calculate_manual_trend(refs, series, '1 1/4')
        decimal = calculate_manual_trend(refs, series, 1.25)
        self.assertEqual(result['rows'][0]['coefficient'], decimal['rows'][0]['coefficient'])
        self.assertIn('PCHIP', result['method'])
        self.assertEqual(result['target_dimension_text'], '1 1/4"')

    def test_sinapi_invalid_fraction_and_wrong_units_are_rejected(self):
        for value in ('3/0', '-1 1/2', '0/4', ''):
            with self.subTest(value=value), self.assertRaises(AnalysisError):
                reference_rows([{'code': 'A', 'dims': [value]},
                                {'code': 'B', 'dims': ['1']}], 'POL')
        with self.assertRaisesRegex(AnalysisError, 'coluna está em MM'):
            reference_rows([{'code': 'A', 'dims': ['3/4″']},
                            {'code': 'B', 'dims': ['1']}], 'MM')


if __name__ == '__main__':
    unittest.main()
