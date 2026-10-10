# Instalación global con asistente

El proyecto se instala como una herramienta de Python con `uv`. No requiere clonar el repositorio ni editar archivos de configuración. Cada persona introduce su propia cuenta de Moodle en la terminal.

## 1. Elegir el instalador de esta entrega

Descarga el artifact de una ejecución correcta de [Build y pruebas multiplataforma](https://github.com/ElkinDelgado25/Moodle_Homework_assignment/actions/workflows/tests.yml) o utiliza el wheel compartido por el autor. Extrae el ZIP antes de instalar: contiene el wheel, `INSTRUCCIONES.md` y `INSTALAR-WINDOWS.ps1`.

| Sistema | Artifact verificado por CI |
| --- | --- |
| Windows x64 | `mcp-moodle-windows` |
| Ubuntu 24.04 | `mcp-moodle-ubuntu` |
| Arch Linux | `mcp-moodle-arch` |
| macOS Apple Silicon | `mcp-moodle-macos-arm64` |
| macOS Intel | `mcp-moodle-macos-intel` |

El mismo wheel sirve para los tres sistemas operativos. `uv` instala Python 3.11 si hace falta y las dependencias para la arquitectura del equipo; el asistente descarga Chromium. El paquete no contiene cuentas de Moodle. Se necesita Internet durante la instalación y para consultar Moodle.

## 2. Instalar según tu sistema

Los comandos para instalar `uv` provienen de su [guía oficial](https://docs.astral.sh/uv/getting-started/installation/). Si ya lo tienes, comprueba `uv --version` y continúa con la instalación del wheel.

### Windows — PowerShell

Usa Windows 11 o Windows Server 2019 o posterior. El CI ejecuta las pruebas en Windows Server 2025 x64.

Después de extraer el ZIP, abre PowerShell en esa carpeta y ejecuta:

```powershell
powershell -ExecutionPolicy Bypass -File .\INSTALAR-WINDOWS.ps1
```

Si acabas de extraer el ZIP y PowerShell estÃ¡ en su carpeta padre, entra primero en la carpeta extraÃ­da (sustituye el nombre si es distinto):

```powershell
cd .\mcp-moodle-installer-0.1.0
powershell -ExecutionPolicy Bypass -File .\INSTALAR-WINDOWS.ps1
```

El instalador prepara `uv` si hace falta, localiza el wheel incluido, instala Python 3.11 y Moodle MCP, y abre el asistente. El asistente descarga Chromium y solicita la cuenta de Moodle y el agente que deseas conectar. No necesitas instalar Python, Chromium ni modificar el PATH manualmente. Reinicia el agente elegido al terminar.

### Linux — Debian y derivados (Debian-based)

Usa estos pasos en Debian, Ubuntu y distribuciones basadas en ellas, como Linux Mint. Consulta los [sistemas compatibles con Playwright](https://playwright.dev/python/docs/intro); el CI comprueba Ubuntu 24.04.

```bash
sudo apt update
sudo apt install -y curl ca-certificates
curl -LsSf https://astral.sh/uv/install.sh | sh
```

En una terminal nueva, desde la carpeta donde extrajiste el ZIP:

```bash
uv --version
uv tool install --python 3.11 ./moodle_homework_assignment-0.1.0-py3-none-any.whl
uv tool update-shell
uvx --python 3.11 --from playwright playwright install-deps chromium
```

El último comando instala las bibliotecas del sistema para Chromium y puede pedir permisos de administrador. Consulta la [documentación de Playwright](https://playwright.dev/python/docs/browsers#install-system-dependencies).

Abre otra terminal y ejecuta:

```bash
mcp-moodle run
```

### Linux — Arch Linux y derivados (Arch-based)

Usa estos pasos en Arch Linux y distribuciones basadas en ella, como CachyOS, EndeavourOS y Manjaro. El CI comprueba Arch Linux; no reproduce todas las derivadas ni un escritorio completo.

```bash
sudo pacman -Syu --needed curl ca-certificates chromium
curl -LsSf https://astral.sh/uv/install.sh | sh
```

El paquete [Chromium de Arch](https://archlinux.org/packages/extra/x86_64/chromium/) instala sus dependencias del sistema. En una terminal nueva, desde la carpeta donde extrajiste el ZIP:

```bash
uv --version
uv tool install --python 3.11 ./moodle_homework_assignment-0.1.0-py3-none-any.whl
uv tool update-shell
```

Abre otra terminal y ejecuta:

```bash
mcp-moodle run
```

Elige únicamente el bloque de tu distribución: `apt` para la familia Debian o `pacman` para la familia Arch. En ambas, el asistente descarga su propio Chromium para Playwright; la preparación guiada no instala automáticamente los paquetes del sistema operativo.

### macOS — Terminal (Intel y Apple Silicon)

Usa macOS 14 Sonoma o posterior, según los [requisitos actuales de Playwright](https://playwright.dev/python/docs/intro). El CI comprueba macOS 15 en Apple Silicon e Intel mediante los runners [oficiales de GitHub](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Abre una ventana nueva de Terminal en la carpeta donde extrajiste el ZIP:

```bash
uv --version
uv tool install --python 3.11 ./moodle_homework_assignment-0.1.0-py3-none-any.whl
uv tool update-shell
```

Abre Terminal de nuevo y ejecuta `mcp-moodle run`. Usa una terminal nativa de tu Mac para que Python y Chromium correspondan a Intel o Apple Silicon. La cuenta se guarda en `~/Library/Application Support/moodle-homework-assignment/`; no necesitas copiarla al proyecto.

### Instalar desde GitHub o desde un clon

Para instalar directamente desde GitHub necesitas Git (`git --version`):

```bash
uv tool install --python 3.11 git+https://github.com/ElkinDelgado25/Moodle_Homework_assignment.git
uv tool update-shell
```

Abre una terminal nueva y ejecuta `mcp-moodle run`. Esta alternativa instala la rama principal, que puede contener cambios posteriores al artifact que descargaste.

Si ya clonaste el repositorio, desde la carpeta padre ejecuta:

```bash
cd .\Moodle_Homework_assignment
powershell -ExecutionPolicy Bypass -File .\INSTALAR-WINDOWS.ps1
```

El asistente prepara las dependencias y Chromium; no necesitas crear un `.env`. Desde un clon utiliza `uv run mcp-moodle ...` para los comandos siguientes. Una instalación con `uv tool install` permite usar `mcp-moodle` desde cualquier carpeta.

## 3. Ejecutar el asistente

```bash
mcp-moodle run
```

También puedes usar `mcp-moodle setup`; es el mismo asistente. Las dependencias de Python se instalan automáticamente con `uv tool install`. Al abrir el asistente, primero se detecta el sistema operativo y se prepara Chromium con una animación en la terminal y sin mostrar la salida interna de la instalación. Al terminar aparece la portada de Moodle y comienzan las preguntas:

Cuando ya tienes una cuenta completa guardada, aparece primero este menú:

```text
¿Qué quieres hacer?
  1. Cambiar credenciales
  2. Configurar otro agente
  3. Salir
  4. Validar cuenta
Selecciona una opción (1-4):
```

La opción **1** pide los nuevos datos, comprueba el acceso y actualiza la cuenta que comparten los agentes registrados; conserva la dirección de Moodle guardada, salvo que indiques otra con `--url`. No vuelve a pedir que elijas un agente. La opción **2** abre el menú de agentes utilizando la cuenta guardada, sin pedir usuario ni contraseña. La opción **3** termina sin modificar tus credenciales ni registros MCP. La opción **4**, **Validar cuenta**, intenta iniciar sesión con la cuenta guardada y muestra **Conectado** si Moodle acepta el acceso, o **Con problemas** si falla. Usa la dirección y las credenciales guardadas, sin modificarlas ni pedir que configures un agente. En la primera instalación, o si faltan datos de la cuenta, comienza directamente con las preguntas de cuenta y agente:

1. **Cuenta de Moodle:** pide usuario o correo y contraseña oculta, comprueba el formato del usuario e intenta iniciar sesión con una animación de espera. Si Moodle rechaza la cuenta, permite corregirla hasta tres veces y no guarda las credenciales rechazadas. Si el servidor devuelve 502 u otro error 5xx, o tarda demasiado en responder, guarda la cuenta antes de abrir el menú de agentes y vuelve a mostrar la portada con **Con problemas**. Informa que la cuenta está guardada y su validación está pendiente; puedes continuar la instalación. La cuenta se conserva incluso si cancelas en el menú de agentes. Cuando el servidor vuelva a responder, la próxima consulta intentará iniciar sesión con esa cuenta; no hay reintentos automáticos permanentes en segundo plano.
2. **Agente:** pide seleccionar Codex, Claude Code, Google Antigravity o Copilot en VS Code. Al abrir el asistente y en este menú, muestra cuáles se detectan en el equipo y cuáles ya tienen **Moodle configurado**. Registra automáticamente el MCP en la configuración personal del agente, conservando sus otros servidores y ajustes.

La detección busca los comandos de los clientes en el PATH y sus archivos personales de configuración. **Configuración encontrada** indica que existe un archivo del cliente, aunque su ejecutable no se detecte; no confirma por sí sola que esté instalado. Para Copilot comprueba además las extensiones en las carpetas habituales de VS Code: si solo encuentra el editor, muestra **VS Code instalado; Copilot sin confirmar**. Las instalaciones o carpetas de extensiones personalizadas pueden no detectarse. Puedes seleccionar cualquier cliente manualmente, y **Moodle configurado** indica un registro existente, no una conexión verificada con Moodle.

Si el archivo JSON del cliente está vacío o solo contiene espacios, el asistente lo inicializa automáticamente. También admite la marca UTF-8 BOM que pueden añadir algunos editores de Windows. Si tiene contenido con JSON inválido, muestra el cliente, la ruta, la línea y la columna del error y conserva el archivo para corregirlo. Una vez corregido, puedes repetir `mcp-moodle setup --connect-only --agent antigravity` para registrar Antigravity con la cuenta ya guardada, sin volver a introducir credenciales.

La terminal muestra **MOODLE** con letras de bloques en tonos rojos, el título **MCP · Aula Moodle**, la cuenta, el sistema operativo detectado y el estado. Reconoce Arch Linux y sus derivadas, por ejemplo **CachyOS (basado en Arch Linux)**.

En una terminal interactiva, cada etapa renueva la pantalla: la portada con la cuenta y el estado actuales reemplaza la anterior, y al terminar desaparecen las preguntas y el menú de selección. Los mensajes de validación pendiente siguen visibles en la etapa correspondiente. Si rediriges la salida a un archivo, se conserva el historial sin códigos de limpieza de pantalla.

La preparación de Chromium muestra un indicador de progreso y termina con **Chromium listo**. Las advertencias de compatibilidad de Playwright se capturan y no aparecen en una instalación correcta. Si hay un fallo real, el asistente muestra **Con problemas**, informa del fallo y guarda los detalles en `browser-install.log` junto a las credenciales, para poder revisarlos.

- **Sin iniciar:** todavía no se ha comprobado una sesión, o falta configurar la cuenta.
- **Conectado:** Moodle aceptó el inicio de sesión en la comprobación actual.
- **Con problemas:** falló la comprobación, por ejemplo por un error 502 o credenciales rechazadas.

Para comprobar el estado de la cuenta guardada en cualquier momento:

```bash
mcp-moodle status
```

El estado se comprueba al ejecutar el comando; no es una conexión permanente ni cambia automáticamente cuando Moodle se recupera. Los colores se adaptan a la terminal y el panel se reorganiza si la ventana es pequeña. La interfaz visual no se imprime en el transporte `mcp-moodle serve`.

Ejemplo de las preguntas:

```text
Usuario o correo de Moodle:
Contraseña de Moodle (no se mostrará):

¿En cuál agente quieres usar Moodle?
  1. Codex
  2. Claude Code
  3. Google Antigravity
  4. Copilot en VS Code
Selecciona una opción (1-4):
```

El Moodle predeterminado es el de ULEAM. Para usar otro:

```bash
mcp-moodle run --url https://moodle.tu-universidad.edu
```

El asistente comprueba accesos con usuario y contraseña. Para correos institucionales de ULEAM selecciona **Microsoft 365 Uleam**, introduce los datos y vuelve a elegir el mismo perfil si aparece **Use a different account**, siguiendo el flujo comprobado en esa institución. Solo muestra **Conectado** cuando confirma la sesión de Moodle. Si Microsoft requiere CAPTCHA, códigos o una verificación adicional, el asistente no los resuelve y comunica que no se pudo confirmar el acceso.

Para enviar la contraseña espera a que esté visible el botón **Sign in**, escribe con eventos de teclado y comprueba que el campo siga completo. Si Microsoft muestra **Please enter your password**, repite ese paso una sola vez; si vuelve a ocurrir, informa un fallo al enviar el formulario. Ese aviso no se presenta como contraseña incorrecta. Un rechazo explícito de las credenciales no se reintenta mediante este mecanismo.

## 4. Reiniciar el agente y consultar

Reinicia el cliente seleccionado para cargar el servidor. En Copilot, usa el modo agente y habilita las herramientas de Moodle. Pide:

> Usa el MCP moodle para consultar mis tareas pendientes.

La respuesta predeterminada es una tabla de hasta cinco tareas pendientes ya disponibles, sin vencidas, con **Tarea, Materia y Cierre (fecha y hora)**. El cierre incluye el tiempo restante al consultar: `11/10/2026 23:59 (quedan 3 días y 8 horas)`. La lista no abre instrucciones ni anexos.

Para profundizar, pide «hagamos la primera tarea» o más información de una actividad: el agente usa `get_assignment` con el ID de su enlace. Para contar o revisar todas las materias, pide explícitamente una revisión completa; `list_all_assignments` requiere `complete_review=true`. Sin ese parámetro también devuelve solo cinco pendientes.

También puedes consultar directamente en la terminal con `mcp-moodle tasks`. El comando `mcp-moodle serve` está destinado a los clientes MCP y no abre preguntas interactivas.

## Conectar otro agente con la misma cuenta

```bash
mcp-moodle run --connect-only
```

Solo pregunta cuál agente quieres conectar. También puedes elegirlo directamente:

```bash
mcp-moodle run --connect-only --agent codex
mcp-moodle run --connect-only --agent claude
mcp-moodle run --connect-only --agent antigravity
mcp-moodle run --connect-only --agent copilot
```

## Configuración que administra el asistente

| Cliente | Configuración personal |
| --- | --- |
| Codex | `~/.codex/config.toml`, o la carpeta configurada mediante `CODEX_HOME` |
| Claude Code | `~/.claude.json` |
| Google Antigravity | `~/.gemini/config/mcp_config.json` |
| Copilot en VS Code | `Code/User/mcp.json` dentro de la configuración personal del sistema |

Para un perfil de VS Code, una edición distinta o una ruta de configuración personalizada, puedes usar `mcp-moodle run --agent-config /ruta/al/mcp.json`.

El servidor usa la ruta absoluta del intérprete instalado y de las credenciales; no depende de que el agente tenga `uv` en su PATH. Las configuraciones de los agentes no contienen la contraseña. Los clientes compatibles con procesos locales pueden utilizarlo; un agente alojado solamente en la nube necesita una conexión remota, que esta instalación no proporciona.

Referencias de los clientes: [Codex](https://developers.openai.com/codex/mcp), [Claude Code](https://code.claude.com/docs/en/mcp), [Antigravity](https://antigravity.google/docs/mcp) y [VS Code](https://code.visualstudio.com/docs/agents/reference/mcp-configuration).

## Datos personales

La cuenta se guarda automáticamente en `credentials.env` dentro de la configuración personal:

- Linux: `~/.config/moodle-homework-assignment/`, o la ubicación indicada por `XDG_CONFIG_HOME`.
- macOS: `~/Library/Application Support/moodle-homework-assignment/`.
- Windows: `%APPDATA%\moodle-homework-assignment\`.

El archivo contiene la contraseña en texto local; en Linux y macOS se crea con permisos `600` para restringir su lectura a tu usuario. No se incorpora al repositorio. El asistente permite cambiar la cuenta al volver a ejecutar `mcp-moodle run`.

## Actualizar y desinstalar

Para instalar los cambios publicados en la rama principal:

```bash
uv tool install --force --python 3.11 git+https://github.com/ElkinDelgado25/Moodle_Homework_assignment.git
```

Si instalaste desde un paquete compartido, pide la versión nueva e instálala con `uv tool install --force --python 3.11 /ruta/al/paquete-nuevo.whl`.

Después ejecuta `mcp-moodle run --connect-only` para actualizar la conexión del agente y reinícialo. La cuenta guardada se conserva.

Para quitar los comandos:

```bash
uv tool uninstall moodle-homework-assignment
```

La desinstalación conserva tus credenciales y las entradas MCP. Puedes retirar `moodle` desde los ajustes de cada agente y eliminar la carpeta personal de Moodle si ya no la necesitas.

## Pruebas automáticas

El CI de GitHub Actions tiene cinco checks independientes que se ejecutan automáticamente en push, pull requests y ejecuciones manuales:

| Entorno | Preparación de Chromium |
| --- | --- |
| Ubuntu 24.04, familia Debian | Playwright instala Chromium y sus bibliotecas con `--with-deps`. |
| Arch Linux en contenedor sobre un runner Linux | `pacman` prepara las bibliotecas con el paquete `chromium`; Playwright descarga el navegador que utiliza el proyecto. |
| Windows Server 2025 x64, runner alojado de GitHub | Playwright instala y ejecuta Chromium para Windows. |
| macOS 15 Apple Silicon (`macos-15`) | Se verifica ARM64 y Playwright instala y ejecuta Chromium nativo. |
| macOS 15 Intel (`macos-15-intel`) | Se verifica x86-64 y Playwright instala y ejecuta Chromium nativo. |

Cada job prepara Python 3.11, construye el wheel, lo instala globalmente con `uv tool install` y comprueba los comandos de terminal. Después ejecuta la suite completa desde el intérprete del paquete instalado, incluyendo pruebas de Chromium, errores de servidor y descubrimiento MCP por stdio. Las pruebas usan páginas y credenciales de prueba; no necesitan cuentas reales de Moodle. El CI construye, prueba y guarda instaladores; no publica paquetes ni despliega servicios.

El check de Windows usa `windows-2025`, el runner x64 alojado de GitHub. No requiere conectar tu equipo ni habilitar variables del repositorio. Comprueba la instalación y las pruebas en Windows Server 2025; esto no equivale a una comprobación específica en Windows 11 de escritorio. [Runners alojados de GitHub](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

En una ejecución correcta, abre la pestaña **Actions**, selecciona **Build y pruebas multiplataforma** y descarga el artifact `mcp-moodle-windows`, `mcp-moodle-ubuntu`, `mcp-moodle-arch`, `mcp-moodle-macos-arm64` o `mcp-moodle-macos-intel`. Se conservan durante 14 días. Cada artifact contiene `mcp-moodle-installer-0.1.0.zip`, con el wheel y estas instrucciones. El wheel de Python es compartido entre plataformas; las dependencias específicas se descargan en el equipo donde lo instales. Probar Ubuntu no garantiza todas las versiones de Debian, y el contenedor Arch no reproduce todas las derivadas ni un escritorio completo.

Cada artifact contiene las mismas instrucciones para Windows, Linux y macOS; utiliza los pasos de tu sistema descritos al inicio. Por ejemplo, en Windows extrae el ZIP, abre PowerShell en esa carpeta y ejecuta:

```powershell
powershell -ExecutionPolicy Bypass -File .\INSTALAR-WINDOWS.ps1
```

El instalador abre el asistente para introducir tu cuenta y elegir el agente.

Para generar el instalador que puedes compartir, desde el checkout de desarrollo ejecuta `uv build --wheel`. El paquete aparece en `dist/` y contiene los comandos y el código, sin el `.env` local.
