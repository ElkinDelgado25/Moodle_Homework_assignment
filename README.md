# Moodle_Homework_assignment

Este programa usa Playwright para iniciar sesión en Moodle, revisar las actividades tipo **Tarea**, mostrar las que todavía no aparecen como entregadas e imprimir su contenido, estado, fecha de vencimiento y enlace.

## Requisitos

- Node.js 18 o superior.
- Una cuenta activa en Moodle.
- Acceso a Internet.

## Instalación

```bash
npm install
npx playwright install chromium
cp .env.example .env
```

Edita `.env` y completa `MOODLE_USERNAME` y `MOODLE_PASSWORD`. No compartas ni subas ese archivo: está incluido en `.gitignore`.

## Ejecutar

```bash
npm start
```

El programa consulta Moodle una vez y avisa por la terminal. Puedes volver a ejecutarlo cuando enciendas la computadora. Para ver el navegador durante una prueba, cambia `MOODLE_HEADLESS=false` en `.env`.

## Notas

- La identificación de tareas pendientes depende del estado que Moodle muestre en cada actividad.
- Si Moodle usa autenticación institucional, CAPTCHA o código de doble factor, el inicio de sesión automático puede requerir una sesión manual o una adaptación de los selectores.
- El programa no entrega tareas ni modifica información en Moodle.
