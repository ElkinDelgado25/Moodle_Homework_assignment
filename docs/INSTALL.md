# Instalacion

Moodle MCP se instala solamente desde un repositorio clonado con Git. No se usan ZIPs, wheels descargados ni instaladores de GitHub Actions.

## Windows

1. Clona el repositorio:

   ```powershell
   git clone https://github.com/ElkinDelgado25/Moodle_Homework_assignment.git
   ```

2. Entra en la carpeta del repositorio:

   ```powershell
   cd .\Moodle_Homework_assignment
   ```

3. Ejecuta el instalador:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\INSTALAR-WINDOWS.ps1
   ```

El instalador prepara `uv` si hace falta, instala las dependencias del proyecto, descarga Chromium y abre el asistente. Ingresa tu cuenta de Moodle y selecciona el agente que deseas conectar. Reinicia ese agente al terminar.

## Configurar otra cuenta o mas agentes

Desde la carpeta del repositorio, ejecuta:

```powershell
uv run mcp-moodle setup
```

El asistente permite cambiar las credenciales o agregar otro agente usando la misma cuenta.

## Debian, Ubuntu y derivadas

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

El instalador muestra secciones y tiempos estimados con Rich. Pregunta antes de preparar las bibliotecas de Chromium; si aceptas, valida `sudo` una sola vez antes de instalar los paquetes.

Para configurar otra cuenta o conectar mas agentes desde Debian, Ubuntu, Arch o sus derivadas, ejecuta dentro del repositorio:

```bash
uv run mcp-moodle setup
```

## Arch Linux y derivadas

1. Clona el repositorio:

   ```bash
   git clone https://github.com/ElkinDelgado25/Moodle_Homework_assignment.git
   ```

2. Entra en la carpeta del repositorio:

   ```bash
   cd Moodle_Homework_assignment
   ```

3. Ejecuta el instalador de Arch:

   ```bash
   bash ./INSTALAR-ARCH.sh
   ```

El instalador valida `sudo` una sola vez antes de instalar `chromium` con `pacman`.

## Usar Moodle MCP

Desde un clon, todos los comandos usan `uv run`:

```powershell
uv run mcp-moodle run
uv run mcp-moodle status
uv run mcp-moodle tasks
```

Para configurar otra cuenta o conectar mas agentes:

```powershell
uv run mcp-moodle run --connect-only
```

Para Antigravity especificamente:

```powershell
uv run mcp-moodle setup --connect-only --agent antigravity
```

Reinicia el agente despues de configurarlo. En Antigravity puedes escribir `/mcp` para comprobar que el servidor `moodle` este conectado.

## Datos locales

Las credenciales se guardan solo en la configuracion local del usuario, no en el repositorio ni en la configuracion MCP del agente. En Windows se guardan en `%APPDATA%\moodle-homework-assignment\credentials.env`.

Si Moodle no responde, ejecuta `uv run mcp-moodle status` mas tarde para comprobar la cuenta otra vez.
