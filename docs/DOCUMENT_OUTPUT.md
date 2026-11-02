# Entregables de tareas

Cuando el usuario pide «hagamos la primera», «resuelve esta tarea» o continuar una actividad, el agente lee la tarea con `get_assignment`, descarga los anexos con `download_assignment_attachments` y resuelve cada requisito con el material de esa actividad. Un resumen genérico, un TXT con una URL o una operación de Git no completan el trabajo; si la consigna exige una aplicación o código, también se prepara ese producto y el informe documenta el trabajo real, sin inventar capturas, resultados ni fuentes. Una consulta solo informativa no crea archivos.

El entregable lo genera el servidor con `build_delivery_document`. El agente solo redacta el contenido; la portada, el formato APA 7, la exportación a PDF y la verificación son automáticos y siempre iguales, sin importar qué agente se use.

## Resultado

Dos archivos con el mismo nombre base en la carpeta pedida (por defecto `~/Documentos` o `~/Documents`):

- `.docx`, editable en Word o WPS Office.
- `.pdf`, con la misma portada y contenido.

Si ya existen archivos con ese nombre, se usa `nombre (1)`, `nombre (2)`... Nunca se sobrescriben. Los dos archivos se copian juntos o ninguno, y después se abre el PDF con la aplicación predeterminada (`open_pdf=false` lo evita; sin pantalla no se abre). El nombre base es el título, o `file_name`, sin caracteres no válidos en Windows, macOS o Linux.

## Contenido (`document`)

```json
{
  "title": "Desarrollo de una aplicación con Jetpack Compose",
  "blocks": [
    {"type": "heading", "level": 1, "text": "Introducción"},
    {"type": "paragraph", "text": "Texto con **negrita**, *cursiva* y https://github.com/usuario/proyecto.\n\nOtro párrafo."},
    {"type": "bullets", "items": ["Uno", "Dos"]},
    {"type": "numbered", "items": ["Paso 1", "Paso 2"]},
    {"type": "table", "title": "Pruebas realizadas", "rows": [["Prueba", "Resultado"], ["Compilación", "Correcta"]], "note": "Elaboración propia."},
    {"type": "figure", "title": "Pantalla principal", "path": "/ruta/absoluta/captura.png", "width_cm": 12},
    {"type": "code", "text": "fun main() {\n    println(\"Hola\")\n}"},
    {"type": "quote", "text": "Cita en bloque de más de cuarenta palabras..."},
    {"type": "page_break"}
  ],
  "references": ["Google. (2024). *Jetpack Compose*. https://developer.android.com/compose"]
}
```

- El texto admite `**negrita**`, `*cursiva*`, `[texto](https://...)` y URLs sueltas, que se convierten en hipervínculos. `\*` escribe un asterisco literal.
- Los enlaces solo pueden ser `http` o `https`, sin usuario ni caracteres invisibles.
- **Un enlace a GitHub debe mostrar la URL exacta como texto.** `[mi repo](https://github.com/...)` se rechaza. Esa URL tiene que ser la confirmada del repositorio realmente trabajado (`git remote -v` y `gh repo view --json url,nameWithOwner`).
- Las tablas se numeran («Tabla 1») y la primera fila es el encabezado. Las figuras se numeran («Figura 1»), deben ser PNG o JPEG con ruta absoluta y pesar menos de 20 MB.
- `references` va en una hoja aparte, ordenada y con sangría francesa. Déjalo vacío en una práctica con repositorio, salvo que la consigna pida bibliografía.
- Se eliminan los caracteres de control y los controles bidi que permiten disfrazar texto. Los campos de plantilla como `{{teacher}}` no se aceptan dentro del contenido de portada o del título. El código puede contener `{{ variable }}` sin problema.
- Límites: 800 bloques, 30 figuras y 400.000 caracteres en total.

## Portada (`cover`)

La plantilla ULEAM incluye el logo arriba a la izquierda en la primera página, la numeración arriba a la derecha y bloques centrados en este orden: universidad, título del trabajo, Materia, Docente, Estudiantes, Carrera, Curso y Año.

| Campo | Origen |
| --- | --- |
| `subject` | Materia de la tarea (debe coincidir con una de las materias verificadas; si no, se avisa). |
| `teacher` | Lo indica el usuario o la consigna. Nunca se inventa. |
| `student_1` | Nombre verificado al instalar; se completa solo si se omite. |
| `student_2` | Opcional. Si está vacío, la línea desaparece sin mover el resto. |
| `degree` | Carrera. |
| `class_group` | Curso o paralelo. |
| `year` | Año o periodo. |

