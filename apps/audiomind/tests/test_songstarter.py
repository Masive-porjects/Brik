"""Tests for SongStarter — BeatGenerator (Module D, Phase 5)."""
import sys

sys.path.insert(0, "src")

import numpy as np

from audiomind.processing.songstarter import BeatGenerator


class TestBeatGenerator:
    """Unit tests for BeatGenerator — pattern grid, swing, modes, synthesis."""

    # ── 5.1 Unit: Pattern grid + swing ────────────────────────────────────

    def test_generate_drum_pattern_length(self):
        """16 steps per bar in 4/4 — step values must be in 0..15 range."""
        g = BeatGenerator()
        pattern = g.generate_drum_pattern(120, 0.0, num_bars=1)
        for stem, events in pattern.items():
            assert len(events) > 0, f"{stem} no produjo eventos"
            for ev in events:
                assert 0 <= ev["step"] < 16, (
                    f"{stem} step {ev['step']} fuera de rango (esperado 0-15)"
                )

    def test_drum_pattern_has_required_stems(self):
        """Devuelve todos los stems necesarios."""
        g = BeatGenerator()
        pattern = g.generate_drum_pattern(120, 0.3)
        required = {'kick', 'snare', 'hihat_closed', 'hihat_open', 'clap'}
        assert required == set(pattern.keys()), (
            f"Stems faltantes: {required - set(pattern.keys())}"
        )

    def test_kick_four_on_floor(self):
        """Kick en los cuatro downbeats (steps 0, 4, 8, 12)."""
        g = BeatGenerator()
        pattern = g.generate_drum_pattern(120, 0.0, num_bars=1)
        kick_steps = {ev["step"] for ev in pattern["kick"]}
        for s in [0, 4, 8, 12]:
            assert s in kick_steps, (
                f"Four-on-the-floor: step {s} no encontrado en kick"
            )

    def test_swing_shifts_even_steps(self):
        """Swing desplaza timing de los steps pares en hihat."""
        g = BeatGenerator()
        no_swing = g.generate_drum_pattern(120, 0.0, num_bars=1)
        with_swing = g.generate_drum_pattern(120, 0.7, num_bars=1)
        no_times = [ev["timing_offset_s"] for ev in no_swing["hihat_closed"]]
        swing_times = [ev["timing_offset_s"] for ev in with_swing["hihat_closed"]]
        assert no_times != swing_times, "Swing debería alterar el timing del hihat"

    def test_different_bpms_produce_valid_patterns(self):
        """BPMs extremos producen patrones válidos (no crashea)."""
        g = BeatGenerator()
        for bpm in [60, 180]:
            pattern = g.generate_drum_pattern(bpm, 0.0)
            assert len(pattern['kick']) > 0
            assert len(pattern['snare']) > 0
            assert len(pattern['hihat_closed']) > 0

    # ── 5.2 Unit: Harmonic modes ─────────────────────────────────────────

    def test_all_modes_produce_intervals(self):
        """Todos los modos devuelven notas sin vacíos."""
        g = BeatGenerator()
        modes = [
            'major', 'natural_minor', 'harmonic_minor', 'melodic_minor',
            'dorian', 'phrygian', 'lydian', 'mixolydian',
            'locrian', 'blues', 'pentatonic_major', 'pentatonic_minor',
        ]
        for mode in modes:
            notes = g.generate_bass_pattern(120, mode, 'C')
            assert len(notes) > 0, f"Modo {mode} no produjo notas"
            # Primera nota debería ser la tónica (C = MIDI 60 o 48 con octave offset)
            first_midi = notes[0]["midi"]
            assert first_midi % 12 == 0, (
                f"Primera nota de {mode} no es C (midi={first_midi})"
            )

    def test_different_roots_produce_different_bass(self):
        """Tónicas distintas producen patrones de bajo distintos."""
        g = BeatGenerator()
        bass_c = g.generate_bass_pattern(120, 'major', 'C')
        bass_d = g.generate_bass_pattern(120, 'major', 'D')
        c_first = bass_c[0]["midi"]
        d_first = bass_d[0]["midi"]
        assert c_first != d_first, (
            f"Distintas tónicas deberían dar distinto midi: C={c_first}, D={d_first}"
        )

    # ── 5.3 Unit: Synthesis produces valid audio ──────────────────────────

    def test_synthesize_drums_returns_stereo(self):
        """synthesize_drums devuelve dict de arrays 2D (2, samples) estéreo."""
        g = BeatGenerator()
        pattern = g.generate_drum_pattern(120, 0.3, num_bars=1)
        stems = g.synthesize_drums(pattern, 44100)
        assert len(stems) > 0, "No se produjeron stems"
        for name, audio in stems.items():
            assert audio.ndim == 2, (
                f"Stem {name}: esperaba 2D, got {audio.ndim}D"
            )
            assert audio.shape[0] == 2, (
                f"Stem {name}: esperaba 2 canales, got {audio.shape[0]}"
            )
            assert audio.shape[1] > 0, f"Stem {name}: audio vacío"

    def test_synthesize_bass_returns_stereo(self):
        """synthesize_bass devuelve array 2D (2, samples) estéreo con señal."""
        g = BeatGenerator()
        notes = g.generate_bass_pattern(120, 'major', 'C')
        audio = g.synthesize_bass(notes, 120, 44100)
        assert audio.ndim == 2, f"Esperaba 2D, got {audio.ndim}D"
        assert audio.shape[0] == 2, f"Esperaba 2 canales, got {audio.shape[0]}"
        assert audio.shape[1] > 0, "Audio vacío"
        assert np.max(np.abs(audio)) > 0, "Bass no produce señal"
