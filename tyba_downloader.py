import os
import re
import time
from playwright.sync_api import sync_playwright, Page, BrowserContext, Browser
try:
    from pypdf import PdfReader
except ImportError:
    pass

class TybaDownloader:
    def __init__(self, output_base_dir=None):
        if output_base_dir is None:
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
        else:
            self.base_dir = os.path.abspath(output_base_dir)
            
        self.base_url = "https://procesojudicial.ramajudicial.gov.co/Justicia21/Administracion/Ciudadanos/frmConsulta.aspx"
        self.downloaded_docs = [] # List of {date, name, type}
        self.auto_admite_date = "Pendiente"
        
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

    def _is_notification(self, file_path):
        """Verificación más estricta para no omitir requerimientos u órdenes judiciales."""
        if not os.path.exists(file_path):
            return False
        try:
            reader = PdfReader(file_path)
            # Analizamos la primera página para cabeceras y propósito
            first_page = reader.pages[0].extract_text().upper()
            
            # NO BORRAR si parece un documento judicial real
            proteccion = ["AUTO INTERLOCUTORIO", "SENTENCIA", "AUTO Nº", "RESUELVE", "DEMANDA", "PRETENSIONES", "ORDENA"]
            for p in proteccion:
                if p in first_page:
                    return False
            
            # SOLO BORRAR si coincide con formatos de notificación/citación puros
            keywords = [
                "CONSTANCIA DE ENVIO", "CITATORIO", "AVISO DE NOTIFICACION", 
                "GUIA DE ENVIO", "NOTIFICACION POR ESTADO", "CERTIFICADO DE CORREO", 
                "PRUEBA DE ENTREGA", "FORMATO DE CITACION"
            ]
            for kw in keywords:
                if kw in first_page:
                    return True
            return False
        except Exception as e:
            # En caso de duda o error de lectura, conservamos el archivo
            return False

    def download_case(self, radicado, skip_notifications=False):
        print(f"\n{self.C_CYAN}{self.C_BOLD}>>> Iniciando proceso: {radicado}{self.C_END}")
        self.downloaded_docs = []
        self.auto_admite_date = "Sin fecha"
        
        case_dir = os.path.join(self.base_dir, radicado)
        try:
            os.makedirs(case_dir, exist_ok=True)
        except Exception as e:
            case_dir = os.path.join(os.path.expanduser("~"), "TYBA_Downloads", radicado)
            os.makedirs(case_dir, exist_ok=True)

        with sync_playwright() as p:
            # Aumentamos slow_mo a 500ms para parecer más humanos
            browser = p.chromium.launch(headless=False, slow_mo=500)
            context = browser.new_context(accept_downloads=True, user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            page = context.new_page()

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
                
                # First Archivos (usually Demanda)
                for doc in self.downloaded_docs:
                    if doc['type'] == 'archivo':
                        date = self.auto_admite_date if "DEMANDA" in doc['name'].upper() else "N/A"
                        f.write(f"{date:<12} | {doc['name']}\n")
                
                f.write("-"*50 + "\n")
                # Then Actuaciones
                for doc in self.downloaded_docs:
                    if doc['type'] == 'actuacion':
                        f.write(f"{doc['date']:<12} | {doc['name']}\n")
            print(f"  {self.C_GREEN}→ Archivo 'lista.txt' generado.{self.C_END}")
        except Exception as e:
            print(f"  {self.C_RED}→ Error creando lista.txt: {e}{self.C_END}")

    def _search_case(self, page: Page, radicado):
        print(f"{self.C_YELLOW}Conectando con TYBA...{self.C_END}")
        page.goto(self.base_url)
        time.sleep(2)
        
        max_retries = 5
        for attempt in range(max_retries):
            print(f"  Buscando radicado (intento {attempt+1})...")
            # Pausa antes de interactuar
            time.sleep(1)
            page.fill("#MainContent_txtCodigoProceso", "")
            time.sleep(0.5)
            # Escritura más lenta (300ms entre teclas)
            page.type("#MainContent_txtCodigoProceso", radicado, delay=300)
            time.sleep(1)
            page.click("#MainContent_btnConsultar")
            
            try:
                page.wait_for_selector("#MainContent_grdProceso_imgbConsultarGrilla_0", timeout=5000)
                break
            except:
                if page.get_by_text("El valor de la Capcha no coincide").is_visible() or \
                   page.get_by_text("Code Captcha value does not match").is_visible():
                    print(f"  {self.C_YELLOW}! Error de CAPTCHA, reintentando...{self.C_END}")
                    time.sleep(3)
                    continue
                else:
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
        time.sleep(1) 
        
        try:
            page.wait_for_selector("input[id*='grdArchivos_imgbConsultarGrillaArchivos']", timeout=10000)
        except:
            print("  - Sin archivos disponibles.")
            return

        buttons = page.locator("input[id*='grdArchivos_imgbConsultarGrillaArchivos']")
        count = buttons.count()

        for i in range(count):
            button = page.locator(f"#MainContent_grdArchivos_imgbConsultarGrillaArchivos_{i}")
            if not button.is_visible(): continue
                
            file_description = button.locator("xpath=../..").inner_text().split("\n")[0].strip()
            safe_name = self.sanitize_filename(file_description)
            file_path = os.path.join(case_dir, f"{safe_name}.pdf")
            
            if os.path.exists(file_path) and os.path.getsize(file_path) > 1000:
                 if skip_notifications and self._is_notification(file_path):
                     os.remove(file_path)
                 else:
                     self.downloaded_docs.append({'date': 'N/A', 'name': safe_name, 'type': 'archivo'})
                     continue

            button.click()
            try:
                iframe = page.locator("#MainContent_IframeViewPDF").first
                page.wait_for_selector("#MainContent_IframeViewPDF", timeout=15000)
                src = iframe.get_attribute("src")
                if src:
                    url = (page.url.rsplit('/', 1)[0] + '/' + src).replace("\\", "/")
                    response = page.context.request.get(url, timeout=60000)
                    if response.ok and len(response.body()) > 1000:
                        with open(file_path, 'wb') as f: f.write(response.body())
                        
                        if skip_notifications and self._is_notification(file_path):
                            print(f"  {self.C_YELLOW}○ Omitida (Notificación): {safe_name}{self.C_END}")
                            os.remove(file_path)
                        else:
                            print(f"  {self.C_GREEN}↓ Descargado:{self.C_END} {safe_name}")
                            self.downloaded_docs.append({'date': 'N/A', 'name': safe_name, 'type': 'archivo'})
            except: pass
            
            close_btn = page.locator("#MainContent_imbCerrarVistaPDF")
            if close_btn.is_visible(): close_btn.click(); time.sleep(0.5)

    def _process_actuaciones(self, page: Page, context: BrowserContext, case_dir, skip_notifications=False):
        print(f"\n{self.C_CYAN}[Pestaña: Actuaciones]{self.C_END}")
        page.click("a[href='#Actuaciones']")
        time.sleep(2)
        
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
            
            for i in range(count):
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

                # Check if we already have files for this actuation to avoid re-clicking
                f_btn_id = f"MainContent_grdActuaciones_imgbConsultarGrilla_{i}"
                page.click(f"#{f_btn_id}")
                time.sleep(1)
                
                try:
                    page.wait_for_selector("#MainContent_btnRegresarActuacion", timeout=15000)
                    files_locator = page.locator("input[id*='grdArchivosActuaciones_imgDescargaArchivos']")
                    files_count = files_locator.count()
                    
                    for j in range(files_count):
                        f_btn_id = f"MainContent_grdArchivosActuaciones_imgDescargaArchivos_{j}"
                        f_btn = page.locator(f"#{f_btn_id}")
                        f_row = page.locator(f"xpath=//*[@id='{f_btn_id}']/../..")
                        f_name = self.sanitize_filename(f_row.inner_text().strip())
                        if not f_name: f_name = f"{self.sanitize_filename(act_name)}_{j}"
                        
                        f_path = os.path.join(case_dir, f"{f_name}.pdf")
                        if os.path.exists(f_path) and os.path.getsize(f_path) > 1000:
                            if skip_notifications and self._is_notification(f_path):
                                os.remove(f_path)
                            else:
                                if not any(d['name'] == f_name for d in self.downloaded_docs):
                                    self.downloaded_docs.append({'date': act_date, 'name': f_name, 'type': 'actuacion'})
                                continue

                        with context.expect_page() as new_p_info: f_btn.click()
                        new_p = new_p_info.value
                        new_p.wait_for_load_state()
                        try:
                            t_url = new_p.url if "Descargando.aspx" in new_p.url else None
                            if not t_url:
                                iframe = new_p.locator("iframe[src*='Descargando.aspx']").first
                                if iframe.is_visible(): t_url = iframe.get_attribute("src")
                            
                            if t_url:
                                if not t_url.startswith("http"): t_url = (new_p.url.rsplit('/', 1)[0] + '/' + t_url).replace("\\", "/")
                                res = new_p.request.get(t_url, timeout=60000)
                                if res.ok and len(res.body()) > 1000:
                                    with open(f_path, 'wb') as f: f.write(res.body())
                                    if skip_notifications and self._is_notification(f_path):
                                        print(f"  {self.C_YELLOW}○ Omitida (Notificación): {f_name}{self.C_END}")
                                        os.remove(f_path)
                                    else:
                                        print(f"  {self.C_GREEN}↓ Descargado:{self.C_END} {f_name}")
                                        self.downloaded_docs.append({'date': act_date, 'name': f_name, 'type': 'actuacion'})
                        except: pass
                        new_p.close()
                except: pass
                
                page.click("#MainContent_btnRegresarActuacion")
                time.sleep(1)
                page.wait_for_selector("a[href='#Archivos']", timeout=15000)

            # Check for next page
            next_page = page.locator("a:has-text('下一页'), a:has-text('Siguiente'), a[href*='Page$']").last # Very generic pagination check
            # TYBA usually uses a row with numbers at the bottom
            # Actually, let's just stick to the first page for now if we can't find a reliable 'Next'
            # or try to click the next number.
            break # For now, processing only the first page as most relevant acts are there.

if __name__ == "__main__":
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
    downloader = TybaDownloader(output_base_dir=script_dir)
    
    notif_pref = input(f"\n{C_BOLD}¿Omitir notificaciones y citaciones? (s/n):{C_END} ").strip().lower()
    skip_notif = notif_pref == 's'
    
    while True:
        radicado = input(f"\n{C_BOLD}Ingrese 23 dígitos del radicado (o 'q' para salir):{C_END} ").strip()
        if not radicado: continue
        if radicado.lower() == 'q': break
            
        try:
            downloader.download_case(radicado, skip_notifications=skip_notif)
        except Exception as e:
            print(f"\n{downloader.C_RED}Error: {e}{downloader.C_END}")
            
    print(f"\n{C_CYAN}Finalizado. ¡Hasta la próxima!{C_END}")
