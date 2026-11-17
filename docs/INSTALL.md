# Instalación

Moodle MCP se instala desde una copia del repositorio. Elige tu sistema y ejecuta sus tres comandos.

## Requisitos

- Git y conexión a Internet.
- `uv`; si no está instalado, el instalador lo prepara. `uv` descarga Python 3.13 cuando hace falta.
- Espacio libre para el entorno y Chromium (alrededor de 1 GB en total).
- Windows 11 o Server 2019+, macOS 14+ o Linux con las bibliotecas de Chromium.

Puedes usar Python 3.11 o posterior, pero la instalación recomendada fija 3.13: es la versión que probamos y la que arranca más rápido.

## Qué hace el instalador

1. Prepara `uv` y deja `mcp-moodle` en el PATH.
2. Instala el paquete con Python 3.13 y `--compile-bytecode`, para que los comandos no compilen módulos en el primer arranque.
3. Descarga Chromium para tu arquitectura.
4. Abre el asistente para configurar la cuenta de Moodle y conectar el agente.

La instalación tarda sobre todo por la descarga de Chromium. Una vez terminada, `mcp-moodle status` responde en menos de medio segundo. Consulta [Rendimiento](RENDIMIENTO.md) para las mediciones y los ajustes por sistema.

## Windows

```powershell
git clone https://github.com/ElkinDelgado25/Moodle_Homework_assignment.git
cd .\Moodle_Homework_assignment
powershell -ExecutionPolicy Bypass -File .\INSTALAR-WINDOWS.ps1
```

El instalador prepara lo necesario, descarga Chromium y abre el asistente de configuración.

## Debian, Ubuntu y derivadas

```bash
git clone https://github.com/ElkinDelgado25/Moodle_Homework_assignment.git
cd Moodle_Homework_assignment
bash ./INSTALAR-DEBIAN.sh
```

Si se solicitan bibliotecas para Chromium, acepta la instalación y proporciona tu contraseña de `sudo`.

## Arch Linux y derivadas

```bash
git clone https://github.com/ElkinDelgado25/Moodle_Homework_assignment.git
cd Moodle_Homework_assignment
bash ./INSTALAR-ARCH.sh
```

El instalador solicita permisos de `sudo` para preparar Chromium.

## macOS

```bash
git clone https://github.com/ElkinDelgado25/Moodle_Homework_assignment.git
cd Moodle_Homework_assignment
bash ./INSTALAR-MACOS.sh
```

Cuando termine, cierra la terminal y abre una nueva. Consulta [Próximos pasos](PROXIMOS_PASOS.md) para configurar, usar y actualizar Moodle MCP.

## Actualizar

```bash
mcp-moodle update
```

Descarga la última release estable y reinstala con Python 3.13 y el bytecode compilado, igual que el instalador. Conserva tu cuenta y la configuración de los agentes. `mcp-moodle setup` hace lo mismo y además permite reconectar agentes o cambiar de cuenta.

## Desinstalar

Usa `uv tool uninstall moodle-homework-assignment`. La cuenta guardada y los archivos generados se quedan en tu carpeta de usuario; bórralos a mano si quieres eliminarlos.
