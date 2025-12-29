# TYBA Expediente Downloader

Esta herramienta automatiza la descarga de expedientes judiciales desde la plataforma **TYBA (Rama Judicial de Colombia)**. Permite obtener de forma masiva y organizada todos los documentos de las pestañas "Archivos" y "Actuaciones".

## Características Principales

- **Descarga Inteligente**: Obtiene automáticamente todos los adjuntos (pestaña Archivos) y documentos (pestaña Actuaciones).
- **Lista de Documentos Organizada**: Genera un archivo `lista.txt` en cada carpeta con el número de expediente y la relación cronológica de documentos vs. su fecha de actuación real.
- **Relación de Fechas**: El script es capaz de identificar la fecha del "Auto Admisorio" y asociarla inteligentemente a la Demanda principal.
- **Filtrado de Notificaciones**: Incluye un motor de filtrado (opcional) que analiza el contenido de los PDFs para omitir citaciones, estados y notificaciones administrativas, descargando solo lo sustancial.
- **Interfaz Premium**: Consola minimalista con colores ANSI, barras de progreso y mensajes claros.
- **Seguridad Anti-Bloqueo**: Implementa retrasos humanos dinámicos y manejo de reintentos para evitar bloqueos por CAPTCHA.

## Requisitos

- **Python 3.8+**
- **Playwright** (para la automatización del navegador)
- **PyPDF** (para el filtrado inteligente de documentos)

## Instalación y Configuración

1. Instale las dependencias necesarias:

   ```bash
   pip install playwright pypdf
   playwright install chromium
   ```

2. Ejecute el programa:

   ```bash
   python tyba_downloader.py
   ```

## Uso

1. Al iniciar, el programa preguntará si desea **omitir notificaciones y citaciones** (s/n).
2. Ingrese el **radicado de 23 dígitos** del proceso.
3. El script creará automáticamente una subcarpeta con el nombre del radicado y comenzará la descarga organizada.
4. Al finalizar, encontrará el archivo `lista.txt` con el índice del expediente.

## Aviso Legal

Este software es una herramienta de productividad para acceder a información de naturaleza **pública** (Constitución Política de Colombia, Art. 74). El usuario es el único responsable del uso que se le dé a la información descargada y del cumplimiento de las políticas de uso de la plataforma TYBA.

## Licencia

Este proyecto se distribuye bajo la licencia **GNU General Public License v3.0** (GPLv3).

- **Uso Estudiantil y Personal**: Totalmente gratuito bajo los términos de la GPLv3.
- **Uso Comercial**: Si una entidad quiere usar el programa o una parte del programa para uso comercial y quiere obtener una licencia, favor contactarse directamente conmigo a **<iangelromero@pm.me>**.

Para consultas sobre licencias comerciales o personalizaciones, por favor contactar al desarrollador.