Si falta un dato obligatorio, la herramienta devuelve `status="missing_cover_fields"` con la lista y no escribe ningún archivo; el agente pregunta solo esos datos. El perfil `document_profile.json` acepta números (por ejemplo `"year": 2026`) y descarta solo los campos inválidos.

## Formato APA 7

- Times New Roman de 12 puntos, interlineado doble, márgenes de 2,54 cm y sangría de primera línea de 1,27 cm.
- Título del trabajo centrado y en negrita al inicio de la página 2.
- Títulos de nivel 1 centrados en negrita, nivel 2 a la izquierda en negrita y nivel 3 a la izquierda en negrita cursiva.
- Listas con viñetas, y listas numeradas que vuelven a empezar en 1.
- Tablas con líneas horizontales.
- Código en Courier New de 10 puntos.
- Referencias en una hoja aparte con sangría francesa de 1,27 cm.
- Numeración en todas las páginas, arriba a la derecha.
- Idioma español (Ecuador) para la ortografía y los metadatos.
- Título y autor también en las propiedades del documento.

### Compatibilidad con Word y WPS Office

Todos los estilos de la plantilla tienen Times New Roman explícita en los cuatro rangos de escritura y ningún atributo de fuente del tema, que Word y WPS priorizan sobre el nombre de la fuente; por eso los títulos ya no salen en Calibri. La plantilla está en modo de compatibilidad actual (15), sin `stylesWithEffects.xml` ni controles de contenido, y los hipervínculos usan el estilo `Hyperlink` con relación externa. Se reconstruye con:

```bash
uv run python scripts/build_document_template.py
```

## PDF

| `pdf_engine` | Comportamiento |
| --- | --- |
| `auto` (predeterminado) | LibreOffice si está instalado (conversión fiel del DOCX); si no está o falla, el renderizador integrado. |
| `builtin` | Renderizador integrado (`fpdf2`): genera el PDF desde el mismo contenido, con la misma portada y maquetación. No necesita LibreOffice ni WPS. |
| `libreoffice` | Exige LibreOffice. |

LibreOffice se busca en el `PATH` (`soffice`, `libreoffice`, `lowriter`), en `Program Files` en Windows, en `/Applications/LibreOffice.app` en macOS y en `MOODLE_SOFFICE`. Se ejecuta sin interfaz, con un perfil propio y un límite de 120 segundos.

El renderizador integrado usa Times New Roman si está instalada (Windows, macOS o `fc-match` en Linux); si no, una serif compatible (Liberation Serif, Tinos o DejaVu Serif), y avisa en `warnings`.

WPS Office para Linux no ofrece una conversión sin interfaz fiable: su automatización RPC falla al exportar a PDF. Por eso el DOCX está pensado para revisarse y editarse en WPS, y el PDF lo genera el servidor. Si se edita el DOCX en WPS, se puede exportar el PDF desde WPS y validar el par con `finish_delivery`.

## Verificación

Antes de copiar, el servidor comprueba:

- que el DOCX es un paquete válido sin XML dañado y sin campos de portada sin llenar;
- que el PDF tiene la cabecera `%PDF-`, se puede leer y tiene páginas;
- que el DOCX y el PDF tienen el mismo nombre base.

Si alguna comprobación falla, no se entrega nada. También se avisa en `warnings`:

- si un enlace del DOCX no está en el PDF;
- si el PDF es anterior al DOCX;
- si algún estilo usa fuentes del tema;
- si el PDF no incrusta Times New Roman.

El resultado incluye `pages`, `hyperlinks`, `pdf_engine`, `tables`, `figures` y las rutas finales.

## Política de contenido

Para una práctica con repositorio, el desarrollo incluye el enlace del proyecto y omite las citas y las referencias, salvo que la consigna o el usuario las pidan. El tutorial del docente es material de entrada, no una referencia ni el repositorio del estudiante. La URL de GitHub se confirma con el remoto Git y con `gh repo view --json url,nameWithOwner`, se distingue el fork del tutorial y se escribe exacta. Si no se puede confirmar, se informa y se pide el enlace. Las incidencias de Git o de preparación se comunican en la conversación, no en el documento. En los trabajos con bibliografía se usan citas autor-fecha y referencias APA verificadas.

## Subir a Moodle

Al presentar los dos archivos, el agente pregunta si se suben, salvo que el usuario ya lo haya pedido. `upload_assignment_files` recibe las rutas del DOCX y el PDF, guarda la entrega y devuelve `submission.note`. Si la actividad usa borradores, el estudiante debe pulsar «Enviar tarea» en Moodle: la herramienta nunca envía para calificar.
