import os
import sys
import time
import random
import sqlite3
import json
import requests
import traceback
import subprocess
import atexit
import re
from datetime import datetime

# Third-party imports
from openai import OpenAI
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium_stealth import stealth
import chromadb

# --- 0. SETUP & UTILS ---
sys.stderr = open(os.devnull, 'w')
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

script_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(script_dir, '.env'))

DB_PATH = os.path.join(script_dir, "pathogen_memory.db")
ID_BACKUP_FILE = os.path.join(script_dir, "backup_processed_ids.txt")

class Logger:
    COLORS = {
        "SYSTEM": "\033[94m", "BRAIN": "\033[95m", 
        "PATROL": "\033[91m", "ACTION": "\033[92m", 
        "VISUAL": "\033[96m", "MARKET": "\033[33m", 
        "RESET": "\033[0m", "SCAM": "\033[41m", "GROWTH": "\033[93m"
    }
    
    @staticmethod
    def log(category, message):
        t = datetime.now().strftime("%H:%M:%S")
        c = Logger.COLORS.get(category, Logger.COLORS["RESET"])
        print(f"[{t}] {c}[{category}]{Logger.COLORS['RESET']} {message}")

    @staticmethod
    def error(message):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ [ERROR] {message}")
        
    @staticmethod
    def timer(seconds):
        for i in range(seconds, 0, -1):
            sys.stdout.write(f"\r[{datetime.now().strftime('%H:%M:%S')}] ⏳ Hibernating: {i}s...   ")
            sys.stdout.flush()
            time.sleep(1)
        sys.stdout.write("\r" + " " * 60 + "\r")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚡ System Activated.")

# --- 1. CONFIGURATION ---
class Config:
    # API & PROJECT
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    PROJECT_NAME = os.getenv('PROJECT_NAME', 'Pathogen Protocol')
    WEBSITE_URL = os.getenv('WEBSITE_URL', 'https://pathogenprotocol.xyz')
    DISCORD_INVITE = os.getenv('DISCORD_INVITE', '')
    
    # BRANDING & HASHTAGS
    PROJECT_TAGS = ["#PathogenProtocol", "$PATHOGEN", "#Solana"]
    
    # LORE & SYSTEM
    LORE_KNOWLEDGE = os.getenv('LORE_KNOWLEDGE', "IDENTITY: Dr. Pathogen. ROLE: Clinical Virologist of DeFi.")
    
    # MODEL ECONOMY
    MODEL_SMART = "gpt-4-turbo" 
    MODEL_CHEAP = "gpt-4o-mini" 

    # BROWSER SETTINGS (CRITICAL FOR BRAVE)
    BROWSER_TYPE = os.getenv('BROWSER_TYPE', 'chrome').lower()
    BROWSER_EXECUTABLE_PATH = os.getenv('BROWSER_EXECUTABLE_PATH')
    BROWSER_PROFILE = os.getenv('BROWSER_PROFILE', 'Default')
    PROFILE_PATH = os.path.join(script_dir, os.getenv('PROFILE_PATH', 'agent_profile'))

    # VISUALS (Fixed Style)
    GENERATE_IMAGES = os.getenv('GENERATE_IMAGES', 'True').lower() == 'true'
    # Wymuszony styl z kodu, aby uniknąć błędów parsowania .env
    IMAGE_STYLE = "aesthetic: abstract bio-hazard data, toxic green and black, medical hud interface, microscopic view, high detail, dark atmosphere. NEGATIVE: blue, purple, red, pink, text, watermark, logo, typography, letters, words, alphabet, blurry, cartoon, face"

    # TIMING
    MIN_SLEEP = int(os.getenv('MIN_SLEEP_DURATION', 45))
    MAX_SLEEP = int(os.getenv('MAX_SLEEP_DURATION', 180))
    POST_COOLDOWN_MINUTES = int(os.getenv('POST_COOLDOWN_MINUTES', 120))

    # SELF AWARENESS
    MY_HANDLE = os.getenv('MY_HANDLE')
    GROWTH_GOAL = os.getenv('GROWTH_GOAL')

    # SELECTORS
    SELECTORS = {
        "TWEET_INPUT": 'div[data-testid="tweetTextarea_0"]',
        "TWEET_BTN": '[data-testid="tweetButton"]',
        "TIMELINE_TWEET": 'article[data-testid="tweet"]',
        "REPLY_ICON": '[data-testid="reply"]',
        "USER_NAME": 'div[data-testid="User-Name"]',
        "USER_BIO": '[data-testid="UserDescription"]',
        "LINK_TO_TWEET": ".//a[contains(@href, '/status/')]",
        "CLOSE_MODAL": '[data-testid="app-bar-close"]'
    }

    # Safe Prompts (Hardcoded for stability)
    SAFE_VISUALS = [
        "abstract macro shot of digital virus cells interacting with green data stream",
        "dark hud interface displaying verifying security protocols in emerald green",
        "geometric 3d structure of a blockchain node infected by green pathogen",
        "cybernetic microscope view of code vulnerability, matrix style green lighting",
        "abstract data visualization shield protecting core, dark aesthetic"
    ]
    
    SCAM_KEYWORDS = ["claim airdrop", "official mint", "migration required", "validate wallet", "distribution live"]

