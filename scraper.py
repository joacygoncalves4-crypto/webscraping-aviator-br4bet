"""
=====================================================
  AVIATOR SCRAPER - br4.bet.br
  Monitora o histórico de velas do Aviator e envia
  cada nova vela para o webhook via POST JSON.

  Seletores auditados manualmente em 12/03/2026
=====================================================
"""

import os
import time
import logging
import requests
import re
import undetected_chromedriver as uc

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    NoSuchFrameException,
    WebDriverException,
    StaleElementReferenceException,
)
from datetime import datetime
from dotenv import load_dotenv

# ─── Carrega variáveis de ambiente ─────────────────────────────────────────────
load_dotenv()

EMAIL         = os.getenv("CASINO_EMAIL")
PASSWORD      = os.getenv("CASINO_PASSWORD")
WEBHOOK_URL   = os.getenv("WEBHOOK_URL")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "2"))

# ─── Configuração de logs ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("aviator_scraper.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ─── URLs ─────────────────────────────────────────────────────────────────────
CASINO_URL  = "https://br4.bet.br"
AVIATOR_URL = "https://br4.bet.br/play/spribe/aviator"

# ─── Seletores do histórico de velas (AUDITADOS no DOM real do Spribe) ────────
# Estrutura confirmada: <app-stats-item class="bubble-multiplier"><div class="payout">1.17x</div></app-stats-item>
HISTORY_SELECTORS = [
    # Seletores confirmados pela inspeção do DOM real
    "app-stats-item .payout",
    ".bubble-multiplier .payout",
    ".stats-list .payout",
    ".stats-list app-stats-item",
    ".payouts-block .payout",
    # Fallbacks adicionais
    "app-stats-item",
    ".bubble-multiplier",
    ".stats-list span",
    ".coef",
    ".stats-coef",
    "[class*='payout']",
    "[class*='bubble-mult']",
    "[class*='stats'] span",
]

