from __future__ import annotations

from vlm_ocr.extract import assign, merge
from vlm_ocr.types import LayoutBlock

SCHEMA = {
    "type": "object",
    "properties": {
        "nomina": {
            "type": "object",
            "properties": {
                "datos_generales": {
                    "type": "object",
                    "properties": {
                        "grupo_cotizacion": {"type": ["string", "null"], "x-labels": ["GRUPO"]}
                    },
                },
                "devengos": {
                    "type": "object",
                    "properties": {
                        "salario_base": {
                            "type": ["number", "null"],
                            "x-labels": ["SALARIO BASE"],
                            "x-source": "devengado",
                        },
                        "antiguedad": {
                            "type": "object",
                            "properties": {
                                "unidades": {
                                    "type": ["number", "null"],
                                    "x-labels": ["ANTIGÜEDAD"],
                                    "x-source": "unidades",
                                },
                                "importe": {
                                    "type": ["number", "null"],
                                    "x-labels": ["ANTIGÜEDAD"],
                                    "x-source": "devengado",
                                },
                            },
                        },
                        "horas_extras": {
                            "type": ["number", "null"],
                            "x-labels": ["HORAS EXTRAS"],
                            "x-source": "devengado",
                        },
                    },
                },
                "deducciones": {
                    "type": "object",
                    "properties": {
                        "irpf": {
                            "type": "object",
                            "properties": {
                                "retencion": {
                                    "type": ["number", "null"],
                                    "x-labels": ["RETENCION I.R.P.F."],
                                    "x-source": "a_deducir",
                                }
                            },
                        },
                        "total_deducciones": {
                            "type": ["number", "null"],
                            "x-labels": ["TOTAL DEDUCCIONES"],
                        },
                        "seguridad_social": {
                            "type": "object",
                            "properties": {
                                "contingencias_comunes": {
                                    "type": "object",
                                    "properties": {
                                        "base": {
                                            "type": ["number", "null"],
                                            "x-labels": ["CONTINGENCIAS COMUNES"],
                                            "x-source": "base",
                                        },
                                        "cuota": {
                                            "type": ["number", "null"],
                                            "x-labels": ["CONTINGENCIAS COMUNES"],
                                            "x-source": "cuota",
                                        },
                                    }
                                }
                            },
                        },
                    },
                },
            },
        }
    },
}


def _row(y: float, *cells: tuple[str, float, float]) -> list[LayoutBlock]:
    return [
        LayoutBlock(0, text, 1.0, (x0, y, x1, y + 10.0))
        for text, x0, x1 in cells
    ]


def _payslip() -> list[LayoutBlock]:
    blocks: list[LayoutBlock] = []
    blocks += _row(10, ("Concepto", 10, 60), ("Unidades", 100, 140), ("Importe", 160, 200), ("Devengado", 220, 280), ("A Deducir", 300, 340))
    blocks += _row(30, ("SALARIO BASE", 10, 90), ("30,00", 100, 130), ("80,2297", 160, 200), ("2.406,89", 220, 280))
    blocks += _row(50, ("ANTIGÜEDAD (1,00 Unidad)", 10, 90), ("30,00", 100, 130), ("1,6463", 160, 200), ("49,39", 220, 280))
    blocks += _row(70, ("RETENCION I.R.P.F.", 10, 90), ("17,00", 100, 130), ("2.610,2400", 160, 200), ("443,74", 300, 340))
    blocks += _row(90, ("Total Deducciones", 10, 90), ("640,40", 220, 280))
    blocks += _row(110, ("GRUPO", 10, 60), ("3", 100, 130), ("Bases", 160, 190), ("%", 200, 210), ("Cuota", 220, 250), ("Bases", 300, 330), ("%", 340, 350), ("Cuota", 360, 390))
    blocks += _row(130, ("Contingencias Comunes", 10, 90), ("3.025,62", 160, 190), ("4,70", 200, 210), ("142,20", 220, 250), ("3.025,62", 300, 330), ("23,60", 340, 350), ("714,05", 360, 390))
    return blocks


def test_header_decides_the_column_for_each_field() -> None:
    assignment = assign(_payslip(), SCHEMA)

    devengos = assignment.data["nomina"]["devengos"]
    assert devengos["salario_base"] == 2406.89
    assert devengos["antiguedad"] == {"unidades": 30.0, "importe": 49.39}
    assert devengos["horas_extras"] is None


def test_column_with_gaps_still_matches_by_position_of_header() -> None:
    assignment = assign(_payslip(), SCHEMA)

    assert assignment.data["nomina"]["deducciones"]["irpf"]["retencion"] == 443.74
    assert assignment.data["nomina"]["deducciones"]["total_deducciones"] == 640.4


def test_bases_table_uses_the_worker_triplet() -> None:
    assignment = assign(_payslip(), SCHEMA)

    cc = assignment.data["nomina"]["deducciones"]["seguridad_social"]["contingencias_comunes"]
    assert cc == {"base": 3025.62, "cuota": 142.2}


def test_string_with_numeric_value_keeps_its_label() -> None:
    assignment = assign(_payslip(), SCHEMA)

    assert assignment.data["nomina"]["datos_generales"]["grupo_cotizacion"] == "GRUPO 3"


def test_missing_concepts_are_unmatched() -> None:
    assignment = assign(_payslip(), SCHEMA)

    assert "nomina.devengos.horas_extras" in assignment.unmatched
    assert "nomina.devengos.salario_base" in assignment.matched


def test_without_header_cells_are_taken_by_index() -> None:
    blocks = [
        LayoutBlock(0, "Concepto | Unidades | Importe | Devengado | A Deducir", 1.0, (0.0, 0.0, 0.0, 0.0)),
        LayoutBlock(0, "SALARIO BASE | 30,00 | 80,2297 | 2.406,89", 1.0, (0.0, 0.0, 0.0, 0.0)),
    ]

    assignment = assign(blocks, SCHEMA)

    assert assignment.data["nomina"]["devengos"]["salario_base"] == 2406.89


def test_merge_prefers_deterministic_values() -> None:
    merged = merge({"a": 1, "b": {"c": 2}}, {"a": 99, "b": {"c": 3, "d": 4}})

    assert merged == {"a": 1, "b": {"c": 2, "d": 4}}


def test_value_under_a_vertical_header_is_assigned() -> None:
    blocks = [
        LayoutBlock(0, "Total Devengado", 1.0, (390.0, 10.0, 465.0, 20.0)),
        LayoutBlock(0, "Total Deducciones", 1.0, (480.0, 10.0, 560.0, 20.0)),
        LayoutBlock(0, "2.705,74", 1.0, (435.0, 30.0, 465.0, 40.0)),
        LayoutBlock(0, "640,40", 1.0, (530.0, 30.0, 558.0, 40.0)),
    ]

    assignment = assign(blocks, SCHEMA)

    assert assignment.data["nomina"]["deducciones"]["total_deducciones"] == 640.4


def test_vertical_header_expires_after_two_rows() -> None:
    blocks = [
        LayoutBlock(0, "Total Deducciones", 1.0, (480.0, 10.0, 560.0, 20.0)),
        LayoutBlock(0, "otra fila", 1.0, (10.0, 30.0, 90.0, 40.0)),
        LayoutBlock(0, "otra mas", 1.0, (10.0, 50.0, 90.0, 60.0)),
        LayoutBlock(0, "640,40", 1.0, (530.0, 70.0, 558.0, 80.0)),
    ]

    assignment = assign(blocks, SCHEMA)

    assert assignment.data["nomina"]["deducciones"]["total_deducciones"] is None
