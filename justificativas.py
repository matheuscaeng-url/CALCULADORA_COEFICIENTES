"""Texto curto e uniforme para todas as calculadoras."""
from __future__ import annotations

import math


def clean_text(value, fallback=''):
    text = ' '.join(str(value if value is not None else '').split()).strip()
    return text or fallback


def build_justification(bank, period, references, technique, *, factor=None):
    """Banco/data, códigos (com dimensões opcionais), técnica e fator final."""
    refs = list(dict.fromkeys(clean_text(value) for value in references if clean_text(value)))
    label = 'Código de referência' if len(refs) == 1 else 'Códigos de referência'
    text = (f'Banco: {clean_text(bank, "não informado")}. '
            f'Data do banco: {clean_text(period, "não informada")}. '
            f'{label}: {", ".join(refs) or "não informados"}. '
            f'Técnica: {clean_text(technique).rstrip(".")}.')
    if factor is not None:
        value = float(factor)
        if not math.isfinite(value) or value <= 0:
            raise ValueError('O fator de correção deve ser positivo e finito.')
        number = f'{value:.12g}'.replace('.', ',')
        text += f' Fator de correção utilizado: {number}.'
    return text
