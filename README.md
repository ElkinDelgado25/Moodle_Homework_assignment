# Moodle_Homework_assignment

Este programa usa Python, `uv` y Playwright para iniciar sesión en Moodle, revisar las actividades tipo **Tarea**, mostrar las que todavía no aparecen como entregadas e imprimir su contenido, estado, fecha de vencimiento y enlace.

## Requisitos

- Python 3.11 o superior.
- `uv`.
- Una cuenta activa en Moodle.
- Acceso a Internet.

## Instalación global recomendada

Con `uv` instalado y el paquete `.whl` compartido por el autor, abre la terminal en la carpeta de descarga:

```bash
uv tool install --python 3.11 ./moodle_homework_assignment-0.1.0-py3-none-any.whl
mcp-moodle run
```

El asistente pide tu cuenta, intenta validarla y te permite seleccionar **Codex, Claude Code, Google Antigravity o Copilot**. Prepara Chromium y configura el agente para tu usuario, sin editar archivos a mano. Sigue [los pasos completos de instalación](docs/INSTALL.md), incluida la alternativa desde GitHub para personas con acceso al repositorio privado.

`mcp-moodle run` muestra el panel de Aula Moodle, con el logo en bloques rojos, tu cuenta y el estado. Si ya tienes una cuenta guardada, elige **4. Validar cuenta** para comprobar el acceso sin volver a introducir tus credenciales. También puedes usar `mcp-moodle status`.

## Ejecutar desde un repositorio clonado

Si clonaste este repositorio, abre PowerShell o una terminal dentro de la carpeta `Moodle_Homework_assignment` y ejecuta un único comando:

```powershell
uv run mcp-moodle setup
```

Este comando instala automáticamente las dependencias indicadas en `uv.lock`, prepara Chromium y abre el asistente para guardar tu cuenta de Moodle y elegir el agente que quieres conectar. No hace falta ejecutar `uv sync`, crear un archivo `.env` ni instalar Chromium por separado para usar el asistente.

No ejecutes `mcp-moodle setup` sin `uv run` desde un clon: ese comando solo existe directamente en la terminal cuando el paquete se instaló de forma global.

Cuando ya hayas terminado la configuración, puedes volver a abrir el panel con:

```powershell
uv run mcp-moodle run
```

Y consultar las tareas desde la terminal con:

```powershell
uv run mcp-moodle tasks
```

Por defecto muestra las próximas cinco tareas desde la línea de tiempo del Área personal, confirmando sus estados y anexos. Para otras búsquedas:

```bash
uv run mcp-moodle tasks --mode recent --limit 5
uv run mcp-moodle tasks --mode overdue
uv run mcp-moodle tasks --mode all --refresh
```

En MCP, `list_assignments` hace la consulta limitada y **`list_all_assignments`** es la herramienta separada para contar o revisar pendientes en todas las materias visibles. La revisión completa usa los índices de tareas por materia y una caché de detalles de 15 minutos, manteniendo la consulta del estado en los índices. `--refresh` evita reutilizar detalles.

Para desarrollo avanzado, `uv sync` crea el entorno del proyecto y `uv run playwright install chromium` permite instalar Chromium de forma independiente.

Ubuntu 24.04 tiene soporte oficial de Playwright. En Arch Linux y sus derivadas puede aparecer esta advertencia:

```text
BEWARE: your OS is not officially supported by Playwright; downloading fallback build for ubuntu24.04-x64.
```

No es un error: indica que Playwright usa una compilación de Chromium para Ubuntu 24.04 como alternativa. En este equipo se comprobó que Chromium inicia correctamente. Si aparece solo esta advertencia y el comando termina sin errores, puedes continuar.

El asistente guarda las credenciales en la configuración local del usuario. Si usas el modo de desarrollo heredado con `.env`, no compartas ni subas ese archivo: está incluido en `.gitignore`.

## Ejecución directa con variables de entorno

Para el modo de desarrollo heredado basado en `.env`, ejecuta desde la carpeta del proyecto:

```bash
uv run moodle-tasks
```

`uv run` ejecuta el programa dentro del entorno de Python del proyecto, sin tener que activarlo manualmente.

El programa consulta Moodle una vez y avisa por la terminal. Puedes volver a ejecutarlo cuando enciendas la computadora. Para ver el navegador durante una prueba, cambia `MOODLE_HEADLESS=false` en `.env`.

Referencias: [sistemas compatibles con Playwright](https://playwright.dev/python/docs/intro) y [ejecución de comandos con uv](https://docs.astral.sh/uv/concepts/projects/run/).

## Integración con agentes mediante MCP

El servidor `mcp-moodle serve` usa el SDK oficial de MCP para Python y expone herramientas de consulta para Codex, Claude, Antigravity, Copilot y otros clientes compatibles con `stdio`. Usa `mcp-moodle run` para configurarlo o consulta [la guía de conexión manual y herramientas](docs/MCP.md). El repositorio incluye configuración para Copilot en `.vscode/mcp.json` y un ejemplo para Claude Desktop.

## Notas

- Si Moodle responde con un error como `HTTP 502`, la consulta no se completó. Vuelve a intentarlo cuando el servidor esté disponible.
- La búsqueda rápida respeta el filtro de la línea de tiempo; la completa consulta los índices de las materias visibles en Mis cursos. Ambas muestran su alcance. Si no encuentra resultados, no puede descartar tareas fuera de esa cobertura.
- Para identificar pendientes comprueba entrega, nota e instrucciones: una actividad ya calificada o que indique no subir documentos no se cuenta como pendiente solo por figurar sin entrega.
- Las cuentas institucionales de ULEAM usan Microsoft 365 y la selección del mismo perfil cuando aparece «Use a different account». Si Microsoft exige CAPTCHA, códigos o verificación adicional, el programa no los resuelve ni afirma que la sesión esté validada.
- El programa no entrega tareas ni modifica información en Moodle.
