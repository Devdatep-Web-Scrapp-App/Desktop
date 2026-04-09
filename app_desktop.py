import os
import time
import random
import threading
import json
from datetime import datetime
from typing import Optional

import requests
import customtkinter as ctk
from tkinter import messagebox
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

# ── Configuracion ──────────────────────────────────────────────────────────────

CONFIG_FILE = "config.json"
SESSION_DIR = os.path.join(os.getcwd(), "chrome_session")

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# ── Colores ────────────────────────────────────────────────────────────────────

BG_BASE     = "#0f0f13"
BG_CARD     = "#16161d"
BG_ELEVATED = "#1e1e28"
ACCENT      = "#7c6af7"
TEAL        = "#00d4aa"
PINK        = "#f72585"
TEXT_PRI    = "#f0f0f5"
TEXT_SEC    = "#8888aa"
BORDER      = "#2a2a38"

# ── Config local ───────────────────────────────────────────────────────────────

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(data: dict):
    existing = load_config()
    existing.update(data)
    with open(CONFIG_FILE, "w") as f:
        json.dump(existing, f, indent=2)

# ── API Client ─────────────────────────────────────────────────────────────────

class APIClient:
    def __init__(self):
        self.base_url = "http://40.67.149.227:8000"
        self.token: Optional[str] = None

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def login(self, email: str, password: str) -> Optional[dict]:
        try:
            res = requests.post(
                self._url("/auth/login"),
                data={"username": email, "password": password},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10
            )
            if res.status_code == 200:
                self.token = res.json().get("access_token")
                return res.json()
            return None
        except Exception as e:
            print(f"[api] login error: {e}")
            return None

    def me(self) -> Optional[dict]:
        try:
            res = requests.get(self._url("/auth/me"), headers=self._headers(), timeout=10)
            return res.json() if res.status_code == 200 else None
        except Exception as e:
            print(f"[api] me error: {e}")
            return None

    def get_users(self) -> list:
        try:
            res = requests.get(self._url("/auth/users"), headers=self._headers(), timeout=10)
            return res.json() if res.status_code == 200 else []
        except Exception as e:
            print(f"[api] get_users error: {e}")
            return []

    def create_user(self, email: str, password: str, full_name: str, role: str = "user") -> tuple[bool, str]:
        try:
            res = requests.post(
                self._url("/auth/register"),
                json={"email": email, "password": password, "full_name": full_name, "role": role},
                headers=self._headers(),
                timeout=10
            )
            if res.status_code == 200:
                return True, "Usuario creado correctamente."
            return False, res.json().get("detail", "Error desconocido.")
        except Exception as e:
            return False, str(e)

    def update_ig_username(self, ig_username: str) -> bool:
        try:
            res = requests.put(
                self._url("/settings/update-ig-username"),
                json={"ig_username": ig_username},
                headers=self._headers(),
                timeout=10
            )
            return res.status_code == 200
        except Exception as e:
            print(f"[api] update_ig_username error: {e}")
            return False

    def submit_results(self, seguidores: dict) -> tuple[bool, str]:
        try:
            payload = {
                "followers": [
                    {"username": u, "full_name": fn}
                    for u, fn in seguidores.items()
                ]
            }
            res = requests.post(
                self._url("/scraper/submit-results"),
                json=payload,
                headers=self._headers(),
                timeout=60
            )
            if res.status_code == 200:
                return True, res.json().get("message", "Completado.")
            return False, res.json().get("detail", "Error desconocido.")
        except Exception as e:
            return False, str(e)

    def upload_cookies(self, cookies: list) -> tuple[bool, str]:
        """Sube las cookies HTTP de Instagram al backend para uso del scheduler."""
        try:
            # Normalizar campos que Selenium devuelve pero la API no necesita
            clean = []
            for c in cookies:
                clean.append({
                    "name":     c.get("name", ""),
                    "value":    c.get("value", ""),
                    "domain":   c.get("domain", ".instagram.com"),
                    "path":     c.get("path", "/"),
                    "secure":   c.get("secure", False),
                    "httpOnly": c.get("httpOnly", False),
                    "expiry":   c.get("expiry"),
                })
            res = requests.post(
                self._url("/sync/cookies"),
                json={"cookies": clean},
                headers=self._headers(),
                timeout=20,
            )
            if res.status_code == 200:
                return True, res.json().get("message", "Cookies guardadas.")
            return False, res.json().get("detail", "Error desconocido.")
        except Exception as e:
            return False, str(e)

    def check_connection(self) -> bool:
        try:
            res = requests.get(self._url("/"), timeout=5)
            return res.status_code == 200
        except Exception:
            return False


