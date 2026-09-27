"""SongStarter — Algorithmic Beat Engine.

Generates rhythmic and harmonic foundations from BPM, scale, and pattern
parameters. Uses sample-based drum synthesis with Pedalboard post-processing.

Phase 1-2: Infra + Core Engine (no API layer yet).
"""

from __future__ import annotations

import random
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import pedalboard
from pedalboard import (
    Compressor,
    Distortion,
    HighShelfFilter,
    Limiter,
    LowpassFilter,
)

# pedalboard's __init__ re-exports Pedalboard via a plain named import and
# defines no __all__; with implicit_reexport=False (mypy strict) the name is
# not treated as exported. Bind the module attribute explicitly — identical
# runtime behavior, satisfies mypy.
Pedalboard = pedalboard.Pedalboard

from audiomind.config import settings

# ── Types ────────────────────────────────────────────────────────────────
SampleBuffer = np.ndarray  # 1-D float32 array
AudioArray = np.ndarray    # (channels, samples) float32

# ── Scale Intervals (12 modes) ──────────────────────────────────────────
SCALE_INTERVALS: dict[str, list[int]] = {
    "major":              [0, 2, 4, 5, 7, 9, 11],
    "natural_minor":      [0, 2, 3, 5, 7, 8, 10],
    "harmonic_minor":     [0, 2, 3, 5, 7, 8, 11],
    "melodic_minor":      [0, 2, 3, 5, 7, 9, 11],
    "dorian":             [0, 2, 3, 5, 7, 9, 10],
    "phrygian":           [0, 1, 3, 5, 7, 8, 10],
    "lydian":             [0, 2, 4, 6, 7, 9, 11],
    "mixolydian":         [0, 2, 4, 5, 7, 9, 10],
    "locrian":            [0, 1, 3, 5, 6, 8, 10],
    "blues":              [0, 3, 5, 6, 7, 10],
    "pentatonic_major":   [0, 2, 4, 7, 9],
    "pentatonic_minor":   [0, 3, 5, 7, 10],
}

# ── Note name → MIDI mapping (C4 = 60) ───────────────────────────────────
NOTE_TO_MIDI: dict[str, int] = {
    "C": 60, "C#": 61, "Db": 61,
    "D": 62, "D#": 63, "Eb": 63,
    "E": 64, "F": 65, "F#": 66, "Gb": 66,
    "G": 67, "G#": 68, "Ab": 68,
    "A": 69, "A#": 70, "Bb": 70,
    "B": 71,
}

# ── Chord quality intervals (relative to root) ──────────────────────────
CHORD_TYPES: dict[str, list[int]] = {
    "major":       [0, 4, 7],
    "minor":       [0, 3, 7],
    "diminished":  [0, 3, 6],
    "augmented":   [0, 4, 8],
    "major7":      [0, 4, 7, 11],
    "minor7":      [0, 3, 7, 10],
    "dominant7":   [0, 4, 7, 10],
    "dim7":        [0, 3, 6, 9],
}

# Degree → chord type mapping per mode
_DEGREE_CHORDS: dict[str, list[str]] = {
    "major":             ["major", "minor", "minor", "major", "major", "minor", "diminished"],
    "natural_minor":     ["minor", "diminished", "major", "minor", "minor", "major", "major"],
    "harmonic_minor":    ["minor", "diminished", "augmented", "minor", "major", "major", "diminished"],
    "melodic_minor":     ["minor", "minor", "augmented", "major", "major", "diminished", "diminished"],
    "dorian":            ["minor", "minor", "major", "minor", "minor", "diminished", "major"],
    "phrygian":          ["minor", "major", "major", "minor", "diminished", "diminished", "major"],
    "lydian":            ["major", "major", "minor", "diminished", "major", "minor", "minor"],
    "mixolydian":        ["major", "minor", "diminished", "major", "minor", "minor", "major"],
    "locrian":           ["diminished", "major", "minor", "minor", "major", "major", "minor"],
    "blues":             ["major", "minor", "major", "major", "minor", "major"],
    "pentatonic_major":  ["major", "major", "minor", "major", "minor"],
    "pentatonic_minor":  ["minor", "major", "minor", "minor", "major"],
}

