import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

import dependencias_runtime
from justificativas import build_justification, clean_text


class JustificationTests(unittest.TestCase):
    def test_clean_text_normalizes_whitespace_and_uses_fallback(self):
        self.assertEqual(clean_text('  SINAPI\n  08/2026  '), 'SINAPI 08/2026')
        self.assertEqual(clean_text(None, 'não informado'), 'não informado')

    def test_justification_deduplicates_references_and_uses_correct_label(self):
        plural = build_justification(' SINAPI ', '08/2026', [' 100 ', '100', '200'], 'método validado.')
        self.assertIn('Códigos de referência: 100, 200.', plural)
        self.assertIn('Técnica: método validado.', plural)

        single = build_justification('', '', ['100'], 'consulta')
        self.assertIn('Banco: não informado.', single)
        self.assertIn('Data do banco: não informada.', single)
        self.assertIn('Código de referência: 100.', single)

    def test_justification_formats_and_validates_correction_factor(self):
        text = build_justification('Próprio', '10/2026', [], 'regra de três', factor=1.25)
        self.assertTrue(text.endswith('Fator de correção utilizado: 1,25.'))
        for invalid in (0, -1, float('nan'), float('inf')):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                build_justification('A', 'B', ['C'], 'T', factor=invalid)


class BundledDependenciesTests(unittest.TestCase):
    def test_configuration_adds_bundled_path_once(self):
        bundled = str(APP / 'dependencias')
        original_path = sys.path[:]
        try:
            sys.path[:] = [item for item in sys.path if item != bundled]
            dependencias_runtime.configure_dependencies()
            dependencias_runtime.configure_dependencies()
            self.assertEqual(sys.path.count(bundled), 1)
            self.assertEqual(sys.path[0], bundled)
        finally:
            sys.path[:] = original_path


if __name__ == '__main__':
    unittest.main()
