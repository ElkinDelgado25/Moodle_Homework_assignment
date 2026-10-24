# Próximos pasos

Produced by elkindelgado25

Después de instalar Moodle MCP, abre una terminal nueva. El comando `mcp-moodle` estará disponible desde cualquier carpeta.

## Configurar una cuenta o un agente

```bash
mcp-moodle setup
```

Para conectar directamente un agente concreto:

```bash
mcp-moodle setup --connect-only --agent antigravity
mcp-moodle setup --connect-only --agent cursor
```

Reinicia el agente después de configurarlo. En Antigravity, escribe `/mcp` para confirmar que el servidor `moodle` está conectado.

> El comando correcto es `mcp-moodle`; `moodle-mcp` inicia el servidor MCP y no admite la opción `setup`.

## Usar Moodle MCP

```bash
mcp-moodle run
mcp-moodle status
mcp-moodle tasks
```

## Actualizar

```bash
mcp-moodle update
```

El comando busca la última versión estable, pide confirmación y conserva tus credenciales y configuraciones. Si tienes cambios locales en el clon, guárdalos o confírmalos antes de actualizar.

Si el comando `update` no existe, ejecuta otra vez el instalador de tu sistema.

## Datos locales y ayuda

Tus credenciales solo se guardan en la configuración local del usuario, nunca en el repositorio ni en la configuración MCP del agente. En Windows se almacenan en `%APPDATA%\moodle-homework-assignment\credentials.env`.

Si Moodle no responde, ejecuta `mcp-moodle status` más tarde para comprobar la cuenta de nuevo.