# I, IV, V, vi degree indices (0-based) per mode
_DEGREE_MAP: dict[str, list[int]] = {
    "major":             [0, 3, 4, 5],
    "natural_minor":     [0, 3, 4, 5],
    "harmonic_minor":    [0, 3, 4, 5],
    "melodic_minor":     [0, 3, 4, 5],
    "dorian":            [0, 3, 4, 5],
    "phrygian":          [0, 3, 4, 5],
    "lydian":            [0, 3, 4, 5],
    "mixolydian":        [0, 3, 4, 5],
    "locrian":           [0, 3, 4, 5],
    "blues":             [0, 3, 4, 5],
    "pentatonic_major":  [0, 3, 2, 4],
    "pentatonic_minor":  [0, 3, 2, 4],
}


def _midi_to_freq(midi: int) -> float:
    """Convert MIDI note number to frequency in Hz."""
    return 440.0 * (2 ** ((midi - 69) / 12))


def _note_name_to_midi(name: str) -> int:
    """Convert note name to MIDI number (C4 = 60).

    Accepts formats: ``"C"``, ``"C#"``, ``"Bb"``, etc.
    """
    name = name.strip().capitalize()
    if name in NOTE_TO_MIDI:
        return NOTE_TO_MIDI[name]
    # Try alternate spelling
    for key, val in NOTE_TO_MIDI.items():
        if key.startswith(name[0]):
            return val
    return 60  # fallback to C


def _apply_fade(audio: np.ndarray, fade_n: int) -> np.ndarray:
    """Apply a linear fade-in/fade-out to prevent clicks.

    Handles both mono ``(samples,)`` and stereo ``(channels, samples)`` arrays.
    """
    out = audio.copy()
    if fade_n <= 0:
        return out

    n_fade = min(fade_n, out.shape[-1])
    fade_in = np.linspace(0, 1, n_fade, dtype=np.float32)
    fade_out = np.linspace(1, 0, n_fade, dtype=np.float32)

    if out.ndim == 1:
        out[:n_fade] *= fade_in
        out[-n_fade:] *= fade_out
    elif out.ndim == 2:
        out[:, :n_fade] *= fade_in[np.newaxis, :]
        out[:, -n_fade:] *= fade_out[np.newaxis, :]

    return out


def _velocity_to_gain(velocity: float) -> float:
    """Map velocity 0.0-1.0 to linear gain with natural curve."""
    return 0.3 + 0.7 * (velocity ** 2)


# ═══════════════════════════════════════════════════════════════════════════
# BeatGenerator
# ═══════════════════════════════════════════════════════════════════════════

