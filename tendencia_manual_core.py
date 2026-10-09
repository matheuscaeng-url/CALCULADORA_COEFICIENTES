"""Tendência manual: 2 a 5 referências, de uma a três dimensões."""
from __future__ import annotations

import math
import re
from datetime import datetime
from decimal import Decimal
from justificativas import build_justification, clean_text

from coeficientes_core import (VERSION, AnalysisError, cable_tray_geometry, cable_tray_signature,
    code_text, connection_geometry,
    dimension_number, dimension_unit_suffix, format_dimension, geometry_signature, number, norm, pchip,
    resolve_composition_code, validation)

MAX_REFERENCES = 5
LENGTH_FACTORS = {'MM': 1.0, 'CM': 10.0, 'M': 1000.0, 'POL': 25.4}


def _unit_name(value):
    if str(value).strip() in ('"', '″', '“', '”'):
        return 'POL'
    return norm(value).replace('POLEGADAS', 'POL').replace('POLEGADA', 'POL')


def dimension_text(value, unit):
    if _unit_name(unit) == 'POL':
        return format_dimension(value, 'POL', include_unit=True)
    return f'{value:g} {unit}'.replace('.', ',')


def geometry_text(dims, units):
    return ' × '.join(dimension_text(d, u) for d, u in zip(dims, units))


def _units(value, count):
    raw = list(value) if isinstance(value, (list, tuple)) else str(value).split(',')
    raw = [_unit_name(u) for u in raw]
    if len(raw) == 1:
        raw *= count
    if len(raw) < count or any(not u for u in raw[:count]):
        raise AnalysisError('Informe a unidade de cada dimensão utilizada.')
    units = raw[:count]
    if count > 1 and any(u not in LENGTH_FACTORS for u in units):
        raise AnalysisError('Com 2 ou 3 dimensões, use medidas de comprimento (MM, CM, M ou POL) para o índice RMS. Para outra grandeza, utilize somente a dimensão 1.')
    return units


def _dimensions(values, label, units=None):
    values = list(values) if isinstance(values, (list, tuple)) else [values]
    while values and str(values[-1] if values[-1] is not None else '').strip() == '':
        values.pop()
    if not 1 <= len(values) <= 3:
        raise AnalysisError(f'{label}: preencha a dimensão 1. As dimensões 2 e 3 são opcionais.')
    if any(value is None or not str(value).strip() for value in values):
        raise AnalysisError(f'{label}: preencha a dimensão 2 antes da dimensão 3.')
    dims = []
    for i, value in enumerate(values):
        try:
            parsed = dimension_number(value)
        except (ValueError, OverflowError) as exc:
            raise AnalysisError(f'{label}: dimensão {i+1} inválida.') from exc
        if parsed <= 0:
            raise AnalysisError(f'{label}: as dimensões devem ser maiores que zero.')
        explicit = dimension_unit_suffix(value)
        if explicit and units and i < len(units):
            if explicit != units[i]:
                raise AnalysisError(f'{label}: a dimensão {i+1} foi escrita em {explicit}, mas a coluna está em {units[i]}. Use a unidade indicada na coluna.')
        dims.append(parsed)
    return dims


def _index(dims, units):
    if len(dims) == 1:
        return dims[0]
    # RMS em mm; hypot evita overflow intermediário em valores grandes.
    result = math.hypot(*(d * LENGTH_FACTORS[u] for d, u in zip(dims, units))) / math.sqrt(len(dims))
    if not math.isfinite(result) or result <= 0:
        raise AnalysisError('Índice RMS inválido. Confira as dimensões.')
    return result


def validate_references(refs):
    if not 2 <= len(refs) <= MAX_REFERENCES:
        raise AnalysisError('Informe de 2 a 5 referências. Com uma única referência, use Regra de 3.')
    codes = [str(ref.get('code', '')).strip() for ref in refs]
    if any(not code for code in codes):
        raise AnalysisError('Cada referência precisa de código ou nome.')
    if len(set(codes)) != len(codes):
        raise AnalysisError('Os códigos/nomes das referências não podem se repetir.')
    xs = [number(ref['x']) for ref in refs]
    if any(x <= 0 for x in xs):
        raise AnalysisError('As dimensões devem ser positivas e finitas.')
    if len({round(x, 10) for x in xs}) != len(xs):
        raise AnalysisError('Há referências com a mesma dimensão ou o mesmo índice RMS. A tendência precisa de índices diferentes; geometrias diferentes com RMS igual não formam dois pontos distintos.')


