# Rendimiento y arranque

Este documento explica cómo arranca Moodle MCP, qué se midió en la auditoría de noviembre de 2026 y qué puedes hacer para que responda antes en tu equipo. No describe el uso del programa: para eso consulta el [README](../README.md) y la [guía MCP](MCP.md).

## Cómo arranca el programa

`mcp-moodle` es un único punto de entrada con varios comandos. El arranque tiene tres costes distintos:

1. **Intérprete y paquete.** Python importa `moodle_tasks.cli`, que solo carga `argparse`, la configuración (`config.py`, sin Playwright) y Sentry. Es el coste más pequeño.
2. **Comando elegido.** Cada comando se importa cuando se usa. `status` y `tasks` no cargan `mcp`, Playwright ni los generadores de documentos; `serve` carga el servidor MCP y Playwright, pero no `pypdf`, `python-docx` ni `fpdf2`, que esperan a la primera herramienta que genera o verifica un entregable.
3. **Navegador.** El primer `chromium.launch()` abre Chromium y tarda más que todo lo anterior. En la terminal se paga en cada comando. En `serve`, un hilo dedicado mantiene Chromium y la sesión de Moodle abiertos entre herramientas: solo lo paga la primera herramienta de Moodle de la conversación, o la primera tras 10 minutos sin usarlas.

El bytecode compilado (`.pyc`) evita recompilar módulos en cada arranque. Con `--compile-bytecode` ese trabajo ocurre durante la instalación, no cuando abres una terminal.

## Mediciones

Equipo de referencia: Windows 11, Intel de 12 hilos, SSD, Python 3.13.7, entorno `uv` con las dependencias bloqueadas. Se toma la mediana de varias ejecuciones y se redondea: los valores absolutos cambian con el equipo, el antivirus y la carga del sistema.

| Escenario | Antes de la auditoría | Después |
| --- | --- | --- |
| Comando ligero (`mcp-moodle --help`) | ~1,7 s | 0,31–0,39 s |
| Importación del servidor MCP en caliente | ~1,3–1,8 s | 1,24–1,84 s (sin cambio; depende del equipo) |
| Primer arranque sin bytecode compilado | compilación en el primer uso | compilación durante la instalación |
| Pruebas automatizadas (345 pruebas, Linux, 16 hilos) | ~100 s en serie (`unittest`) | ~20 s con `pytest -n auto` |

En la misma máquina, Python 3.13 fue alrededor de un 4 % más rápido que 3.11 para el arranque del CLI y del servidor. La diferencia es pequeña para un comando suelto, pero se nota en cada herramienta MCP que el agente invoca durante una conversación.

La ganancia grande está en el punto 2: antes, `cli.py` importaba todos los módulos al cargarse, de modo que `status` pagaba el coste de `mcp`, Playwright y `fpdf2`. Ahora esos imports viven dentro de la rama del comando que los necesita y una prueba de arquitectura ([`tests/test_architecture.py`](../tests/test_architecture.py)) impide que vuelvan arriba.

### Validación contra el Moodle de la ULEAM

Comprobado el 18 de noviembre de 2026 con una cuenta de estudiante (Linux, zona horaria `America/Guayaquil`), en solo lectura y comparando la rama con `main`. Cada tiempo es una ejecución sobre la red real, así que varía de una consulta a otra.

| Consulta (`only_pending=true`) | Tareas | `main` | Chromium persistente y servicios AJAX |
| --- | --- | --- | --- |
| `upcoming` | 6 | 12,0 s | 5,0 s |
| `overdue` | 3 | 18,9 s | 11,1 s |
| `all` | 16 | 21,1 s | 12,0 s |
| Tres `upcoming` seguidos (límite 5) en el mismo servidor | 5 | 14,5 / 10,2 / 11,0 s | 5,2 / 4,6 / 5,8 s |

- **Servicios AJAX.** `core_calendar_get_action_events_by_timesort` y `core_course_get_enrolled_courses_by_timeline_classification` responden con la sesión del estudiante, y Mis cursos publica `data-grouping`: `stats` muestra `timeline_source=service` y `courses_source=service`, sin `service_error`. Las tres consultas devuelven las mismas tareas, con las mismas fechas, que la línea de tiempo y los índices dibujados.
- **Fechas.** `timesort` convertido con la hora del equipo coincide con el cierre que muestra Moodle cuando la zona horaria del equipo es la del perfil. Si no coinciden, la hora mostrada puede diferir de la página de Moodle; el tiempo restante se sigue calculando con el reloj del equipo.
- **Subida sin imágenes.** Los controles del selector de archivos del tema `academi` no dependen de imágenes: «Agregar...» es un icono de fuente (`fa-circle-plus`) y «Subir un archivo» es texto con un icono de 16×16 de tamaño fijo. El área de entrega se muestra en vista de tabla, que `_file_names` reconoce.
- **Procesos.** Con el navegador abierto hay un proceso de Chromium; tras `close()` y tras el cierre por inactividad no queda ninguno.

## Qué se cambió

