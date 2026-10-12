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

El instalador prepara `uv` si hace falta, deja `mcp-moodle` en el PATH, descarga Chromium y abre el asistente. Ingresa tu cuenta de Moodle y selecciona el agente que deseas conectar. Reinicia ese agente al terminar. Cierra las terminales que ya estaban abiertas y abre una nueva para usar el comando desde cualquier carpeta.

## Configurar otra cuenta o mas agentes

```powershell
mcp-moodle setup
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

El instalador muestra secciones y tiempos estimados con Rich. Deja `mcp-moodle` en el PATH y pregunta antes de preparar las bibliotecas de Chromium; si aceptas, valida `sudo` una sola vez antes de instalar los paquetes. Abre una terminal nueva para usar el comando desde cualquier carpeta.

Para configurar otra cuenta o conectar mas agentes desde Debian, Ubuntu, Arch, macOS o Windows:

```bash
mcp-moodle setup
```

> **Importante:** el comando correcto es `mcp-moodle`, no `moodle-mcp`. `moodle-mcp` inicia el servidor MCP y no acepta la opción `setup`.

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

El instalador deja `mcp-moodle` en el PATH y valida `sudo` una sola vez antes de instalar `chromium` con `pacman`. Abre una terminal nueva para usar el comando desde cualquier carpeta.

## macOS

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
   bash ./INSTALAR-MACOS.sh
   ```

El instalador prepara `uv` si hace falta, deja `mcp-moodle` en el PATH y abre el asistente. Abre una terminal nueva para usar el comando desde cualquier carpeta.

## Usar Moodle MCP

Despues de instalar, abre una terminal nueva. Estos comandos funcionan desde cualquier carpeta:

```powershell
mcp-moodle run
mcp-moodle status
mcp-moodle tasks
```

Para configurar otra cuenta o conectar mas agentes:

```powershell
mcp-moodle setup
```

Para Antigravity especificamente:

```powershell
mcp-moodle setup --connect-only --agent antigravity
```

Para Cursor:

```powershell
mcp-moodle setup --connect-only --agent cursor
```

Reinicia el agente despues de configurarlo. En Antigravity puedes escribir `/mcp` para comprobar que el servidor `moodle` este conectado.

## Datos locales

Las credenciales se guardan solo en la configuracion local del usuario, no en el repositorio ni en la configuracion MCP del agente. En Windows se guardan en `%APPDATA%\moodle-homework-assignment\credentials.env`.

Si Moodle no responde, ejecuta `mcp-moodle status` mas tarde para comprobar la cuenta otra vez. Si actualizas el repositorio, vuelve a ejecutar el instalador de tu sistema para actualizar el comando del PATH.
