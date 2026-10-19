"""``audiomind.main`` must import without an operational RAG subsystem.

The 2026-10-19 production candidate crashed on boot because ``api/agent.py``
imported the RAG config at module scope, and that module resolved paths with a
monorepo-only assumption. The import has to stay lazy: a RAG that cannot load
degrades one endpoint, it never takes the API down.
"""

import subprocess
import sys

_PROBE = (
    "import sys\n"
    "import audiomind.main as main\n"
    "assert main.app is not None\n"
    "loaded = 'audiomind.intelligence.rag.config' in sys.modules\n"
    "print('rag-config-loaded' if loaded else 'rag-config-not-loaded')\n"
)


def test_main_imports_without_pulling_the_rag_config() -> None:
    """A fresh interpreter is the only honest way to see the boot import graph."""

    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "rag-config-not-loaded" in result.stdout, (
        "api/agent.py imports the RAG config at boot again: in the container "
        "layout (/app/src/...) that module raises IndexError and the API "
        f"never starts.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
