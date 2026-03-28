"""
仮名変換モジュール

歴史的仮名遣い、カタカナ助詞、変体仮名の変換を行う。
"""

from senzen_word.kana.historical import (
    KANA_MAPPINGS,
    convert_historical_kana,
    find_historical_kana,
)
from senzen_word.kana.katakana_particle import (
    COMPOUND_PARTICLES,
    SINGLE_PARTICLES,
    convert_katakana_particles,
    find_katakana_particles,
)
from senzen_word.kana.hentaigana import convert_hentaigana, find_hentaigana

__all__ = [
    "KANA_MAPPINGS",
    "convert_historical_kana",
    "find_historical_kana",
    "COMPOUND_PARTICLES",
    "SINGLE_PARTICLES",
    "convert_katakana_particles",
    "find_katakana_particles",
    "convert_hentaigana",
    "find_hentaigana",
]