# --- 2. PROCESS MANAGER ---
class ProcessManager:
    @staticmethod
    def kill_stale_bot_processes():
        try:
            # Ustalamy co zabijać (chrome.exe czy brave.exe)
            if Config.BROWSER_EXECUTABLE_PATH:
                process_name = os.path.basename(Config.BROWSER_EXECUTABLE_PATH)
            else:
                process_name = "chrome.exe"

            folder_name = os.path.basename(Config.PROFILE_PATH)
            Logger.log("SYSTEM", f"Cleaning up stale processes: {process_name}...")
            
            # Zabija procesy używające naszego folderu profilu
            cmd = f'wmic process where "name=\'{process_name}\' and CommandLine like \'%{folder_name}%\'" call terminate'
            with open(os.devnull, 'w') as DEVNULL:
                subprocess.call(cmd, shell=True, stdout=DEVNULL, stderr=DEVNULL)
            time.sleep(2)
        except Exception: pass

# --- 3. VIRAL INTELLIGENCE (MARKET & RISK) ---
class ViralIntelligence:
    def __init__(self, db):
        self.db = db
        self.cg_url = "https://api.coingecko.com/api/v3"
        self.dex_url = "https://api.dexscreener.com/latest/dex"
        self.headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    def get_market_sentiment(self):
        try:
            data = requests.get(f"{self.cg_url}/simple/price?ids=bitcoin,ethereum,solana&vs_currencies=usd&include_24hr_change=true", headers=self.headers, timeout=5).json()
            btc_price = data['bitcoin']['usd']
            btc_change = data['bitcoin']['usd_24h_change']
            sol_price = data['solana']['usd']
            
            trend = "NEUTRAL"
            if btc_change > 3: trend = "BULLISH"
            elif btc_change < -3: trend = "BEARISH"
            
            return f"BTC: ${btc_price} ({btc_change:.1f}%), SOL: ${sol_price}. Trend: {trend}."
        except:
            return "Market Data Unavailable."

    def analyze_token_risk(self, query):
        try:
            url = f"{self.dex_url}/search?q={query}"
            res = requests.get(url, headers=self.headers, timeout=5)
            if res.status_code != 200: return {"score": 50, "reason": "API Error"}
            
            pairs = res.json().get('pairs', [])
            if not pairs: return {"score": 50, "reason": "Token not found on DEX"}

            pair = pairs[0]
            liquidity = float(pair.get('liquidity', {}).get('usd', 0))
            fdv = float(pair.get('fdv', 0))
            created_at = pair.get('pairCreatedAt', 0)
            age_hours = (time.time() * 1000 - created_at) / (1000 * 3600)
            
            risk_score = 0
            reasons = []

            # Safety Check: Bardzo stara i płynna para = Bezpieczna
            if liquidity > 500000 and age_hours > 168:
                return {"score": 0, "reason": "Safe, established project"}

            if liquidity < 2000: 
                risk_score += 40
                reasons.append("Liquidity Critically Low (<$2k)")
            
            if fdv > 0 and (liquidity / fdv) < 0.02:
                risk_score += 30
                reasons.append("Low Liquidity/FDV Ratio")

            if age_hours < 2:
                risk_score += 15
                reasons.append("New Pair (<2h)")

            return {
                "score": min(risk_score, 100),
                "symbol": pair['baseToken']['symbol'],
                "reasons": ", ".join(reasons)
            }
        except:
            return {"score": 0, "reason": "Error"}

