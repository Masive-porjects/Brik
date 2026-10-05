"""Validate the Dockerfile prewarm call shape without downloading 300 MB.

Checks that prewarm() rejects unknown model names (so a typo in the Dockerfile
fails fast) and that the model the app actually uses is a valid key.
"""

from __future__ import annotations

import demucs_onnx

APP_MODEL = "htdemucs"  # must match processing/splitter.py split_audio(model=...)
DEFAULT_MODEL = "htdemucs_ft"  # what prewarm() bakes if you pass no models


def main() -> None:
    models = demucs_onnx.list_models()

    try:
        demucs_onnx.prewarm(["no_existe_este_modelo"], precision="fp32")
    except Exception as exc:  # noqa: BLE001 - we only care that it rejects
        print(f"prewarm() valida el nombre -> {type(exc).__name__}: {str(exc)[:140]}")
    else:
        print("prewarm() NO valido el nombre (inesperado)")

    print()
    print(f"modelo de la app   '{APP_MODEL}'  -> clave valida: {APP_MODEL in models}")
    print(f"default de prewarm '{DEFAULT_MODEL}' -> presente: {DEFAULT_MODEL in models}")
    print()
    print(f"  app  kind: {models[APP_MODEL]['kind']}")
    print(f"  def  kind: {models[DEFAULT_MODEL]['kind']}")
    print()
    print("OJO: si el Dockerfile no pasa models=['htdemucs'], hornea el bag _ft")
    print("que la app nunca carga -> el runtime igual descarga htdemucs.")


if __name__ == "__main__":
    main()
