# Moodle como servidor MCP

Para instalar y conectar el MCP con preguntas en la terminal, sigue [la instalación global con asistente](INSTALL.md). Las instrucciones de esta página también permiten conectarlo manualmente desde un checkout de desarrollo.

El proyecto usa el [SDK oficial de MCP para Python](https://github.com/modelcontextprotocol/python-sdk) v2. El servidor se comunica por `stdio`, por lo que pueden usarlo Codex, Claude Code, Claude Desktop, Copilot en VS Code y otros clientes que admitan servidores MCP locales. Cada cliente inicia su propia instancia cuando lo necesita.

## Preparación

Desde la carpeta del proyecto:

```bash
uv sync
uv run playwright install chromium
```

Completa y guarda `.env`, como indica el README. El servidor lee ese archivo aunque el cliente se ejecute desde otra carpeta. También acepta variables de entorno, que tienen prioridad, o una ruta explícita mediante `--env-file /ruta/a/.env`.

El comando del servidor es `uv run mcp-moodle serve`. Un cliente MCP lo inicia y mantiene conectado; al ejecutarlo directamente en una terminal, espera mensajes del protocolo por la entrada estándar. La salida estándar está reservada para MCP.

## Herramientas disponibles

| Herramienta | Función |
| --- | --- |
| `configuration_status` | Comprueba si están completas las variables, sin devolver usuario ni contraseña. |
| `check_moodle_connection` | Comprueba el acceso a Moodle y devuelve el error si falla. |
| `list_assignments(only_pending=true, mode="upcoming", limit=5, refresh=false)` | Herramienta predeterminada para «¿qué tareas pendientes tengo?». `upcoming` muestra cinco tareas ya abiertas y con plazo vigente desde la línea de tiempo; `recent` ordena por apertura y también excluye vencidas y futuras; `overdue` solo se usa si se piden expresamente vencidas. Devuelve materia, fechas, instrucciones y anexos. |
| `list_all_assignments(only_pending=true, refresh=false)` | Herramienta separada para revisar todas las materias visibles, sin límite. Úsala para preguntas como «¿cuántas tareas tengo pendientes en todas las materias?». Con `only_pending=false` incluye entregadas y calificadas. |
| `get_assignment(assignment_id)` | Consulta una actividad por el identificador `id` de su enlace. |

Las herramientas son de consulta. Las credenciales permanecen en `.env`; no hace falta escribirlas en las configuraciones MCP.

Los resultados usan `submitted=true`, `false` o `null` (estado desconocido). Los estados desconocidos también se incluyen al pedir pendientes. `requires_submission=false` identifica actividades entregadas, calificadas o que indican no subir documentos. Una actividad calificada que figura «Sin entrega» no se suma a las pendientes. Los anexos corresponden al material del docente, no a los archivos ya entregados por el estudiante. Las fechas normalizadas conservan la hora mostrada por Moodle, sin asignar una zona horaria que Moodle no indique.

`reviewed_count`, `incomplete`, `errors` y `coverage` indican el alcance: cero actividades o errores no permiten afirmar que no hay tareas pendientes. `pending_count` cuenta los resultados pendientes de esa consulta; solo la herramienta completa sirve para estimar el total de todas las materias visibles. `available_pending_count`, `not_yet_open_count`, `overdue_count` y `uncertain_count` distinguen tareas ya abiertas, futuras, vencidas y de estado desconocido. Las vencidas forman parte de las ya abiertas; estos contadores no son categorías que deban sumarse.

La consulta rápida lee el filtro actual de la línea de tiempo, carga más actividades si necesita completar el límite y abre solo los candidatos necesarios. No modifica los filtros de Moodle. Si no encuentra resultados o la línea de tiempo falla, usa los índices por materia como alternativa y comunica los errores. Su alcance está limitado al filtro, por ejemplo «Próximos 30 días»; no calcula automáticamente un total global ni incluye todas las tareas sin fecha o vencidas.

Para una pregunta general el agente debe usar `list_assignments` y mostrar el campo `response_markdown`: **Estas son las tareas pendientes**, seguido de una sola tabla con **Tarea**, **Materia**, **Fecha límite** y **Anexos**. La consulta continúa cargando actividades si necesita sustituir una que todavía no esté abierta. Si hay menos de cinco coincidencias, muestra solo las encontradas. No añade totales globales ni secciones por urgencia. Una respuesta incompleta debe comunicar los errores o su alcance después de la tabla. La herramienta completa queda reservada a solicitudes explícitas de todas las materias, un total o una revisión completa.

La consulta completa recorre Mis cursos y el índice de tareas de cada materia, descarta las entregadas y calificadas antes de abrir detalles y conserva la cobertura y los fallos de cada curso. La caché local dura 15 minutos y se separa por cuenta y servidor. Solo reutiliza detalles cuando el índice recién consultado mantiene la misma fila (título, fecha, entrega y nota). Las instrucciones o anexos pueden permanecer en caché durante ese intervalo. `refresh=true` fuerza su lectura. La ruta rápida comprueba cada tarea directamente; no reutiliza estados desde la caché. `search` informa la fuente, candidatos, páginas de detalles abiertas y detalles reutilizados.

Para una revisión completa de material y estado actual usa `list_all_assignments(refresh=true)`. Una materia que no sea visible en Mis cursos o actividades de otro tipo pueden quedar fuera; el resultado lo indica en `coverage`.

Si Moodle devuelve un error del servidor, como 502, las herramientas de consulta devuelven este mensaje:

> Por ahora no se pudieron consultar tus tareas porque Moodle tiene un error del servidor. Inténtalo de nuevo más tarde.

El mismo mensaje se usa para otros errores HTTP 5xx. `check_moodle_connection` también devuelve `connected=false`, `error_code="server_error"` y `http_status` con el código recibido. Las instrucciones del MCP piden al agente comunicar el fallo sin afirmar que no hay pendientes ni reintentar automáticamente en esa respuesta. Reinicia el servidor MCP en cada cliente después de actualizar para cargar estas instrucciones.

## Codex

Desde la carpeta del proyecto, registra el servidor para tu usuario:

```bash
codex mcp add moodle -- uv --directory "$PWD" run mcp-moodle serve
```

Abre una nueva sesión o reinicia la extensión para que cargue el servidor. Puedes comprobar su presencia con `/mcp` en Codex CLI. La configuración global permite usarlo desde otros proyectos. [Documentación de OpenAI](https://developers.openai.com/codex/mcp).

## Claude Code

Desde la carpeta del proyecto:

```bash
claude mcp add --transport stdio --scope user moodle -- uv --directory "$PWD" run mcp-moodle serve
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
