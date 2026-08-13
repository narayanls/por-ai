"""
Geração de gráficos (PNG) a partir da mesma spec usada por sheet_gen.

O gráfico NÃO é nativo do formato de planilha (xlsx/ods): é uma imagem
raster embutida, no mesmo espírito do que o Claude gera quando pedido
via chat na web. A alternativa seria gráfico nativo (openpyxl.chart pro
xlsx, XML de <chart:chart> manual pro ods), mas isso duplicaria a
implementação por formato e, no caso do ods, exige montar objeto OLE
embutido na mão — o odfpy não tem helper de alto nível pra isso. Uma
imagem única, gerada uma vez e reaproveitada nos dois backends, é menos
código e mais previsível.

matplotlib é opcional, como odfpy e openpyxl: se não estiver instalado,
render_chart() devolve None e o chamador (sheet_gen) entrega a planilha
só com a tabela — nunca quebra a geração por causa do gráfico.

A spec de gráfico NÃO duplica valores: ela referencia nomes de colunas
que já existem em `columns`/`rows` (validados por sheet_gen._parse_spec).
Isso evita a tabela e o gráfico divergirem se o modelo errar um número
ao copiar dados de um lugar pro outro.
"""

from __future__ import annotations

import io
import logging
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

try:
    import matplotlib
    matplotlib.use("Agg")  # backend sem display: obrigatório rodando em
    # thread de app GTK, sem isso o matplotlib tenta abrir uma janela e
    # trava ou lança erro fora da thread principal.
    import matplotlib.pyplot as plt
    CHART_BACKEND = True
except ImportError:
    CHART_BACKEND = False


SUPPORTED_CHART_TYPES = ("bar", "line", "pie", "scatter")

_DPI = 150
_FIGSIZE = (7.5, 4.5)  # polegadas; ~1125x675px em 150dpi, cabe bem numa célula


def _column_index(columns: Sequence[str], name: Any) -> Optional[int]:
    """Acha o índice de uma coluna pelo nome (comparação exata primeiro,
    case-insensitive como fallback — o modelo às vezes muda a caixa)."""
    if not isinstance(name, str):
        return None
    if name in columns:
        return columns.index(name)
    lowered = name.strip().lower()
    for index, col in enumerate(columns):
        if col.strip().lower() == lowered:
            return index
    return None


def _numeric_series(rows: Sequence[list], index: int) -> List[float]:
    """Extrai uma coluna como floats; valores não numéricos viram 0.0 em vez
    de quebrar o gráfico — planilha gerada por LLM não tem garantia de tipo."""
    values: List[float] = []
    for row in rows:
        if index >= len(row):
            values.append(0.0)
            continue
        raw = row[index]
        if isinstance(raw, bool):
            values.append(1.0 if raw else 0.0)
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            values.append(0.0)
    return values


def _category_labels(rows: Sequence[list], index: int) -> List[str]:
    labels = []
    for row in rows:
        labels.append(str(row[index]) if index < len(row) else "")
    return labels


# Paleta usada nas séries do gráfico. header_bg entra como primeira cor pra
# manter alguma coerência com o tema pedido no `style`; o resto é uma paleta
# fixa e neutra — não dá pra pedir mais cores ao modelo sem inflar a spec.
_FALLBACK_PALETTE = ("4C72B0", "DD8452", "55A868", "C44E52", "8172B2", "937860")


def _palette(style: Dict[str, str], count: int) -> List[str]:
    colors = [style.get("header_bg", _FALLBACK_PALETTE[0])]
    colors.extend(_FALLBACK_PALETTE)
    # Garante cores suficientes repetindo a paleta se houver muitas séries.
    while len(colors) < count:
        colors.extend(_FALLBACK_PALETTE)
    return [f"#{c.lstrip('#')}" for c in colors[:count]]


def render_chart(
    chart_spec: Dict[str, Any],
    columns: Sequence[str],
    rows: Sequence[list],
    style: Dict[str, str],
) -> Optional[bytes]:
    """Renderiza o gráfico descrito por ``chart_spec`` como PNG (bytes).

    Formato esperado de ``chart_spec`` (ver capabilities_prompt() em
    sheet_gen.py pro texto exato mandado ao modelo):

        {
          "type": "bar" | "line" | "pie" | "scatter",
          "title": "opcional",
          "x_label": "opcional",
          "y_label": "opcional",
          "category_column": "nome de uma coluna existente",
          "value_columns": ["nome de coluna", ...],
          # scatter usa x_column no lugar de category_column:
          "x_column": "nome de coluna numérica"
        }

    Devolve None (nunca levanta exceção) se matplotlib não estiver
    disponível ou a spec/colunas referenciadas forem inválidas — o
    chamador decide o que fazer (tipicamente: entregar só a tabela).
    """
    if not CHART_BACKEND:
        return None
    if not isinstance(chart_spec, dict):
        return None

    chart_type = str(chart_spec.get("type", "")).strip().lower()
    if chart_type not in SUPPORTED_CHART_TYPES:
        logger.info("Tipo de gráfico não suportado: %r", chart_type)
        return None
    if not rows or not columns:
        return None

    try:
        if chart_type == "scatter":
            return _render_scatter(chart_spec, columns, rows, style)
        return _render_categorical(chart_type, chart_spec, columns, rows, style)
    except Exception:  # pylint: disable=broad-except
        # Qualquer erro de renderização (matplotlib é sensível a dado
        # inesperado) vira "sem gráfico", não uma planilha quebrada.
        logger.exception("Falha ao renderizar gráfico")
        return None