def normalize_references(refs, dimension_unit='MM'):
    normalized, expected_count, expected_units = [], None, None
    for i, ref in enumerate(refs):
        raw_dims = ref.get('dims', [ref.get('x')])
        dims = _dimensions(raw_dims, f'Referência {i+1}')
        units = _units(ref.get('units', dimension_unit), len(dims))
        dims = _dimensions(raw_dims, f'Referência {i+1}', units)
        if expected_count is None:
            expected_count, expected_units = len(dims), units
        if len(dims) != expected_count:
            raise AnalysisError('Use a mesma quantidade de dimensões em todas as referências. Para calcular só pela dimensão 1, deixe as dimensões 2 e 3 vazias em todas as linhas.')
        if units != expected_units:
            raise AnalysisError('Cada coluna de dimensão precisa usar a mesma unidade em todas as referências.')
        normalized.append({**ref, 'code': str(ref.get('code', '')).strip(),
                           'dims': dims, 'units': units, 'x': _index(dims, units)})
    validate_references(normalized)
    return normalized


def reference_rows(rows, units='MM', manual=False):
    """Lê as caixas do formulário. Linhas adicionais totalmente vazias são ignoradas."""
    if len(rows) > MAX_REFERENCES:
        raise AnalysisError('São permitidas até 5 composições de referência.')
    refs = []
    for i, row in enumerate(rows):
        code = str(row.get('code') or '').strip()
        values = list(row.get('dims', []))
        populated = code or any(value is not None and str(value).strip() for value in values)
        if not populated:
            continue
        if not code:
            if not manual:
                raise AnalysisError(f'Linha {i+1}: informe o código SINAPI.')
            code = f'REF_{i+1}'
        dims = _dimensions(values, f'Linha {i+1}')
        axis_units = _units(units, len(dims))
        dims = _dimensions(values, f'Linha {i+1}', axis_units)
        refs.append({'code': code, 'dims': dims, 'units': axis_units, 'row_id': row.get('row_id', i)})
    return normalize_references(refs, units)


def parse_references(text):
    """Compatibilidade com arquivos/scripts anteriores; o formulário usa caixas."""
    rows = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split(';')]
        if not 2 <= len(parts) <= 4 or not parts[0]:
            raise AnalysisError(f'Linha {line_number}: use código; dimensão 1; dimensão 2; dimensão 3.')
        rows.append({'code': parts[0], 'dims': parts[1:]})
    refs = reference_rows(rows)
    if all(len(ref['dims']) == 1 for ref in refs):
        return [{'code': ref['code'], 'x': ref['x']} for ref in refs]
    return refs


def _manual_dimension_text(description):
    """Preserva símbolos dimensionais antes da normalização ASCII."""
    text = str(description or '')
    for symbol, fraction in {'½': '1/2', '¼': '1/4', '¾': '3/4', '⅛': '1/8',
                             '⅜': '3/8', '⅝': '5/8', '⅞': '7/8'}.items():
        text = re.sub(rf'(?<=\d){symbol}', ' ' + fraction, text)
        text = text.replace(symbol, fraction)
    text = text.translate(str.maketrans({'×': ' X ', '″': '"', '“': '"', '”': '"',
                                        '–': '-', '—': '-', '°': ' GRAUS', 'º': ' GRAUS'}))
    text = re.sub(r'(\d+)\s*/\s*(\d+)', r'\1/\2', text)
    text = re.sub(r'(\d+)[.-](\d+/\d+)(?=\s*(?:"|POL))', r'\1 \2', text, flags=re.I)
    return norm(text)