api = APIClient()

# ── Scraper ────────────────────────────────────────────────────────────────────

def tiene_sesion(user_id: int) -> bool:
    p1 = os.path.join(SESSION_DIR, str(user_id), "Default", "Network", "Cookies")
    p2 = os.path.join(SESSION_DIR, str(user_id), "Default", "Cookies")
    if os.path.exists(p1) and os.path.getsize(p1) > 10_000:
        return True
    if os.path.exists(p2) and os.path.getsize(p2) > 10_000:
        return True
    return False

def run_scraping(user_id: int, ig_username: str, log_fn, done_fn, headless: bool = True):
    user_session = os.path.join(SESSION_DIR, str(user_id))
    os.makedirs(user_session, exist_ok=True)

    options = Options()
    options.add_argument(f"--user-data-dir={user_session}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    if headless:
        options.add_argument("--headless=new")
        log_fn("Modo: headless")
    else:
        log_fn("Modo: visible — inicia sesion en Chrome")

    service = Service(ChromeDriverManager().install())
    driver  = webdriver.Chrome(service=service, options=options)

    try:
        driver.get(f"https://www.instagram.com/{ig_username}/")
        log_fn(f"Navegando al perfil @{ig_username}...")
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//a[contains(@href, '/followers/')]")
                )
            )
            log_fn("Sesion activa.")
            _continuar_scraping(driver, user_id, ig_username, log_fn, done_fn)
        except TimeoutException:
            if headless:
                log_fn("No hay sesion guardada. Ejecuta primero en modo visible.")
                driver.quit()
                done_fn(False)
            else:
                log_fn("Inicia sesion en Chrome. Cuando termines haz clic en Continuar en la app.")
                done_fn(("waiting_login", driver))

    except Exception as e:
        log_fn(f"Error: {e}")
        import traceback
        traceback.print_exc()
        done_fn(False)
        driver.quit()

