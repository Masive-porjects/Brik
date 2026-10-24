"""Comprehensive verification for SongStarter beat engine."""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import soundfile as sf

from audiomind.processing.songstarter import BeatGenerator


def main():
    g = BeatGenerator()

    # Test 1: Default
    print("=== Test 1: 120bpm, major, C ===")
    r = g.generate_beat(120, "major", "C")
    info = sf.info(r["output_path"])
    print(f"  Output: {r['output_path']}")
    print(f"  Duration: {info.duration:.2f}s, SR: {info.samplerate}, Channels: {info.channels}")
    print(f"  Stems: {list(r['stems'].keys())}")
    assert Path(r["output_path"]).exists()
    assert info.channels == 2
    assert r["bpm"] == 120
    assert r["scale"] == "major"
    print("  PASSED")

    # Test 2: Different scale + swing
    print("\n=== Test 2: 140bpm, dorian, D, swing=0.5 ===")
    r2 = g.generate_beat(140, "dorian", "D", swing_amount=0.5)
    info2 = sf.info(r2["output_path"])
    print(f"  Duration: {info2.duration:.2f}s")
    assert Path(r2["output_path"]).exists()
    assert r2["bpm"] == 140
    print("  PASSED")

    # Test 3: Minor scale
    print("\n=== Test 3: 100bpm, natural_minor, A ===")
    r3 = g.generate_beat(100, "natural_minor", "A")
    info3 = sf.info(r3["output_path"])
    print(f"  Duration: {info3.duration:.2f}s")
    assert Path(r3["output_path"]).exists()
    assert r3["scale"] == "natural_minor"
    print("  PASSED")

    # Test 4: Pentatonic + swing
    print("\n=== Test 4: 130bpm, pentatonic_minor, E, swing=0.7 ===")
    r4 = g.generate_beat(130, "pentatonic_minor", "E", swing_amount=0.7)
    print(f"  Duration: {r4['duration']}s")
    assert Path(r4["output_path"]).exists()
    print("  PASSED")

    # Test 5: Quick harmonic_minor
    print("\n=== Test 5: 160bpm, harmonic_minor, F# ===")
    r5 = g.generate_beat(160, "harmonic_minor", "F#")
    assert Path(r5["output_path"]).exists()
    print(f"  Duration: {r5['duration']}s")
    print("  PASSED")

    print("\n" + "=" * 40)
    print("All SongStarter verification tests PASSED!")
    print("=" * 40)


if __name__ == "__main__":
    main()
