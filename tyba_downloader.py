import os
import random
import sys
import time
import traceback


# LOG DE DEPURACIÓN DETALLADO
class DebugLogger:
    def __init__(self):
        self.log_file = "debug_log.txt"
        with open(self.log_file, "w", encoding="utf-8") as f:
            f.write(f"=== INICIO DE SESIÓN DE DEPURACIÓN: {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
    
    def log(self, msg):
        timestamp = time.strftime('%H:%M:%S')
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {msg}\n")
        except: pass

logger = DebugLogger()

# ARCHIVO DE LOG DE ERRORES CRÍTICOS
def log_fatal_error(error_msg):
    try:
        logger.log(f"ERROR FATAL: {error_msg}")
        with open("fatal_error.txt", "w", encoding="utf-8") as f:
            f.write("=== LOG DE ERROR CRÍTICO ===\n")
            f.write(f"Fecha: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(error_msg)
    except:
        pass

try:
    import re
    import unicodedata
    from playwright.sync_api import sync_playwright, Page, BrowserContext, Browser
    from playwright_stealth import Stealth
    try:
        from pypdf import PdfReader
    except ImportError:
        pass
except Exception:
    error_info = traceback.format_exc()
    print(f"\n\033[91m!!! ERROR DE INICIO !!!\033[0m\n{error_info}")
    log_fatal_error(error_info)
    input("\nPresione Enter para salir...")
    sys.exit(1)

class TybaDownloader:
    def __init__(self, output_base_dir=None, silent_mode=True):
        if output_base_dir is None:
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
        else:
            self.base_dir = os.path.abspath(output_base_dir)
            
        self.silent_mode = silent_mode
            
        self.base_url = "https://procesojudicial.ramajudicial.gov.co/Justicia21/Administracion/Ciudadanos/frmConsulta.aspx"
        self.downloaded_docs = [] # List of {date, name, type}
        self.auto_admite_date = "Pendiente"
        self.errors = [] # List of errors for the final report
        
        # ANSI Colors
        self.C_CYAN = "\033[96m"
        self.C_GREEN = "\033[92m"
        self.C_YELLOW = "\033[93m"
        self.C_RED = "\033[91m"
        self.C_BOLD = "\033[1m"
        self.C_END = "\033[0m"

    def sanitize_filename(self, name):
        cleaned = re.sub(r'[\\/*?:"<>|]', "", name)
        cleaned = " ".join(cleaned.split())
        return cleaned

    def _normalize_text(self, text):
        """Normaliza el texto: quita acentos, convierte a mayúsculas y limpia espacios."""
        if not text: return ""
        text = text.upper()
        # Eliminar acentos usando unicodedata
        normalized = "".join(
            c for c in unicodedata.normalize('NFD', text)
            if unicodedata.category(c) != 'Mn'
        )
        return " ".join(normalized.split())

    def _is_notification(self, file_path, act_name=""):
        """Verificación robusta y general para identificar notificaciones y citaciones."""
        # 1. Normalización y Palabras Clave Generales
        u_act = self._normalize_text(act_name)
        
        # 0. Palabras de Protección (Documentos sustanciales que NUNCA se deben borrar)
        # Ampliado para cubrir todos los tipos de procesos (Ejecutivos, Familia, etc.)
        proteccion = [
            "AUTO INTERLOCUTORIO", "SENTENCIA", "AUTO NR", "AUTO NUMERO", "RESUELVE", 
            "DEMANDA", "PRETENSIONES", "ORDENA", "CONTESTACION", "RECURSO", "ALEGATOS", 
            "MEMORIAL", "AUDIENCIA", "ACTA", "PODER", "SOLICITUD", "INCIDENTE",
            "MANDAMIENTO", "LIQUIDACION", "AVALUO", "SECUESTRO", "REMATE", "COSTAS", 
            "INVENTARIO", "DICTAMEN", "PERITAJE", "AUTO", "FALLO"
        ]
        
        # Palabras clave que indican una comunicación puramente procesal/notoria
        notif_keywords = [
            "NOTIFICACION", "ENVIO", "CITATORIO", "AVISO", "ESTADO", 
            "CERTIFICADO", "PRUEBA DE ENTREGA", "FORMATO DE CITACION", 
            "COMUNICACION", "OFICIO", "COMUNICADO", "CONSTANCIA", "ACUSE",
            "GUIA", "REPORTE DE CORREO", "Telegrama", "HACE SABER"
        ]
        
        # Si el nombre de la actuación contiene estas palabras, es casi seguro que es omitible
        is_likely_notif = False
        for kw in notif_keywords:
            if kw in u_act:
                is_likely_notif = True
                logger.log(f"    [Filtro] Posible notificación por nombre ('{kw}'): '{act_name}'")
                break

        # Si el nombre indica que es sustancial, lo protegemos por NOMBRE
        # PERO SOLO SI NO TIENE TAMBIÉN PALABRAS DE NOTIFICACIÓN EXPLÍCITAS
        has_protected_word = False
        protected_word_found = ""
        for p in proteccion:
            if p in u_act:
                has_protected_word = True
                protected_word_found = p
                break
        
        if has_protected_word and not is_likely_notif:
            logger.log(f"    [Filtro] Protegido por nombre: '{act_name}' (Palabra: {protected_word_found})")
            return False
        elif has_protected_word and is_likely_notif:
             logger.log(f"    [Filtro] Nombre ambiguo ('{protected_word_found}' + Notificación). Se analizará contenido.")

        if not os.path.exists(file_path):
            return is_likely_notif
            
        try:
            reader = PdfReader(file_path)
            # Solo analizamos la primera página para eficiencia
            raw_content = reader.pages[0].extract_text()
            first_page = self._normalize_text(raw_content)
            
            # PRIORIDAD 1: ¿Tiene formato obvio de notificación? (Si sí, es notificación sin duda)
            # Ampliamos los indicios para cubrir más formatos de Tyba / Rama Judicial
            indicios_formato = [
                "DIRECCION DE NOTIFICACION", "CODIGO DE BARRAS", "GUIA NO", "ACUSE DE RECIBO", 
                "AVISO DE NOTIFICACION", "HACE SABER", "POR MEDIO DEL PRESENTE", 
                "NOTIFICACION POR ESTADO", "NOTIFICACION PERSONAL", "SECRETARIA",
                "RAMA JUDICIAL DEL PODER PUBLICO", "DE MANERA ELECTRONICA", "SISTEMA DE GESTION"
            ]
            
            if is_likely_notif:
                # Si ya sospechábamos por el nombre, somos agresivos confirmando formato
                if any(ind in first_page for ind in indicios_formato):
                    logger.log(f"    [Filtro] Confirmado como notificación (Formato detected, nombre sospechoso): '{act_name}'")
                    return True

            # 2. Protección por contenido del PDF
            # Usamos una lista más estricta para contenido (quitamos palabras genéricas como "AUTO" que aparecen en notificaciones)
            proteccion_contenido = [
                "AUTO INTERLOCUTORIO", "SENTENCIA", "RESUELVE", "DEMANDA", "PRETENSIONES", 
                "ORDENA", "CONTESTACION", "RECURSO", "ALEGATOS", "MEMORIAL", "AUDIENCIA", 
                "ACTA", "PODER", "SOLICITUD", "INCIDENTE", "MANDAMIENTO", "LIQUIDACION", 
                "AVALUO", "SECUESTRO", "REMATE", "COSTAS", "INVENTARIO", "DICTAMEN", "PERITAJE", "FALLO"
            ]
            
            for p in proteccion_contenido:
                if p in first_page:
                    logger.log(f"    [Filtro] Protegido por contenido ('{p}')")
                    return False # Es un documento de fondo, proteger
            
            # 3. Verificación final: ¿Contiene el PDF palabras de notificación?
            for kw in notif_keywords:
                if kw in first_page:
                    logger.log(f"    [Filtro] Detectado como notificación por contenido ('{kw}')")
                    return True
                    
            return is_likely_notif
        except Exception as e:
            logger.log(f"    [Filtro] Error analizando PDF: {e}. Usando predicción por nombre: {is_likely_notif}")
            return is_likely_notif

    def _human_delay(self, min_s=1, max_s=3):
        """Simula una pausa humana aleatoria."""
        time.sleep(random.uniform(min_s, max_s))

    def _emulate_mouse(self, page: Page):
        """Mueve el ratón de forma aleatoria para parecer humano."""
        try:
            viewport = page.viewport_size or {'width': 1280, 'height': 720}
            for _ in range(3):
                x = random.randint(0, viewport['width'])
                y = random.randint(0, viewport['height'])
                page.mouse.move(x, y, steps=10)
                self._human_delay(0.2, 0.5)
        except:
            pass

    def download_case(self, radicado, skip_notifications=False):
        print(f"\n{self.C_CYAN}{self.C_BOLD}>>> Iniciando proceso: {radicado}{self.C_END}")
        self.downloaded_docs = []
        self.errors = []
        self.auto_admite_date = "Sin fecha"
        
        case_dir = os.path.join(self.base_dir, radicado)
        try:
            os.makedirs(case_dir, exist_ok=True)
        except Exception as e:
            case_dir = os.path.join(os.path.expanduser("~"), "TYBA_Downloads", radicado)
            os.makedirs(case_dir, exist_ok=True)

        with sync_playwright() as p:
            # Pseudo-Silent Mode: Navegador visible pero fuera de la pantalla
            # Esto ayuda con reCAPTCHA y evita errores de visibilidad de elementos
            browser = p.chromium.launch(
                headless=False, 
                slow_mo=50,
                args=["--window-position=-2000,0", "--no-sandbox"]
            )
            
            # Configuración de contexto con viewport fijo y grande
            context = browser.new_context(
                accept_downloads=True, 
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={'width': 1920, 'height': 1080},
                locale="es-CO",
                timezone_id="America/Bogota",
                permissions=["geolocation"]
            )
            
            page = context.new_page()
            
            # Aplicamos modo sigilo (Compatibilidad con v2.0.0)
            Stealth().use_sync(page)

            try:
                self._search_case(page, radicado)
                
                # We process Actuaciones first to find the "Auto Admite" date
                self._process_actuaciones(page, context, case_dir, skip_notifications)
                self._process_archivos(page, case_dir, skip_notifications)
                
                print(f"\n{self.C_GREEN}{self.C_BOLD}✓ Expediente completo: {radicado}{self.C_END}")
            except Exception as e:
                print(f"\n{self.C_RED}✗ Error fatal durante el proceso: {e}{self.C_END}")
                try: page.screenshot(path=os.path.join(case_dir, "error_screenshot.png"))
                except: pass
            finally:
                # Guardamos la lista aunque haya habido un error parcial
                self._save_doc_list(case_dir)
                print(f"{self.C_CYAN}Ubicación: {case_dir}{self.C_END}")
                browser.close()

    def _save_doc_list(self, case_dir):
        list_path = os.path.join(case_dir, "lista.txt")
        try:
            with open(list_path, "w", encoding="utf-8") as f:
                f.write(f"EXPEDIENTE: {os.path.basename(case_dir)}\n")
                f.write("="*50 + "\n")
                f.write(f"{'FECHA':<12} | {'DOCUMENTO'}\n")
                f.write("-"*50 + "\n")
                
                for doc in self.downloaded_docs:
                    if doc['type'] == 'archivo':
                        date = self.auto_admite_date if "DEMANDA" in doc['name'].upper() else "N/A"
                        f.write(f"{date:<12} | {doc['name']}\n")
                
                f.write("-"*50 + "\n")
                for doc in self.downloaded_docs:
                    if doc['type'] == 'actuacion':
                        f.write(f"{doc['date']:<12} | {doc['name']}\n")
                
                if self.errors:
                    f.write("\n" + "!"*20 + " ERRORES DURANTE LA DESCARGA " + "!"*20 + "\n")
                    for err in self.errors:
                        f.write(f"- {err}\n")
            
            print(f"  {self.C_GREEN}→ Archivo 'lista.txt' generado.{self.C_END}")
            if self.errors:
                print(f"  {self.C_YELLOW}⚠ Se encontraron {len(self.errors)} errores (ver lista.txt).{self.C_END}")
        except Exception as e:
            print(f"  {self.C_RED}→ Error creando lista.txt: {e}{self.C_END}")

    def _search_case(self, page: Page, radicado):
        print(f"{self.C_YELLOW}Conectando con TYBA...{self.C_END}")
        page.goto(self.base_url)
        time.sleep(2)
        
        max_retries = 8
        logger.log(f"Iniciando búsqueda de radicado: {radicado} con {max_retries} intentos.")
        for attempt in range(max_retries):
            print(f"  Buscando radicado (intento {attempt+1})...")
            
            # Emulamos comportamiento humano antes de llenar
            self._emulate_mouse(page)
            self._human_delay(1, 2)
            
            page.fill("#MainContent_txtCodigoProceso", "")
            self._human_delay(0.2, 0.5)
            
            # Escritura con ritmo variable
            for char in radicado:
                page.type("#MainContent_txtCodigoProceso", char)
                time.sleep(random.uniform(0.1, 0.3))
                
            self._human_delay(1, 1.5)
            self._emulate_mouse(page)
            page.click("#MainContent_btnConsultar")
            
            # Espera algo más larga por el captcha
            time.sleep(random.uniform(4, 6))
            
            try:
                page.wait_for_selector("#MainContent_grdProceso_imgbConsultarGrilla_0", timeout=8000)
                break
            except:
                captcha_err = page.get_by_text("El valor de la Capcha no coincide").is_visible() or \
                              page.get_by_text("Code Captcha value does not match").is_visible()
                
                if captcha_err:
                    wait_time = 5 + (attempt * 2) # Espera incremental
                    print(f"  {self.C_YELLOW}! Error de CAPTCHA, reintentando en {wait_time}s...{self.C_END}")
                    time.sleep(wait_time)
                    reload_btn = page.locator("#MainContent_imgCaptcha").first
                    if reload_btn.is_visible(): reload_btn.click() # Intentar refrescar imagen si existe
                    continue
                else:
                    # Si no es error de captcha, quizás la página está lenta
                    try:
                        page.wait_for_selector("#MainContent_grdProceso_imgbConsultarGrilla_0", timeout=5000)
                        break
                    except: continue

        details_btn = page.locator("#MainContent_grdProceso_imgbConsultarGrilla_0").first
        details_btn.wait_for(state="visible", timeout=60000)
        details_btn.click(force=True)
        page.wait_for_selector("a[href='#Archivos']", timeout=45000)

    def _process_archivos(self, page: Page, case_dir, skip_notifications=False):
        print(f"\n{self.C_CYAN}[Pestaña: Archivos]{self.C_END}")
        page.click("a[href='#Archivos']")
        # Eliminamos sleeps innecesarios, wait_for_selector es más rápido
        
        try:
            page.wait_for_selector("input[id*='grdArchivos_imgbConsultarGrillaArchivos']", timeout=10000)
        except:
            print("  - Sin archivos disponibles.")
            return

        logger.log(f"Entrando a pestaña Archivos...")
        buttons = page.locator("input[id*='grdArchivos_imgbConsultarGrillaArchivos']")
        count = buttons.count()
        logger.log(f"Encontrados {count} botones de descarga en Archivos.")

        for i in range(count):
            button = page.locator(f"#MainContent_grdArchivos_imgbConsultarGrillaArchivos_{i}")
            if not button.is_visible(): continue
                
            file_description = button.locator("xpath=../..").inner_text().split("\n")[0].strip()
            safe_name = self.sanitize_filename(file_description)
            file_path = os.path.join(case_dir, f"{safe_name}.pdf")
            
            if os.path.exists(file_path) and os.path.getsize(file_path) > 1000:
                 if skip_notifications and self._is_notification(file_path, act_name=file_description):
                     os.remove(file_path)
                     logger.log(f"Archivo existente eliminado por filtro (Notificación): {safe_name}")
                 else:
                     self.downloaded_docs.append({'date': 'N/A', 'name': safe_name, 'type': 'archivo'})
                     print(f"  {self.C_CYAN}○ Ya existe:{self.C_END} {safe_name}")
                     logger.log(f"Archivo ya existe: {safe_name}")
                     continue

            # Reintentos de descarga para mayor resiliencia
            max_dl_retries = 2
            success = False
            
            for dl_attempt in range(max_dl_retries):
                try:
                    button.click()
                    iframe = page.locator("#MainContent_IframeViewPDF").first
                    page.wait_for_selector("#MainContent_IframeViewPDF", timeout=30000)
                    src = iframe.get_attribute("src")
                    if src:
                        url = (page.url.rsplit('/', 1)[0] + '/' + src).replace("\\", "/")
                        response = page.context.request.get(url, timeout=60000)
                        if response.ok and len(response.body()) > 100:
                            with open(file_path, 'wb') as f: f.write(response.body())
                            
                            if skip_notifications and self._is_notification(file_path, act_name=file_description):
                                print(f"  {self.C_YELLOW}○ Omitida (Notificación): {safe_name}{self.C_END}")
                                os.remove(file_path)
                            else:
                                print(f"  {self.C_GREEN}↓ Descargado:{self.C_END} {safe_name}")
                                self.downloaded_docs.append({'date': 'N/A', 'name': safe_name, 'type': 'archivo'})
                            success = True
                            break # Exito, salir del loop de reintentos
                    
                    close_btn = page.locator("#MainContent_imbCerrarVistaPDF")
                    if close_btn.is_visible(): close_btn.click()
                except Exception as e:
                    if dl_attempt == max_dl_retries - 1:
                        self.errors.append(f"Error final en Archivo '{safe_name}': {e}")
                        print(f"  {self.C_RED}⚠ Falló descarga de {safe_name} tras {max_dl_retries} intentos.{self.C_END}")
                    else:
                        print(f"  {self.C_YELLOW}! Reintentando descarga de {safe_name}...{self.C_END}")
                        time.sleep(2)

    def _process_actuaciones(self, page: Page, context: BrowserContext, case_dir, skip_notifications=False):
        print(f"\n{self.C_CYAN}[Pestaña: Actuaciones]{self.C_END}")
        page.click("a[href='#Actuaciones']")
        # Velocidad: esperamos contenido, no tiempo
        page.wait_for_selector("#MainContent_grdActuaciones", timeout=10000)
        
        # Determine column indices more robustly
        header_row = page.locator("#MainContent_grdActuaciones tr").first
        headers = header_row.locator("th, td").all_text_contents()
        date_idx = -1
        desc_idx = -1
        for idx, h in enumerate(headers):
            text = h.upper().strip()
            if "FECHA" in text and "REGISTRO" not in text: date_idx = idx
            if "ACTUACIÓN" in text or "DESCRIPCIÓN" in text: desc_idx = idx

        # Logic for multiple pages if they exist
        while True:
            btns = page.locator("input[id*='grdActuaciones_imgbConsultarGrilla']")
            count = btns.count()
            print(f"  Analizando {count} actuaciones en esta página...")
            logger.log(f"Procesando página de actuaciones. Encontradas: {count}")
            
            for i in range(count):
                # Mensaje de progreso visual para el usuario
                print(f"  > Procesando actuación {i+1}/{count} de esta página...", end="\r")
                logger.log(f"--- Inicio procesamiento actuación {i+1}/{count} ---")
                
                btn_id = f"MainContent_grdActuaciones_imgbConsultarGrilla_{i}"
                row_xpath = f"xpath=//*[@id='{btn_id}']/../.."
                row = page.locator(row_xpath)
                
                cols = row.locator("td").all_text_contents()
                if not cols: continue
                
                act_date = cols[date_idx].strip() if date_idx != -1 else "N/A"
                act_name = cols[desc_idx].strip() if desc_idx != -1 else f"Actuación_{i}"
                
                # Identify Auto Admite date (Auto Admite, Auto Admisorio, or Auto de Admisión)
                # Using more robust matching (ADMIS covers Admisorio, Admisión, etc)
                u_name = act_name.upper()
                if "AUTO" in u_name and ("ADMITE" in u_name or "ADMIS" in u_name):
                    if self.auto_admite_date == "Sin fecha":
                        self.auto_admite_date = act_date
                        print(f"  {self.C_YELLOW}→ Fecha detectada para Demanda: {act_date}{self.C_END}")

                # Selección rápida de actuación
                f_btn_id = f"MainContent_grdActuaciones_imgbConsultarGrilla_{i}"
                page.click(f"#{f_btn_id}")
                
                try:
                    # Esperamos la vista de detalle
                    page.wait_for_selector("#MainContent_btnRegresarActuacion", timeout=20000)
                    
                    # Intentamos esperar explícitamente la tabla de archivos
                    # Aumentamos a 5s para cubrir conexiones lentas ("solución general")
                    try:
                        page.wait_for_selector("#MainContent_grdArchivosActuaciones", timeout=5000)
                    except:
                        pass 

                    files_locator = page.locator("input[id*='grdArchivosActuaciones_imgDescargaArchivos']")
                    files_count = files_locator.count()
                    logger.log(f"Actuación '{act_name}': Encontrados {files_count} archivos adjuntos.")
                    
                    if files_count == 0:
                        # Verificación visual rápida: ¿está vacío o falló la carga?
                        print(f"  - No se encontraron archivos adjuntos.")
                    
                    for j in range(files_count):
                        f_btn_id = f"MainContent_grdArchivosActuaciones_imgDescargaArchivos_{j}"
                        f_btn = page.locator(f"#{f_btn_id}")
                        f_row = page.locator(f"xpath=//*[@id='{f_btn_id}']/../..")
                        f_name = self.sanitize_filename(f_row.inner_text().strip())
                        if not f_name: f_name = f"{self.sanitize_filename(act_name)}_{j}"
                        
                        logger.log(f"  [Archivo {j+1}/{files_count}] Procesando: '{f_name}'")

                        f_path = os.path.join(case_dir, f"{f_name}.pdf")
                        if os.path.exists(f_path) and os.path.getsize(f_path) > 1000:
                            is_notif = False
                            if skip_notifications:
                                is_notif = self._is_notification(f_path, act_name=f_name)
                                logger.log(f"  - Check Notificación (Existente): {is_notif}")

                            if skip_notifications and is_notif:
                                os.remove(f_path)
                                logger.log(f"  - ELIMINADO (Notificación existente): {f_name}")
                            else:
                                if not any(d['name'] == f_name for d in self.downloaded_docs):
                                    self.downloaded_docs.append({'date': act_date, 'name': f_name, 'type': 'actuacion'})
                                print(f"  {self.C_CYAN}○ Ya existe:{self.C_END} {f_name}")
                                logger.log(f"  - OMITIDO (Ya existe validado): {f_name}")
                                continue

                        # Reintentos para descargas de actuaciones
                        max_act_retries = 3 
                        success = False
                        for act_attempt in range(max_act_retries):
                            logger.log(f"  - Intento de descarga {act_attempt+1}/{max_act_retries} para '{f_name}'")
                            new_p = None
                            try:
                                # Aseguramos que el botón sea visible en el viewport antes de click
                                f_btn.scroll_into_view_if_needed()
                                time.sleep(0.5) # Pequeña pausa para que el scroll termine
                                
                                # A veces el click necesita ser forzado o reintentado si el portal ignora el primero
                                with context.expect_page(timeout=60000) as new_p_info: 
                                    f_btn.click(force=True, timeout=30000)
                                    
                                new_p = new_p_info.value
                                
                                # Esperamos a que la página inicie carga de forma resiliente
                                try:
                                    new_p.wait_for_load_state("domcontentloaded", timeout=45000)
                                except:
                                    pass 
                                
                                t_url = new_p.url if "Descargando.aspx" in new_p.url else None
                                if not t_url:
                                    iframe = new_p.locator("iframe[src*='Descargando.aspx']").first
                                    # Espera generosa para el iframe generador
                                    if iframe.is_visible() or iframe.wait_for(state="visible", timeout=30000):
                                        t_url = iframe.get_attribute("src")
                                
                                if t_url:
                                    if not t_url.startswith("http"): 
                                        t_url = (new_p.url.rsplit('/', 1)[0] + '/' + t_url).replace("\\", "/")
                                    
                                    # Tiempo muy generoso para generación de PDF en servidores lentos
                                    res = new_p.request.get(t_url, timeout=120000) 
                                    if res.ok and len(res.body()) > 100:
                                        with open(f_path, 'wb') as f: f.write(res.body())
                                        
                                        logger.log(f"  - Descarga completada. Tamaño: {len(res.body())} bytes")
                                        
                                        is_notif = False
                                        if skip_notifications:
                                            is_notif = self._is_notification(f_path, act_name=f_name)
                                            logger.log(f"  - Check Notificación (Nuevo): {is_notif}")

                                        if skip_notifications and is_notif:
                                            print(f"  {self.C_YELLOW}○ Omitida (Notificación): {f_name}{self.C_END}")
                                            logger.log(f"  - ELIMINADO (Filtro Notificación): {f_name}")
                                            os.remove(f_path)
                                        else:
                                            print(f"  {self.C_GREEN}↓ Descargado:{self.C_END} {f_name}")
                                            logger.log(f"  - CONSERVADO: {f_name}")
                                            self.downloaded_docs.append({'date': act_date, 'name': f_name, 'type': 'actuacion'})
                                        success = True
                                        new_p.close()
                                        break
                                
                                if new_p: new_p.close()
                                raise Exception("No se pudo detectar el generador del PDF")
                            except Exception as e:
                                if new_p: 
                                    try: new_p.close()
                                    except: pass
                                if act_attempt == max_act_retries - 1:
                                    self.errors.append(f"Error final en Actuación '{f_name}' ({act_date}): {e}")
                                    print(f"  {self.C_RED}⚠ Falló descarga de {f_name} tras {max_act_retries} intentos.{self.C_END}")
                                else:
                                    wait_retry = 3 + (act_attempt * 2)
                                    print(f"  {self.C_YELLOW}! Reintentando descarga de {f_name} en {wait_retry}s... ({e}){self.C_END}")
                                    time.sleep(wait_retry)
                except Exception as e:
                    self.errors.append(f"Error procesando lista de archivos en actuación {i}: {e}")
                    logger.log(f"Error procesando lista de archivos en actuación {i} ('{act_name}'): {e}")

                page.click("#MainContent_btnRegresarActuacion")
                # CRÍTICO: Esperar a que la tabla de actuaciones reaparezca totalmente antes de continuar
                try:
                    page.wait_for_selector("#MainContent_grdActuaciones", timeout=15000)
                    # Pequeña pausa de estabilización del DOM
                    time.sleep(0.5)
                except:
                    logger.log("Advertencia: No se detectó regeneración de tabla de actuaciones.")

            # Lógica de paginación de TYBA (Números en la parte inferior)
            # Buscamos el siguiente número de página después de la actual
            try:
                # TYBA suele usar un grid con una fila de paginación al final
                pagination_row = page.locator("#MainContent_grdActuaciones tr.Paginacion").first
                if pagination_row.is_visible():
                    current_page_span = pagination_row.locator("span").first
                    if current_page_span.is_visible():
                        current_page_num = int(current_page_span.inner_text())
                        next_page_link = pagination_row.locator(f"a:has-text('{current_page_num + 1}')").first
                        if next_page_link.is_visible():
                            print(f"  {self.C_YELLOW}→ Avanzando a página {current_page_num + 1}...{self.C_END}")
                            next_page_link.click()
                            time.sleep(2)
                            page.wait_for_selector("#MainContent_grdActuaciones", timeout=10000)
                            continue # Seguimos en el while True
            except Exception:
                pass
            
            # Si no hay más páginas o hubo error, salimos
            break

if __name__ == "__main__":
    try:
        os.system('cls' if os.name == 'nt' else 'clear')
        C_CYAN = "\033[96m"
        C_BLUE = "\033[94m"
        C_BOLD = "\033[1m"
        C_END = "\033[0m"
        
        title = "TYBA DOWNLO@DER"
        print(f"\n{C_BLUE}{C_BOLD}{'='*60}")
        print(f"{title:^60}")
        print(f"{'='*60}{C_END}")
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        notif_pref = input(f"{C_BOLD}¿Omitir notificaciones y citaciones? (s/n) [S]:{C_END} ").strip().lower()
        skip_notif = notif_pref != 'n'
        
        downloader = TybaDownloader(output_base_dir=script_dir, silent_mode=True)
        
        while True:
            radicado = input(f"\n{C_BOLD}Ingrese 23 dígitos del radicado (o 'q' para salir):{C_END} ").strip()
            if not radicado: continue
            if radicado.lower() == 'q': break
                
            try:
                downloader.download_case(radicado, skip_notifications=skip_notif)
            except Exception as e:
                print(f"\n{downloader.C_RED}Error: {e}{downloader.C_END}")
                
        print(f"\n{C_CYAN}Finalizado. ¡Hasta la próxima!{C_END}")
        
    except Exception:
        error_msg = traceback.format_exc()
        print(f"\n\033[91m!!! ERROR CRÍTICO !!!\033[0m\n{error_msg}")
        log_fatal_error(error_msg)
        print("\nSe ha generado 'fatal_error.txt' con los detalles.")
        input("\nPresione Enter para salir...")
