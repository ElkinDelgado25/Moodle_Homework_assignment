# Rendimiento y arranque

Este documento explica cómo arranca Moodle MCP, qué se midió en la auditoría de noviembre de 2026 y qué puedes hacer para que responda antes en tu equipo. No describe el uso del programa: para eso consulta el [README](../README.md) y la [guía MCP](MCP.md).

## Cómo arranca el programa

`mcp-moodle` es un único punto de entrada con varios comandos. El arranque tiene tres costes distintos:

1. **Intérprete y paquete.** Python importa `moodle_tasks.cli`, que solo carga `argparse`, la configuración y Sentry. Es el coste más pequeño.
2. **Comando elegido.** Cada comando se importa cuando se usa. `status` y `tasks` no cargan `mcp`, Playwright ni los generadores de documentos; `serve` carga el servidor MCP y Playwright.
3. **Navegador.** El primer `chromium.launch()` de cada proceso abre Chromium y tarda más que todo lo anterior. Se paga una vez por ejecución, no por herramienta MCP.

El bytecode compilado (`.pyc`) evita recompilar módulos en cada arranque. Con `--compile-bytecode` ese trabajo ocurre durante la instalación, no cuando abres una terminal.

## Mediciones

Equipo de referencia: Windows 11, Intel de 12 hilos, SSD, Python 3.13.7, entorno `uv` con las dependencias bloqueadas. Se toma la mediana de varias ejecuciones y se redondea: los valores absolutos cambian con el equipo, el antivirus y la carga del sistema.

| Escenario | Antes de la auditoría | Después |
| --- | --- | --- |
| Comando ligero (`mcp-moodle --help`) | ~1,7 s | 0,31–0,39 s |
| Importación del servidor MCP en caliente | ~1,3–1,8 s | 1,24–1,84 s (sin cambio; depende del equipo) |
| Primer arranque sin bytecode compilado | compilación en el primer uso | compilación durante la instalación |
| Pruebas automatizadas (329 pruebas) | ~102–111 s | ~102–111 s (la suite no es el objetivo de la optimización) |

En la misma máquina, Python 3.13 fue alrededor de un 4 % más rápido que 3.11 para el arranque del CLI y del servidor. La diferencia es pequeña para un comando suelto, pero se nota en cada herramienta MCP que el agente invoca durante una conversación.

La ganancia grande está en el punto 2: antes, `cli.py` importaba todos los módulos al cargarse, de modo que `status` pagaba el coste de `mcp`, Playwright y `fpdf2`. Ahora esos imports viven dentro de la rama del comando que los necesita y una prueba de arquitectura ([`tests/test_architecture.py`](../tests/test_architecture.py)) impide que vuelvan arriba.

## Qué se cambió

- **Imports por comando** en `src/moodle_tasks/cli.py`. Es la mejora que más se percibe.
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

El cliente lanza el servidor al inicio de la conversación y lo mantiene vivo. Por eso el coste de arranque se paga una vez por sesión y no por pregunta. Si tu cliente reinicia el servidor con frecuencia (por ejemplo, al abrir cada conversación), el arranque en caliente de ~1,3 s es el número que vas a percibir.

## Trabajo futuro

- **Reutilizar Chromium entre llamadas.** Hoy cada herramienta abre y cierra su propio navegador. Mantener una instancia viva ahorraría entre 0,5 s y 1,5 s por llamada, pero Playwright sincrónico ata sus objetos al hilo que los creó y el servidor MCP atiende llamadas en hilos distintos. Hacerlo bien exige mover la sesión a un hilo dedicado con una cola de trabajos; es un cambio de arquitectura que no se incluyó en esta auditoría para no arriesgar la estabilidad de las descargas autenticadas.
- **Medir con `python -X importtime`** en tu equipo antes de optimizar más. Cualquier cambio debe acompañarse de una medición reproducible.
- **Revisar el tamaño de las dependencias** si `mcp` o `playwright` incorporan imports costosos en versiones futuras.

Si detectas un arranque anómalo, abre un informe con las instrucciones de [`docs/informes/README.md`](informes/README.md) e incluye la versión de Python, el sistema y el tiempo medido.
