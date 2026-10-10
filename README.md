<p align="center">
  <img src="docs/assets/readme/header.svg" width="1000" alt="Moodle MCP · Aula Moodle. Encabezado inspirado en mcp-moodle setup.">
</p>

<h1 align="center">Moodle MCP</h1>

<p align="center">
  Conecta tu cuenta de Moodle con tu agente y trabaja desde una sola conversación.
</p>

<p align="center">
  <a href="#instalacion">Instalación</a> ·
  <a href="#opciones-extras">Opciones extras</a> ·
  <a href="#entregables">Entregables</a> ·
  <a href="docs/MCP.md">Guía MCP</a> ·
  <a href="docs/DOCUMENT_OUTPUT.md">Documentos</a>
</p>

| Consulta tus tareas | Descarga los anexos | Prepara tus documentos |
| :--- | :--- | :--- |
| Próximas cinco pendientes, materia y tiempo restante. | Descarga autenticada con la misma sesión de Moodle. | DOCX y PDF con portada ULEAM, APA 7 y Times New Roman. |

Compatible con **Codex, Claude Code, Cursor, Google Antigravity y Copilot**. Usa Python, `uv` y Playwright. Las instrucciones y los anexos se consultan cuando eliges una tarea para trabajar en ella.

<p align="center">
  <a href="https://openai.com/codex" title="Codex"><img src="docs/assets/readme/agents/codex-reference.png" width="38" height="38" style="border-radius: 50%;" alt="Codex"></a>
  &nbsp;&nbsp;
  <a href="https://www.anthropic.com/claude-code" title="Claude Code"><img src="docs/assets/readme/agents/claude-code.svg" width="38" height="38" style="border-radius: 50%;" alt="Claude Code"></a>
  &nbsp;&nbsp;
  <a href="https://cursor.com/" title="Cursor"><img src="docs/assets/readme/agents/cursor-reference.png" width="38" height="38" style="border-radius: 50%;" alt="Cursor"></a>
  &nbsp;&nbsp;
  <a href="https://antigravity.google/" title="Google Antigravity"><img src="docs/assets/readme/agents/antigravity-reference.png" width="38" height="38" style="border-radius: 50%;" alt="Google Antigravity"></a>
  &nbsp;&nbsp;
  <a href="https://github.com/features/copilot" title="GitHub Copilot"><img src="docs/assets/readme/agents/copilot.svg" width="38" height="38" style="border-radius: 50%;" alt="GitHub Copilot"></a>
</p>

<p align="center"><sub>Codex &nbsp;·&nbsp; Claude Code &nbsp;·&nbsp; Cursor &nbsp;·&nbsp; Google Antigravity &nbsp;·&nbsp; Copilot</sub></p>

---

## Requisitos

- Windows 11 o Windows Server 2019+, macOS 14+, o Linux con las bibliotecas necesarias para Chromium. El CI comprueba Windows Server 2025, Ubuntu 24.04, Arch Linux y macOS 15 en Intel y Apple Silicon.
- `uv`; obtiene Python 3.11 automáticamente si hace falta.
- Una cuenta activa en Moodle, acceso a Internet y un agente compatible instalado.