def _manual_description_signature(description):
    """Assinatura sem as grandezas que normalmente variam entre referências.

    A Tendência manual deve aceitar qualquer CPU da referência, não apenas tubos e
    conexões. Mantemos material, norma, classe, texto técnico etc., mas mascaramos
    dimensões/capacidades para reconhecer o mesmo papel com outro tamanho.
    """
    text = _manual_dimension_text(description)
    # Algumas descrições SINAPI marcam grandezas variáveis com asteriscos
    # (ex.: E = *3,65* MM). Eles são apenas marcação gráfica.
    text = re.sub(r'\*(?=\d)', '', text)
    text = re.sub(r'(?<=\d)\*', '', text)
    # Formatos históricos como 2.1/2" significam 2 1/2".
    text = re.sub(r'(\d+)[.-](\d+/\d+)(?=\s*(?:"|POL))', r'\1 \2', text)
    # Datas AF não definem o papel do recurso dentro da CPU.
    text = re.sub(r"\bAF[_ -]?\d{2}/\d{4}\b", "", text)
    # A unidade no fim também qualifica os valores anteriores: 20 X 30 MM.
    # Exige unidade de comprimento; números de norma/classe e ângulos ficam.
    dim_number = r'(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?)'
    dim_unit = r'(?:MM\b|CM\b|M\b|POL(?:EGADAS?)?\b|")'
    sequence = rf'(?<![\w.,])(?:{dim_number}\s*(?:{dim_unit}\s*)?X\s*)+{dim_number}\s*{dim_unit}'
    text = re.sub(sequence, lambda match: ' X '.join('{MEDIDA}' for _ in match[0].split('X')), text)
    # Frações/polegadas, inclusive 1 1/2\".
    text = re.sub(rf'(?<!\w){dim_number}\s*(?:\"|POL(?:EGADAS?)?\b)', ' {MEDIDA} ', text)
    # Grandezas dimensionais/técnicas usuais. BTUS/H é normalizado junto com BTU/H.
    technical_units = (r"MM2|MM3|CM2|CM3|M2|M3|MM|CM|M|BTU(?:S)?\s*/?\s*H|"
                       r"KVA|KW|W|V|A|CV|HP|KG|T|L|HZ")
    text = re.sub(rf'(?<![\w.,])\d+(?:[.,]\d+)?\s*(?:{technical_units})\b', ' {MEDIDA} ', text)
    # DN/DE/diâmetro com unidade eventualmente omitida.
    text = re.sub(r'\b(?:DN|DE|DIAMETRO(?:\s+NOMINAL)?(?:\s+DE)?)\s*=?\s*\d+(?:[.,]\d+)?',
                  lambda m: re.sub(r'\d+(?:[.,]\d+)?', '{MEDIDA}', m.group(0)), text)
    # "LARGURA DE 100 MM" e "LARGURA 50MM" descrevem o mesmo papel.
    labels = r'DIAMETRO(?:\s+(?:NOMINAL|EXTERNO|DO FURO))?|LARGURA|ALTURA|COMPRIMENTO|ESPESSURA|PROFUNDIDADE|CAPACIDADE|DN|DE'
    text = re.sub(rf'\b({labels})\s*(?:DE\s*)?(?:[=:]\s*)?(?=\{{MEDIDA\}})', r'\1 ', text)
    text = re.sub(r'#\s+', '#', text)
    # Não remove vírgula decimal que ainda faça parte de classe/especificação.
    text = re.sub(r'(?<!\d),|,(?!\d)|;|\s*-\s*', ' ', text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ,-.")


def _manual_resource_signature(description):
    text = _manual_dimension_text(description)
    tray = cable_tray_geometry(text)
    if tray:
        # Larguras e bitola variam na família observada; altura, material,
        # função e a relação entre largura e perfil do suporte permanecem.
        return ('eletrocalha', cable_tray_signature(text, tray, align_gauge=True),
                tray['kind'], tray['profile_offset_mm'])
    geometry = connection_geometry(text)
    if geometry:
        text = geometry_signature(text, geometry)
    return ('recurso', _manual_description_signature(text))


def _manual_resource_maps(database, refs):
    """Alinha recursos sem restringir a Tendência manual a famílias pré-programadas.

    Ordem de prioridade:
    1) mesmo código/unidade/tipo em todas as referências;
    2) mesma descrição técnica após mascarar dimensões/capacidades;

    Repetições são distinguidas por ocorrência dentro da mesma assinatura.
    Tipo e unidade também devem coincidir. Recursos sem par permanecem na
    união com célula vazia, para conferência/edição pelo usuário, em vez de impedir
    o carregamento de uma composição SINAPI válida. A posição sozinha não
    permite unir recursos tecnicamente diferentes.
    """
    component_lists = [database['compositions'][ref['code']]['components'] for ref in refs]
    assigned = [dict() for _ in refs]          # index -> key

    # 1. Código exato, incluindo códigos repetidos (ocorrência 1, 2, ...).
    occurrences_by_ref = []
    for components in component_lists:
        groups = {}
        for idx, component in enumerate(components):
            identity = (code_text(component.get('code')), norm(component.get('unit')), norm(component.get('kind')))
            groups.setdefault(identity, []).append(idx)
        occurrences_by_ref.append(groups)
    common_identities = set.intersection(*(set(groups) for groups in occurrences_by_ref)) if occurrences_by_ref else set()
    for identity in sorted(common_identities):
        count = min(len(groups[identity]) for groups in occurrences_by_ref)
        for occurrence in range(count):
            key = ('codigo',) + identity + (occurrence,)
            for ref_index, groups in enumerate(occurrences_by_ref):
                assigned[ref_index][groups[identity][occurrence]] = key

    # 2. Assinatura sem dimensões. Ocorrência separa, por exemplo, duas porcas
    #    dimensionais diferentes na mesma CPU.
    semantic_groups = []
    for ref_index, components in enumerate(component_lists):
        groups = {}
        for idx, component in enumerate(components):
            if idx in assigned[ref_index]:
                continue
            semantic = _manual_resource_signature(component.get('description', ''))
            signature = (semantic, norm(component.get('unit')), norm(component.get('kind')))
            groups.setdefault(signature, []).append(idx)
        semantic_groups.append(groups)
    all_signatures = set().union(*(set(groups) for groups in semantic_groups)) if semantic_groups else set()
    for signature in sorted(all_signatures, key=str):
        max_count = max((len(groups.get(signature, [])) for groups in semantic_groups), default=0)
        for occurrence in range(max_count):
            key = ('descricao',) + signature + (occurrence,)
            for ref_index, groups in enumerate(semantic_groups):
                indexes = groups.get(signature, [])
                if occurrence < len(indexes):
                    assigned[ref_index][indexes[occurrence]] = key

    maps = []
    for ref_index, components in enumerate(component_lists):
        mapping = {}
        for idx, component in enumerate(components):
            key = assigned[ref_index][idx]
            # Por construção cada linha recebe chave única; não há soma silenciosa.
            mapping[key] = component
        maps.append(mapping)
    return maps


def series_from_sinapi(database, refs, dimension_unit='MM'):
    """Carrega qualquer composição existente na referência SINAPI selecionada.

    A função tenta alinhar automaticamente os recursos, mas nunca rejeita uma CPU
    válida apenas porque os códigos internos mudam, se repetem ou os conjuntos de
    recursos não são idênticos. Recursos sem correspondente ficam com célula vazia
    para conferência/preenchimento na tabela manual.
    """
    refs = normalize_references(refs, dimension_unit)
    compositions = database['compositions']
    resolved = []
    missing = []
    for ref in refs:
        actual = resolve_composition_code(compositions, ref['code'])
        if actual is None:
            missing.append(code_text(ref['code']) or str(ref['code']))
            continue
        resolved.append({**ref, 'code': actual})
    if missing:
        raise AnalysisError('Códigos ausentes da referência SINAPI selecionada: ' + ', '.join(missing))
    refs = resolved
    units = {norm(compositions[ref['code']]['unit']) for ref in refs}
    if len(units) != 1:
        raise AnalysisError('As referências possuem unidades de serviço diferentes. Para uma tendência de coeficientes, use composições com a mesma unidade de serviço.')

    maps = _manual_resource_maps(database, refs)
    if not maps or not any(maps):
        raise AnalysisError('As referências não possuem componentes analíticos utilizáveis.')

    # Ordem: primeiro a CPU de origem; depois acrescenta recursos existentes apenas
    # nas demais referências. Assim nenhuma linha SINAPI é descartada.
    ordered_keys = []
    seen = set()
    for mapping in maps:
        for key in mapping:
            if key not in seen:
                seen.add(key)
                ordered_keys.append(key)

    series = []
    for key in ordered_keys:
        available = [mapping.get(key) for mapping in maps]
        first = next(component for component in available if component is not None)
        series.append({
            'description': first['description'],
            'unit': first['unit'],
            'coefficients': [component['coefficient'] if component is not None else '' for component in available],
            'codes': [component['code'] if component is not None else '' for component in available],
            'descriptions': [component['description'] if component is not None else first['description'] for component in available],
            'orders': [list(mapping).index(key) if key in mapping else None for mapping in maps],
            'rows': [component['row'] if component is not None else '' for component in available],
            'alignment_complete': all(component is not None for component in available),
        })
    return series, units.pop(), [compositions[ref['code']]['description'] for ref in refs]


def clipboard_coefficients(text, reference_count):
    """Matriz copiada do Excel: uma coluna por referência, uma linha por recurso."""
    if not 2 <= reference_count <= MAX_REFERENCES:
        raise AnalysisError('Prepare primeiro de 2 a 5 referências.')
    matrix = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        values = line.split('\t') if '\t' in line else line.split(';')
        if len(values) != reference_count:
            raise AnalysisError(f'Linha {line_number}: esperava {reference_count} colunas de coeficientes. Copie somente os números, sem cabeçalhos, do Excel.')
        try:
            parsed = [number(value) for value in values]
        except (ValueError, TypeError) as exc:
            raise AnalysisError(f'Linha {line_number}: há coeficiente vazio ou inválido.') from exc
        if any(value < 0 for value in parsed):
            raise AnalysisError(f'Linha {line_number}: coeficientes negativos não são aceitos.')
        matrix.append(parsed)
    if not matrix:
        raise AnalysisError('Não há coeficientes para colar.')
    return matrix


def remap_coefficients(series, old_refs, new_refs):
    """Preserva células manuais pelo identificador da linha de referência."""
    positions = {ref.get('row_id', ref['code']): i for i, ref in enumerate(old_refs)}
    result = []
    for component in series:
        values = component['coefficients']
        remapped = []
        for ref in new_refs:
            index = positions.get(ref.get('row_id', ref['code']))
            remapped.append(values[index] if index is not None and index < len(values) else '')
        result.append({'description': component.get('description', ''), 'unit': component.get('unit', ''),
                       'coefficients': remapped})
    return result


def coefficient_text(value):
    if value is None:
        return ''
    # Mesma precisão da tela e da cópia; sem notação científica nem arredondar
    # coeficientes pequenos para zero por um número fixo de casas decimais.
    return format(Decimal(f'{number(value):.12g}'), 'f').replace('.', ',')


def result_clipboard(result, table=False, indices=None):
    rows = result['rows'] if indices is None else [result['rows'][i] for i in indices]
    if not rows:
        raise AnalysisError('Selecione um resultado para copiar.')
    if not table and any(row['coefficient'] is None for row in rows):
        raise AnalysisError('Há itens sem coeficiente válido. Copie a tabela com a situação dos itens ou selecione apenas linhas calculadas; a cópia de números não omite linhas.')
    if not table:
        return '\r\n'.join(coefficient_text(row['coefficient']) for row in rows)
    def cell(value):
        text = str(value or '').replace('\t', ' ').replace('\r', ' ').replace('\n', ' ')
        return "'" + text if text.startswith(('=', '+', '-', '@')) else text
    lines = ['Item\tCódigo na origem\tIdentificação\tUnidade\tCoeficiente original\tNovo coeficiente\tSituação']
    for row in rows:
        lines.append('\t'.join([str(row.get('item', '')), cell(row['source_resource']),
            cell(row['description']), cell(row['unit']), coefficient_text(row['source_coefficient']),
            coefficient_text(row['coefficient']), cell(row['status'])]))
    return '\r\n'.join(lines)



def calculate_generic_parameter_trend(references, target_parameter, allow_extrapolation=False,
                                      parameter_units=None, *, bank="", period=""):
    """Tendência genérica por 1+ parâmetros dimensionais e N coeficientes independentes.

    Cada referência informa um código/identificação, um ou mais parâmetros dimensionais
    e a mesma quantidade de coeficientes. Com um parâmetro, ele próprio forma o eixo da
    tendência. Com dois ou mais, os parâmetros são reduzidos a um índice RMS, exatamente
    para permitir peças com múltiplas dimensões (ex.: joelhos de redução e tês) sem aplicar
    um único fator de regra de três a todos os coeficientes.

    Cada coluna de coeficiente forma sua própria série: com 2 referências usa a reta entre
    os pontos; com 3 ou mais usa PCHIP. Parâmetros aceitam decimais e frações.
    Unidades opcionais conferem a entrada e formatam a memória, sem alterar o eixo RMS.
    """
    references = list(references or [])
    if len(references) < 2:
        raise AnalysisError('Informe pelo menos duas referências.')

    def units_for(count):
        if parameter_units is None:
            return None
        raw = list(parameter_units) if isinstance(parameter_units, (list, tuple)) else [parameter_units]
        units = [_unit_name(unit) for unit in raw]
        if len(units) == 1:
            units *= count
        if len(units) != count or any(not unit for unit in units):
            raise AnalysisError('Informe a unidade de cada parâmetro dimensional ativo.')
        return units

    def parse_vector(raw, label):
        values = list(raw) if isinstance(raw, (list, tuple)) else [raw]
        if not values:
            raise AnalysisError(f'{label}: informe pelo menos um parâmetro dimensional.')
        units = units_for(len(values))
        parsed = []
        for column, value in enumerate(values, 1):
            try:
                item = dimension_number(value)
            except (ValueError, TypeError, OverflowError) as exc:
                raise AnalysisError(f'{label}: parâmetro {column} inválido ou vazio. Use um número, como 25, 3/4 ou 1 1/2.') from exc
            if not math.isfinite(item) or item <= 0:
                raise AnalysisError(f'{label}: parâmetro {column} deve ser maior que zero.')
            explicit = dimension_unit_suffix(value)
            if explicit and units and explicit != units[column-1]:
                raise AnalysisError(f'{label}: o parâmetro {column} foi escrito em {explicit}, mas a coluna está em {units[column-1]}. Use a unidade indicada na coluna.')
            parsed.append(item)
        return parsed

    def rms_index(values):
        if len(values) == 1:
            return values[0]
        result = math.hypot(*values) / math.sqrt(len(values))
        if not math.isfinite(result) or result <= 0:
            raise AnalysisError('Índice RMS inválido. Confira os parâmetros dimensionais.')
        return result

    normalized = []
    coefficient_count = None
    parameter_count = None
    for index, reference in enumerate(references, 1):
        code = str(reference.get('code') or '').strip()
        if not code:
            raise AnalysisError(f'Referência {index}: informe o código ou identificação.')
        raw_parameters = reference.get('parameters')
        if raw_parameters is None:
            raw_parameters = [reference.get('parameter')]
        parameters = parse_vector(raw_parameters, f'Referência {index}')
        if parameter_count is None:
            parameter_count = len(parameters)
        elif len(parameters) != parameter_count:
            raise AnalysisError('Todas as referências precisam ter a mesma quantidade de parâmetros dimensionais.')

        raw_values = list(reference.get('coefficients') or [])
        if coefficient_count is None:
            coefficient_count = len(raw_values)
            if coefficient_count < 1:
                raise AnalysisError('Informe pelo menos um coeficiente de referência.')
        if len(raw_values) != coefficient_count:
            raise AnalysisError('Todas as referências precisam ter a mesma quantidade de coeficientes.')
        values = []
        for column, value in enumerate(raw_values, 1):
            try:
                parsed = number(value)
            except (ValueError, TypeError, OverflowError) as exc:
                raise AnalysisError(f'Referência {index}: coeficiente {column} inválido ou vazio.') from exc
            if not math.isfinite(parsed) or parsed < 0:
                raise AnalysisError(f'Referência {index}: coeficiente {column} deve ser zero ou positivo.')
            values.append(parsed)
        normalized.append({
            'code': code,
            'parameters': parameters,
            'parameter': parameters[0] if len(parameters) == 1 else None,
            'x': rms_index(parameters),
            'coefficients': values,
        })

    codes = [reference['code'] for reference in normalized]
    if len(set(codes)) != len(codes):
        raise AnalysisError('Os códigos/identificações das referências não podem se repetir.')
    xs = [reference['x'] for reference in normalized]
    if len({round(value, 12) for value in xs}) != len(xs):
        label = 'parâmetro dimensional' if parameter_count == 1 else 'índice RMS'
        raise AnalysisError(f'Cada referência precisa ter um {label} diferente para formar a tendência.')

    raw_target = target_parameter
    if not isinstance(raw_target, (list, tuple)):
        raw_target = [raw_target]
    target_parameters = parse_vector(raw_target, 'Parâmetro desejado')
    if len(target_parameters) != parameter_count:
        raise AnalysisError(f'O alvo precisa ter {parameter_count} parâmetro(s), como as referências.')
    target = rms_index(target_parameters)

    order = sorted(range(len(normalized)), key=lambda i: normalized[i]['x'])
    ordered = [normalized[i] for i in order]
    xs = [reference['x'] for reference in ordered]
    outside = target < xs[0] or target > xs[-1]
    if outside and not allow_extrapolation:
        raise AnalysisError('O parâmetro desejado está fora do intervalo das referências. Marque Permitir extrapolação para continuar.')
    exact_index = next((i for i, value in enumerate(xs)
                        if math.isclose(value, target, rel_tol=0, abs_tol=1e-12)), None)

    if exact_index is not None:
        method = 'Consulta ao ponto informado'
    elif len(ordered) == 2:
        method = 'Extrapolação linear' if outside else 'Interpolação linear'
    else:
        method = 'Extrapolação pela tangente PCHIP' if outside else 'Interpolação PCHIP'

    results = []
    for column in range(coefficient_count):
        ys = [reference['coefficients'][column] for reference in ordered]
        value = ys[exact_index] if exact_index is not None else pchip(xs, ys, target)
        if not math.isfinite(value):
            raise AnalysisError(f'Coeficiente {column+1}: resultado não finito.')
        if value < 0:
            raise AnalysisError(f'Coeficiente {column+1}: a tendência resultou em valor negativo. Confira as referências ou o alvo.')
        results.append(value)

    axis_units = units_for(parameter_count)

    def vector_text(values):
        if axis_units:
            return geometry_text(values, axis_units)
        return ' × '.join(f'{value:g}' for value in values)

    if parameter_count == 1:
        reference_text = '; '.join(
            f'{reference["code"]}: parâmetro {vector_text(reference["parameters"])}'
            for reference in ordered)
        target_text = vector_text(target_parameters)
    else:
        reference_text = '; '.join(
            f'{reference["code"]}: parâmetros {vector_text(reference["parameters"])} '
            f'(índice RMS {reference["x"]:g})'
            for reference in ordered)
        target_text = f'{vector_text(target_parameters)} (índice RMS {target:g})'

    chosen = [ordered[exact_index]] if exact_index is not None else ordered
    reference_labels = [f'{ref["code"]} ({vector_text(ref["parameters"])})' for ref in chosen]
    technique = method + ' por coeficiente'
    if parameter_count > 1 and exact_index is None:
        technique += f', com índice RMS de {parameter_count} parâmetros'
    technique += f', alvo {vector_text(target_parameters)}'
    justification = build_justification(bank, period, reference_labels, technique)

    return {
        'references': ordered,
        'target_parameter': target,
        'target_parameters': target_parameters,
        'parameter_count': parameter_count,
        'parameter_units': axis_units,
        'bank': clean_text(bank),
        'period': clean_text(period),
        'coefficient_count': coefficient_count,
        'coefficients': results,
        'method': method,
        'outside': outside,
        'exact': exact_index is not None,
        'justification': justification,
    }

def calculate_manual_trend(refs, series, target, source_code=None, dimension_unit='MM',
                           service_unit='UN', allow_extrapolation=False, meta=None):
    refs = normalize_references(refs, dimension_unit)
    count, axis_units = len(refs[0]['dims']), refs[0]['units']
    if not series:
        raise AnalysisError('Adicione pelo menos um componente e informe seus coeficientes em todas as referências.')
    target_dims = _dimensions(target, 'Alvo', axis_units)
    if len(target_dims) != count:
        raise AnalysisError(f'O alvo precisa de {count} dimensão(ões), como as referências.')
    target_x = _index(target_dims, axis_units)
    source_code = source_code or refs[0]['code']
    source_index = next((i for i, ref in enumerate(refs) if ref['code'] == source_code), None)
    if source_index is None:
        raise AnalysisError('Escolha uma referência de origem da tabela.')
    order = sorted(range(len(refs)), key=lambda i: refs[i]['x'])
    xs = [refs[i]['x'] for i in order]
    outside = target_x < xs[0] or target_x > xs[-1]
    if outside and not allow_extrapolation:
        raise AnalysisError('O alvo está fora do intervalo das referências. Autorize a extrapolação para continuar.')
    exact = next((i for i, ref in enumerate(refs) if all(
        math.isclose(a, b, rel_tol=0, abs_tol=1e-10) for a, b in zip(ref['dims'], target_dims))), None)
    same_index = any(math.isclose(x, target_x, rel_tol=0, abs_tol=1e-10) for x in xs)
    method = ('Consulta ao ponto informado' if exact is not None else
              'Interpolação linear por componente (2 referências)' if len(refs) == 2 else 'PCHIP por componente')
    if outside:
        method = 'Extrapolação linear (2 referências)' if len(refs) == 2 else 'Extrapolação pela tangente da extremidade PCHIP'
    warnings = ['Comparabilidade declarada pelo usuário: confira material, unidade de serviço, método executivo, aplicação e as dimensões usadas.',
                'A mesma linha deve representar recursos equivalentes em todas as referências. A entrada manual não comprova equivalência técnica.',
                'Resultado para composição própria a revisar. Não cria código SINAPI, não define insumos substitutos nem estima seus preços.']
    if count > 1:
        warnings.append(f'Índice RMS das {count} dimensões em mm = raiz da média dos quadrados. É a mesma hipótese dimensional usada na calculadora de tubos/conexões, não uma aferição de produtividade.')
        if same_index and exact is None:
            warnings.append('O alvo tem o mesmo RMS de um ponto, mas geometria diferente. O resultado é uma estimativa pelo índice, não consulta à geometria dessa referência.')
    if len(refs) == 2:
        warnings.append('Somente 2 referências: reta que une os pontos, não regra de três pela origem. Maior possibilidade de erro; sem validação interna.')
    if outside:
        warnings.append('EXTRAPOLAÇÃO: sem observações envolvendo o alvo e sem limite percentual. Revisão técnica obrigatória.')
    sinapi_metadata = meta is not None
    meta = dict(meta or {'period': 'Entrada manual', 'filename': 'Tabela informada pelo usuário',
                        'sheet': 'Tendência manual', 'price_sheet': None, 'sha256': 'não se aplica'})
    meta.setdefault('bank', 'SINAPI' if sinapi_metadata else 'não informado')
    if meta.get('manual_edited'):
        warnings.append('A tabela carregada da referência SINAPI foi editada pelo usuário. Os valores desta memória são os informados na tabela, não necessariamente os coeficientes originais da base.')
    rows = []
    for item_index, component in enumerate(series):
        description = str(component.get('description') or '').strip() or f'Item {item_index+1}'
        unit = str(component.get('unit') or '').strip() or 'Não informada'
        values = component.get('coefficients', [])
        if len(values) != len(refs):
            raise AnalysisError(f'{description}: informe um coeficiente para cada referência.')
        try:
            values = [number(value) for value in values]
        except (ValueError, TypeError) as exc:
            raise AnalysisError(f'Coeficiente ausente ou inválido: {description}. Não use vazio como zero.') from exc
        if any(value < 0 for value in values):
            raise AnalysisError(f'{description}: coeficientes negativos não são aceitos.')
        ys = [values[i] for i in order]
        value = values[exact] if exact is not None else pchip(xs, ys, target_x)
        if not math.isfinite(value) or value < 0:
            value = None
        source = values[source_index]
        codes = component.get('codes', [''] * len(refs))
        source_rows = component.get('rows', [''] * len(refs))
        descriptions = component.get('descriptions', [description] * len(refs))
        source_orders = component.get('orders')
        if any(len(items) != len(refs) for items in (codes, source_rows, descriptions)):
            raise AnalysisError('Códigos/linhas dos recursos não correspondem à quantidade de referências.')
        if source_orders is not None and len(source_orders) != len(refs):
            raise AnalysisError('Ordem dos recursos incompatível com as referências.')
        status = 'Ponto informado, sem estimativa' if exact is not None else 'Estimado; revisar'
        if value is None:
            status = 'Resultado negativo/não finito; não estimado'
        check = validation(xs, ys)
        if check['nmae_pct'] is not None and check['nmae_pct'] > 20 and exact is None:
            status += ' — variação irregular'
        source_order = (source_orders[source_index] if source_orders is not None and
                        source_index < len(source_orders) and source_orders[source_index] is not None else item_index)
        rows.append({'item': item_index+1, 'source_order': source_order,
                     'kind': 'Componente informado', 'source_resource': codes[source_index],
                     'description': descriptions[source_index],
                     'target_description': descriptions[exact] if exact is not None else description + ' [ESPECIFICAÇÃO DO ALVO A CONFERIR]',
                     'target_resource': codes[exact] if exact is not None else 'DEFINIR/CONFERIR COMPONENTE DO ALVO',
                     'unit': unit, 'source_coefficient': source, 'coefficient': value,
                     'change_pct': (value / source - 1) * 100 if value is not None and source else None,
                     'status': status, 'validation': check,
                     'points': [{'x': refs[i]['x'], 'coefficient': values[i], 'dimensions': refs[i]['dims'],
                                 'dimension_text': geometry_text(refs[i]['dims'], refs[i]['units']), 'composition': refs[i]['code'],
                                 'resource': codes[i], 'row': source_rows[i]} for i in order],
                     'supply_checked': False, 'supply_matches': [], 'supply_status': 'Não consultado: cálculo genérico'})
    if all(component.get('orders') is not None for component in series):
        rows.sort(key=lambda row: row['source_order'])
    if any(row['coefficient'] is None for row in rows):
        warnings.append('Resultado parcial: existe componente sem estimativa válida.')
    if any(row['unit'] == 'Não informada' for row in rows):
        warnings.append('Há recursos sem unidade informada. Confira as unidades antes de aplicar os coeficientes.')
    references = [{**refs[i], 'description': refs[i].get('description', 'Referência informada pelo usuário'),
                   'dimension_text': geometry_text(refs[i]['dims'], refs[i]['units']), 'reported_dimensions': count,
                   'used': True, 'row': ''} for i in order]
    origin_text = geometry_text(refs[source_index]['dims'], axis_units)
    target_text = geometry_text(target_dims, axis_units)
    chosen = [refs[exact]] if exact is not None else references
    reference_labels = [f'{ref["code"]} ({geometry_text(ref["dims"], ref["units"])})' for ref in chosen]
    technique = method
    if count > 1 and exact is None:
        technique += f', com índice RMS de {count} dimensões'
    technique += f', com origem na referência {source_code}, de {origin_text} para {target_text}'
    period = meta.get('period') if sinapi_metadata else ''
    justification = build_justification(meta['bank'], period, reference_labels, technique)
    curve_label = f'Índice RMS de {count} dimensões (mm)' if count > 1 else f'Grandeza informada ({axis_units[0]})'
    return {'version': VERSION, 'created_at': datetime.now().isoformat(timespec='seconds'), 'meta': meta,
            'family': {'curve_label': curve_label, 'service_unit': service_unit.strip() or 'Não informada',
                       'dimension_count': count, 'axis_units': axis_units},
            'source_code': source_code, 'source_description': refs[source_index].get('description', 'Referência informada manualmente'),
            'source_x': refs[source_index]['x'], 'source_dims': refs[source_index]['dims'], 'source_dimension_text': origin_text,
            'target': target_x, 'target_dims': target_dims, 'target_dimension_text': target_text, 'target_code': None,
            'mode': 'Tendência manual — ' + ('ponto informado' if exact is not None else 'extrapolação' if outside else 'interpolação'),
            'calculation_type': 'manual_trend', 'target_reference': refs[exact]['code'] if exact is not None else None,
            'method': method, 'justification': justification, 'warnings': warnings,
            'range': [xs[0], xs[-1]], 'references': references, 'rows': rows}
