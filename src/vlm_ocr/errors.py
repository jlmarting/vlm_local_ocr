class VlmOcrError(Exception):
    """Error base del proyecto."""


class InputError(VlmOcrError):
    """Fichero de entrada, formato o OCR no procesable."""


class ContractError(VlmOcrError):
    """Contrato, instrucciones o modelo no válidos."""
