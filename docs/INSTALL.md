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

El asistente busca la última release estable, la instala automáticamente si es más nueva y continúa la configuración con el código actualizado. Al conectar un agente sincroniza también los demás agentes detectados.

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

## Actualizar Moodle MCP

Ejecuta desde cualquier carpeta:

```bash
mcp-moodle update
```

El comando consulta la release estable más reciente, muestra la versión instalada y la nueva, y pide confirmación antes de actualizar. Instala el código exacto de la etiqueta de esa release, sincroniza las dependencias fijadas en `uv.lock` y reinstala el comando `mcp-moodle`. Después prepara Chromium y vuelve a registrar Moodle en todos los agentes instalados o que ya tengan una conexión de Moodle. Si ya está en la última versión, sincroniza sus configuraciones igualmente.

Si el clon tiene cambios locales o la etiqueta de release no pertenece a la misma línea de historial, la actualización se detiene y conserva el clon. Guarda o confirma tus cambios y vuelve a intentarlo. Las credenciales y configuraciones de agentes permanecen en las carpetas personales del usuario.

`mcp-moodle setup` y `mcp-moodle run` buscan la última release cada vez que se ejecutan y la instalan sin una confirmación adicional. Si actualizan, continúan el asistente con el intérprete recién instalado, preparan Chromium y sincronizan las conexiones antes de mostrar el menú de la cuenta guardada. También funciona al indicar un agente concreto:

```bash
mcp-moodle setup --connect-only --agent codex
```

Se registra el agente elegido y se sincronizan Codex, Claude Code, Cursor, Antigravity y Copilot cuando se detectan instalados o ya conectados a Moodle. Una instalación de VS Code por sí sola no confirma que tenga Copilot. Cada agente ya conectado conserva la ruta de su cuenta; los agentes nuevos usan la cuenta de este setup. `--agent-config` actualiza el perfil solicitado además de las configuraciones globales detectadas. Se conservan las demás entradas MCP y ajustes del cliente. Un archivo inválido no se sobrescribe: se continúa con los otros agentes, se informa el fallo y el comando termina con código 1. Esta sincronización actualiza configuraciones; los clientes abiertos requieren recargar su MCP o reiniciarse para usar el proceso nuevo.

Para sincronizar sin preguntas de cuenta, o configurar sin consultar releases:

```bash
mcp-moodle setup --sync-only
mcp-moodle setup --skip-update
```

Si GitHub no responde o el clon no puede actualizarse sin perder cambios locales, `setup` explica el motivo y continúa con la versión disponible. `mcp-moodle status` muestra un aviso y guarda su comprobación durante 24 horas; `MOODLE_UPDATE_CHECK_HOURS` modifica ese intervalo o `0` lo desactiva. Este caché no retrasa la búsqueda de releases de `setup`. El comando `update` sí necesita acceso a GitHub para confirmar y descargar la release.

Si una versión antigua no reconoce `mcp-moodle update`, vuelve a ejecutar el instalador de tu sistema para actualizar el comando del PATH.

## Datos locales

Las credenciales se guardan solo en la configuracion local del usuario, no en el repositorio ni en la configuracion MCP del agente. En Windows se guardan en `%APPDATA%\moodle-homework-assignment\credentials.env`.

Si Moodle no responde, ejecuta `mcp-moodle status` mas tarde para comprobar la cuenta otra vez.
