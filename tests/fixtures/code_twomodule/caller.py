"""Caller module containing an import/usage bug."""

from code_twomodule.util import formata_moeda


def gerar_recibo(item: str, preco: float) -> str:
    return f"Item: {item} - Total: {formata_moeda(preco)}"