class BeatGenerator:
    """Algorithmic beat engine — drum patterns, bass lines, chord progressions.

    Usage::

        gen = BeatGenerator()
        result = gen.generate_beat(120, "major", "C", swing_amount=0.3)
        print(result["output_path"])
    """

    # ── Sample cache ─────────────────────────────────────────────────────
    _samples: dict[str, SampleBuffer] = {}

    def _load_sample(self, name: str, sr: int = 44100) -> SampleBuffer:
        """Load a drum sample from ``settings.samples_dir``, cached."""
        if name in self._samples:
            return self._samples[name]

        path = settings.samples_dir / name
        if not path.exists():
            raise FileNotFoundError(
                f"Sample not found: {path}. Run scripts/generate_samples.py first."
            )

        audio, file_sr = sf.read(str(path))
        # Resample if needed (simple linear)
        if file_sr != sr:
            ratio = sr / file_sr
            n_new = int(len(audio) * ratio)
            audio = np.interp(
                np.linspace(0, len(audio) - 1, n_new),
                np.arange(len(audio)),
                audio,
            )

        self._samples[name] = audio.astype(np.float32)
        return self._samples[name]

    # ── 2.1 Drum Pattern Generation ──────────────────────────────────────

    def generate_drum_pattern(
        self,
        bpm: float,
        swing_amount: float = 0.3,
        num_bars: int = 2,
    ) -> dict[str, list[dict[str, Any]]]:
        """Generate a drum pattern as a dict of step events.

        Each stem has a list of dicts::

            {"step": int, "velocity": float, "timing_offset_s": float}

        Args:
            bpm: Beats per minute.
            swing_amount: Swing intensity 0.0-1.0.
            num_bars: Number of bars (default 2 → 32 sixteenths).

        Returns:
            ``{"kick": [...], "snare": [...], "hihat_closed": [...],
              "hihat_open": [...], "clap": [...]}``
        """
        steps_per_bar = 16
        total_steps = steps_per_bar * num_bars
        beat_duration = 60.0 / bpm
        step_duration = beat_duration / 4.0  # 16th note

        seed = random.randint(0, 2 ** 16)

        def _step_time(step: int) -> float:
            """Return absolute time in seconds for a step, with swing applied."""
            t = step * step_duration
            # Swing: shift even 16th notes within each beat
            beat_16th = step % 4  # 0,1,2,3 within each quarter
            if beat_16th == 1 or beat_16th == 3:  # even 8th note subdivisions
                t += swing_amount * 0.03  # shift forward
            return t

        def _humanize(v: float, jitter_s: float = 0.002) -> tuple[float, float]:
            """Apply velocity (±15%) and timing jitter (±jitter_s)."""
            v = v * random.uniform(0.85, 1.15)
            j = random.uniform(-jitter_s, jitter_s)
            return max(0.0, min(1.0, v)), j

        rng = random.Random(seed)

        pattern: dict[str, list[dict[str, Any]]] = {
            "kick": [],
            "snare": [],
            "hihat_closed": [],
            "hihat_open": [],
            "clap": [],
        }

        for bar in range(num_bars):
            offset = bar * steps_per_bar

            # ── Kick: four-on-the-floor ──────────────────────────────────
            for beat in range(4):
                step = offset + beat * 4
                vel = rng.uniform(0.85, 1.0)
                # Occasionally skip a kick (open hi-hat feel)
                if bar > 0 and rng.random() < 0.05:
                    continue
                v, jit = _humanize(vel)
                pattern["kick"].append({
                    "step": step,
                    "velocity": v,
                    "timing_offset_s": _step_time(step) + jit,
                })

            # Occasional ghost kick on offbeats
            for _ in range(rng.randint(0, 2)):
                off_step = offset + rng.choice([2, 6, 10, 14])
                if not any(e["step"] == off_step for e in pattern["kick"]):
                    v, jit = _humanize(0.4)
                    pattern["kick"].append({
                        "step": off_step,
                        "velocity": v,
                        "timing_offset_s": _step_time(off_step) + jit,
                    })

            # ── Snare: backbeat (beats 2 & 4) ────────────────────────────
            for beat in [1, 3]:  # 2nd and 4th beat (0-indexed)
                step = offset + beat * 4
                v, jit = _humanize(0.95)
                pattern["snare"].append({
                    "step": step,
                    "velocity": v,
                    "timing_offset_s": _step_time(step) + jit,
                })

            # Snare ghost notes on offbeats
            ghost_positions = [1, 3, 5, 7, 9, 11, 13, 15]
            for pos in ghost_positions:
                if rng.random() < 0.2:
                    step = offset + pos
                    v, jit = _humanize(rng.uniform(0.15, 0.35))
                    pattern["snare"].append({
                        "step": step,
                        "velocity": v,
                        "timing_offset_s": _step_time(step) + jit,
                    })

            # ── Hi-hat closed: all 8th notes ─────────────────────────────
            for pos in range(steps_per_bar):
                step = offset + pos
                if pos % 2 == 0:  # on-beat 8th
                    vel = rng.uniform(0.7, 0.9)
                else:  # off-beat 8th
                    vel = rng.uniform(0.4, 0.6)
                v, jit = _humanize(vel)
                pattern["hihat_closed"].append({
                    "step": step,
                    "velocity": v,
                    "timing_offset_s": _step_time(step) + jit,
                })

            # ── Hi-hat open: open on specific steps ──────────────────────
            for step_idx in [8, 9]:  # downbeat of second half + next 16th
                step = offset + step_idx
                v, jit = _humanize(0.8)
                pattern["hihat_open"].append({
                    "step": step,
                    "velocity": v,
                    "timing_offset_s": _step_time(step) + jit,
                })

            # Occasional open hi-hat accents
            if rng.random() < 0.3:
                extra = offset + rng.choice([2, 6, 12, 14])
                v, jit = _humanize(0.5)
                pattern["hihat_open"].append({
                    "step": extra,
                    "velocity": v,
                    "timing_offset_s": _step_time(extra) + jit,
                })

            # ── Clap: same as snare but with flam ────────────────────────
            for beat in [1, 3]:
                step = offset + beat * 4
                v, jit = _humanize(0.85)
                pattern["clap"].append({
                    "step": step,
                    "velocity": v,
                    "timing_offset_s": _step_time(step) + jit,
                })

            # Clap flam (slightly before the main clap)
            for beat in [1, 3]:
                step = offset + beat * 4
                flam_time = _step_time(step) - 0.015 + random.uniform(-0.002, 0.002)
                v = rng.uniform(0.2, 0.4)
                pattern["clap"].append({
                    "step": step,
                    "velocity": v,
                    "timing_offset_s": flam_time,
                })

        return pattern

    # ── 2.2 Bass Pattern Generation ──────────────────────────────────────

    def generate_bass_pattern(
        self,
        bpm: float,
        scale: str,
        root_note: str,
        num_bars: int = 4,
    ) -> list[dict[str, Any]]:
        """Generate a bass note sequence.

        Each note::

            {"midi": int, "start_s": float, "duration_s": float, "velocity": float}

        Args:
            bpm: Beats per minute.
            scale: Scale name (see ``SCALE_INTERVALS``).
            root_note: Root note name (e.g. ``"C"``, ``"F#"``).
            num_bars: Number of bars.

        Returns:
            List of note dicts.
        """
        intervals = SCALE_INTERVALS.get(scale, SCALE_INTERVALS["major"])
        root_midi = _note_name_to_midi(root_note)
        beat_duration = 60.0 / bpm
        bar_duration = beat_duration * 4
        total_duration = bar_duration * num_bars

        notes: list[dict[str, Any]] = []

        rng = random.Random(hash(f"bass-{bpm}-{scale}-{root_note}"))

        for bar in range(num_bars):
            bar_start = bar * bar_duration

            # Beat 1: Root (tonic)
            midi = root_midi + intervals[0]
            # Decide octave: alternate between root octave and one octave down
            octave_offset = -12 if bar % 2 == 0 else 0
            notes.append({
                "midi": midi + octave_offset,
                "start_s": bar_start,
                "duration_s": beat_duration * rng.uniform(0.5, 1.0),
                "velocity": rng.uniform(0.7, 0.9),
            })

            # Beat 2: Walking note (nearby scale degree)
            degree = rng.choice([1, 2, 6])
            midi = root_midi + intervals[degree % len(intervals)]
            notes.append({
                "midi": midi + octave_offset,
                "start_s": bar_start + beat_duration,
                "duration_s": beat_duration * rng.uniform(0.3, 0.8),
                "velocity": rng.uniform(0.5, 0.7),
            })

            # Beat 3: 5th (dominant)
            midi = root_midi + intervals[4]  # 5th degree
            notes.append({
                "midi": midi + octave_offset,
                "start_s": bar_start + beat_duration * 2,
                "duration_s": beat_duration * rng.uniform(0.5, 1.0),
                "velocity": rng.uniform(0.7, 0.85),
            })

            # Beat 4: Walking or leading tone
            degree = rng.choice([5, 6, 0])
            midi = root_midi + intervals[degree % len(intervals)]
            if degree == 0 and bar < num_bars - 1:
                # Leading to next bar's root
                midi -= 1  # half-step below
            notes.append({
                "midi": midi + octave_offset,
                "start_s": bar_start + beat_duration * 3,
                "duration_s": beat_duration * rng.uniform(0.3, 0.6),
                "velocity": rng.uniform(0.5, 0.7),
            })

        return notes

    # ── 2.3 Chord Pattern Generation ─────────────────────────────────────

    def generate_chord_pattern(
        self,
        bpm: float,
        scale: str,
        root_note: str,
        num_bars: int = 8,
    ) -> list[dict[str, Any]]:
        """Generate a chord progression.

        Each chord::

            {"midi_notes": list[int], "start_s": float, "duration_s": float}

        Typical progression: I-IV-V-vi, each chord lasting 2 bars.

        Args:
            bpm: Beats per minute.
            scale: Scale name.
            root_note: Root note.
            num_bars: Total bars.

        Returns:
            List of chord dicts.
        """
        intervals = SCALE_INTERVALS.get(scale, SCALE_INTERVALS["major"])
        root_midi = _note_name_to_midi(root_note)
        beat_duration = 60.0 / bpm
        bar_duration = beat_duration * 4
        total_duration = bar_duration * num_bars

        # Get chord types per degree for this mode
        degree_chords = _DEGREE_CHORDS.get(scale, _DEGREE_CHORDS["major"])
        degree_indices = _DEGREE_MAP.get(scale, _DEGREE_MAP["major"])

        chords: list[dict[str, Any]] = []

        # Build a 4-chord progression
        # I → IV → V → vi  (or I → vi → IV → V)
        progression_choices = [
            [0, 3, 4, 5],   # I - IV - V - vi
            [0, 5, 3, 4],   # I - vi - IV - V
            [0, 4, 5, 3],   # I - V - IV - vi
        ]
        rng = random.Random(hash(f"chord-{bpm}-{scale}-{root_note}"))
        prog_degrees = rng.choice(progression_choices)

        chords_per_bar = num_bars // 4  # each chord gets (num_bars/4) bars
        if chords_per_bar < 1:
            chords_per_bar = 1

        for i, degree_idx in enumerate(prog_degrees[:4]):
            if degree_idx >= len(degree_chords):
                continue
            chord_type = degree_chords[degree_idx]
            if chord_type not in CHORD_TYPES:
                chord_type = "major"

            # Root of this chord
            chord_root_midi = root_midi + intervals[degree_idx % len(intervals)]
            chord_intervals = CHORD_TYPES[chord_type]

            # Build chord notes
            midi_notes = [chord_root_midi + iv for iv in chord_intervals]
            # Spread across octaves: put some notes up an octave
            if len(midi_notes) >= 3:
                midi_notes[1] += 12  # 3rd up one octave
                if len(midi_notes) >= 4:
                    midi_notes[3] += 12  # 7th up one octave

            start_s = i * chords_per_bar * bar_duration
            duration_s = chords_per_bar * bar_duration

            chords.append({
                "midi_notes": sorted(set(midi_notes)),
                "start_s": start_s,
                "duration_s": duration_s,
            })

        return chords

    # ── 2.4 Synthesize Drums ─────────────────────────────────────────────

    def synthesize_drums(
        self,
        pattern: dict[str, list[dict[str, Any]]],
        sample_rate: int = 44100,
    ) -> dict[str, np.ndarray]:
        """Synthesize drum stems from a pattern.

        Args:
            pattern: Output of ``generate_drum_pattern()``.
            sample_rate: Output sample rate in Hz.

        Returns:
            ``{"kick": ndarray, "snare": ndarray, "hihat_closed": ndarray,
              "hihat_open": ndarray, "clap": ndarray}``

            Each array is stereo ``(2, samples)``.
        """
        # Calculate total duration from the last event
        last_time = 0.0
        for stem_events in pattern.values():
            for ev in stem_events:
                t = ev["timing_offset_s"]
                last_time = max(last_time, t)

        # Better: compute total length from pattern
        # 4 bars = 4 * (60/bpm) * 4 beats = 16 * (60/bpm)
        # We'll just use a generous fixed duration: 8 seconds at 120 BPM (2 bars)
        # Actually, we can infer from max timing_offset
        for stem_events in pattern.values():
            for ev in stem_events:
                last_time = max(last_time, ev["timing_offset_s"])

        total_samples = int(last_time * sample_rate) + sample_rate * 2  # 2s padding
        total_samples = max(total_samples, int(4 * sample_rate))  # at least 4s

        # Sample name mapping
        stem_files = {
            "kick": "kick.wav",
            "snare": "snare.wav",
            "hihat_closed": "hihat-closed.wav",
            "hihat_open": "hihat-open.wav",
            "clap": "clap.wav",
        }

        stems: dict[str, np.ndarray] = {}

        for stem_name, sf_name in stem_files.items():
            if stem_name not in pattern:
                continue
            sample = self._load_sample(sf_name, sample_rate)

            # Normalize sample to prevent DC offset / level issues
            peak = np.max(np.abs(sample)) or 1.0
            sample = sample / peak

            stem_audio = np.zeros((2, total_samples), dtype=np.float32)

            for ev in pattern[stem_name]:
                vel = ev["velocity"]
                t_offset = ev["timing_offset_s"]
                start_idx = int(t_offset * sample_rate)

                if start_idx >= total_samples:
                    continue

                # Apply velocity gain
                gain = _velocity_to_gain(vel)
                hit = sample * gain

                # Apply per-hit envelope (fast attack, natural decay)
                if len(hit) > 0:
                    env = np.exp(-np.linspace(0, 8, len(hit)))  # gentle decay
                    hit = hit * env

                # Place in stereo field
                # Kick and snare: center; hihat: slightly right; clap: left
                if stem_name == "hihat_closed" or stem_name == "hihat_open":
                    pan = 0.3  # right
                    left_gain = 1.0 - pan
                    right_gain = pan
                elif stem_name == "clap":
                    pan = -0.2  # slightly left
                    left_gain = 1.0 + pan
                    right_gain = 1.0 - abs(pan)
                else:
                    left_gain = 1.0
                    right_gain = 1.0

                # Clamp to valid range (prevent negative indices from jitter)
                if start_idx < 0:
                    start_idx = 0
                end_idx = min(start_idx + len(hit), total_samples)
                hlen = end_idx - start_idx

                if hlen <= 0:
                    continue

                stem_audio[0, start_idx:end_idx] += hit[:hlen] * left_gain
                stem_audio[1, start_idx:end_idx] += hit[:hlen] * right_gain

            # Soft clip to prevent harsh distortion from summing
            stem_audio = np.tanh(stem_audio)
            stems[stem_name] = stem_audio

        return stems

    # ── 2.5 Synthesize Bass ──────────────────────────────────────────────

    def synthesize_bass(
        self,
        notes: list[dict[str, Any]],
        bpm: float,
        sample_rate: int = 44100,
    ) -> np.ndarray:
        """Synthesize a bass line from a note sequence.

        Args:
            notes: Output of ``generate_bass_pattern()``.
            bpm: Beats per minute.
            sample_rate: Output sample rate.

        Returns:
            Stereo array ``(2, samples)``.
        """
        if not notes:
            return np.zeros((2, int(sample_rate * 2)), dtype=np.float32)

        # Calculate total duration
        last_end = 0.0
        for n in notes:
            end = n["start_s"] + n["duration_s"]
            last_end = max(last_end, end)

        total_samples = int(last_end * sample_rate) + int(0.5 * sample_rate)
        audio = np.zeros((2, total_samples), dtype=np.float32)

        for n in notes:
            midi = n["midi"]
            freq = _midi_to_freq(midi)
            start_s = n["start_s"]
            dur_s = n["duration_s"]
            velocity = n.get("velocity", 0.8)

            start_idx = int(start_s * sample_rate)
            dur_samples = int(dur_s * sample_rate)

            if start_idx >= total_samples:
                continue

            # Clamp
            dur_samples = min(dur_samples, total_samples - start_idx)
            t = np.arange(dur_samples, dtype=np.float32) / sample_rate

            # Smooth sine wave (with a touch of triangle wave character)
            sine = np.sin(2 * np.pi * freq * t)
            # Add a subtle sub octave
            sub = np.sin(2 * np.pi * (freq / 2) * t) * 0.3
            wave = sine + sub

            # Envelope: quick attack 5ms, sustain, release 200ms
            attack_n = min(int(0.005 * sample_rate), dur_samples)
            release_n = min(int(0.2 * sample_rate), dur_samples)
            env = np.ones(dur_samples, dtype=np.float32)
            env[:attack_n] = np.linspace(0, 1, attack_n)
            env[-release_n:] = np.linspace(1, 0, release_n)
            wave = wave * env * _velocity_to_gain(velocity) * 0.5

            # Place in stereo (center)
            end_idx = start_idx + dur_samples
            audio[0, start_idx:end_idx] += wave
            audio[1, start_idx:end_idx] += wave

        # Apply lowpass filter via Pedalboard
        board = Pedalboard([
            LowpassFilter(cutoff_frequency_hz=300),
        ])
        audio = board(audio, sample_rate)

        return audio.astype(np.float32)

    # ── Synthesize Chords ────────────────────────────────────────────────

    def synthesize_chords(
        self,
        chords: list[dict[str, Any]],
        bpm: float,
        sample_rate: int = 44100,
    ) -> np.ndarray:
        """Synthesize chord pads from a chord progression.

        Args:
            chords: Output of ``generate_chord_pattern()``.
            bpm: Beats per minute.
            sample_rate: Output sample rate.

        Returns:
            Stereo array ``(2, samples)``.
        """
        if not chords:
            return np.zeros((2, int(sample_rate * 2)), dtype=np.float32)

        last_end = 0.0
        for c in chords:
            end = c["start_s"] + c["duration_s"]
            last_end = max(last_end, end)

        total_samples = int(last_end * sample_rate) + int(0.5 * sample_rate)
        audio = np.zeros((2, total_samples), dtype=np.float32)

        for c in chords:
            midi_notes = c["midi_notes"]
            start_s = c["start_s"]
            dur_s = c["duration_s"]

            start_idx = int(start_s * sample_rate)
            dur_samples = int(dur_s * sample_rate)

            if start_idx >= total_samples:
                continue

            dur_samples = min(dur_samples, total_samples - start_idx)
            t = np.arange(dur_samples, dtype=np.float32) / sample_rate

            # Synthesize each note as a sine wave and mix
            chord_wave = np.zeros(dur_samples, dtype=np.float32)
            for midi in midi_notes:
                freq = _midi_to_freq(midi)
                note_wave = np.sin(2 * np.pi * freq * t)

                # Volume scaling: more notes → lower individual volume
                note_gain = 1.0 / max(len(midi_notes), 1)
                chord_wave += note_wave * note_gain

            # Envelope: slow attack (50ms), sustain, slow release (500ms)
            attack_n = min(int(0.05 * sample_rate), dur_samples)
            release_n = min(int(0.5 * sample_rate), dur_samples)
            env = np.ones(dur_samples, dtype=np.float32)
            env[:attack_n] = np.linspace(0, 1, attack_n)
            env[-release_n:] = np.linspace(1, 0, release_n)
            chord_wave = chord_wave * env * 0.3  # low in mix (pad)

            # Center in stereo
            end_idx = start_idx + dur_samples
            audio[0, start_idx:end_idx] += chord_wave
            audio[1, start_idx:end_idx] += chord_wave

        # Apply gentle high shelf to soften (low-pass-ish)
        board = Pedalboard([
            HighShelfFilter(cutoff_frequency_hz=2000, gain_db=-6),
        ])
        audio = board(audio, sample_rate)

        return audio.astype(np.float32)

    # ── 2.6 Generate Beat (Orchestrator) ─────────────────────────────────

    def generate_beat(
        self,
        bpm: float,
        scale: str,
        root_note: str,
        swing_amount: float = 0.3,
        output_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        """Generate a full beat: drums + bass + chords → mix → WAV.

        This is the main entry point. It orchestrates pattern generation,
        stem synthesis, mix-down, Pedalboard post-processing, and WAV export.

        Args:
            bpm: Beats per minute (e.g. 120).
            scale: Scale/mode name (e.g. ``"major"``, ``"dorian"``).
            root_note: Root note (e.g. ``"C"``, ``"F#"``).
            swing_amount: Swing feel 0.0-1.0.
            output_dir: Where to write the WAV. Defaults to
                ``settings.output_dir / {beat_id}``.

        Returns:
            ``{
                "output_path": str,
                "duration": float,
                "stems": {"kick": str, ...},
                "bpm": float,
                "scale": str,
                "root_note": str,
            }``
        """
        sr = settings.sample_rate
        beat_id = uuid.uuid4().hex[:12]

        if output_dir is None:
            output_dir = settings.output_dir / beat_id
        else:
            output_dir = Path(output_dir).resolve()

        output_dir.mkdir(parents=True, exist_ok=True)

        # ── 1. Generate patterns ─────────────────────────────────────────
        drum_pattern = self.generate_drum_pattern(bpm, swing_amount, num_bars=4)
        bass_notes = self.generate_bass_pattern(bpm, scale, root_note, num_bars=4)
        chord_notes = self.generate_chord_pattern(bpm, scale, root_note, num_bars=8)

        # ── 2. Synthesize stems ──────────────────────────────────────────
        drum_stems = self.synthesize_drums(drum_pattern, sr)
        bass_audio = self.synthesize_bass(bass_notes, bpm, sr)
        chord_audio = self.synthesize_chords(chord_notes, bpm, sr)

        # ── 3. Mix ───────────────────────────────────────────────────────
        # Ensure all arrays are same length
        max_len = 0
        for arr in list(drum_stems.values()) + [bass_audio, chord_audio]:
            if arr.shape[1] > max_len:
                max_len = arr.shape[1]

        mix = np.zeros((2, max_len), dtype=np.float32)

        # Drum mix levels
        drum_gains = {
            "kick": 1.0,
            "snare": 0.85,
            "hihat_closed": 0.4,
            "hihat_open": 0.3,
            "clap": 0.5,
        }

        for name, stem_audio in drum_stems.items():
            gain = drum_gains.get(name, 0.5)
            stem_len = stem_audio.shape[1]
            mix[:, :stem_len] += stem_audio * gain

        # Bass level
        bass_len = bass_audio.shape[1]
        mix[:, :bass_len] += bass_audio * 0.7

        # Chords level (pads are subtle)
        chord_len = chord_audio.shape[1]
        mix[:, :chord_len] += chord_audio * 0.3

        # ── 4. Post-processing (Pedalboard) ──────────────────────────────
        board = Pedalboard([
            # Gentle compression
            Compressor(
                threshold_db=-20,
                ratio=2.5,
                attack_ms=10,
                release_ms=100,
            ),
            # Subtle saturation (warmth via Distortion's tanh waveshaping)
            Distortion(
                drive_db=1.0,
            ),
            # Safety limiter
            Limiter(
                threshold_db=-0.5,
                release_ms=50,
            ),
        ])

        processed = board(mix, sr)

        # Safety gain — prevent clipping
        peak = np.max(np.abs(processed))
        if peak > 0.99:
            processed = processed * (0.95 / peak)

        # ── 5. Apply fade in/out ─────────────────────────────────────────
        fade_n = int(0.01 * sr)  # 10ms
        processed = _apply_fade(processed, fade_n)

        # ── 6. Write WAV ─────────────────────────────────────────────────
        output_path = output_dir / "mix.wav"
        sf.write(str(output_path), processed.T, sr)

        # Determine duration
        duration = float(processed.shape[1] / sr)

        # ── 7. Write individual stem WAVs ────────────────────────────────
        stem_paths: dict[str, str] = {}
        stem_output_dir = output_dir / "stems"
        stem_output_dir.mkdir(parents=True, exist_ok=True)

        for name, stem_audio in drum_stems.items():
            gain = drum_gains.get(name, 0.5)
            stem_path = stem_output_dir / f"{name}.wav"
            # Trim to actual content (remove trailing silence)
            stem_mono = stem_audio[0] + stem_audio[1]
            if np.max(np.abs(stem_mono)) > 1e-6:
                sf.write(str(stem_path), stem_audio.T, sr)
                stem_paths[name] = str(stem_path)

        # Write bass stem
        bass_path = stem_output_dir / "bass.wav"
        sf.write(str(bass_path), bass_audio.T, sr)
        stem_paths["bass"] = str(bass_path)

        # Write chords stem
        chords_path = stem_output_dir / "chords.wav"
        sf.write(str(chords_path), chord_audio.T, sr)
        stem_paths["chords"] = str(chords_path)

        return {
            "output_path": str(output_path.resolve()),
            "duration": round(duration, 2),
            "stems": stem_paths,
            "bpm": bpm,
            "scale": scale,
            "root_note": root_note,
        }
