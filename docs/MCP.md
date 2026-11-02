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

Después de instalar, el comando del servidor es `mcp-moodle serve`. Un cliente MCP lo inicia y mantiene conectado; al ejecutarlo directamente en una terminal, espera mensajes del protocolo por la entrada estándar. La salida estándar está reservada para MCP. No confundas `mcp-moodle` con `moodle-mcp`: el segundo es el punto de entrada directo del servidor y no tiene el subcomando `setup`; para abrir el asistente usa `mcp-moodle setup`.

## Herramientas disponibles

| Herramienta | Función |
| --- | --- |
| `configuration_status` | Comprueba si están completas las variables, sin devolver usuario ni contraseña. |
| `check_moodle_connection` | Comprueba el acceso a Moodle y devuelve el error si falla. |
| `list_assignments(mode="upcoming", limit=5, only_pending=true)` | Herramienta para «¿qué tareas pendientes tengo?». `upcoming` (predeterminado) muestra las cinco próximas tareas abiertas desde la línea de tiempo, con `response_markdown` listo para mostrar. `overdue` solo si se piden vencidas. `all` recorre los índices de todas las materias visibles, sin límite, y solo se usa si se pide un total o una revisión completa. No abre tareas ni lee anexos. |
| `get_assignment(assignment_id=null, url=null)` | Lee UNA tarea: `description`, fechas, estado, anexos y el texto de hasta cinco páginas enlazadas en `linked_resources` (30.000 caracteres en total). Las páginas del propio Moodle se leen con la sesión; los enlaces a archivos indican que se descarguen. Acepta el `id` o el enlace `.../mod/assign/view.php?id=...`, también en instalaciones dentro de una subcarpeta. No crea archivos. |
| `download_assignment_attachments(assignment_id=null, url=null, destination_directory=null)` | Descarga los anexos de la descripción y los recursos enlazados (`/mod/resource`) con la sesión de Moodle. La carpeta debe ser absoluta (o empezar por `~`); por defecto `~/Documentos` o `~/Documents`. Se valida antes de abrir el navegador, nunca sobrescribe y devuelve errores parciales. |
| `build_delivery_document(document, cover, destination_directory=null, file_name=null, open_pdf=true, pdf_engine="auto")` | Genera el entregable: el agente envía el contenido estructurado (títulos, párrafos, listas, tablas, figuras, código, citas y referencias) y los datos de portada; el servidor arma la portada ULEAM, aplica APA 7, crea el DOCX editable (Word o WPS) y su PDF, los verifica, los copia sin sobrescribir y abre el PDF. Si faltan datos de portada devuelve `missing_cover_fields` sin escribir nada. Ver [DOCUMENT_OUTPUT.md](DOCUMENT_OUTPUT.md). |
| `finish_delivery(docx_path, pdf_path, destination_directory, open_pdf=true)` | Solo para documentos hechos fuera de `build_delivery_document`: verifica el par (mismo nombre, sin campos `{{...}}`, PDF legible), lo copia sin sobrescribir y abre el PDF. |
| `upload_assignment_files(file_paths, assignment_id=null, url=null, replace_existing=false)` | Adjunta archivos a una tarea y guarda la entrega, solo si el usuario lo pidió. Valida tipo, contenido y ubicación antes de abrir Moodle; todo o nada; nunca envía para calificar. |
| `get_document_template()` | Datos de portada guardados (`student_1`, materias), formato APA 7 y política de contenido. No genera archivos. |

### Sesión de Moodle

Cada herramienta abre su propio navegador, pero reutiliza la sesión: las cookies del dominio de Moodle (nunca las de Microsoft) se guardan en la carpeta de configuración del usuario, en `sessions/`, con permisos `0600` y una vigencia de 12 horas. Si la sesión venció, se vuelve a iniciar una vez; si Moodle rechaza las credenciales, el archivo se borra. Para desactivarlo, define `MOODLE_SESSION_CACHE=false` (también `0`, `no` u `off`) en el entorno o en `credentials.env`; basta con que lo indique uno de los dos. Esa carpeta no se puede adjuntar a una entrega.

### Anexos y enlaces

Los enlaces `pluginfile.php` requieren una sesión de Moodle: un `curl` sin cookies puede recibir una página de acceso con HTTP 200 aunque el nombre termine en `.pdf`. La herramienta de descarga sigue solo redirecciones del mismo Moodle, renueva una sesión vencida una vez y no guarda HTML ni un PDF sin firma `%PDF-`. Los nombres se limpian (sin separadores, controles bidi ni nombres reservados de Windows) y se acortan a 200 bytes.

