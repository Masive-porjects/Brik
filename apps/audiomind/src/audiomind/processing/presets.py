"""
Mastering preset definitions — CHARACTER + TARGETS.

Each preset defines the intended tonal character, compressor behavior,
saturation type, and target loudness. The engine dynamically calculates
DSP parameters based on input analysis (proportional mastering).
"""

from typing import Any

PRESET_CHAINS: dict[str, dict[str, Any]] = {
    "universal": {
        "display_name": "Pulido",
        "style": "Equilibrado",
        "description": "Balance tonal dinámico y natural.",
        "highpass_hz": 30,
        "eq_character": "equilibrado",
        "eq_bands": [
            {"freq": 250, "max_gain_db": -2.0, "q": 1.0, "type": "peak"},
            {"freq": 3000, "max_gain_db": 1.0, "q": 0.8, "type": "peak"},
        ],
        "compressor": {
            "ratio": 1.5,
            "attack_ms": 30,
            "release_ms": 200,
        },
        "saturation": None,
        "mono_below_hz": 120,
        "target_lufs": -14,
        "limiter_ceiling_db": -1.0,
        "target_genres": ["Rock", "Pop", "Electrónica", "Alternativa"],
    },
    "fuego": {
        "display_name": "Brutal",
        "style": "Impacto",
        "description": "Bajos impactantes y claridad de rango medio.",
        "highpass_hz": 25,
        "eq_character": "punch",
        "eq_bands": [
            {"freq": 80, "max_gain_db": 6.0, "q": 0.7, "type": "low_shelf"},
            {"freq": 250, "max_gain_db": -3.0, "q": 1.2, "type": "peak"},
            {"freq": 2500, "max_gain_db": 2.0, "q": 0.8, "type": "peak"},
        ],
        "compressor": {
            "ratio": 4.0,
            "attack_ms": 10,
            "release_ms": 100,
        },
        "saturation": {"type": "soft_clip", "drive_max": 1.5},
        "mono_below_hz": 120,
        "target_lufs": -12,
        "limiter_ceiling_db": -1.0,
        "target_genres": ["Trap", "Experimental", "Reguetón"],
    },
    "claridad": {
        "display_name": "Cristalino",
        "style": "Brillante",
        "description": "Agudos prístinos con una ligera expansión dinámica.",
        "spatial": "claridad",
        "highpass_hz": 40,
        "eq_character": "brillante",
        "eq_bands": [
            {"freq": 12000, "max_gain_db": 4.0, "q": 0.5, "type": "high_shelf"},
            {"freq": 3000, "max_gain_db": 1.5, "q": 0.7, "type": "peak"},
            {"freq": 400, "max_gain_db": -2.0, "q": 1.0, "type": "peak"},
        ],
        "compressor": {
            "ratio": 1.8,
            "attack_ms": 25,
            "release_ms": 180,
        },
        "saturation": None,
        "mono_below_hz": 100,
        "target_lufs": -13,
        "limiter_ceiling_db": -1.5,
        "target_genres": [
            "Clásica", "R&B", "Cantautor", "Jazz",
            "Alternativa", "Indie", "Rock",
        ],
    },
    "cinta": {
        "display_name": "Vintage",
        "style": "Analógico",
        "description": "Saturación cálida con dinámica analógica.",
        "highpass_hz": 35,
        "eq_character": "calido",
        "eq_bands": [
            {"freq": 200, "max_gain_db": 2.0, "q": 0.8, "type": "peak"},
            {"freq": 3000, "max_gain_db": 0.5, "q": 0.7, "type": "peak"},
            {"freq": 8000, "max_gain_db": -2.0, "q": 0.6, "type": "peak"},
        ],
        "compressor": {
            "ratio": 2.5,
            "attack_ms": 40,
            "release_ms": 300,
        },
        "saturation": {"type": "tape", "drive_max": 2.0},
        "mono_below_hz": 120,
        "target_lufs": -12,
        "limiter_ceiling_db": -1.0,
        "target_genres": ["Acústico", "Jazz", "Cantautor"],
    },
    "natural": {
        "display_name": "Crudo",
        "style": "Transparente",
        "description": "Dinámicas equilibradas y compresión suave.",
        "highpass_hz": 20,
        "eq_character": "transparente",
        "eq_bands": [],
        "compressor": {
            "ratio": 1.1,
            "attack_ms": 60,
            "release_ms": 400,
        },
        "saturation": None,
        "mono_below_hz": 80,
        "target_lufs": -14,
        "limiter_ceiling_db": -2.0,
        "target_genres": ["Ambiente", "Experimental", "Electrónica"],
    },
    "espacial": {
        "display_name": "Envolvente",
        "style": "Amplio",
        "description": "Reverberación atmosférica y amplitud de stereo mejorada.",
        "spatial": "espacial",
        "highpass_hz": 30,
        "eq_character": "brillante",
        "eq_bands": [
            {"freq": 8000, "max_gain_db": 2.5, "q": 0.5, "type": "high_shelf"},
            {"freq": 200, "max_gain_db": 1.0, "q": 0.8, "type": "peak"},
        ],
        "compressor": {
            "ratio": 1.6,
            "attack_ms": 30,
            "release_ms": 250,
        },
        "saturation": None,
        "stereo_width": 1.4,
        "mono_below_hz": 100,
        "target_lufs": -13,
        "limiter_ceiling_db": -1.0,
        "target_genres": ["Banda sonora", "Orquestal", "Clásica"],
    },
    "cinematico": {
        "display_name": "Épico",
        "style": "Pesado",
        "description": "Saturación intensa y distorsión armónica.",
        "highpass_hz": 25,
        "eq_character": "punch",
        "eq_bands": [
            {"freq": 60, "max_gain_db": 4.0, "q": 0.7, "type": "peak"},
            {"freq": 250, "max_gain_db": -2.0, "q": 1.0, "type": "peak"},
            {"freq": 4000, "max_gain_db": 3.0, "q": 0.8, "type": "peak"},
        ],
        "compressor": {
            "ratio": 5.0,
            "attack_ms": 8,
            "release_ms": 80,
        },
        "saturation": {"type": "tape", "drive_max": 3.0},
        "mono_below_hz": 120,
        "target_lufs": -12,
        "limiter_ceiling_db": -1.0,
        "target_genres": ["Hip-hop", "Trap", "R&B"],
    },
    "empuje": {
        "display_name": "Muro",
        "style": "Agresivo",
        "description": "Bajo enérgico combinado con agudos potenciados.",
        "highpass_hz": 20,
        "eq_character": "punch",
        "eq_bands": [
            {"freq": 60, "max_gain_db": 6.0, "q": 0.6, "type": "low_shelf"},
            {"freq": 250, "max_gain_db": -2.0, "q": 1.0, "type": "peak"},
            {"freq": 3000, "max_gain_db": 1.5, "q": 0.8, "type": "peak"},
            {"freq": 10000, "max_gain_db": 5.0, "q": 0.5, "type": "high_shelf"},
        ],
        "compressor": {
            "ratio": 6.0,
            "attack_ms": 6,
            "release_ms": 60,
        },
        "saturation": {"type": "soft_clip", "drive_max": 1.0},
        "mono_below_hz": 120,
        "target_lufs": -12,
        "limiter_ceiling_db": -1.0,
        "target_genres": ["EDM", "House", "Techno"],
    },
}


def get_preset(name: str) -> dict[str, Any] | None:
    """Get a preset definition by name."""
    return PRESET_CHAINS.get(name)


def list_presets() -> list[dict[str, Any]]:
    """List all available presets with summary info."""
    return [
        {
            "name": key,
            "display_name": val["display_name"],
            "style": val["style"],
            "description": val["description"],
            "target_genres": val.get("target_genres", []),
        }
        for key, val in PRESET_CHAINS.items()
    ]
