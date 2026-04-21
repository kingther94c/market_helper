from __future__ import annotations

from dataclasses import dataclass
import html
from typing import Mapping, Sequence


@dataclass(frozen=True)
class HtmlTableColumn:
    key: str
    label: str
    align: str = "start"
    allow_html: bool = False
    header_class: str = ""
    cell_class: str = ""


@dataclass(frozen=True)
class HtmlTableRow:
    cells: Mapping[str, str | None]
    row_class: str = ""


def render_html_table(
    *,
    columns: Sequence[HtmlTableColumn],
    rows: Sequence[HtmlTableRow],
    empty_message: str = "No data",
    table_class: str = "report-table",
    wrapper_class: str = "report-table-wrap",
    fixed_columns: int = 0,
    tail_columns: int = 0,
    data_attributes: Mapping[str, str] | None = None,
) -> str:
    wrapper_attrs = [f"class='{html.escape(wrapper_class)}'"]
    if fixed_columns > 0:
        wrapper_attrs.append(f"data-fixed-columns='{fixed_columns}'")
    if tail_columns > 0:
        wrapper_attrs.append(f"data-tail-columns='{tail_columns}'")
    if data_attributes:
        for key, value in data_attributes.items():
            wrapper_attrs.append(f"data-{html.escape(key)}='{html.escape(value, quote=True)}'")

    header_cells = "".join(
        _render_header_cell(column)
        for column in columns
    )
    if rows:
        body_rows = "".join(_render_row(columns, row) for row in rows)
    else:
        body_rows = (
            "<tr class='report-table__empty'>"
            f"<td colspan='{len(columns)}'>{html.escape(empty_message)}</td>"
            "</tr>"
        )

    return (
        f"<div {' '.join(wrapper_attrs)}>"
        f"<table class='{html.escape(table_class)}'>"
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{body_rows}</tbody>"
        "</table>"
        "</div>"
    )


def _render_header_cell(column: HtmlTableColumn) -> str:
    classes = _join_classes("report-table__header", _align_class(column.align), column.header_class)
    return f"<th class='{classes}'>{html.escape(column.label)}</th>"


def _render_row(columns: Sequence[HtmlTableColumn], row: HtmlTableRow) -> str:
    row_class = _join_classes("report-table__row", row.row_class)
    cells = "".join(_render_cell(column, row.cells.get(column.key)) for column in columns)
    return f"<tr class='{row_class}'>{cells}</tr>"


def _render_cell(column: HtmlTableColumn, value: str | None) -> str:
    classes = _join_classes("report-table__cell", _align_class(column.align), column.cell_class)
    if value is None:
        rendered = "n/a"
    elif column.allow_html:
        rendered = value
    else:
        rendered = html.escape(value)
    return f"<td class='{classes}'>{rendered}</td>"


def _align_class(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"end", "right", "num", "numeric"}:
        return "is-num"
    if normalized in {"center", "middle"}:
        return "is-center"
    return "is-start"


def _join_classes(*values: str) -> str:
    return " ".join(value for value in values if value).strip()
