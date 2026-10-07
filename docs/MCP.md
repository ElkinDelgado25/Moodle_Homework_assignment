# Moodle como servidor MCP

El proyecto usa el [SDK oficial de MCP para Python](https://github.com/modelcontextprotocol/python-sdk) v2. El servidor se comunica por `stdio`, por lo que pueden usarlo Codex, Claude Code, Claude Desktop, Copilot en VS Code y otros clientes que admitan servidores MCP locales. Cada cliente inicia su propia instancia cuando lo necesita.

## Preparación

Desde la carpeta del proyecto:

```bash
uv sync
uv run playwright install chromium
```

Completa y guarda `.env`, como indica el README. El servidor lee ese archivo aunque el cliente se ejecute desde otra carpeta. También acepta variables de entorno, que tienen prioridad, o una ruta explícita mediante `--env-file /ruta/a/.env`.

El comando del servidor es `uv run moodle-mcp`. Un cliente MCP lo inicia y mantiene conectado; al ejecutarlo directamente en una terminal, espera mensajes del protocolo por la entrada estándar. La salida estándar está reservada para MCP.

## Herramientas disponibles

| Herramienta | Función |
| --- | --- |
| `configuration_status` | Comprueba si están completas las variables, sin devolver usuario ni contraseña. |
| `check_moodle_connection` | Comprueba el acceso a Moodle y devuelve el error si falla. |
| `list_assignments(only_pending=true)` | Consulta posibles tareas pendientes, con texto, fecha, estado y enlace. Con `false`, devuelve todas las revisadas. |
| `get_assignment(assignment_id)` | Consulta una actividad por el identificador `id` de su enlace. |

Las herramientas son de consulta. Las credenciales permanecen en `.env`; no hace falta escribirlas en las configuraciones MCP.

Los resultados usan `submitted=true`, `false` o `null` (estado desconocido). Los estados desconocidos también se incluyen al pedir pendientes. `reviewed_count`, `incomplete`, `errors` y `coverage` indican el alcance de la consulta: cero actividades o errores no permiten afirmar que no hay tareas pendientes. La búsqueda actual recorre los enlaces del área personal y de los cursos encontrados; puede omitir actividades en otras secciones o páginas.

## Codex

Desde la carpeta del proyecto, registra el servidor para tu usuario:

```bash
codex mcp add moodle -- uv --directory "$PWD" run moodle-mcp
```

Abre una nueva sesión o reinicia la extensión para que cargue el servidor. Puedes comprobar su presencia con `/mcp` en Codex CLI. La configuración global permite usarlo desde otros proyectos. [Documentación de OpenAI](https://developers.openai.com/codex/mcp).

## Claude Code

Desde la carpeta del proyecto:

```bash
claude mcp add --transport stdio --scope user moodle -- uv --directory "$PWD" run moodle-mcp
```

Inicia una nueva sesión y comprueba `/mcp`. [Documentación de Claude Code](https://code.claude.com/docs/en/mcp).

## Copilot en VS Code

El repositorio incluye `.vscode/mcp.json` con la ruta `${workspaceFolder}`. Abre el proyecto, usa `MCP: List Servers` en la paleta de comandos e inicia `moodle`. Utiliza Copilot en modo agente con las herramientas de Moodle habilitadas.

Para usarlo desde otros proyectos, añade la misma entrada a la configuración MCP de usuario, cambiando `${workspaceFolder}` por la ruta absoluta de este proyecto. [Configuración MCP de VS Code](https://code.visualstudio.com/docs/agents/reference/mcp-configuration).

## Claude Desktop y otros clientes

Usa `examples/claude_desktop_config.json` como ejemplo. Sustituye `/RUTA/ABSOLUTA/Moodle_Homework_assignment` por la carpeta real e incorpora la entrada `moodle` a `mcpServers` en la configuración existente. Reinicia el cliente. [Guía de conexión de Claude Desktop](https://modelcontextprotocol.io/docs/develop/connect-local-servers).

Si el cliente no encuentra `uv`, usa la ruta completa al ejecutable; en este equipo es `/home/elkindev/.local/bin/uv`.

Un cliente que solo se ejecuta en la nube necesitaría un servidor remoto accesible por HTTP; esta implementación usa un proceso local `stdio`.

## Ejemplo de uso

Pide al agente: «Usa el MCP moodle para comprobar la conexión y consultar mis tareas pendientes. Si la consulta falla o queda incompleta, indícalo».

El cliente descubre las herramientas por MCP; tener el repositorio en GitHub por sí solo no conecta los agentes. Moodle también debe estar disponible para obtener datos actuales.

## Pruebas

```bash
uv run python -m unittest discover -s tests -v
```

Las pruebas incluyen descubrimiento de herramientas por `stdio` desde otra carpeta, validación de argumentos, ocultación de credenciales en errores y tratamiento de resultados parciales.
