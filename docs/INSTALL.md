# Instalación

Produced by elkindelgado25

Moodle MCP se instala desde una copia del repositorio. Elige tu sistema y ejecuta sus tres comandos.

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