# ═══════════════════════════════════════════════════════════════════════════════
class AviatorScraper:
    """Scraper principal do jogo Aviator no br4.bet.br"""

    def __init__(self):
        self.driver = None
        self.wait   = None
        self.last_multipliers = []
        self.total_sent       = 0
        self.last_webhook_time = time.time()  # Watchdog: para evitar travamentos infinitos
        self.max_inactivity    = 360           # 6 minutos sem velas = Reinício completo

    # ─── Driver ───────────────────────────────────────────────────────────────
    def setup_driver(self):
        log.info("Iniciando Chrome com undetected-chromedriver...")
        opts = uc.ChromeOptions()
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--window-size=1280,900")
        # Para rodar SEM janela (headless), descomente a linha abaixo:
        # opts.add_argument("--headless=new")

        self.driver = uc.Chrome(options=opts, version_main=145)
        self.wait   = WebDriverWait(self.driver, 30)
        log.info("Chrome iniciado.")

    # ─── Helpers ──────────────────────────────────────────────────────────────
    def _try_click(self, xpath: str, label: str, timeout: int = 5) -> bool:
        """Tenta clicar em um elemento por XPath. Filtra apenas elementos visíveis."""
        try:
            elements = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_all_elements_located((By.XPATH, xpath))
            )
            for el in elements:
                if el.is_displayed():
                    # Garante que está clicável antes de clicar
                    self.wait.until(EC.element_to_be_clickable(el))
                    el.click()
                    log.info(f"✔ Clicado: {label}")
                    return True
            log.debug(f"✗ Elementos encontrados mas nenhum visível: {label}")
            return False
        except (TimeoutException, NoSuchElementException):
            log.debug(f"✗ Não encontrado: {label}")
            return False

    def _quick_click(self, xpath: str, label: str) -> bool:
        """Tenta clicar instantaneamente (sem esperar). Útil para popups opcionais."""
        try:
            elements = self.driver.find_elements(By.XPATH, xpath)
            for el in elements:
                if el.is_displayed():
                    el.click()
                    log.info(f"✔ Popup fechado (instantâneo): {label}")
                    return True
            return False
        except Exception:
            return False

    def _try_fill(self, css: str, value: str, label: str, timeout: int = 10) -> bool:
        """Tenta preencher um input por CSS selector."""
        try:
            el = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, css))
            )
            el.click()
            time.sleep(0.3)
            el.clear()
            el.send_keys(value)
            log.info(f"✔ Preenchido: {label}")
            return True
        except (TimeoutException, NoSuchElementException):
            log.warning(f"✗ Campo não encontrado: {label} ({css})")
            return False

    # ─── Popups iniciais ──────────────────────────────────────────────────────
    def handle_initial_popups(self):
        """Fecha o modal de verificação de idade e o banner de cookies."""
        log.info("Verificando popups iniciais...")
        time.sleep(3)

        # 1. Modal de Verificação de Idade: "Você possui mais de 18 anos?"
        self._try_click(
            "//button[contains(text(), 'Sim')]",
            "Verificação de idade (+18) → Sim",
            timeout=6,
        )
        time.sleep(1)

        # 2. Banner de Cookies: "Aceitar todos"
        self._try_click(
            "//button[contains(text(), 'Aceitar todos')]",
            "Banner de cookies → Aceitar todos",
            timeout=5,
        )
        time.sleep(1)

        # 3. Qualquer botão de fechar genérico (ícone X)
        for xpath in [
            "//button[@aria-label='Close']",
            "//button[@aria-label='Fechar']",
            "//*[contains(@class,'close') and (self::button or self::span)]",
        ]:
            self._try_click(xpath, "Botão X genérico", timeout=2)

        log.info("Popups iniciais tratados.")

    # ─── Verificação de Login ─────────────────────────────────────────────────
    def is_logged_in(self) -> bool:
        """Verifica se o usuário está autenticado na br4.bet."""
        # Se os seletores abaixo existirem, estamos logados
        logged_in_indicators = [
            "//span[contains(@class, 'balance')]", 
            "//div[contains(@class, 'user-info')]",
            "//a[contains(@href, '/profile')]",
            "//button[contains(text(), 'Sair') or contains(text(), 'Logout')]",
            "//*[contains(@class, 'wallet')]",
        ]
        # Se estes existirem, NÃO estamos logados
        not_logged_indicators = [
            "//button[contains(., 'Entrar') and contains(@class, 'md:flex')]",
            "//button[normalize-space(text())='Entrar']",
        ]

        # Tenta achar indicadores de logado
        for xpath in logged_in_indicators:
            try:
                el = self.driver.find_element(By.XPATH, xpath)
                if el.is_displayed():
                    log.debug(f"Indicador de logado encontrado: {xpath}")
                    return True
            except NoSuchElementException:
                continue
        
        # SUCESSO ADICIONAL: Se o popup do Hades/Smartico estiver na tela, com certeza logou
        try:
            hades = self.driver.find_element(By.XPATH, "//a[@href='dp:close']")
            if hades.is_displayed():
                log.info("Indicador de login detectado: Popup Hades/Smartico visível.")
                return True
        except NoSuchElementException:
            pass

        # Se não achou logado, verifica se o botão de Entrar ainda está lá
        for xpath in not_logged_indicators:
            try:
                el = self.driver.find_element(By.XPATH, xpath)
                if el.is_displayed():
                    log.debug("Ainda deslogado: botão 'Entrar' visível.")
                    return False
            except NoSuchElementException:
                continue

        return False

    def handle_post_login_popups(self):
        """Identifica e fecha popups promocionais de forma instantânea (sem travar o loop)."""
        popups_to_close = [
            ("//a[@href='dp:close']", "Hades (Smartico)"),
            ("//a[contains(@class, 'close-btn')]", "Botão fechar Smartico"),
            ("//div[contains(@class, 'modal-close')]", "Div fechar modal"),
            ("//button[contains(@class, 'close')]", "Botão fechar genérico"),
            ("//*[@data-testid='close-button']", "Close button TestID"),
            ("//button[contains(text(), 'Não') or contains(text(), 'Agora não')]", "Botão 'Agora não'")
        ]

        any_closed = False
        for xpath, label in popups_to_close:
            if self._quick_click(xpath, label):
                any_closed = True
        
        # Backup ultra-rápido via JS para Hades
        if not any_closed:
            try:
                self.driver.execute_script("""
                    var h = document.querySelector('a[href="dp:close"]');
                    if (h) h.click();
                """)
            except Exception:
                pass

    # ─── Login ────────────────────────────────────────────────────────────────
    def login(self):
        log.info(f"Acessando {CASINO_URL}...")
        self.driver.get(CASINO_URL)
        time.sleep(4)

        # Trata popups antes de tentar logar
        self.handle_initial_popups()

        # Aguarda a página estabilizar após fechar os popups
        log.info("Aguardando página estabilizar após popups...")
        time.sleep(4)

        # Abre o modal de login clicando em "Entrar" (focando explicitamente no Desktop)
        login_xpaths = [
            "//button[contains(., 'Entrar') and contains(@class, 'md:flex')]", 
            "//button[normalize-space(text())='Entrar']",
            "//button[contains(text(),'Entrar')]",
            "//a[contains(text(),'Entrar')]",
        ]
        clicked = False
        for xpath in login_xpaths:
            log.info(f"Tentando clicar botão login: {xpath}")
            if self._try_click(xpath, "Botão Entrar", timeout=5):
                clicked = True
                break

        if not clicked:
            log.warning("⚠️  Botão 'Entrar' não encontrado por XPath — tentando por JavaScript...")
            try:
                # Tenta clicar pelo JavaScript buscando botão com texto "Entrar"
                self.driver.execute_script("""
                    var btns = document.querySelectorAll('button, a');
                    for (var i = 0; i < btns.length; i++) {
                        if (btns[i].textContent.trim() === 'Entrar') {
                            btns[i].click();
                            break;
                        }
                    }
                """)
                log.info("Clique via JavaScript enviado.")
                clicked = True
            except Exception as e:
                log.error(f"Falha no clique JS: {e}")

        time.sleep(3)

        # Pode aparecer outro popup depois de abrir o modal — fecha se existir
        self._try_click(
            "//button[contains(text(), 'Sim')]",
            "Popup pós-modal → Sim",
            timeout=2,
        )

        # Preenche Email ou CPF
        # Seletor auditado: input[placeholder="Email ou CPF"]
        log.info("Preenchendo formulário de login...")
        if not self._try_fill("input[placeholder='Email ou CPF']", EMAIL, "Campo email/CPF"):
            for css in [
                "input[placeholder*='mail']",
                "input[placeholder*='CPF']",
                "input[placeholder*='Login']",
                "input[type='email']",
                "input[name='email']",
                "input[name='username']",
                "input[name='login']",
            ]:
                if self._try_fill(css, EMAIL, f"Email fallback: {css}"):
                    break

        time.sleep(0.5)

        # Preenche Senha
        if not self._try_fill("input[placeholder='Senha']", PASSWORD, "Campo senha"):
            for css in [
                "input[placeholder*='senha']",
                "input[placeholder*='Senha']",
                "input[type='password']",
                "input[name='password']",
                "input[name='senha']",
            ]:
                if self._try_fill(css, PASSWORD, f"Senha fallback: {css}"):
                    break

        time.sleep(0.5)

        # ─── FASE 1: Submissão (Clique Único) ───
        log.info("Tentando submeter formulário de login...")
        submitted = False
        for i in range(3):
            # Tenta clicar no botão de enviar
            if self._try_click("//*[@id='legitimuz-action-send-analisys']", "Submit ID", timeout=5):
                submitted = True
            elif self._try_click("//button[@type='submit']", "Submit type=submit", timeout=3):
                submitted = True
            
            # Backup via JavaScript se o clique físico falhar
            if not submitted:
                try:
                    self.driver.execute_script("""
                        var btn = document.getElementById('legitimuz-action-send-analisys') || 
                                  document.querySelector('button[type="submit"]') ||
                                  Array.from(document.querySelectorAll('button')).find(b => b.textContent.trim() === 'Entrar');
                        if (btn) btn.click();
                    """)
                    log.info("Clique de submit via JS enviado.")
                    submitted = True
                except Exception:
                    pass
            
            if submitted:
                break
            time.sleep(2)

        if not submitted:
            log.error("Não foi possível clicar no botão de Submit.")
            raise Exception("Erro de interface: Botão de submit não responde.")

        # ─── FASE 2: Policiamento/Verificação (Aguardando autenticação) ───
        log.info("Aguardando confirmação de login (Polling rápido)...")
        authenticated = False
        for sec in range(30):  # 30 iterações de 1s = 30 segundos
            # 1. Verifica se logou (Instantâneo)
            if self.is_logged_in():
                log.info(f"✅ Login confirmado em {sec}s!")
                authenticated = True
                break
            
            # 2. Se não logou ainda, limpa possíveis bloqueadores de forma ultra-rápida
            self.handle_post_login_popups()

            if sec % 5 == 0:
                log.info(f"   [{sec}s] Aguardando autenticação...")
            
            time.sleep(1)

        if not authenticated:
            log.error("❌ Falha crítica: Tempo esgotado sem confirmação de login.")
            raise Exception("Erro de autenticação: Timeout ao confirmar sessão.")

        # Aguarda estabilizar final
        time.sleep(1)

        # Limpeza final rápida
        self.handle_post_login_popups()

        log.info(f"✅ Sessão autenticada com sucesso. URL: {self.driver.current_url}")

    # ─── Ir para o Aviator ────────────────────────────────────────────────────
    def navigate_to_aviator(self):
        log.info(f"Navegando para o Aviator: {AVIATOR_URL}")
        self.driver.get(AVIATOR_URL)
        time.sleep(8)

        # Fecha qualquer popup que apareça na página do jogo
        for xpath in [
            "//button[contains(text(), 'Sim')]",
            "//button[contains(text(), 'Aceitar')]",
            "//button[contains(@class,'close')]",
        ]:
            self._try_click(xpath, "Popup na página do Aviator", timeout=2)

        log.info("Página do Aviator carregada.")

    # ─── Entrar no Iframe ─────────────────────────────────────────────────────
    def switch_to_game_iframe(self):
        """
        Navega pelos dois níveis de iframes aninhados confirmados pela auditoria:
          Nível 1: launchdigi.net  (iframe na página do casino)
          Nível 2: aviator-next.spribegaming.com  (jogo real do Spribe)
        """
        log.info("Voltando ao contexto principal da página...")
        self.driver.switch_to.default_content()
        time.sleep(2)

        # ── NÍVEL 1: Entra no iframe do launchdigi (ou qualquer launcher) ─────
        log.info("[iframe nível 1] Procurando iframe do launcher...")
        iframes_lvl1 = self.driver.find_elements(By.TAG_NAME, "iframe")
        log.info(f"  Encontrados {len(iframes_lvl1)} iframe(s) na página principal.")

        for i, f in enumerate(iframes_lvl1):
            src = f.get_attribute("src") or ""
            log.info(f"  iframe[{i}]: {src[:100]}")

        entered_lvl1 = False
        # Tenta por src primeiro (prioridade: spribe, launchdigi, qualquer launcher)
        for kw in ["spribe", "aviator", "launchdigi", "launch", "game"]:
            for f in iframes_lvl1:
                src = f.get_attribute("src") or ""
                if kw in src.lower():
                    self.driver.switch_to.frame(f)
                    log.info(f"✅ [nível 1] Entrou no iframe: {src[:80]}")
                    entered_lvl1 = True
                    break
            if entered_lvl1:
                break

        # Fallback: CSS selector
        if not entered_lvl1:
            for css in ["iframe.relative.z-20", "iframe.z-20", "iframe"]:
                try:
                    el = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, css))
                    )
                    self.driver.switch_to.frame(el)
                    log.info(f"✅ [nível 1] Entrou via CSS: {css}")
                    entered_lvl1 = True
                    break
                except TimeoutException:
                    continue

        if not entered_lvl1:
            # Se falhar aqui, verifica se não deslogou
            if CASINO_URL in self.driver.current_url and "play" not in self.driver.current_url:
                raise Exception("Fora da página do jogo! Possível deslogue ou redirecionamento.")
            raise Exception("Iframe nível 1 não encontrado!")

        time.sleep(4)  # Aguarda o conteúdo do nível 1 carregar

        # ── NÍVEL 2: Dentro do launchdigi, procura o iframe do Spribe ─────────
        log.info("[iframe nível 2] Procurando iframe do Spribe dentro do launcher...")
        iframes_lvl2 = self.driver.find_elements(By.TAG_NAME, "iframe")
        log.info(f"  Encontrados {len(iframes_lvl2)} iframe(s) no nível 1.")

        if iframes_lvl2:
            for i, f in enumerate(iframes_lvl2):
                src = f.get_attribute("src") or ""
                log.info(f"  iframe_lvl2[{i}]: {src[:100]}")

            # Tenta por src do Spribe primeiro
            entered_lvl2 = False
            for kw in ["spribe", "aviator", "spribegaming"]:
                for f in iframes_lvl2:
                    src = f.get_attribute("src") or ""
                    if kw in src.lower():
                        self.driver.switch_to.frame(f)
                        log.info(f"✅ [nível 2] Entrou no iframe Spribe: {src[:80]}")
                        entered_lvl2 = True
                        break
                if entered_lvl2:
                    break

            # Se não achou pelo src, entra no primeiro iframe do nível 2
            if not entered_lvl2:
                self.driver.switch_to.frame(iframes_lvl2[0])
                src = iframes_lvl2[0].get_attribute("src") or ""
                log.info(f"✅ [nível 2 fallback] Entrou no primeiro iframe: {src[:80]}")

            time.sleep(3)
        else:
            log.info("ℹ️  Sem iframe nível 2 — o jogo pode estar diretamente no nível 1.")

        log.info("✅ Dentro do contexto do jogo Aviator. Pronto para monitorar.")

    # ─── Lê o Histórico ───────────────────────────────────────────────────────
    def get_history_multipliers(self) -> list:
        """
        Tenta ler os multiplicadores do histórico dentro do iframe.
        Retorna lista de floats (mais recente primeiro).
        """
        for selector in HISTORY_SELECTORS:
            try:
                els = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if not els:
                    continue
                values = []
                for el in els:
                    try:
                        raw   = el.text.strip()
                        clean = re.sub(r"[xX,\s]", "", raw).replace(",", ".")
                        if clean:
                            val = float(clean)
                            if 1.0 <= val <= 10000.0:
                                values.append(val)
                    except (ValueError, StaleElementReferenceException):
                        continue
                if values:
                    log.debug(f"Histórico lido ({selector}): {values[:5]}")
                    return values
            except Exception:
                continue
        return []

    # ─── Enviar para Webhook ──────────────────────────────────────────────────
    def send_to_webhook(self, multiplier: float):
        payload = {
            "multiplier": multiplier,
            "ts":         int(time.time() * 1000),
            "source":     "aviator-history-next",
        }
        try:
            resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
            if resp.status_code in (200, 201, 202):
                self.total_sent += 1
                self.last_webhook_time = time.time()  # Reseta watchdog
                log.info(f"✅ Vela enviada: {multiplier}x  (total: {self.total_sent})")
            else:
                log.warning(f"⚠️  Webhook respondeu {resp.status_code}: {resp.text[:100]}")
        except requests.exceptions.RequestException as e:
            log.error(f"❌ Erro ao enviar webhook: {e}")

    # ─── Loop de Monitoramento ────────────────────────────────────────────────
    def monitor_loop(self):
        log.info("═══════════════════════════════════════════")
        log.info("   Monitoramento iniciado — aguardando...  ")
        log.info("═══════════════════════════════════════════")

        consecutive_empties = 0
        max_empties = 30  # ~60s sem dados = reconectar iframe

        while True:
            try:
                # ─── WATCHDOG CHECK ───
                inactivity_duration = time.time() - self.last_webhook_time
                if inactivity_duration > self.max_inactivity:
                    log.error(f"🚨 WATCHDOG: {int(inactivity_duration)}s sem novas velas. Reiniciando tudo...")
                    raise RuntimeError("Watchdog timeout - Inatividade prolongada detectada.")

                current = self.get_history_multipliers()

                if not current:
                    consecutive_empties += 1
                    log.debug(f"Histórico vazio ({consecutive_empties}/{max_empties})")
                    
                    if consecutive_empties >= max_empties:
                        log.warning("Histórico vazio por muito tempo — verificando se ainda estamos logados...")
                        
                        # Verifica se ainda está na URL correta
                        if AVIATOR_URL not in self.driver.current_url:
                            raise Exception(f"Redirecionamento detectado! URL atual: {self.driver.current_url}")
                        
                        self.switch_to_game_iframe()
                        consecutive_empties = 0
                    
                    time.sleep(POLL_INTERVAL)
                    continue

                consecutive_empties = 0

                if not self.last_multipliers:
                    log.info(f"Histórico inicial: {current[:5]}")
                    self.send_to_webhook(current[0])
                    self.last_multipliers = current
                else:
                    # Descobre velas novas (head da lista = mais recente)
                    new_candles = []
                    for val in current:
                        if self.last_multipliers and val == self.last_multipliers[0]:
                            break
                        new_candles.append(val)

                    if new_candles:
                        for candle in reversed(new_candles):
                            log.info(f"🕯️  Nova vela: {candle}x")
                            self.send_to_webhook(candle)
                        self.last_multipliers = current

            except StaleElementReferenceException:
                log.debug("Elemento stale — retentando...")
            except NoSuchFrameException:
                log.warning("Iframe perdido — reconectando...")
                self.switch_to_game_iframe()
                self.last_multipliers = []
            except (WebDriverException, RuntimeError) as e:
                log.error(f"Erro no monitoramento: {e}")
                raise

            time.sleep(POLL_INTERVAL)

    # ─── Limpa recursos ───────────────────────────────────────────────────────
    def teardown(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
            log.info("Browser fechado.")

    # ─── Run 24/7 ─────────────────────────────────────────────────────────────
    def run(self):
        log.info("══════════════════════════════════════════")
        log.info("   AVIATOR SCRAPER — Iniciando 24/7      ")
        log.info("══════════════════════════════════════════")
        log.info(f"Webhook: {WEBHOOK_URL}")
        log.info(f"Intervalo: {POLL_INTERVAL}s")

        attempt = 0
        while True:
            attempt += 1
            log.info(f"\n─── Tentativa #{attempt} ───")
            try:
                self.setup_driver()
                self.login()
                self.navigate_to_aviator()
                self.switch_to_game_iframe()
                self.monitor_loop()

            except KeyboardInterrupt:
                log.info("\n🛑 Encerrado pelo usuário.")
                break

            except Exception as e:
                log.error(f"💥 Erro fatal: {e}")
                log.info("Aguardando 30s antes de reiniciar...")
                self.teardown()
                time.sleep(30)

            finally:
                self.teardown()


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    scraper = AviatorScraper()
    scraper.run()