- **Imports por comando** en `src/moodle_tasks/cli.py`. Es la mejora que más se percibe.
- **Chromium persistente en `serve`** (`BrowserThread` y `BrowserSession` en `session.py`). Todas las herramientas de Moodle corren en un único hilo que conserva el navegador y el contexto con las cookies; cada llamada abre solo una pestaña. Con `MOODLE_SESSION_CACHE=false` se reutiliza el proceso, nunca la sesión. Contra un Moodle local, a partir de la segunda herramienta cada llamada ahorra ~0,65 s en Linux (por ejemplo, `check_moodle_connection` pasa de ~770 ms a ~100 ms).
- **Servicios AJAX de Moodle** (`moodle_api.py`). La línea de tiempo y la lista de cursos se piden como JSON a los mismos servicios que usan esas páginas, en vez de esperar a que el tema dibuje las tarjetas y pulsar «Mostrar más». Si el servicio falla, se lee la página que ya está cargada, sin coste extra. Además, una línea de tiempo ordenada por cursos o con un filtro corto ya no obliga a recorrer los índices de todas las materias.
- **Sin imágenes en las páginas de Moodle** (`LAUNCH_ARGS` en `session.py`). Chromium arranca con `imagesEnabled=false`: avatares, imágenes de cursos y fondos no se descargan. No se usa `page.route` porque interceptar peticiones desactiva la caché HTTP: en la medición, CSS y JavaScript se descargaban en cada página en vez de una vez.
- **Generadores de documentos al primer uso** en `server.py` y `verification.py`. En Linux, importar el servidor MCP pasó de ~1,17 s a ~0,47 s: es el arranque que paga cada conversación nueva del agente.
- **Configuración sin Playwright** en `src/moodle_tasks/config.py`. Leer `credentials.env` ya no importa Playwright (~110 ms): en Linux, importar el CLI pasó de ~160 ms a ~55 ms.
- **Python 3.13** en instaladores, `mcp-moodle update` y CI, mediante la constante `moodle_tasks.PYTHON_VERSION`. Se mantiene `requires-python >= 3.11` y el CI prueba ambos intérpretes.
- **`--compile-bytecode`** en `uv tool install`. Elimina la compilación del primer arranque, sobre todo en Windows y macOS.
- **Caché de Chromium en CI**, con clave basada en `uv.lock`. No afecta al usuario, pero evita descargar el navegador en cada ejecución de las pruebas.
- **Dependencias actualizadas** a versiones estables: Playwright 1.65, pydantic 2.14, pypdf 7.1, Rich 15, entre otras.

## Notas por plataforma

### Windows

Es la plataforma donde más se nota `--compile-bytecode`: escribir cientos de archivos `.pyc` pequeños en NTFS es más lento que en Linux o macOS. Además, Microsoft Defender analiza cada `.pyc` y cada ejecutable de Chromium en el primer uso.

Recomendaciones:

- Instala en una ruta local (`C:\Users\...`), no dentro de OneDrive ni de una carpeta sincronizada.
- Si el equipo es de tu uso y tienes permisos, añade una exclusión de Defender para la carpeta de `uv` y para `%LOCALAPPDATA%\ms-playwright`. Es opcional y depende de las políticas de tu institución.
- Deja que el instalador termine: la descarga de Chromium es la parte más lenta de la instalación, no del uso diario.

### Linux (Debian, Ubuntu, Arch)

Es el entorno más rápido de los cuatro: menos sobrecarga del sistema de archivos y arranque de Chromium más directo. En contenedores conviene mantener `--shm-size=1g` o más; con el valor por defecto Chromium puede tardar o fallar. En Arch, el paquete `chromium` del sistema se usa cuando está disponible y evita una descarga adicional.

### macOS

En Apple Silicon, `uv` y Playwright descargan binarios `arm64` nativos; no uses una terminal bajo Rosetta, porque todo el proceso pasa a `x86_64` y pierdes rendimiento. La primera ejecución de Chromium puede tardar más por la verificación de Gatekeeper; las siguientes son normales.

### Agentes MCP

El cliente lanza el servidor al inicio de la conversación y lo mantiene vivo. Por eso el coste de arranque se paga una vez por sesión y no por pregunta. Lo mismo ocurre con Chromium: se abre con la primera herramienta de Moodle, se reutiliza en las siguientes y se cierra cuando el cliente se desconecta o tras 10 minutos sin uso, de modo que no quedan procesos del navegador abiertos. Si tu cliente reinicia el servidor con frecuencia (por ejemplo, al abrir cada conversación), el arranque en caliente de ~1,3 s es el número que vas a percibir.

## Trabajo futuro

- **Medir con `python -X importtime`** en tu equipo antes de optimizar más. Cualquier cambio debe acompañarse de una medición reproducible.
- **Revisar el tamaño de las dependencias** si `mcp` o `playwright` incorporan imports costosos en versiones futuras.

Si detectas un arranque anómalo, abre un informe con las instrucciones de [`docs/informes/README.md`](informes/README.md) e incluye la versión de Python, el sistema y el tiempo medido.