# --- 4. VISUAL CORTEX ---
class VisualCortex:
    def generate(self, ignored_context=None):
        if not Config.GENERATE_IMAGES: return None
        Logger.log("VISUAL", "Synthesizing visual data (Green/Abstract)...")
        try:
            base = random.choice(Config.SAFE_VISUALS)
            full_prompt = f"{base}, {Config.IMAGE_STYLE}"
            safe_prompt = full_prompt.replace(" ", "%20")
            
            # Wymuszamy seed i nologo, żeby uniknąć tekstu
            seed = random.randint(1, 999999)
            url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1024&height=768&model=flux&nologo=true&enhance=false&seed={seed}"
            
            res = requests.get(url, timeout=20)
            if res.status_code == 200:
                path = os.path.join(script_dir, "temp_visual.jpg")
                with open(path, 'wb') as f: f.write(res.content)
                return path
        except Exception as e:
            Logger.error(f"Visual gen failed: {e}")
        return None

# --- 5. DATABASE ---
# --- 5. DATABASE ---
class DatabaseManager:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._init_tables()
        self._init_vector()
        self._init_backup()

    def _init_tables(self):
        # Tabela interakcji (historia postów)
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS engagements 
                             (target_id TEXT PRIMARY KEY, timestamp TEXT, type TEXT, content TEXT, user_handle TEXT)''')
        
        # Tabela pamięci treści (anty-spam)
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS seen_content 
                             (content_hash TEXT PRIMARY KEY, timestamp TEXT)''')
        
        # NOWE: Tabela statystyk profilu (do growth trendu)
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS profile_stats 
                             (timestamp TEXT, followers INTEGER, phase TEXT)''')
        self.conn.commit()

    def _init_backup(self):
        if not os.path.exists(ID_BACKUP_FILE):
            with open(ID_BACKUP_FILE, "w") as f: f.write("")

    def _init_vector(self):
        try:
            self.chroma = chromadb.PersistentClient(path="pathogen_vector_store")
            self.memory = self.chroma.get_or_create_collection(name="pathogen_memories")
        except: self.memory = None

    # --- CORE METHODS ---
    def exists(self, tid):
        # 1. Sprawdź plik (szybki cache)
        try:
            with open(ID_BACKUP_FILE, "r") as f:
                if tid in f.read(): return True
        except: pass
        
        # 2. Sprawdź bazę SQL
        self.cursor.execute("SELECT 1 FROM engagements WHERE target_id=?", (tid,))
        return self.cursor.fetchone() is not None

    def is_content_seen(self, text):
        """Sprawdza duplikaty treści"""
        if not text: return False
        text_hash = str(hash(text[:100])) 
        self.cursor.execute("SELECT 1 FROM seen_content WHERE content_hash=?", (text_hash,))
        return self.cursor.fetchone() is not None

    def mark_as_seen(self, tid, text, action_type):
        """Zapisuje ID i Hash jako przetworzone"""
        try:
            ts = datetime.now().isoformat()
            # Zapisz ID
            self.cursor.execute("INSERT OR IGNORE INTO engagements VALUES (?, ?, ?, ?, ?)", 
                            (tid, ts, action_type, "PROCESSED", "SYSTEM"))
            # Zapisz treść
            if text:
                text_hash = str(hash(text[:100]))
                self.cursor.execute("INSERT OR IGNORE INTO seen_content VALUES (?, ?)", (text_hash, ts))
            
            self.conn.commit()
            with open(ID_BACKUP_FILE, "a") as f: f.write(f"{tid}\n")
        except Exception as e:
            print(f"DB Mark Error: {e}")

    def save_interaction(self, tid, user, content, type_name):
        """Zapisuje szczegóły interakcji (nasz tweet/odpowiedź)"""
        try:
            ts = datetime.now().isoformat()
            self.cursor.execute("INSERT OR IGNORE INTO engagements VALUES (?, ?, ?, ?, ?)", 
                            (tid, ts, type_name, content, user))
            self.conn.commit()
            
            # Dodaj do wektora (pamięć długotrwała)
            if self.memory and content:
                self.memory.add(
                    documents=[content], 
                    metadatas=[{"type": type_name, "user": user}], 
                    ids=[f"{tid}_{int(time.time())}"]
                )
        except: pass

    # --- STATS & TRENDS (Naprawione metody) ---
    def save_stats(self, followers, following, posts, phase):
        """Zapisuje statystyki profilu"""
        try:
            ts = datetime.now().isoformat()
            self.cursor.execute("INSERT INTO profile_stats VALUES (?, ?, ?)", (ts, followers, phase))
            self.conn.commit()
        except Exception as e:
            print(f"Stats Save Error: {e}")

    def get_growth_trend(self):
        """Oblicza trend wzrostu na podstawie historii"""
        try:
            self.cursor.execute("SELECT followers FROM profile_stats ORDER BY timestamp DESC LIMIT 2")
            rows = self.cursor.fetchall()
            if len(rows) < 2: return "STABLE"
            
            current = rows[0][0]
            previous = rows[1][0]
            
            if current > previous: return "GROWING"
            elif current < previous: return "DECLINING"
            return "STABLE"
        except: return "UNKNOWN"

    # --- UTILS ---
    def get_recent_post_types(self, limit=3):
        self.cursor.execute("SELECT type FROM engagements WHERE user_handle='SELF' ORDER BY timestamp DESC LIMIT ?", (limit,))
        return [row[0] for row in self.cursor.fetchall()]

    def get_relevant_memory(self, query_text):
        if not self.memory: return ""
        try:
            results = self.memory.query(query_texts=[query_text], n_results=2)
            return "\n".join(results['documents'][0]) if results['documents'] else ""
        except: return ""
        
    def get_last_post_time(self):
        self.cursor.execute("SELECT timestamp FROM engagements WHERE user_handle='SELF' ORDER BY timestamp DESC LIMIT 1")
        res = self.cursor.fetchone()
        return datetime.fromisoformat(res[0]) if res else None
        
# --- 6. BROWSER ENGINE (FIXED FOR BRAVE) ---
class BrowserEngine:
    def __init__(self):
        self.driver = self._setup()
        self.wait = WebDriverWait(self.driver, 15)
        atexit.register(self.quit)

    def _setup(self):
        browser_name = Config.BROWSER_EXECUTABLE_PATH if Config.BROWSER_EXECUTABLE_PATH else "Chrome"
        Logger.log("SYSTEM", f"Launching Browser: {browser_name}...")
        
        options = webdriver.ChromeOptions()
        
        # --- BRAVE FIX ---
        if Config.BROWSER_EXECUTABLE_PATH:
            options.binary_location = Config.BROWSER_EXECUTABLE_PATH
        # -----------------

        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument(f"--user-data-dir={Config.PROFILE_PATH}")
        options.add_argument(f"--profile-directory={Config.BROWSER_PROFILE}")
        options.add_argument("--log-level=3")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        
        try:
            from selenium.webdriver.chrome.service import Service
            service = Service(log_output=os.devnull)
            driver = webdriver.Chrome(options=options, service=service)
            stealth(driver, languages=["en-US"], vendor="Google Inc.", platform="Win32", webgl_vendor="Intel Inc.", renderer="Intel Iris OpenGL Engine", fix_hairline=True)
            return driver
        except Exception as e:
            Logger.error(f"Browser Init Failed: {e}")
            sys.exit(1)

    def quit(self):
        try: self.driver.quit()
        except: pass

    def wait_for(self, selector, timeout=10):
        try: return WebDriverWait(self.driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
        except: return None

    def wait_clickable(self, selector, timeout=10):
        try: return WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
        except: return None

    def safe_click(self, element):
        try: element.click()
        except:
            try: self.driver.execute_script("arguments[0].click();", element)
            except: ActionChains(self.driver).move_to_element(element).click().perform()

    def type_human(self, element, text):
        try:
            self.safe_click(element)
            time.sleep(0.2)
            for char in text:
                element.send_keys(char)
                time.sleep(random.uniform(0.02, 0.08))
        except: pass

    def upload_file(self, file_path):
        try:
            file_inputs = self.driver.find_elements(By.XPATH, "//input[@type='file']")
            if not file_inputs: return False
            file_inputs[0].send_keys(os.path.abspath(file_path))
            return True
        except: return False

# --- 7. AGENT BRAIN ---
class AgentBrain:
    def __init__(self, db):
        self.client = OpenAI(api_key=Config.OPENAI_API_KEY)
        self.db = db

    def _query(self, system, user, model=Config.MODEL_CHEAP):
        try:
            res = self.client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={"type": "json_object"}
            )
            return json.loads(res.choices[0].message.content)
        except Exception: return {}

    def analyze_situation(self, text, stats, risk_data, market_context):
        # --- SAFETY RAIL: Blokada fałszywych oskarżeń ---
        risk_score = risk_data.get('score', 0)
        
        # Jeśli ryzyko jest niskie i brak słów-kluczy scamu, AI ma zakaz ostrzegania
        if risk_score < 20 and "claim" not in text.lower():
            return {"decision": "IGNORE", "reasoning": "Risk score too low for intervention."}
        # ------------------------------------------------

        sys_prompt = f"""
        {Config.LORE_KNOWLEDGE}
        TASK: Analyze tweet. MARKET: {market_context}
        INPUT: Tweet="{text}", Risk={risk_score}/100.
        
        RULES:
        1. Risk < 30: IGNORE.
        2. Risk 30-70: INVESTIGATE (Ask politely).
        3. Risk > 70: WARNING (Clinical alert).
        
        OUTPUT JSON: {{ "decision": "IGNORE/INVESTIGATE/WARNING", "reply_content": "...", "broadcast_content": "...", "reasoning": "..." }}
        """
        return self._query(sys_prompt, "Analyze.", model=Config.MODEL_SMART)

    def generate_broadcast(self, topic, market_context):
        sys_prompt = f"""
        {Config.LORE_KNOWLEDGE}
        TASK: Write a viral post about {topic}.
        CONTEXT: {market_context}.
        
        STYLE:
        - Clinical, ominous but protective.
        - Mention {Config.WEBSITE_URL}.
        - TAGS: {', '.join(Config.PROJECT_TAGS)}.
        - NO FLUFF.
        
        OUTPUT JSON: {{ "content": "Tweet text here" }}
        """
        return self._query(sys_prompt, "Generate.", model=Config.MODEL_SMART)

    def decide_next_move(self, profile_stats, recent_posts, market_status):
        history_str = ", ".join(recent_posts)
        prompt = f"""
        IDENTITY: {Config.LORE_KNOWLEDGE} GOAL: {Config.GROWTH_GOAL}
        STATS: {profile_stats}
        HISTORY: {history_str}
        MARKET: {market_status}
        
        RULES:
        - Don't repeat the same action type twice in a row.
        - If market is RED -> BROADCAST_EDU or WARNING.
        - If market is GREEN -> GROWTH_HACK or BROADCAST_MARKET.
        
        ACTIONS: SCAM_HUNT, BROADCAST_EDU, BROADCAST_MARKET, CHECK_MENTIONS, GROWTH_HACK.
        OUTPUT JSON: {{ "action": "ACTION_NAME", "reasoning": "..." }}
        """
        return self._query(prompt, "Direct mission.", model=Config.MODEL_SMART)

# --- 8. PROFILE MANAGER ---
class ProfileManager:
    def __init__(self, driver, db):
        self.driver = driver
        self.db = db

    def perform_audit(self):
        Logger.log("SYSTEM", "Performing Self-Audit...")
        if not Config.MY_HANDLE: return {"followers": 0, "phase": "BOOTSTRAP"}

        try:
            self.driver.get(f"https://twitter.com/{Config.MY_HANDLE.replace('@', '')}")
            WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, Config.SELECTORS["USER_BIO"])))
            
            try:
                f_el = self.driver.find_element(By.XPATH, f"//a[contains(@href, '/followers')]//span")
                followers = self._parse_number(f_el.text)
            except: followers = 0
            
            phase = "BOOTSTRAP"
            if followers > 100: phase = "GROWTH"
            if followers > 1000: phase = "AUTHORITY"
            
            self.db.save_stats(followers, 0, 0, phase)
            return {"followers": followers, "phase": phase}
        except: return {"followers": 0, "phase": "UNKNOWN"}

    def _parse_number(self, text):
        text = text.upper().replace(',', '.')
        mult = 1
        if 'K' in text: mult = 1000
        elif 'M' in text: mult = 1000000
        return int(float(re.sub(r"[^0-9.]", "", text)) * mult)

# --- 9. MAIN AGENT ---
class PathogenAgent:
    def __init__(self):
        ProcessManager.kill_stale_bot_processes()
        self.db = DatabaseManager()
        self.market = ViralIntelligence(self.db)
        self.brain = AgentBrain(self.db)
        self.browser = BrowserEngine()
        self.visual = VisualCortex()
        self.profile = ProfileManager(self.browser.driver, self.db)

    def run(self):
        Logger.log("SYSTEM", f"PROTOCOL ONLINE. Identity: {Config.MY_HANDLE}")
        self.browser.driver.get("https://twitter.com/home")
        
        if not self.browser.wait_for(Config.SELECTORS["TWEET_INPUT"], timeout=20):
            Logger.log("SYSTEM", "Please log in manually if needed.")
            time.sleep(30)
        
        my_stats = self.profile.perform_audit()
            
        while True:
            try:
                market_status = self.market.get_market_sentiment()
                recent_activity = self.db.get_recent_post_types(limit=5)
                my_stats['trend'] = self.db.get_growth_trend()
                
                Logger.log("MARKET", market_status)
                
                # Decyzja Strategiczna
                strategy = self.brain.decide_next_move(my_stats, recent_activity, market_status)
                action = strategy.get('action', 'SCAM_HUNT')
                reason = strategy.get('reasoning', 'Default')
                
                # Cooldown Check
                last_post = self.db.get_last_post_time()
                if last_post and "BROADCAST" in action:
                    minutes = (datetime.now() - last_post).total_seconds() / 60
                    if minutes < Config.POST_COOLDOWN_MINUTES:
                        Logger.log("SKIP", f"Cooldown ({int(minutes)}m). Switching to patrol.")
                        action = "SCAM_HUNT"

                Logger.log("STRATEGY", f"Executing: {action}. Reason: {reason}")
                
                if action == "SCAM_HUNT": self._scam_hunt(market_status)
                elif "BROADCAST" in action: self._broadcast(action, market_status)
                elif action == "CHECK_MENTIONS": self._check_mentions()
                elif action == "GROWTH_HACK": self._growth_hack(market_status)

                sleep_time = random.randint(Config.MIN_SLEEP, Config.MAX_SLEEP)
                Logger.timer(sleep_time)
                
                if random.randint(1, 10) == 1: my_stats = self.profile.perform_audit()

            except KeyboardInterrupt: break
            except Exception as e:
                Logger.error(f"Loop Error: {e}")
                time.sleep(60)

    def _scam_hunt(self, market_context):
        keyword = random.choice(Config.SCAM_KEYWORDS)
        Logger.log("PATROL", f"Searching for vector: '{keyword}'")
        
        self.browser.driver.get(f"https://twitter.com/search?q={keyword}&src=typed_query&f=live")
        
        # Czekamy na tweety
        if not self.browser.wait_for(Config.SELECTORS["TIMELINE_TWEET"], timeout=10):
            Logger.log("PATROL", "No targets found.")
            return

        # 1. ZBIERANIE DANYCH (Snapshot)
        # Pobieramy elementy od razu, żeby uniknąć "StaleElementReference" przy odświeżaniu DOM
        found_tweets = []
        try:
            elements = self.browser.driver.find_elements(By.CSS_SELECTOR, Config.SELECTORS["TIMELINE_TWEET"])[:5]
            for el in elements:
                try:
                    # Wyciągamy link (ID) i tekst
                    link_el = el.find_element(By.XPATH, Config.SELECTORS["LINK_TO_TWEET"])
                    url = link_el.get_attribute('href')
                    text = el.text
                    tid = url.split('/')[-1]
                    found_tweets.append({"obj": el, "url": url, "tid": tid, "text": text})
                except: continue
        except Exception as e:
            Logger.error(f"Snapshot failed: {e}")
            return

        # 2. PRZETWARZANIE
        processed_count = 0
        for item in found_tweets:
            tid = item['tid']
            text = item['text']
            
            # --- WARSTWA OCHRONY PAMIĘCI ---
            # Sprawdź czy ID już było
            if self.db.exists(tid):
                continue
            
            # Sprawdź czy TREŚĆ już była (ochrona przed spam-botami wrzucającymi to samo)
            if self.db.is_content_seen(text):
                Logger.log("PATROL", f"Skipping duplicate content (TID: {tid})")
                self.db.mark_as_seen(tid, text, "DUPLICATE_IGNORE")
                continue
            # -------------------------------

            try:
                # Parsowanie usera
                handle = "Unknown"
                if "@" in text:
                    handle = re.search(r"@(\w+)", text).group(0)

                # Sprawdź ticker
                ticker_match = re.search(r'\$([a-zA-Z]{2,8})', text)
                risk_data = {"score": 0}
                if ticker_match:
                    risk_data = self.market.analyze_token_risk(ticker_match.group(1))
                
                # ANALIZA AI
                analysis = self.brain.analyze_situation(text, "Unknown stats", risk_data, market_context)
                decision = analysis.get('decision', 'IGNORE')
                
                Logger.log("BRAIN", f"Target: {handle} | Risk: {risk_data.get('score')} | Decision: {decision}")
                
                # 3. WYKONANIE AKCJI
                if decision == "WARNING":
                    alert_text = f"🚨 PATHOGEN DETECTED.\n\nTarget: {handle}\nRisk Factor: {risk_data.get('score')}/100\nDiagnosis: {analysis.get('broadcast_content')}\n\nStay Safe. Visit {Config.WEBSITE_URL}."
                    img_path = self.visual.generate()
                    
                    self._post_new_tweet(alert_text, img_path)
                    
                    # Zapisujemy sukces
                    self.db.mark_as_seen(tid, text, "SCAM_WARNING")
                    self.db.save_interaction(str(time.time()), "SELF", alert_text, "SCAM_BROADCAST")
                    return # Kończymy rundę po jednej akcji (żeby nie spamować)

                elif decision == "INVESTIGATE":
                    self._reply_to_tweet(item['obj'], analysis['reply_content'])
                    self.db.mark_as_seen(tid, text, "INVESTIGATED")
                    return

                else:
                    # WAŻNE: Nawet jak ignorujemy, zapisujemy to!
                    # Żeby w następnej pętli nie analizować tego samego.
                    self.db.mark_as_seen(tid, text, "IGNORE_DECISION")

            except Exception as e:
                Logger.error(f"Processing error: {e}")
                continue

    def _broadcast(self, type_name, market_context):
        topic = "Market" if "MARKET" in type_name else "Security"
        res = self.brain.generate_broadcast(topic, market_context)
        if res.get('content'):
            img = self.visual.generate()
            self._post_new_tweet(res['content'], img)
            self.db.save_interaction(str(time.time()), "SELF", res['content'], type_name)

    def _check_mentions(self):
        Logger.log("ACTION", "Checking Mentions...")
        self.browser.driver.get("https://twitter.com/notifications/mentions")
        # (Uproszczona logika dla zwięzłości, pełna w poprzednich wersjach)
        pass 

    def _growth_hack(self, market_status):
        targets = ["Solana", "aeyakovenko", "zachxbt", "coindesk"]
        target = random.choice(targets)
        Logger.log("GROWTH", f"Hacking reach of @{target}")
        try:
            self.browser.driver.get(f"https://twitter.com/{target}")
            self.browser.wait_for(Config.SELECTORS["TIMELINE_TWEET"])
            tweets = self.browser.driver.find_elements(By.CSS_SELECTOR, Config.SELECTORS["TIMELINE_TWEET"])
            if tweets:
                res = self.brain.analyze_situation(tweets[0].text, target, {}, market_status)
                if res.get('reply_content'):
                    self._reply_to_tweet(tweets[0], res['reply_content'])
        except: pass

    # --- POSTING LOGIC (FIXED ORDER) ---
    def _post_new_tweet(self, text, img_path=None):
        Logger.log("ACTION", "Navigating to Compose...")
        self.browser.driver.get("https://twitter.com/compose/tweet")
        
        box = self.browser.wait_for(Config.SELECTORS["TWEET_INPUT"], timeout=15)
        if not box: return

        try:
            # 1. WPISZ TEKST
            self.browser.type_human(box, text)
            time.sleep(3) # Czekaj aż X przetworzy tekst
            
            # 2. DODAJ OBRAZ (Jeśli jest)
            if img_path and os.path.exists(img_path):
                Logger.log("ACTION", "Uploading visual...")
                if self.browser.upload_file(img_path):
                    time.sleep(8) # Długi czas na upload
            
            # 3. KLIKNIJ
            btn = self.browser.wait_clickable(Config.SELECTORS["TWEET_BTN"])
            if btn:
                self.browser.safe_click(btn)
                Logger.log("ACTION", "Tweet sent.")
                time.sleep(5)
            else:
                Logger.error("Tweet button blocked.")

        except Exception as e:
            Logger.error(f"Post failed: {e}")

    def _reply_to_tweet(self, tweet_element, text):
        try:
            reply_icon = tweet_element.find_element(By.CSS_SELECTOR, Config.SELECTORS["REPLY_ICON"])
            self.browser.safe_click(reply_icon)
            box = self.browser.wait_for(Config.SELECTORS["TWEET_INPUT"])
            self.browser.type_human(box, text)
            btn = self.browser.wait_clickable(Config.SELECTORS["TWEET_BTN"])
            self.browser.safe_click(btn)
            Logger.log("ACTION", "Reply sent.")
            time.sleep(3)
        except:
            ActionChains(self.browser.driver).send_keys(Keys.ESCAPE).perform()

if __name__ == "__main__":
    agent = PathogenAgent()
    agent.run()