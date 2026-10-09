"""Proporcionalidade direta para famílias com exatamente uma composição.

Não ajusta tendência, não valida produtividade e não cria códigos SINAPI.
O diâmetro equivalente RMS é apenas uma hipótese explícita nas conexões.
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from justificativas import build_justification

from coeficientes_core import (
    VERSION, AnalysisError, build_families, connection_geometry,
    format_geometry, format_reference_dimensions, is_tube_or_fitting,
    measures, nominal_dimensions_equal, norm, number, resource_kind,
    _estimated_target_description, _supply_matches, _target_geometry,
)


def single_reference_families(families):
    """Quantidade de códigos, não de pontos/recursos remanescentes de uma CPU."""
    return [family for family in families
            if len({ref['code'] for ref in family['refs']}) == 1
            and len(family['refs']) == 1 and not family.get('manual')]


def dimensional_component(component, family):
    """O recurso representa o tubo/conexão com a dimensão da origem?"""
    if not is_tube_or_fitting(component['description']):
        return False
    ref = family['refs'][0]
    if family['dimension_count'] > 1:
        geometry = connection_geometry(component['description'])
        return bool(geometry and len(geometry['dims']) == len(ref['dims']) and all(
            nominal_dimensions_equal(a, ua, b, ub)
            for a, ua, b, ub in zip(geometry['dims'], geometry['units'], ref['dims'], ref['units'])))
    return any(nominal_dimensions_equal(axis['value'], axis['unit'], ref['dims'][0], ref['units'][0])
               for axis in measures(component['description']))


def default_scaled_indices(database, family):
    """Conserva o consumo do tubo/conexão principal; demais recursos selecionados."""
    components = database['compositions'][family['refs'][0]['code']]['components']
    return {index for index, component in enumerate(components)
            if not dimensional_component(component, family)}


def proportional_factor(family, target):
    dims, units, target_x = _target_geometry(family, target)
    source_x = family['refs'][0]['x']
    if not math.isfinite(source_x) or source_x <= 0:
        raise AnalysisError('A dimensão de origem precisa ser positiva e finita.')
    factor = target_x / source_x
    if not math.isfinite(factor) or factor <= 0:
        raise AnalysisError('O fator deve ser positivo e finito. Confira as dimensões.')
    return dims, units, source_x, target_x, factor



def calculate_generic_rule_of_three(reference_dims, target_dims, reference_coefficient,
                                    reference_code, bank, period):
    """Regra de 3 genérica baseada na soma de 1 a 3 dimensões.

    c_alvo = c_ref × (ΣD_alvo / ΣD_ref)

    As dimensões 2 e 3 podem ficar vazias, desde que o mesmo conjunto de
    colunas seja preenchido na referência e na peça desejada.
    """
    def clean_dims(values, label):
        values = list(values or [])[:3]
        values += [''] * (3 - len(values))
        active = []
        pattern = []
        for i, raw in enumerate(values):
            text = str(raw or '').strip()
            pattern.append(bool(text))
            if not text:
                active.append(None)
                continue
            value = number(raw)
            if value <= 0:
                raise AnalysisError(f'{label} D{i+1} deve ser maior que zero.')
            active.append(value)
        if not pattern[0]:
            raise AnalysisError(f'Informe D1 da {label.lower()}.')
        # Não permite pular D2 e preencher D3, para manter a leitura da tabela clara.
        if pattern[2] and not pattern[1]:
            raise AnalysisError(f'Preencha D2 antes de D3 na {label.lower()}.')
        return active, pattern

    ref_dims, ref_pattern = clean_dims(reference_dims, 'Peça de referência')
    dst_dims, dst_pattern = clean_dims(target_dims, 'Peça desejada')
    if ref_pattern != dst_pattern:
        raise AnalysisError('Use a mesma quantidade de dimensões na peça de referência e na peça desejada.')

    code = str(reference_code or '').strip()
    bank_text = str(bank or '').strip()
    period_text = str(period or '').strip()
    if not code:
        raise AnalysisError('Informe o código da referência.')
    if not bank_text:
        raise AnalysisError('Informe o banco da referência.')
    if not period_text:
        raise AnalysisError('Informe a data/competência da referência.')

    coef = number(reference_coefficient)
    if coef < 0:
        raise AnalysisError('O coeficiente da referência não pode ser negativo.')
    ref_values = [v for v in ref_dims if v is not None]
    dst_values = [v for v in dst_dims if v is not None]
    ref_sum, dst_sum = sum(ref_values), sum(dst_values)
    if ref_sum <= 0:
        raise AnalysisError('A soma das dimensões da referência deve ser maior que zero.')
    factor = dst_sum / ref_sum
    result = coef * factor
    if not math.isfinite(result):
        raise AnalysisError('O resultado não é finito. Confira os valores informados.')

    used = len(ref_values)
    justification = build_justification(
        bank_text, period_text, [code], 'regra de três direta', factor=factor)
    return {
        'reference_code': code, 'bank': bank_text, 'period': period_text,
        'reference_dims': ref_dims, 'target_dims': dst_dims, 'dimension_count': used,
        'reference_sum': ref_sum, 'target_sum': dst_sum, 'reference_coefficient': coef,
        'factor': factor, 'coefficient': result, 'justification': justification,
    }

def calculate_rule_of_three(database, family, target, scaled_indices=None):
    """c_alvo = c_origem × (índice_alvo / índice_origem), apenas uma referência.

    Verifica a família contra a base completa: reduzir manualmente uma família
    de duas ou mais referências não libera a regra de três.
    """
    if len(family.get('refs', [])) != 1 or family.get('manual'):
        raise AnalysisError('A regra de 3 é exclusiva para famílias com exatamente 1 referência. Use a aba Tendência.')
    canonical = next((candidate for candidate in build_families(database)
                      if candidate['id'] == family['id']), None)
    if canonical is None or canonical not in single_reference_families([canonical]):
        raise AnalysisError('Esta família não possui exatamente 1 referência na base ativa. Use a aba Tendência.')
    family = canonical
    ref = family['refs'][0]
    composition = database['compositions'][ref['code']]
    dims, units, source_x, target_x, factor = proportional_factor(family, target)
    components = composition['components']
    selected = default_scaled_indices(database, family) if scaled_indices is None else set(scaled_indices)
    if any(not isinstance(i, int) or isinstance(i, bool) or i < 0 or i >= len(components) for i in selected):
        raise AnalysisError('Seleção de componentes inválida. Selecione novamente a composição.')
    unchanged = all(math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-10)
                    for a, b in zip(ref['dims'], dims))
    warnings = [
        'REFERÊNCIA ÚNICA: proporcionalidade assumida pelo usuário; não há tendência observada, PCHIP, regressão nem validação estatística. Revisão técnica obrigatória.',
        'Somente os recursos marcados recebem o fator. Os demais mantêm o consumo original; isso não comprova sua adequação ao novo diâmetro.',
        'O consumo do tubo/conexão principal é mantido por padrão: metros por metro e peças por unidade não são proporcionais ao diâmetro automaticamente.',
        'A consulta de insumos mantém código e descrição do alvo coerentes. Preços PE/SP não são multiplicados pelo fator.',
    ]
    axis_note = 'dimensão desejada / dimensão de origem'
    if family['dimension_count'] > 1:
        axis_note = 'RMS das bocas desejadas / RMS das bocas de origem'
        warnings.append('CONEXÃO MULTIDIMENSIONAL: fator = RMS_alvo/RMS_origem; RMS = raiz da média dos quadrados das bocas em mm. Esta escolha é uma hipótese simplificadora, não uma tendência aferida.')
    if ref.get('range'):
        warnings.append('A referência descreve uma faixa DN; para a proporção foi usado o ponto médio de origem explicitado na memória. Confira a aplicabilidade.')
    elif re.search(r'\bOU\b', norm(composition['description'])):
        warnings.append('A descrição contém alternativas: o cálculo usa a geometria de origem exibida, não todas as alternativas simultaneamente. Confira a descrição original.')
    if family.get('tee') and ref.get('inferred'):
        warnings.append('Tê com uma medida: D × D × D. Com duas: D1 × D1 × D2. Confira a ordem das três bocas.')
    rows = []
    for index, component in enumerate(components):
        original = component['coefficient']
        applied = index in selected
        value = None if original is None else original * (factor if applied else 1.0)
        if value is not None and (not math.isfinite(value) or value < 0):
            value = None
        dimensional = dimensional_component(component, family)
        supply = ({'checked': False, 'matches': [], 'status': 'Não se aplica a este componente'}
                  if not dimensional else _supply_matches(database, component, component if unchanged else None,
                                                         family, ref, dims, units))
        target_code, target_description = component['code'], component['description']
        if dimensional and not unchanged:
            target_code = 'DEFINIR INSUMO DO ALVO'
            target_description = _estimated_target_description(component, family, dims, units)
            if len(supply['matches']) == 1:
                target_code = supply['matches'][0]['code']
                target_description = supply['matches'][0]['description']
            elif len(supply['matches']) > 1:
                target_code = 'SELECIONAR INSUMO DO ALVO'
                supply['status'] += ' — múltiplos candidatos; escolha técnica necessária'
        if value is None:
            status = 'Coeficiente ausente/inválido; não calculado'
        elif unchanged:
            status = 'Mesma dimensão: coeficiente original'
        elif applied:
            status = 'Regra de 3 — estimativa proporcional; revisar'
        else:
            status = 'Mantido por seleção; revisar aplicabilidade'
        change = (value / original - 1) * 100 if value is not None and original not in (None, 0) else None
        rows.append({
            'kind': resource_kind(component), 'source_resource': component['code'],
            'description': component['description'], 'target_resource': target_code,
            'target_description': target_description, 'unit': component['unit'],
            'source_coefficient': original, 'coefficient': value, 'change_pct': change, 'status': status,
            'validation': {'n': 0, 'nmae_pct': None, 'label': 'Não se aplica: apenas 1 referência'},
            'points': [{'x': source_x, 'coefficient': original, 'dimensions': ref['dims'],
                        'dimension_text': format_reference_dimensions(ref), 'composition': ref['code'],
                        'resource': component['code'], 'row': component['row']}],
            'supply_checked': supply['checked'], 'supply_status': supply['status'], 'supply_matches': supply['matches'],
            'proportional_applied': applied, 'applied_factor': factor if applied else 1.0,
            'calculation': (f'{original} × ({target_x:.10g} / {source_x:.10g}) = {value}'
                            if applied and value is not None else f'Consumo mantido: {original}'),
        })
    if any(row['coefficient'] is None for row in rows):
        warnings.append('RESULTADO PARCIAL: há coeficientes sem valor válido. A composição não está pronta para uso.')
    if any('DEFINIR' in row['target_resource'] or 'SELECIONAR' in row['target_resource'] for row in rows):
        warnings.append('Existem recursos dimensionais sem código do alvo definido. Não reutilize o código do material de origem com descrição de outro diâmetro.')
    source_text, target_text = format_reference_dimensions(ref), format_geometry(dims, units)
    justification = build_justification(
        'SINAPI', database['meta']['period'], [ref['code']],
        'consulta direta, sem adaptação dimensional' if unchanged
        else 'regra de três direta nos recursos selecionados', factor=factor)
    return {
        'version': VERSION, 'created_at': datetime.now().isoformat(timespec='seconds'), 'meta': database['meta'],
        'family': family, 'source_code': ref['code'], 'source_description': composition['description'],
        'source_x': source_x, 'source_dims': ref['dims'], 'source_dimension_text': source_text,
        'target': target_x, 'target_dims': dims, 'target_dimension_text': target_text,
        'target_code': ref['code'] if unchanged else None, 'calculation_type': 'rule_of_three',
        'mode': 'Consulta na dimensão original' if unchanged else 'Estimativa própria — regra de 3 (1 referência)',
        'method': 'Proporcionalidade direta nos recursos selecionados; ' + axis_note,
        'factor': factor, 'factor_formula': f'F = {target_x:.10g} / {source_x:.10g} = {factor:.10g}',
        'justification': justification, 'warnings': warnings, 'range': [source_x, source_x],
        'references': [{**ref, 'description': composition['description'],
                        'dimension_text': source_text, 'row': composition['row'], 'used': True}],
        'rows': rows,
    }
