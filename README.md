# Moodle_Homework_assignment

Este programa usa Python, `uv` y Playwright para iniciar sesión en Moodle, revisar las actividades tipo **Tarea**, mostrar las que todavía no aparecen como entregadas e imprimir su contenido, estado, fecha de vencimiento y enlace.

## Requisitos

- Python 3.11 o superior.
- `uv`.
- Una cuenta activa en Moodle.
- Acceso a Internet.

## Instalación global recomendada

Con `uv` y Git instalados:

```bash
uv tool install --python 3.11 git+https://github.com/ElkinDelgado25/Moodle_Homework_assignment.git
moodle-setup
```

El asistente pide tu cuenta, intenta validarla y te permite seleccionar **Codex, Claude Code, Google Antigravity o Copilot**. Prepara Chromium y configura el agente para tu usuario, sin editar archivos a mano. Sigue [los pasos completos de instalación](docs/INSTALL.md).

## Instalación para desarrollar desde este repositorio

```bash
uv sync
uv run playwright install chromium
cp .env.example .env
```

`uv sync` instala las dependencias de Python y `uv run playwright install chromium` instala el navegador que usa el programa. Este último comando se puede usar tanto en Ubuntu 24.04 como en distribuciones basadas en Arch Linux.

Ubuntu 24.04 tiene soporte oficial de Playwright. En Arch Linux y sus derivadas puede aparecer esta advertencia:

```text
BEWARE: your OS is not officially supported by Playwright; downloading fallback build for ubuntu24.04-x64.
```

No es un error: indica que Playwright usa una compilación de Chromium para Ubuntu 24.04 como alternativa. En este equipo se comprobó que Chromium inicia correctamente. Si aparece solo esta advertencia y el comando termina sin errores, puedes continuar.

Edita `.env` y completa `MOODLE_USERNAME` y `MOODLE_PASSWORD`. No compartas ni subas ese archivo: está incluido en `.gitignore`.

## Ejecutar

En distribuciones basadas en Arch Linux, ejecuta desde la carpeta del proyecto:

```bash
uv run moodle-tasks
```

El mismo comando sirve en Ubuntu 24.04. `uv run` ejecuta el programa dentro del entorno de Python del proyecto, sin tener que activarlo manualmente; no es exclusivo de Arch Linux.

El programa consulta Moodle una vez y avisa por la terminal. Puedes volver a ejecutarlo cuando enciendas la computadora. Para ver el navegador durante una prueba, cambia `MOODLE_HEADLESS=false` en `.env`.

Referencias: [sistemas compatibles con Playwright](https://playwright.dev/python/docs/intro) y [ejecución de comandos con uv](https://docs.astral.sh/uv/concepts/projects/run/).

## Integración con agentes mediante MCP

El servidor `moodle-mcp` usa el SDK oficial de MCP para Python y expone herramientas de consulta para Codex, Claude, Antigravity, Copilot y otros clientes compatibles con `stdio`. Usa `moodle-setup` para configurarlo o consulta [la guía de conexión manual y herramientas](docs/MCP.md). El repositorio incluye configuración para Copilot en `.vscode/mcp.json` y un ejemplo para Claude Desktop.

## Notas

- Si Moodle responde con un error como `HTTP 502`, la consulta no se completó. Vuelve a intentarlo cuando el servidor esté disponible.
- El programa busca enlaces a tareas en el área personal, la lista de cursos y los cursos encontrados. Si muestra `Tareas revisadas: 0`, no puede confirmar si tienes tareas pendientes; algunas actividades pueden estar en secciones o páginas que todavía no se recorren.
- La identificación de tareas pendientes depende del estado que Moodle muestre en cada actividad.
- Si Moodle usa autenticación institucional, CAPTCHA o código de doble factor, el inicio de sesión automático puede requerir una sesión manual o una adaptación de los selectores.
- El programa no entrega tareas ni modifica información en Moodle.
