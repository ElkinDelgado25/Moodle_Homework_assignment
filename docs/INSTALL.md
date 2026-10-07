# Instalación global con asistente

El proyecto se instala como una herramienta de Python con `uv`. No requiere clonar el repositorio ni editar archivos de configuración. Cada persona introduce su propia cuenta de Moodle en la terminal.

## 1. Instalar uv y tener Git disponible

En Linux y macOS, si todavía no tienes `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

En Windows, usa el instalador de PowerShell de la [guía oficial de uv](https://docs.astral.sh/uv/getting-started/installation/). Abre una terminal nueva después de instalarlo. Comprueba `uv --version`. Si vas a instalar desde GitHub, también necesitarás Git; puedes comprobarlo con `git --version`.

## 2. Instalar Moodle MCP para tu usuario

Si recibiste el paquete `.whl`, abre la terminal en la carpeta donde lo descargaste:

```bash
uv tool install --python 3.11 ./moodle_homework_assignment-0.1.0-py3-none-any.whl
```

Esta opción permite compartir el instalador sin dar acceso al repositorio. No incluye las credenciales de quien creó el paquete. Hace falta Internet para descargar las dependencias y Chromium.

Si tienes acceso al repositorio, también puedes instalar directamente desde GitHub:

```bash
uv tool install --python 3.11 git+https://github.com/ElkinDelgado25/Moodle_Homework_assignment.git
```

El repositorio es privado actualmente: esta segunda opción requiere que tengas acceso y Git esté autenticado. El paquete `.whl` compartido no necesita acceso a GitHub ni Git instalado.

Esto instala `moodle-setup`, `moodle-mcp` y `moodle-tasks` en un entorno aislado. `uv` obtiene Python 3.11 si hace falta. Es una instalación global para tu usuario, disponible desde cualquier carpeta. Si los comandos no aparecen, ejecuta `uv tool update-shell` y abre una terminal nueva. [Herramientas globales con uv](https://docs.astral.sh/uv/guides/tools/).

## 3. Ejecutar el asistente

```bash
moodle-setup
```

El asistente prepara Chromium y tiene dos etapas:

1. **Cuenta de Moodle:** pide usuario o correo y contraseña oculta, comprueba el formato del usuario e intenta iniciar sesión. Si Moodle rechaza la cuenta, permite corregirla hasta tres veces y no guarda las credenciales rechazadas. Si el servidor devuelve 502 u otro error 5xx, configura la cuenta dejando explícitamente pendiente su validación.
2. **Agente:** pide seleccionar Codex, Claude Code, Google Antigravity o Copilot en VS Code. Registra automáticamente el MCP en la configuración personal del agente, conservando sus otros servidores y ajustes.

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
moodle-setup --url https://moodle.tu-universidad.edu
```

El asistente comprueba accesos con usuario y contraseña. Un Moodle que requiera CAPTCHA, autenticación institucional o doble factor puede necesitar una adaptación antes de que se pueda confirmar la sesión.

## 4. Reiniciar el agente y consultar

Reinicia el cliente seleccionado para cargar el servidor. En Copilot, usa el modo agente y habilita las herramientas de Moodle. Pide:

> Usa el MCP moodle para consultar mis tareas pendientes.

También puedes consultar directamente en la terminal con `moodle-tasks`.

## Conectar otro agente con la misma cuenta

```bash
moodle-setup --connect-only
```

Solo pregunta cuál agente quieres conectar. También puedes elegirlo directamente:

```bash
moodle-setup --connect-only --agent codex
moodle-setup --connect-only --agent claude
moodle-setup --connect-only --agent antigravity
moodle-setup --connect-only --agent copilot
```

## Configuración que administra el asistente

| Cliente | Configuración personal |
| --- | --- |
| Codex | `~/.codex/config.toml`, o la carpeta configurada mediante `CODEX_HOME` |
| Claude Code | `~/.claude.json` |
| Google Antigravity | `~/.gemini/config/mcp_config.json` |
| Copilot en VS Code | `Code/User/mcp.json` dentro de la configuración personal del sistema |

Para un perfil de VS Code, una edición distinta o una ruta de configuración personalizada, puedes usar `moodle-setup --agent-config /ruta/al/mcp.json`.

El servidor usa la ruta absoluta del intérprete instalado y de las credenciales; no depende de que el agente tenga `uv` en su PATH. Las configuraciones de los agentes no contienen la contraseña. Los clientes compatibles con procesos locales pueden utilizarlo; un agente alojado solamente en la nube necesita una conexión remota, que esta instalación no proporciona.

Referencias de los clientes: [Codex](https://developers.openai.com/codex/mcp), [Claude Code](https://code.claude.com/docs/en/mcp), [Antigravity](https://antigravity.google/docs/mcp) y [VS Code](https://code.visualstudio.com/docs/agents/reference/mcp-configuration).

## Datos personales

La cuenta se guarda automáticamente en `credentials.env` dentro de la configuración personal:

- Linux: `~/.config/moodle-homework-assignment/`, o la ubicación indicada por `XDG_CONFIG_HOME`.
- macOS: `~/Library/Application Support/moodle-homework-assignment/`.
- Windows: `%APPDATA%\moodle-homework-assignment\`.

El archivo contiene la contraseña en texto local; en Linux y macOS se crea con permisos `600` para restringir su lectura a tu usuario. No se incorpora al repositorio. El asistente permite cambiar la cuenta al volver a ejecutar `moodle-setup`.

## Actualizar y desinstalar

Para instalar los cambios publicados en la rama principal:

```bash
uv tool install --force --python 3.11 git+https://github.com/ElkinDelgado25/Moodle_Homework_assignment.git
```

Si instalaste desde un paquete compartido, pide la versión nueva e instálala con `uv tool install --force --python 3.11 /ruta/al/paquete-nuevo.whl`.

Después ejecuta `moodle-setup --connect-only` para actualizar la conexión del agente y reinícialo. La cuenta guardada se conserva.

Para quitar los comandos:

```bash
uv tool uninstall moodle-homework-assignment
```

La desinstalación conserva tus credenciales y las entradas MCP. Puedes retirar `moodle` desde los ajustes de cada agente y eliminar la carpeta personal de Moodle si ya no la necesitas.

## Pruebas automáticas

El CI de GitHub Actions se activa en push y pull requests. Prepara Python 3.11, las dependencias y Chromium, y ejecuta `python -m unittest discover -s tests -v`. Las pruebas usan páginas y credenciales de prueba; no necesitan cuentas reales de Moodle. El workflow solo ejecuta pruebas.

Para generar el instalador que puedes compartir, desde el checkout de desarrollo ejecuta `uv build --wheel`. El paquete aparece en `dist/` y contiene los comandos y el código, sin el `.env` local.