def _continuar_scraping(driver, user_id: int, ig_username: str, log_fn, done_fn):
    try:
        try:
            el = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//a[contains(@href, '/followers/')]/span")
                )
            )
            txt = el.get_attribute("title") or el.text
            total_seg = int("".join(filter(str.isdigit, txt)))
            log_fn(f"Total segun perfil: {total_seg}")
        except Exception:
            total_seg = 0

        log_fn("Abriendo lista de seguidores...")
        btn = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//a[contains(@href, '/followers/')]")
            )
        )
        btn.click()
        time.sleep(5)

        dialog = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//div[@role='dialog']"))
        )
        scroll_box = dialog.find_element(
            By.XPATH, ".//div[contains(@style, 'overflow: hidden auto')]"
        )
        log_fn("Modal encontrado. Capturando seguidores...")

        seguidores = {}
        intentos   = 0
        max_int    = max(8, min(30, total_seg // 50)) if total_seg else 10

        def extraer():
            try:
                elementos = scroll_box.find_elements(
                    By.XPATH, ".//div[contains(@class, 'x1qnrgzn')]"
                )
                for _el in elementos:
                    try:
                        username = _el.find_element(
                            By.XPATH, ".//span[contains(@class, '_ap3a')]"
                        ).text.strip()
                        full_name = ""
                        try:
                            full_name = _el.find_element(
                                By.XPATH,
                                ".//span[contains(@class, 'x1lliihq') and contains(@class, 'x193iq5w')]"
                            ).text.strip()
                        except Exception:
                            pass
                        if username and username not in seguidores:
                            seguidores[username] = full_name
                    except StaleElementReferenceException:
                        continue
                    except Exception:
                        continue
            except Exception as _e:
                log_fn(f"Error extrayendo: {_e}")

        extraer()
        ciclo = 0

        while intentos < max_int:
            ciclo += 1
            antes = len(seguidores)

            # Scroll más robusto como el script original
            for _ in range(3):
                try:
                    driver.execute_script("""
                        var box = arguments[0];
                        var items = box.querySelectorAll('div, li');
                        if (items.length > 0) {
                            items[items.length - 1].scrollIntoView();
                        }
                        box.scrollTop += arguments[1];
                    """, scroll_box, random.randint(1200, 1500))
                except Exception:
                    try:
                        driver.execute_script(
                            "arguments[0].scrollTop = arguments[0].scrollTop + arguments[1]",
                            scroll_box,
                            random.randint(600, 900)
                        )
                    except Exception:
                        pass
                time.sleep(1.5)

            try:
                WebDriverWait(driver, 5).until(
                    EC.invisibility_of_element_located(
                        (By.XPATH, "//div[@role='progressbar']")
                    )
                )
            except Exception:
                pass

            extraer()
            ahora = len(seguidores)

            if ahora > antes:
                log_fn(f"Ciclo {ciclo}: {ahora} capturados (+{ahora - antes})")
                intentos = 0
            else:
                intentos += 1
                log_fn(f"Ciclo {ciclo}: {ahora} capturados (sin cambios {intentos}/{max_int})")

            if total_seg and ahora >= total_seg:
                log_fn(f"Objetivo alcanzado ({total_seg})")
                break

            time.sleep(0.3)

        log_fn(f"Captura final: {len(seguidores)} seguidores")
        seguidores_hoy = {u: fn for u, fn in seguidores.items() if u and len(u) > 1}

        log_fn("Enviando resultados al backend...")
        ok, mensaje = api.submit_results(seguidores_hoy)
        log_fn(mensaje)
        done_fn(ok)

    except Exception as e:
        log_fn(f"Error: {e}")
        import traceback
        traceback.print_exc()
        done_fn(False)
    finally:
        driver.quit()

def extract_and_upload_cookies(driver: webdriver.Chrome, log_fn) -> tuple[bool, str]:
    """
    Extrae las cookies HTTP de Instagram desde un driver con sesion activa
    y las sube al backend. Solo se llaman cookies del dominio instagram.com,
    que son portables entre sistemas operativos (no dependen del perfil de Chrome).
    """
    try:
        driver.get("https://www.instagram.com/")
        import time as _t
        _t.sleep(2)
        all_cookies = driver.get_cookies()
        ig_cookies  = [c for c in all_cookies if "instagram.com" in c.get("domain", "")]
        if not ig_cookies:
            return False, "No se encontraron cookies de Instagram."
        log_fn(f"Cookies extraidas: {len(ig_cookies)}")
        ok, msg = api.upload_cookies(ig_cookies)
        return ok, msg
    except Exception as e:
        return False, str(e)




class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("RRSS Analytics")
        self.geometry("900x620")
        self.resizable(False, False)
        self.configure(fg_color=BG_BASE)

        self.current_user         = None
        self.scraping_count_today = 0
        self.last_scrape_time     = None

        self._setup_fonts()
        self._show_login()

    def _setup_fonts(self):
        self.font_title = ctk.CTkFont(family="Segoe UI", size=22, weight="bold")
        self.font_sub   = ctk.CTkFont(family="Segoe UI", size=13)
        self.font_label = ctk.CTkFont(family="Segoe UI", size=12)
        self.font_mono  = ctk.CTkFont(family="Consolas", size=11)
        self.font_btn   = ctk.CTkFont(family="Segoe UI", size=13, weight="bold")

    def _clear(self):
        for w in self.winfo_children():
            w.destroy()

    # ── Login ──────────────────────────────────────────────────────────────────

    def _show_login(self):
        self._clear()
        cfg = load_config()

        frame = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=16,
                             width=420, height=460)
        frame.place(relx=0.5, rely=0.5, anchor="center")
        frame.pack_propagate(False)

        ctk.CTkLabel(frame, text="RRSS Analytics",
                    font=self.font_title, text_color=TEXT_PRI).pack(pady=(36, 4))
        ctk.CTkLabel(frame, text="Inicia sesion para continuar",
                    font=self.font_sub, text_color=TEXT_SEC).pack(pady=(0, 8))

        ctk.CTkLabel(frame, text="Correo", font=self.font_label,
                    text_color=TEXT_SEC, anchor="w").pack(padx=36, fill="x")
        email_entry = ctk.CTkEntry(frame, height=38, fg_color=BG_ELEVATED,
                                  border_color=BORDER, text_color=TEXT_PRI)
        email_entry.insert(0, cfg.get("last_email", ""))
        email_entry.pack(padx=36, fill="x", pady=(2, 12))

        ctk.CTkLabel(frame, text="Contrasena", font=self.font_label,
                    text_color=TEXT_SEC, anchor="w").pack(padx=36, fill="x")
        pass_entry = ctk.CTkEntry(frame, height=38, fg_color=BG_ELEVATED,
                                 border_color=BORDER, text_color=TEXT_PRI, show="*")
        pass_entry.pack(padx=36, fill="x", pady=(2, 12))

        err_label = ctk.CTkLabel(frame, text="", font=self.font_label,
                                text_color=PINK)
        err_label.pack()

        def do_login():
            email = email_entry.get().strip()
            pwd   = pass_entry.get()

            if not email or not pwd:
                err_label.configure(text="Completa todos los campos.")
                return

            if not api.check_connection():
                err_label.configure(text="No se pudo conectar al backend.")
                return

            result = api.login(email, pwd)
            if not result:
                err_label.configure(text="Credenciales incorrectas.")
                return

            user = api.me()
            if not user:
                err_label.configure(text="Error obteniendo datos del usuario.")
                return

            save_config({"last_email": email})
            self.current_user = user
            self._show_main()

        pass_entry.bind("<Return>", lambda e: do_login())
        ctk.CTkButton(frame, text="Iniciar sesion", font=self.font_btn,
                     fg_color=ACCENT, hover_color="#6355d4",
                     height=42, command=do_login).pack(padx=36, fill="x", pady=(4, 32))

    # ── Main ───────────────────────────────────────────────────────────────────

    def _show_main(self):
        self._clear()
        user = self.current_user

        sidebar = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0, width=200)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        ctk.CTkLabel(sidebar, text="RRSS", font=self.font_title,
                    text_color=ACCENT).pack(pady=(28, 4))
        ctk.CTkLabel(sidebar, text="Analytics", font=self.font_sub,
                    text_color=TEXT_SEC).pack(pady=(0, 32))

        self.content = ctk.CTkFrame(self, fg_color=BG_BASE, corner_radius=0)
        self.content.pack(side="left", fill="both", expand=True)

        nav_items = [("Scraping", self._build_scraping)]
        if user.get("role") == "admin":
            nav_items.append(("Usuarios", self._build_users))

        nav_btns = {}

        def switch(_name, _builder):
            for w in self.content.winfo_children():
                w.destroy()
            _builder()
            for n, b in nav_btns.items():
                b.configure(
                    fg_color=ACCENT if n == _name else "transparent",
                    text_color=TEXT_PRI if n == _name else TEXT_SEC
                )

        for name, builder in nav_items:
            btn = ctk.CTkButton(
                sidebar, text=name, font=self.font_btn,
                fg_color="transparent", text_color=TEXT_SEC,
                hover_color=BG_ELEVATED, height=42, anchor="w",
                command=lambda n=name, b=builder: switch(n, b)
            )
            btn.pack(padx=12, fill="x", pady=2)
            nav_btns[name] = btn

        ctk.CTkLabel(sidebar,
                    text=user.get("full_name") or user.get("email", ""),
                    font=self.font_label, text_color=TEXT_SEC,
                    wraplength=160).place(relx=0.5, rely=0.88, anchor="center")

        ctk.CTkButton(sidebar, text="Salir", font=self.font_label,
                     fg_color="transparent", text_color=TEXT_SEC,
                     hover_color=BG_ELEVATED, height=32,
                     command=self._logout).place(relx=0.5, rely=0.94, anchor="center")

        switch("Scraping", self._build_scraping)
        nav_btns["Scraping"].configure(fg_color=ACCENT, text_color=TEXT_PRI)

    # ── Scraping panel ─────────────────────────────────────────────────────────

    def _build_scraping(self):
        user  = self.current_user
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=28, pady=28)

        ctk.CTkLabel(frame, text="Scraping de Instagram",
                    font=self.font_title, text_color=TEXT_PRI).pack(anchor="w")
        ctk.CTkLabel(frame, text="Captura la lista de seguidores de tu cuenta",
                    font=self.font_sub, text_color=TEXT_SEC).pack(anchor="w", pady=(2, 20))

        # Cuenta IG
        card = ctk.CTkFrame(frame, fg_color=BG_CARD, corner_radius=12)
        card.pack(fill="x", pady=(0, 14))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=16)

        ctk.CTkLabel(inner, text="Usuario de Instagram",
                    font=self.font_label, text_color=TEXT_SEC).pack(anchor="w")

        ig_row = ctk.CTkFrame(inner, fg_color="transparent")
        ig_row.pack(fill="x", pady=(4, 0))

        ig_entry = ctk.CTkEntry(ig_row, height=38, fg_color=BG_ELEVATED,
                               border_color=BORDER, text_color=TEXT_PRI,
                               placeholder_text="username sin @")
        ig_entry.pack(side="left", fill="x", expand=True)
        if user.get("ig_username"):
            ig_entry.insert(0, user["ig_username"])

        ig_status = ctk.CTkLabel(inner, text="", font=self.font_label, text_color=TEAL)
        ig_status.pack(anchor="w", pady=(4, 0))

        def save_ig():
            val = ig_entry.get().strip().lstrip("@")
            if not val:
                return
            if api.update_ig_username(val):
                self.current_user["ig_username"] = val
                ig_status.configure(text="Guardado", text_color=TEAL)
            else:
                ig_status.configure(text="Error al guardar", text_color=PINK)
            self.after(2000, lambda: ig_status.configure(text=""))

        ctk.CTkButton(ig_row, text="Guardar", font=self.font_btn,
                     fg_color=ACCENT, hover_color="#6355d4",
                     width=90, height=38, command=save_ig).pack(side="left", padx=(8, 0))

        # Controles
        ctrl_card = ctk.CTkFrame(frame, fg_color=BG_CARD, corner_radius=12)
        ctrl_card.pack(fill="x", pady=(0, 14))

        ctrl_row = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        ctrl_row.pack(fill="x", padx=20, pady=16)

        btn_visible = ctk.CTkButton(
            ctrl_row, text="Primer login (visible)",
            font=self.font_btn, fg_color=BG_ELEVATED,
            text_color=TEXT_PRI, hover_color=BORDER, height=40, width=200
        )
        btn_visible.pack(side="left", padx=(0, 10))

        btn_scrape = ctk.CTkButton(
            ctrl_row, text="Ejecutar scraping",
            font=self.font_btn, fg_color=TEAL,
            text_color="#000", hover_color="#00b899", height=40, width=180
        )
        btn_scrape.pack(side="left")

        btn_sync_session = ctk.CTkButton(
            ctrl_row, text="Sincronizar sesion con servidor",
            font=self.font_btn, fg_color=ACCENT,
            text_color=TEXT_PRI, hover_color="#6355d4", height=40, width=240
        )
        btn_sync_session.pack(side="left", padx=(10, 0))

        scrape_status = ctk.CTkLabel(
            ctrl_row, text="", font=self.font_label, text_color=TEXT_SEC
        )
        scrape_status.pack(side="left", padx=(16, 0))

        # Log
        log_card = ctk.CTkFrame(frame, fg_color=BG_CARD, corner_radius=12)
        log_card.pack(fill="both", expand=True)

        ctk.CTkLabel(log_card, text="Log", font=self.font_label,
                    text_color=TEXT_SEC).pack(anchor="w", padx=20, pady=(12, 0))

        log_box = ctk.CTkTextbox(
            log_card, fg_color=BG_ELEVATED, text_color=TEXT_PRI,
            font=self.font_mono, corner_radius=8, border_width=0
        )
        log_box.pack(fill="both", expand=True, padx=20, pady=(4, 20))
        log_box.configure(state="disabled")

        def log(msg: str):
            ts = datetime.now().strftime("%H:%M:%S")
            log_box.configure(state="normal")
            log_box.insert("end", f"[{ts}] {msg}\n")
            log_box.see("end")
            log_box.configure(state="disabled")

        def can_scrape() -> tuple[bool, str]:
            if self.scraping_count_today >= 3:
                return False, "Limite diario alcanzado (3/3)"
            if self.last_scrape_time:
                diff = (datetime.now() - self.last_scrape_time).total_seconds()
                if diff < 600:
                    return False, f"Espera {int(600 - diff)}s antes de volver a ejecutar"
            return True, ""

        def on_done(result):
            btn_scrape.configure(state="normal")
            btn_visible.configure(state="normal")
            if result is True:
                self.scraping_count_today += 1
                self.last_scrape_time = datetime.now()
                scrape_status.configure(
                    text=f"Completado ({self.scraping_count_today}/3 hoy)",
                    text_color=TEAL
                )
            elif result is False:
                scrape_status.configure(text="Error en el scraping", text_color=PINK)

        def start_scraping():
            ok, msg = can_scrape()
            if not ok:
                log(f"No se puede ejecutar: {msg}")
                scrape_status.configure(text=msg, text_color=PINK)
                return
            ig = ig_entry.get().strip().lstrip("@")
            if not ig:
                log("Ingresa tu username de Instagram primero.")
                return
            btn_scrape.configure(state="disabled")
            btn_visible.configure(state="disabled")
            scrape_status.configure(text="Ejecutando...", text_color=TEXT_SEC)
            log(f"Iniciando scraping para @{ig}...")
            threading.Thread(
                target=run_scraping,
                args=(user["id"], ig, log, on_done, True),
                daemon=True
            ).start()

        def start_visible():
            ig = ig_entry.get().strip().lstrip("@")
            if not ig:
                log("Ingresa tu username de Instagram primero.")
                return
            btn_scrape.configure(state="disabled")
            btn_visible.configure(state="disabled")
            scrape_status.configure(text="Esperando login...", text_color=TEXT_SEC)
            log(f"Abriendo Chrome para @{ig}. Inicia sesion manualmente...")

            def after_login(result):
                if isinstance(result, tuple) and result[0] == "waiting_login":
                    driver_abierto = result[1]

                    def continuar():
                        # Verificar que el usuario ya inicio sesion
                        try:
                            WebDriverWait(driver_abierto, 5).until(
                                EC.presence_of_element_located(
                                    (By.XPATH, "//a[contains(@href, '/followers/')]")
                                )
                            )
                            log("Sesion confirmada. Continuando scraping...")
                            # Continuar el scraping con el driver ya abierto
                            threading.Thread(
                                target=_continuar_scraping,
                                args=(driver_abierto, user["id"], ig, log, on_done),
                                daemon=True
                            ).start()
                        except TimeoutException:
                            log("Aun no has iniciado sesion. Intenta de nuevo.")
                            driver_abierto.quit()
                            on_done(False)

                    self.after(0, lambda: [
                        messagebox.showinfo(
                            "Login",
                            "Inicia sesion en Chrome.\nCuando termines haz clic en OK."
                        ),
                        continuar()
                    ])
                else:
                    on_done(result)

            threading.Thread(
                target=run_scraping,
                args=(user["id"], ig, log, after_login, False),
                daemon=True
            ).start()

        btn_scrape.configure(command=start_scraping)
        btn_visible.configure(command=start_visible)

        def start_sync_session():
            """
            Flujo: abre Chrome visible -> usuario inicia sesion en Instagram ->
            extrae cookies HTTP -> las sube al backend -> cierra Chrome.
            A partir de aqui el scheduler del servidor puede hacer scraping autonomo.
            """
            ig = ig_entry.get().strip().lstrip("@")
            if not ig:
                log("Ingresa tu username de Instagram primero.")
                return

            btn_scrape.configure(state="disabled")
            btn_visible.configure(state="disabled")
            btn_sync_session.configure(state="disabled")
            scrape_status.configure(text="Abriendo Chrome...", text_color=TEXT_SEC)
            log("Abriendo Chrome para capturar sesion de Instagram...")

            def _do_sync():
                user_session = os.path.join(SESSION_DIR, str(user["id"]))
                os.makedirs(user_session, exist_ok=True)

                options = Options()
                # Visible para que el usuario pueda hacer login
                options.add_argument(f"--user-data-dir={user_session}")
                options.add_argument("--profile-directory=Default")
                options.add_argument("--disable-notifications")
                options.add_argument("--disable-blink-features=AutomationControlled")
                options.add_argument("--window-size=1280,800")

                service = Service(ChromeDriverManager().install())
                driver  = webdriver.Chrome(service=service, options=options)

                try:
                    driver.get("https://www.instagram.com/accounts/login/")
                    WebDriverWait(driver, 10).until(
                        lambda d: d.execute_script("return document.readyState") == "complete"
                    )

                    # Esperar confirmacion del usuario via messagebox en hilo principal
                    confirmed = threading.Event()

                    def ask_user():
                        messagebox.showinfo(
                            "Sincronizar sesion",
                            "Inicia sesion en Instagram en la ventana de Chrome.\n\n"
                            "Cuando hayas iniciado sesion correctamente, haz clic en OK."
                        )
                        confirmed.set()

                    self.after(0, ask_user)
                    confirmed.wait()

                    # Verificar que hay sesion activa
                    try:
                        driver.get(f"https://www.instagram.com/{ig}/")
                        WebDriverWait(driver, 15).until(
                            EC.presence_of_element_located(
                                (By.XPATH, "//a[contains(@href, '/followers/')]")
                            )
                        )
                        log("Sesion activa confirmada. Extrayendo cookies...")
                    except TimeoutException:
                        log("No se detecto sesion activa. Intenta de nuevo.")
                        self.after(0, lambda: [
                            btn_scrape.configure(state="normal"),
                            btn_visible.configure(state="normal"),
                            btn_sync_session.configure(state="normal"),
                            scrape_status.configure(text="Sin sesion detectada", text_color=PINK),
                        ])
                        return

                    ok, msg = extract_and_upload_cookies(driver, log)
                    log(msg)

                    def _restore(color):
                        btn_scrape.configure(state="normal")
                        btn_visible.configure(state="normal")
                        btn_sync_session.configure(state="normal")
                        scrape_status.configure(
                            text="Sesion sincronizada" if ok else "Error al sincronizar",
                            text_color=color
                        )
                        self.after(4000, lambda: scrape_status.configure(text=""))

                    self.after(0, lambda: _restore(TEAL if ok else PINK))

                except Exception as e:
                    log(f"Error: {e}")
                    self.after(0, lambda: [
                        btn_scrape.configure(state="normal"),
                        btn_visible.configure(state="normal"),
                        btn_sync_session.configure(state="normal"),
                        scrape_status.configure(text="Error", text_color=PINK),
                    ])
                finally:
                    try:
                        driver.quit()
                    except Exception:
                        pass

            threading.Thread(target=_do_sync, daemon=True).start()

        btn_sync_session.configure(command=start_sync_session)

    # ── Config panel ───────────────────────────────────────────────────────────

    def _build_config(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=28, pady=28)

        ctk.CTkLabel(frame, text="Configuracion",
                    font=self.font_title, text_color=TEXT_PRI).pack(anchor="w")
        ctk.CTkLabel(frame, text="Conexion al backend",
                    font=self.font_sub, text_color=TEXT_SEC).pack(anchor="w", pady=(2, 20))

        # Backend URL
        url_card = ctk.CTkFrame(frame, fg_color=BG_CARD, corner_radius=12)
        url_card.pack(fill="x")

        ctk.CTkLabel(url_card, text="URL del backend",
                    font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
                    text_color=TEXT_PRI).pack(anchor="w", padx=20, pady=(16, 4))

        url_row = ctk.CTkFrame(url_card, fg_color="transparent")
        url_row.pack(fill="x", padx=20, pady=(0, 8))

        url_entry = ctk.CTkEntry(url_row, height=38, fg_color=BG_ELEVATED,
                                border_color=BORDER, text_color=TEXT_PRI)
        url_entry.insert(0, api.base_url)
        url_entry.pack(side="left", fill="x", expand=True)

        url_status = ctk.CTkLabel(url_card, text="", font=self.font_label,
                                 text_color=TEAL)
        url_status.pack(anchor="w", padx=20, pady=(0, 16))

        def save_url():
            val = url_entry.get().strip().rstrip("/")
            if not val:
                return
            api.set_base_url(val)
            if api.check_connection():
                url_status.configure(text="Conexion exitosa", text_color=TEAL)
            else:
                url_status.configure(text="No se pudo conectar al backend", text_color=PINK)
            self.after(3000, lambda: url_status.configure(text=""))

        ctk.CTkButton(url_row, text="Guardar", font=self.font_btn,
                     fg_color=ACCENT, hover_color="#6355d4",
                     width=90, height=38, command=save_url).pack(side="left", padx=(8, 0))

    # ── Users panel (admin) ────────────────────────────────────────────────────

    def _build_users(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=28, pady=28)

        ctk.CTkLabel(frame, text="Gestion de usuarios",
                    font=self.font_title, text_color=TEXT_PRI).pack(anchor="w")
        ctk.CTkLabel(frame, text="Administra las cuentas de acceso",
                    font=self.font_sub, text_color=TEXT_SEC).pack(anchor="w", pady=(2, 20))

        new_card = ctk.CTkFrame(frame, fg_color=BG_CARD, corner_radius=12)
        new_card.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(new_card, text="Crear nuevo usuario",
                    font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
                    text_color=TEXT_PRI).pack(anchor="w", padx=20, pady=(16, 8))

        form_row = ctk.CTkFrame(new_card, fg_color="transparent")
        form_row.pack(fill="x", padx=20, pady=(0, 8))

        name_e = ctk.CTkEntry(form_row, placeholder_text="Nombre completo",
                             height=36, fg_color=BG_ELEVATED,
                             border_color=BORDER, text_color=TEXT_PRI, width=160)
        name_e.pack(side="left", padx=(0, 8))

        email_e = ctk.CTkEntry(form_row, placeholder_text="Email",
                              height=36, fg_color=BG_ELEVATED,
                              border_color=BORDER, text_color=TEXT_PRI, width=180)
        email_e.pack(side="left", padx=(0, 8))

        pass_e = ctk.CTkEntry(form_row, placeholder_text="Password",
                             height=36, fg_color=BG_ELEVATED,
                             border_color=BORDER, text_color=TEXT_PRI,
                             show="*", width=140)
        pass_e.pack(side="left", padx=(0, 8))

        role_menu = ctk.CTkOptionMenu(form_row, values=["user", "admin"],
                                     fg_color=BG_ELEVATED, button_color=ACCENT,
                                     width=100, height=36)
        role_menu.pack(side="left", padx=(0, 8))

        create_status = ctk.CTkLabel(new_card, text="", font=self.font_label,
                                    text_color=TEAL)
        create_status.pack(anchor="w", padx=20)

        users_list = ctk.CTkScrollableFrame(frame, fg_color=BG_CARD, corner_radius=12)

        def refresh_list():
            for w in users_list.winfo_children():
                w.destroy()
            ctk.CTkLabel(users_list,
                        text=f"{'Nombre':<20} {'Email':<28} {'Rol':<8} {'IG':<18} Estado",
                        font=self.font_mono, text_color=TEXT_SEC).pack(
                            anchor="w", padx=12, pady=(8, 4))
            for u in api.get_users():
                row = ctk.CTkFrame(users_list, fg_color=BG_ELEVATED, corner_radius=8)
                row.pack(fill="x", padx=12, pady=4)
                ctk.CTkLabel(row, text=u.get("full_name") or "—",
                            font=self.font_btn, text_color=TEXT_PRI,
                            width=140, anchor="w").pack(side="left", padx=(12, 0))
                ctk.CTkLabel(row, text=u.get("email", ""),
                            font=self.font_label, text_color=TEXT_SEC,
                            width=200, anchor="w").pack(side="left", padx=(8, 0))
                ctk.CTkLabel(row, text=u.get("role", ""),
                            font=self.font_label,
                            text_color=ACCENT if u.get("role") == "admin" else TEXT_SEC,
                            width=60).pack(side="left")
                ctk.CTkLabel(row, text=u.get("ig_username") or "—",
                            font=self.font_mono, text_color=TEXT_SEC,
                            width=120).pack(side="left")
                ctk.CTkLabel(row,
                            text="Activo" if u.get("is_active") else "Inactivo",
                            font=self.font_label,
                            text_color=TEAL if u.get("is_active") else PINK,
                            width=70).pack(side="left")

        def do_create():
            ok, msg = api.create_user(
                email_e.get().strip(), pass_e.get(),
                name_e.get().strip(), role_menu.get()
            )
            create_status.configure(text=msg, text_color=TEAL if ok else PINK)
            if ok:
                name_e.delete(0, "end")
                email_e.delete(0, "end")
                pass_e.delete(0, "end")
                refresh_list()
            self.after(3000, lambda: create_status.configure(text=""))

        ctk.CTkButton(new_card, text="Crear usuario", font=self.font_btn,
                     fg_color=ACCENT, hover_color="#6355d4",
                     height=36, width=140, command=do_create).pack(
                         anchor="w", padx=20, pady=(4, 16))

        users_list.pack(fill="both", expand=True)
        refresh_list()

    # ── Logout ─────────────────────────────────────────────────────────────────

    def _logout(self):
        self.current_user = None
        api.token = None
        self._show_login()


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()