`description_found=false` indica que Moodle no expuso una descripción visible; no demuestra que la actividad carezca de consigna. Una descripción que solo contiene una URL se lee como instrucciones alojadas en ese enlace. Las páginas externas se leen sin JavaScript ni cookies, solo en direcciones públicas, con un máximo de 2 MB y seis redirecciones.

### Subida

La subida exige una petición explícita del usuario. Antes de abrir Moodle rechaza credenciales, la carpeta de configuración, archivos o carpetas ocultas, rutas del sistema (`/proc`, `/etc`, `/dev`...), enlaces simbólicos hacia ellas, archivos vacíos, de más de 100 MB o de tipos no habituales, y PDF/DOCX con firma incorrecta. En Moodle:

- espera a que el área de archivos termine de cargar y cuenta como existentes los archivos visibles en la tarea;
- no reemplaza archivos sin `replace_existing=true`; si ya están exactamente los mismos nombres devuelve `already_uploaded`;
- si falla un archivo no guarda ninguno (`failed` o `replacement_cancelled`);
- detecta errores del formulario y la declaración de originalidad (`requires_statement`, nunca la marca sola);
- respeta el número y tamaño máximos configurados;
- devuelve `submission.state` (`draft`, `submitted`...), `requires_submit_for_grading` y una nota para el estudiante. Nunca pulsa «Enviar tarea».

Esta operación declara `read_only_hint=false`, `destructive_hint=true` e `idempotent_hint=false`.

### Listados

`submitted` vale `true`, `false` o `null` (desconocido); los desconocidos se incluyen al pedir pendientes. Una actividad calificada o que indica no subir documentos no cuenta como pendiente. `reviewed_count`, `incomplete`, `errors` y `coverage` indican el alcance: una lista vacía o con errores no prueba que no haya tareas pendientes.

La consulta `upcoming` lee el filtro actual de la línea de tiempo y carga más actividades si hace falta. Si la línea de tiempo no existe o falla, usa los índices de cada materia y marca `availability_confirmed=false`, porque los índices no muestran la apertura. Una línea de tiempo vacía se respeta y no dispara esa búsqueda. Cada fila trae `assignment_id`, `title`, `course`, `due_at`, `due_display`, `submitted` y `url`.

Si Moodle devuelve un error del servidor (5xx), las herramientas responden:

> Por ahora no se pudieron consultar tus tareas porque Moodle tiene un error del servidor. Inténtalo de nuevo más tarde.

`check_moodle_connection` devuelve además `connected=false`, `error_code="server_error"` y `http_status`. Las respuestas incluyen su copia de texto en JSON compacto. Reinicia el servidor MCP en cada cliente después de actualizar para cargar las nuevas herramientas.

### Cambios de la versión 0.4.0

- `list_all_assignments` se integró en `list_assignments(mode="all")`; se quitaron `refresh` y `mode="recent"`, que no funcionaban.
- `get_assignment` ya no incluye `assignment_workflow` ni `document_template`; la consigna está en `description` (antes `instructions`) y `linked_resources`.
- `prepare_delivery_workspace` se reemplazó por `build_delivery_document`.
- `upload_assignment_files` devuelve `submission` en lugar de `sent_for_grading`.
- Los identificadores y `limit` son enteros estrictos: `true`, `"11"` o `11.0` se rechazan.
- El SDK de MCP ignora los argumentos desconocidos sin error: un cliente que aún envíe `refresh` o `complete_review` recibe el listado `upcoming`. Reinicia el cliente para que cargue la nueva lista de herramientas.


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

## Cursor

El repositorio incluye `.cursor/mcp.json`, por lo que Cursor CLI detecta Moodle al ejecutar `agent` desde esta carpeta. Para registrarlo tambien en la configuracion personal, ejecuta `mcp-moodle setup` y selecciona **Cursor**. Comprueba el estado con:

```bash
agent mcp list
```

Cursor carga servidores MCP locales desde `.cursor/mcp.json` o `~/.cursor/mcp.json`. [Documentacion de Cursor](https://cursor.com/docs/cli/mcp).

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

Las pruebas incluyen descubrimiento de herramientas por `stdio`, un Moodle local simulado con el flujo completo (listar, leer, descargar, generar el entregable y subirlo con un solo inicio de sesión), una batería de entradas fuera de rango, la seguridad de rutas, la verificación de DOCX y PDF y la ocultación de credenciales.
