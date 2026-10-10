#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -f /etc/debian_version ]]; then
  echo "Este instalador es solo para Debian, Ubuntu y sus derivadas." >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "Instalando uv para el usuario actual..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

uv_bin="${HOME}/.local/bin"
if [[ -d "$uv_bin" ]]; then
  export PATH="$uv_bin:$PATH"
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "No se encontro uv. Cierra la terminal, abre otra y ejecuta este archivo de nuevo." >&2
  exit 1
fi

if [[ ! -f "$project_dir/pyproject.toml" ]]; then
  echo "Este instalador debe ejecutarse desde la raiz del repositorio clonado." >&2
  exit 1
fi

exec uv --directory "$project_dir" run python scripts/install_linux.py --family debian