def _finish_figure(fig, ax, title: Any, style: Dict[str, str]) -> bytes:
    fg = f"#{style.get('row_fg', '1F2933').lstrip('#')}"
    if title:
        ax.set_title(str(title), color=fg, fontsize=13, fontweight="bold")
    ax.tick_params(colors=fg, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(fg)
    ax.xaxis.label.set_color(fg)
    ax.yaxis.label.set_color(fg)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    buffer = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buffer, format="png", dpi=_DPI)
    plt.close(fig)
    return buffer.getvalue()


def _render_categorical(
    chart_type: str,
    chart_spec: Dict[str, Any],
    columns: Sequence[str],
    rows: Sequence[list],
    style: Dict[str, str],
) -> Optional[bytes]:
    cat_index = _column_index(columns, chart_spec.get("category_column"))
    if cat_index is None:
        logger.info("category_column não encontrada: %r", chart_spec.get("category_column"))
        return None

    value_columns = chart_spec.get("value_columns")
    if not isinstance(value_columns, list) or not value_columns:
        return None

    series: List[tuple] = []  # (nome, valores)
    for name in value_columns:
        index = _column_index(columns, name)
        if index is None:
            continue
        series.append((str(name), _numeric_series(rows, index)))
    if not series:
        logger.info("Nenhuma value_columns válida em %r", value_columns)
        return None

    labels = _category_labels(rows, cat_index)
    colors = _palette(style, len(series))

    fig, ax = plt.subplots(figsize=_FIGSIZE)

    if chart_type == "pie":
        # Pizza só faz sentido com uma série; usa a primeira e ignora o
        # resto em vez de recusar o gráfico inteiro.
        name, values = series[0]
        ax.pie(
            values,
            labels=labels,
            autopct="%1.1f%%",
            colors=_palette(style, len(values)),
            textprops={"color": f"#{style.get('row_fg', '1F2933').lstrip('#')}"},
        )
        ax.axis("equal")
    elif chart_type == "line":
        for (name, values), color in zip(series, colors):
            ax.plot(labels, values, marker="o", label=name, color=color)
        ax.set_ylabel(str(chart_spec.get("y_label") or ""))
        if len(series) > 1:
            ax.legend()
        _rotate_labels(ax, labels)
    else:  # bar
        import numpy as np
        x = np.arange(len(labels))
        width = 0.8 / max(len(series), 1)
        for offset, ((name, values), color) in enumerate(zip(series, colors)):
            ax.bar(x + offset * width, values, width, label=name, color=color)
        ax.set_xticks(x + width * (len(series) - 1) / 2)
        ax.set_xticklabels(labels)
        ax.set_ylabel(str(chart_spec.get("y_label") or ""))
        if len(series) > 1:
            ax.legend()
        _rotate_labels(ax, labels)

    ax.set_xlabel(str(chart_spec.get("x_label") or "") if chart_type != "pie" else "")
    return _finish_figure(fig, ax, chart_spec.get("title"), style)


def _render_scatter(
    chart_spec: Dict[str, Any],
    columns: Sequence[str],
    rows: Sequence[list],
    style: Dict[str, str],
) -> Optional[bytes]:
    x_index = _column_index(columns, chart_spec.get("x_column"))
    if x_index is None:
        return None
    value_columns = chart_spec.get("value_columns")
    if not isinstance(value_columns, list) or not value_columns:
        return None

    x_values = _numeric_series(rows, x_index)
    series: List[tuple] = []
    for name in value_columns:
        index = _column_index(columns, name)
        if index is None:
            continue
        series.append((str(name), _numeric_series(rows, index)))
    if not series:
        return None

    colors = _palette(style, len(series))
    fig, ax = plt.subplots(figsize=_FIGSIZE)
    for (name, values), color in zip(series, colors):
        ax.scatter(x_values, values, label=name, color=color)
    ax.set_xlabel(str(chart_spec.get("x_label") or chart_spec.get("x_column") or ""))
    ax.set_ylabel(str(chart_spec.get("y_label") or ""))
    if len(series) > 1:
        ax.legend()
    return _finish_figure(fig, ax, chart_spec.get("title"), style)


def _rotate_labels(ax, labels: Sequence[str]) -> None:
    # Rótulos longos ou numerosos colam uns nos outros sem rotação.
    if len(labels) > 6 or any(len(str(label)) > 8 for label in labels):
        for tick in ax.get_xticklabels():
            tick.set_rotation(35)
            tick.set_ha("right")