Los requisitos del navegador se basan en la [documentación oficial de Playwright](https://playwright.dev/python/docs/intro).

<a id="instalacion"></a>

## Elige tu sistema

La unica instalacion soportada consiste en clonar este repositorio con Git. Consulta [INSTALL.md](docs/INSTALL.md).

<table>
  <tr>
    <td align="center"><a href="#windows"><img src="docs/assets/readme/windows.svg" width="42" height="42" alt="Windows"><br><strong>Windows</strong></a><br>PowerShell</td>
    <td align="center"><a href="#debian"><img src="docs/assets/readme/debian.svg" width="42" height="42" alt="Debian"><br><strong>Debian y derivados</strong></a><br>apt</td>
    <td align="center"><a href="#arch"><img src="docs/assets/readme/archlinux.svg" width="42" height="42" alt="Arch Linux"><br><strong>Arch y derivados</strong></a><br>pacman</td>
    <td align="center"><a href="#macos"><img src="docs/assets/readme/apple.svg" width="42" height="42" alt="Apple"><br><strong>macOS</strong></a><br>Intel / Apple Silicon</td>
  </tr>
</table>

Instala `uv` siguiendo el bloque de tu sistema y abre una terminal nueva. Los comandos de instalación de `uv` proceden de su [guía oficial](https://docs.astral.sh/uv/getting-started/installation/).

---

<a id="windows"></a>

<img src="docs/assets/readme/windows-section.svg" width="1000" alt="Windows — PowerShell">

### Windows — PowerShell

Clona el repositorio y entra en su carpeta:

```powershell
git clone https://github.com/ElkinDelgado25/Moodle_Homework_assignment.git
cd .\Moodle_Homework_assignment
```

Luego ejecuta el instalador incluido:

```powershell
powershell -ExecutionPolicy Bypass -File .\INSTALAR-WINDOWS.ps1
```

El instalador prepara `uv`, instala las dependencias, descarga Chromium y abre el asistente para configurar Moodle y conectar un agente.

### Configurar otra cuenta o mas agentes

Desde la carpeta del repositorio ejecuta:

```powershell
uv run mcp-moodle setup
```

El asistente permite cambiar las credenciales o conectar otro agente.

---


<a id="debian"></a>

<img src="docs/assets/readme/debian-section.svg" width="1000" alt="Debian y derivados">

### Debian y derivados

1. Clona el repositorio:

   ```bash
   git clone https://github.com/ElkinDelgado25/Moodle_Homework_assignment.git
   ```

2. Entra en la carpeta del repositorio:

   ```bash
   cd Moodle_Homework_assignment
   ```

3. Ejecuta el instalador:

   ```bash
   bash ./INSTALAR-DEBIAN.sh
   ```

El instalador muestra tres secciones con Rich y tiempos estimados. Pregunta antes de instalar las bibliotecas de Chromium y solicita la contrasena de `sudo` una sola vez si aceptas.

Para configurar otra cuenta o conectar mas agentes:

```bash
uv run mcp-moodle setup
```

---

<a id="arch"></a>

<img src="docs/assets/readme/archlinux-section.svg" width="1000" alt="Arch Linux y derivados">

### Arch Linux y derivados

1. Clona el repositorio:

   ```bash
   git clone https://github.com/ElkinDelgado25/Moodle_Homework_assignment.git
   ```

2. Entra en la carpeta del repositorio:

   ```bash
   cd Moodle_Homework_assignment
   ```

3. Ejecuta el instalador:

   ```bash
   bash ./INSTALAR-ARCH.sh
   ```

El instalador prepara `uv`, instala el paquete `chromium` y abre el asistente de Moodle. Puede pedir la contrasena de `sudo`.

Para configurar otra cuenta o conectar mas agentes:

```bash
uv run mcp-moodle setup
```

---

<a id="macos"></a>

<img src="docs/assets/readme/apple-section.svg" width="1000" alt="macOS — Intel y Apple Silicon">

### macOS — Intel y Apple Silicon

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

En una ventana nueva de Terminal, desde la carpeta del wheel:

```bash
uv tool install --python 3.11 ./moodle_homework_assignment-0.1.0-py3-none-any.whl
uv tool update-shell
```

Abre Terminal de nuevo y ejecuta `mcp-moodle run`. Usa una terminal nativa de tu Mac; `uv` y Playwright descargan Python y Chromium para su arquitectura. El asistente guarda la cuenta en `~/Library/Application Support/moodle-homework-assignment/`.

El asistente pide tu cuenta, intenta validarla, prepara Chromium y te permite elegir el agente. Sigue [los pasos completos de instalación](docs/INSTALL.md), incluida la alternativa desde GitHub, la actualización y los instaladores disponibles en Actions.

`mcp-moodle run` muestra el panel de Aula Moodle. Si ya tienes una cuenta guardada, elige **4. Validar cuenta** para comprobar el acceso. También puedes usar `mcp-moodle status`.

---

<a id="opciones-extras"></a>

## Opciones extras

Despues de instalar, usa estos comandos desde la carpeta del repositorio:

| Opcion | Comando |
| --- | --- |
| Ver el estado de la cuenta | `uv run mcp-moodle status` |
| Abrir el asistente y conectar otra cuenta o agente | `uv run mcp-moodle setup` |
| Consultar las proximas tareas pendientes | `uv run mcp-moodle tasks` |
| Consultar tareas vencidas | `uv run mcp-moodle tasks --mode overdue` |
| Revisar todas las materias | `uv run mcp-moodle tasks --mode all --refresh` |
| Abrir de nuevo el panel de configuracion | `uv run mcp-moodle run` |

Para integrar Moodle con Codex, Claude, Cursor, Antigravity o Copilot, usa el asistente con `setup`. Cursor tambien detecta la configuracion incluida en [.cursor/mcp.json](.cursor/mcp.json) al abrir este repositorio. Los comandos manuales y las herramientas MCP estan explicados en [MCP.md](docs/MCP.md).

## Entregables

Para crear un trabajo, el agente usa `get_document_template()`. La portada ULEAM y el logo estan incluidos en el repositorio en [academic-cover.docx](src/moodle_tasks/assets/academic-cover.docx) y [uleam-logo.png](src/moodle_tasks/assets/uleam-logo.png).

El resultado documental predeterminado contiene dos archivos con el mismo nombre:

- Un DOCX editable.
- Un PDF exportado desde ese DOCX.

La portada contiene los campos de materia, docente, estudiantes, carrera, curso y ano. El desarrollo comienza en la pagina siguiente y aplica APA 7 con Times New Roman de 12 puntos. Consulta la [politica completa de entregables](docs/DOCUMENT_OUTPUT.md) para los campos, formato y revision final.

## Notas

- Si Moodle responde con un error como `HTTP 502`, la consulta no se completó. Vuelve a intentarlo cuando el servidor esté disponible.
- La búsqueda rápida respeta el filtro de la línea de tiempo; la completa consulta los índices de las materias visibles en Mis cursos. Ambas muestran su alcance. Si no encuentra resultados, no puede descartar tareas fuera de esa cobertura.
- Para identificar pendientes comprueba los datos de entrega y nota disponibles en los listados: una actividad ya calificada o que indique no subir documentos no se cuenta como pendiente solo por figurar sin entrega.
- Las cuentas institucionales de ULEAM usan Microsoft 365 y la selección del mismo perfil cuando aparece «Use a different account». Si Microsoft exige CAPTCHA, códigos o verificación adicional, el programa no los resuelve ni afirma que la sesión esté validada.
- El programa no entrega tareas ni modifica información en Moodle.

---

<p align="center">
  <a href="docs/INSTALL.md">Instalación completa</a> ·
  <a href="docs/MCP.md">Conexión de agentes</a> ·
  <a href="docs/assets/readme/SOURCES.md">Créditos visuales</a>
</p>
