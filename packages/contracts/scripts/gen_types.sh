#!/usr/bin/env bash
# Genera tipos TypeScript desde live_params.schema.json (el backend Python fue eliminado)
# Uso: ./gen_types.sh
# Requiere: npm i -g json-schema-to-typescript (para TS)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTRACTS_DIR="$SCRIPT_DIR"
SCHEMA_FILE="$CONTRACTS_DIR/live_params.schema.json"

# ──────────────────────────────────────────────────────────────────────
# TypeScript → packages/contracts/liveParams.gen.ts
#
# El generador escribía en apps/studio/src/lib/live/liveParams.gen.ts, que
# se eliminó junto al Live Engine. El contrato se conserva como artefacto
# propio del paquete: el schema sigue siendo la fuente de verdad.
# ──────────────────────────────────────────────────────────────────────
TS_OUT="$CONTRACTS_DIR/liveParams.gen.ts"
mkdir -p "$(dirname "$TS_OUT")"

if command -v json-schema-to-typescript >/dev/null 2>&1; then
  echo "🔧 Generando TypeScript → $TS_OUT"
  json-schema-to-typescript "$SCHEMA_FILE" \
    --output "$TS_OUT" \
    --style.singleQuote true \
    --style.semi true \
    --bannerComment "// AUTOGENERADO desde live_params.schema.json — NO EDITAR A MANO"
else
  echo "⚠️  json-schema-to-typescript no instalado. Saltando TS."
  echo "   Instalar: npm i -g json-schema-to-typescript"
fi

echo "✅ Generación completa"