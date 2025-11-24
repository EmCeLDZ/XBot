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
# Wyciszenie logów systemowych TensorFlow/Selenium
sys.stderr = open(os.devnull, 'w')
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

script_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(script_dir, '.env'))

DB_PATH = os.path.join(script_dir, "pathogen_memory.db")
ID_BACKUP_FILE = os.path.join(script_dir, "backup_processed_ids.txt")

class Logger:
    COLORS = {
        "SYSTEM": "\033[94m", "BRAIN": "\033[95m", 
        "PATROL": "\033[91m", "SCOUT": "\033[93m", 
        "ACTION": "\033[92m", "VISUAL": "\033[96m", 
        "MARKET": "\033[33m", "SKIP": "\033[90m", "RESET": "\033[0m",
        "SCAM": "\033[41m" # Red Background
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

# --- 1. CONFIGURATION (ENV INTEGRATION) ---
class Config:
    # API & PROJECT
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    PROJECT_NAME = os.getenv('PROJECT_NAME', 'Pathogen Protocol')
    WEBSITE_URL = os.getenv('WEBSITE_URL', 'https://pathogenprotocol.xyz')
    DISCORD_INVITE = os.getenv('DISCORD_INVITE', '')
    LAUNCH_PHASE = os.getenv('LAUNCH_PHASE', 'UNKNOWN')
    
    # HASHTAGS & BRANDING
    PROJECT_TAGS = ["#PathogenProtocol", "$PATHOGEN", "#Solana", "#DeFi"]
    
    # LORE CONSTRUCTION
    _base_lore = os.getenv('LORE_KNOWLEDGE', 'Protocol details missing.')
    LORE_KNOWLEDGE = f"{_base_lore}\nCURRENT PHASE: {LAUNCH_PHASE}. DISCORD: {DISCORD_INVITE}"
    
    # SYSTEM PROMPT (Dynamic)
    SYSTEM_INSTRUCTIONS = f"""
    IDENTITY: You are Dr. Pathogen, Lead Architect of Pathogen Protocol on Solana.
    ROLE: Clinical Observer & Virologist of DeFi.
    KNOWLEDGE BASE: {LORE_KNOWLEDGE}
    
    OPERATIONAL RULES:
    1. CONTEXT: You are inside a Twitter thread. Read the history. Be relevant.
    2. TONE: Clinical, slightly ominous, protective, high intellect.
    3. BRANDING: 
       - If user is interested/neutral -> Use tags: {', '.join(PROJECT_TAGS)}.
       - If user is a SCAMMER or HOSTILE -> NO TAGS. Do not associate the brand with trash.
    4. DECISION: If a conversation leads nowhere (one word replies, emojis), TERMINATE it.
    """
    
    # TEMPLATES
    PROMPT_TEMPLATE = os.getenv('PROMPT_TEMPLATE', "Topic: {topic}")
    
    # MODEL ECONOMY
    MODEL_SMART = "gpt-4-turbo" 
    MODEL_CHEAP = "gpt-4o-mini" 

    # BROWSER
    BROWSER_TYPE = os.getenv('BROWSER_TYPE', 'chrome').lower()
    BROWSER_EXECUTABLE_PATH = os.getenv('BROWSER_EXECUTABLE_PATH')
    BROWSER_PROFILE = os.getenv('BROWSER_PROFILE', 'Default')
    _env_profile_path = os.getenv('PROFILE_PATH', 'agent_profile')
    PROFILE_PATH = os.path.abspath(_env_profile_path) if os.path.isabs(_env_profile_path) else os.path.join(script_dir, _env_profile_path)

    # VISUALS
    GENERATE_IMAGES = os.getenv('GENERATE_IMAGES', 'False').lower() == 'true'
    IMAGE_STYLE = os.getenv('IMAGE_STYLE')

    # TIMING & LIMITS
    MIN_SLEEP = int(os.getenv('MIN_SLEEP_DURATION', 30))
    MAX_SLEEP = int(os.getenv('MAX_SLEEP_DURATION', 120))
    POST_COOLDOWN_MINUTES = int(os.getenv('POST_COOLDOWN_MINUTES', 60))
    
    # MARKET THRESHOLDS
    DUMP_THRESHOLD = float(os.getenv('DUMP_THRESHOLD', -20))
    PUMP_THRESHOLD = float(os.getenv('PUMP_THRESHOLD', 50))

    # SEARCH QUERIES
    RUG_QUERIES = [
        "wallet drained help", "scammed metamask", "hacked phantom", 
        "rug pull alert", "crypto exploit victim", "solana drainer", 
        "private key exposed"
    ]

    SCAM_KEYWORDS = [
        "claim airdrop", "official mint", "migration required", 
        "validate wallet", "rectify node", "distribution live", 
        "snapshot taken claim", "whitelist closing"
    ]

    # SELECTORS (Centralized)
    SELECTORS = {
        "TWEET_INPUT": 'div[data-testid="tweetTextarea_0"]',
        "TWEET_BTN": '[data-testid="tweetButton"]',
        "TIMELINE_TWEET": 'article[data-testid="tweet"]',
        "REPLY_ICON": '[data-testid="reply"]',
        "FILE_INPUT": "input[type='file']",
        "USER_NAME": 'div[data-testid="User-Name"]',
        "USER_BIO": '[data-testid="UserDescription"]',
        "LINK_TO_TWEET": ".//a[contains(@href, '/status/')]",
        "HANDLE": ".//div[@data-testid='User-Name']//span[contains(text(), '@')]",
        "PROFILE_FOLLOWERS": "//a[contains(@href, '/followers')]//span",
        "PROFILE_TWEETS_HEADER": "//h2[@role='heading']/following-sibling::div"
    }

    SAFE_VISUALS = [
        "complex 3d rotating virus structure being scanned by blue laser, wireframe render",
        "futuristic circular hud interface displaying encrypted data streams, cyan glowing text",
        "microscopic view of digital pathogen cells, neon blue and green lighting, dark background",
        "cybernetic security shield protecting a digital core, geometric hexagon patterns, cold atmosphere",
        "abstract data visualization of a network node, floating holographic elements, dark mode ui",
        "medical mri scan of digital code, vertical data rain, turquoise bioluminescence"
    ]

# --- 2. PROCESS MANAGER ---
class ProcessManager:
    @staticmethod
    def kill_stale_bot_processes():
        Logger.log("SYSTEM", "Cleaning up stale bot processes...")
        try:
            folder_name = os.path.basename(Config.PROFILE_PATH)
            cmd = f'wmic process where "name=\'brave.exe\' and CommandLine like \'%{folder_name}%\'" call terminate'
            if Config.BROWSER_TYPE == 'chrome':
                cmd = cmd.replace('brave.exe', 'chrome.exe')
            with open(os.devnull, 'w') as DEVNULL:
                subprocess.call(cmd, shell=True, stdout=DEVNULL, stderr=DEVNULL)
        except Exception: pass

# --- 3. VIRAL INTELLIGENCE ---
class ViralIntelligence:
    def __init__(self, db):
        self.db = db
        self.cg_url = "https://api.coingecko.com/api/v3"
        self.dex_url = "https://api.dexscreener.com/latest/dex"
        self.headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    def get_macro_pulse(self):
        try:
            data = requests.get(f"{self.cg_url}/simple/price?ids=bitcoin,ethereum,solana&vs_currencies=usd&include_24hr_change=true&include_market_cap=true", headers=self.headers, timeout=5).json()
            g_data = requests.get(f"{self.cg_url}/global", headers=self.headers, timeout=5).json()['data']
            
            btc_d = g_data['market_cap_percentage']['btc']
            total3 = g_data['total_market_cap']['usd'] - data['bitcoin']['usd_market_cap'] - data['ethereum']['usd_market_cap']
            sol_change = data['solana']['usd_24h_change']

            snapshot = {
                "btc_price": data['bitcoin']['usd'],
                "sol_price": data['solana']['usd'],
                "btc_d": btc_d,
                "total3": total3,
                "timestamp": time.time()
            }
            self.db.save_market_snapshot(snapshot)
            
            trend = "STABLE"
            if sol_change < Config.DUMP_THRESHOLD: trend = "CRASH_IMMINENT"
            elif sol_change > Config.PUMP_THRESHOLD: trend = "PARABOLIC_PUMP"
            
            return f"STATUS: {trend}. SOL: ${snapshot['sol_price']:.2f} ({sol_change:.1f}%)."
        except: return "MARKET DATA UNAVAILABLE"

    def analyze_token_security(self, query):
        """
        Sprawdza ticker lub adres kontraktu w DexScreenerze.
        Zwraca raport ryzyka.
        """
        try:
            # Szukamy po tickerze (np. UBU) lub adresie
            url = f"{self.dex_url}/search?q={query}"
            res = requests.get(url, headers=self.headers, timeout=5)
            if res.status_code != 200: return {"risk": "UNKNOWN", "details": "API Error"}
            
            pairs = res.json().get('pairs', [])
            if not pairs: return {"risk": "UNKNOWN", "details": "Token not found on DEX"}

            # Bierzemy parę z największą płynnością na Solana
            best_pair = None
            for p in pairs:
                if p.get('chainId') == 'solana':
                    best_pair = p
                    break
            
            if not best_pair: return {"risk": "SAFE", "details": "Not on Solana chain"}

            # ANALIZA RYZYKA (Holistyczna)
            liquidity = float(best_pair.get('liquidity', {}).get('usd', 0))
            fdv = float(best_pair.get('fdv', 0))
            created_at = best_pair.get('pairCreatedAt', 0) # timestamp
            age_hours = (time.time() * 1000 - created_at) / (1000 * 3600)
            
            risk_score = 0
            reasons = []

            # 1. Płynność
            if liquidity < 1000: 
                risk_score += 5
                reasons.append("EXTREME LOW LIQUIDITY (<$1k)")
            elif liquidity < 5000:
                risk_score += 2
            
            # 2. FDV vs Liquidity (Honey Pot ratio)
            if fdv > 0 and (liquidity / fdv) < 0.01: # Mniej niż 1% płynności
                risk_score += 4
                reasons.append(f"Liquidity is only {((liquidity/fdv)*100):.2f}% of FDV (Rug risk)")

            # 3. Wiek
            if age_hours < 1.0: 
                risk_score += 2
                reasons.append("Token created < 1h ago")

            status = "SAFE"
            if risk_score >= 5: status = "CRITICAL_SCAM"
            elif risk_score >= 3: status = "SUSPICIOUS"

            return {
                "risk": status,
                "symbol": best_pair['baseToken']['symbol'],
                "liquidity": liquidity,
                "age_hours": age_hours,
                "reason": ", ".join(reasons),
                "url": best_pair['url']
            }

        except Exception as e:
            return {"risk": "UNKNOWN", "details": str(e)}

    def scan_for_rugs(self):
        # (Tutaj pozostaje Twoja stara funkcja bez zmian)
        return []

# --- 4. VISUAL CORTEX ---
# --- 4. VISUAL CORTEX ---
class VisualCortex:
    def generate(self, ignored_context=None):
        """
        Generuje obraz.
        UWAGA: Argument 'ignored_context' jest celowo ignorowany, aby treść tweeta (np. słowo 'scam')
        nie zanieczyściła promptu graficznego kolorem czerwonym.
        """
        if not Config.GENERATE_IMAGES: return None
        Logger.log("VISUAL", "Synthesizing visual data...")
        try:
            # 1. Wybieramy losowy, bezpieczny szablon z Configa
            base_prompt = random.choice(Config.SAFE_VISUALS)
            
            # 2. Sklejamy to ze stylem
            full_prompt = f"{base_prompt}, {Config.IMAGE_STYLE}"
            
            # 3. URL Encode
            safe_prompt = full_prompt.replace(" ", "%20").replace("#", "")
            
            # 4. Generowanie SEED
            seed = random.randint(100000, 999999)
            
            # 5. URL - Dodajemy parametry 'enhance=false' (ważne!)
            # enhance=true w Pollinations często dodaje "filmowy look" który wprowadza ciepłe kolory.
            # nologo=true - próba usunięcia watermarku (zależy od obciążenia serwisu)
            url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1024&height=1024&model=flux&nologo=true&enhance=false&seed={seed}"
            
            res = requests.get(url, timeout=20)
            if res.status_code == 200:
                path = os.path.join(script_dir, f"visual_{seed}.jpg")
                with open(path, 'wb') as f: f.write(res.content)
                return path
        except Exception as e:
            Logger.error(f"Image Gen Failed: {e}")
        return None

# --- 5. DATABASE ---
class DatabaseManager:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._init_tables()
        self._init_vector()
        self._init_backup_file()

    def _init_tables(self):
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS engagements 
                             (target_id TEXT PRIMARY KEY, timestamp TEXT, type TEXT, content TEXT, user_handle TEXT)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS partners 
                             (screen_name TEXT PRIMARY KEY, status TEXT, score INTEGER, notes TEXT, strategy TEXT, last_check TEXT)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS market_history 
                             (timestamp REAL, btc_price REAL, sol_price REAL, btc_d REAL, total3 REAL)''')
        self.conn.commit()
    
    def _init_backup_file(self):
        if not os.path.exists(ID_BACKUP_FILE):
            with open(ID_BACKUP_FILE, "w") as f: f.write("")

    def _init_vector(self):
        try:
            self.chroma = chromadb.PersistentClient(path="pathogen_vector_store")
            self.memory = self.chroma.get_or_create_collection(name="pathogen_memories")
        except: 
            self.memory = None
            Logger.log("SYSTEM", "Vector DB unavailable. Running simple mode.")

    def exists(self, tid):
        # Sprawdzanie pliku tekstowego (szybsze i trwalsze przy resetach bazy)
        try:
            with open(ID_BACKUP_FILE, "r") as f:
                if tid in f.read(): return True
        except: pass
        self.cursor.execute("SELECT 1 FROM engagements WHERE target_id=?", (tid,))
        return self.cursor.fetchone() is not None

    def save_interaction(self, tid, user, content, type_name):
        try:
            self.cursor.execute("INSERT OR IGNORE INTO engagements VALUES (?, ?, ?, ?, ?)", 
                            (tid, datetime.now().isoformat(), type_name, content, user))
            self.conn.commit()
            with open(ID_BACKUP_FILE, "a") as f: f.write(f"{tid}\n")
            if type_name == "BROADCAST":
                with open("last_post_backup.txt", "w") as f: f.write(datetime.now().isoformat())
            if self.memory and content:
                self.memory.add(documents=[content], metadatas=[{"type": type_name, "user": user}], ids=[f"{tid}_{int(time.time())}"])
        except: pass
    
    def get_relevant_context(self, query_text):
        if not self.memory: return ""
        try:
            results = self.memory.query(query_texts=[query_text], n_results=2)
            return "\n".join(results['documents'][0]) if results['documents'] else ""
        except: return ""

    def save_market_snapshot(self, data):
        self.cursor.execute("INSERT INTO market_history VALUES (?, ?, ?, ?, ?)",
                           (data['timestamp'], data['btc_price'], data['sol_price'], data['btc_d'], data['total3']))
        self.conn.commit()

    def get_market_snapshot(self, hours_ago=24):
        target_time = time.time() - (hours_ago * 3600)
        self.cursor.execute("SELECT * FROM market_history WHERE timestamp < ? ORDER BY timestamp DESC LIMIT 1", (target_time,))
        row = self.cursor.fetchone()
        if row: return {"timestamp": row[0], "btc_price": row[1], "sol_price": row[2], "btc_d": row[3], "total3": row[4]}
        return None

    def get_last_post_time(self):
        self.cursor.execute("SELECT timestamp FROM engagements WHERE type='BROADCAST' ORDER BY timestamp DESC LIMIT 1")
        res = self.cursor.fetchone()
        db_time = datetime.fromisoformat(res[0]) if res else None
        
        file_time = None
        if os.path.exists("last_post_backup.txt"):
            try:
                with open("last_post_backup.txt", "r") as f:
                    file_time = datetime.fromisoformat(f.read().strip())
            except: pass
        
        if db_time and file_time: return max(db_time, file_time)
        return db_time or file_time

    def get_partner_to_vet(self):
        self.cursor.execute("SELECT screen_name FROM partners WHERE status='DISCOVERED' ORDER BY RANDOM() LIMIT 1")
        return self.cursor.fetchone()

# --- 6. BROWSER ENGINE ---
class BrowserEngine:
    def __init__(self):
        self.driver = self._setup()
        self.wait = WebDriverWait(self.driver, 15)
        atexit.register(self.quit)

    def _setup(self):
        Logger.log("SYSTEM", f"Launching Terminal: {Config.BROWSER_TYPE.upper()}...")
        options = webdriver.ChromeOptions()
        if Config.BROWSER_TYPE == 'brave':
            if os.path.exists(Config.BROWSER_EXECUTABLE_PATH):
                options.binary_location = Config.BROWSER_EXECUTABLE_PATH
            else: sys.exit(1)

        options.add_argument(f"--user-data-dir={Config.PROFILE_PATH}")
        options.add_argument(f"--profile-directory={Config.BROWSER_PROFILE}")
        options.add_argument("--log-level=3")
        options.add_argument("--silent")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-blink-features=AutomationControlled")

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
        try:
            if selector.startswith("//"):
                return WebDriverWait(self.driver, timeout).until(EC.presence_of_element_located((By.XPATH, selector)))
            return WebDriverWait(self.driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
        except: return None

    def wait_clickable(self, selector, timeout=10):
        try:
            if selector.startswith("//"):
                return WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable((By.XPATH, selector)))
            return WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
        except: return None

    def type_human(self, element, text):
        try:
            self.click_safe(element)
            time.sleep(0.2)
            element.send_keys(text)
            time.sleep(0.5)
        except: pass

    def click_safe(self, element):
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", element)
            time.sleep(0.3)
            element.click()
        except: 
            self.driver.execute_script("arguments[0].click();", element)

    def upload_image(self, path):
        if not path or not os.path.exists(path): return
        try:
            # X ma input type=file, ale często ukryty. Wysyłamy do niego bezpośrednio.
            file_input = self.driver.find_element(By.CSS_SELECTOR, Config.SELECTORS["FILE_INPUT"])
            file_input.send_keys(os.path.abspath(path))
            time.sleep(2) 
        except Exception as e:
            Logger.error(f"Upload failed: {e}")
            
    def get_profile_stats(self, handle):
        # Wchodzi na profil i ocenia czy to konto kupione pod airdrop
        stats = {"followers": 0, "tweets": 0}
        try:
            self.driver.get(f"https://twitter.com/{handle.replace('@', '')}")
            time.sleep(3) 
            
            try:
                followers_el = self.driver.find_element(By.XPATH, Config.SELECTORS["PROFILE_FOLLOWERS"])
                # Parsowanie liczb "12.5K" -> 12500
                text = followers_el.text.upper()
                multiplier = 1
                if 'K' in text: multiplier = 1000
                elif 'M' in text: multiplier = 1000000
                stats["followers"] = float(re.sub(r"[^0-9.]", "", text)) * multiplier
            except: pass

            try:
                header_text = self.driver.find_element(By.XPATH, Config.SELECTORS["PROFILE_TWEETS_HEADER"]).text
                multiplier = 1
                if 'K' in header_text: multiplier = 1000
                stats["tweets"] = float(re.sub(r"[^0-9.]", "", header_text)) * multiplier
            except: pass
            
        except: pass
        return stats

# --- 7. AGENT BRAIN ---
class AgentBrain:
    def __init__(self, db):
        self.client = OpenAI(api_key=Config.OPENAI_API_KEY)
        self.db = db

    def _query(self, prompt, model=Config.MODEL_CHEAP, system_override=None):
        sys_msg = system_override if system_override else Config.SYSTEM_INSTRUCTIONS
        # Format JSON dla łatwego parsowania decyzji
        sys_msg += '\nRETURN JSON: { "decision": "REPLY" or "TERMINATE", "content": "tweet text", "thought": "analysis" }'
        
        try:
            res = self.client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": sys_msg}, {"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            return json.loads(res.choices[0].message.content)
        except Exception as e:
            return {"decision": "SKIP", "content": None}

    def think_post(self, topic, market_context="Uncertain"):
        past = self.db.get_relevant_context(topic)
        prompt = Config.PROMPT_TEMPLATE.format(market_context=market_context, topic=topic) + f"\nMemory: {past}"
        return self._query(prompt, model=Config.MODEL_SMART) # Smart for broadcasts

    def think_reply(self, thread_context, context="Unknown"):
        prompt = f"""
        THREAD HISTORY:
        {thread_context}
        
        CONTEXT: {context}
        
        TASK: Reply to the last user. 
        - If they ask about the project -> Explain & Tag.
        - If they are a victim -> Comfort.
        - If nonsense -> TERMINATE.
        """
        return self._query(prompt, model=Config.MODEL_CHEAP) # Cheap for replies
    
    def think_vetting(self, data):
        prompt = f"Analyze bio: {data}. Rate 1-10 ally potential."
        return self._query(prompt, model=Config.MODEL_CHEAP)

    def think_warning(self, token_data):
        prompt = f"WARN about token ${token_data['symbol']}. Reason: {token_data['reason']}."
        return self._query(prompt, model=Config.MODEL_SMART)

    def think_scam_analysis(self, tweet_text, user_stats):
        # Specjalna logika dla modułu SCAM HUNT
        prompt = f"""
        TASK: Analyze tweet for SCAM/MALWARE.
        Tweet: "{tweet_text}"
        User Stats: {user_stats} (Followers/Tweets ratio suspect if high/low).
        
        INDICATORS: "Airdrop", "Claim", "Migration", "Validate", Urgency, Bad Grammar.
        
        OUTPUT JSON:
        {{
            "is_scam": true/false,
            "confidence": 0-100,
            "reply_text": "Short medical warning to victim (max 100 chars)",
            "broadcast_text": "Public alert about this user (max 200 chars)"
        }}
        """
        return self._query(prompt, model=Config.MODEL_CHEAP)

# --- 8. STRATEGY ENGINE ---
class StrategyEngine:
    def decide(self, db, market_status_text):
        if "CRASH" in market_status_text: return "MARKET_DIAGNOSTICS"
        
        last_post = db.get_last_post_time()
        can_post = True
        if last_post:
            diff = (datetime.now() - last_post).total_seconds() / 60
            if diff < Config.POST_COOLDOWN_MINUTES: can_post = False

        # USUNIĘTO: SCOUT_PARTNERS, VET_PARTNER
        weights = {
            "SCAM_HUNT": 40,          # Podniesiony priorytet
            "RUG_PATROL": 25,
            "CHECK_MENTIONS": 25,
            "MARKET_DIAGNOSTICS": 10,
            "BROADCAST": 50 if can_post else 0 
        }
        
        return random.choices(list(weights.keys()), weights=list(weights.values()))[0]

# --- 9. MAIN CONTROLLER ---
class PathogenAgent:
    def __init__(self):
        ProcessManager.kill_stale_bot_processes()
        self.db = DatabaseManager()
        self.market = ViralIntelligence(self.db)
        self.brain = AgentBrain(self.db)
        self.browser = BrowserEngine()
        self.visual = VisualCortex()
        self.strategy = StrategyEngine()
        self.driver = self.browser.driver
        self.last_market_status = "STABLE"

    def run(self):
        Logger.log("SYSTEM", f"PROTOCOL ONLINE. Project: {Config.PROJECT_NAME}")
        self.driver.get("https://twitter.com/home")
        try: self.browser.wait_for(Config.SELECTORS["TWEET_INPUT"], timeout=20)
        except: Logger.log("SYSTEM", "Login check...")
        
        while True:
            try:
                action = self.strategy.decide(self.db, self.last_market_status)
                Logger.log("SYSTEM", f"Engaging: {action}")

                if action == "SCAM_HUNT": self._scam_hunt()
                elif action == "RUG_PATROL": self._rug_patrol()
                elif action == "CHECK_MENTIONS": self._check_mentions()
                elif action == "MARKET_DIAGNOSTICS": self._market_diagnostics()
                elif action == "SCOUT_PARTNERS": self._scout_partners()
                elif action == "VET_PARTNER": self._vet_partner()
                elif action == "BROADCAST": self._broadcast()

                sleep_time = random.randint(Config.MIN_SLEEP, Config.MAX_SLEEP)
                Logger.timer(sleep_time)

            except KeyboardInterrupt:
                break
            except Exception as e:
                Logger.error(f"Loop Error: {e}")
                time.sleep(60)

    def _scam_hunt(self):
        # MODUŁ: Aktywne Polowanie (Naprawiony Styl)
        keyword = random.choice(Config.SCAM_KEYWORDS)
        Logger.log("SCAM", f"Hunting for pathogen: '{keyword}'")
        
        self.driver.get(f"https://twitter.com/search?q={keyword}&src=typed_query&f=live")
        try:
            self.browser.wait_for(Config.SELECTORS["TIMELINE_TWEET"])
            raw_tweets = self.driver.find_elements(By.CSS_SELECTOR, Config.SELECTORS["TIMELINE_TWEET"])
        except: return

        candidates = []
        for t in raw_tweets[:5]:
            try:
                link = t.find_element(By.XPATH, Config.SELECTORS["LINK_TO_TWEET"]).get_attribute('href')
                text = t.text
                candidates.append({"url": link, "text_preview": text})
            except: continue

        for item in candidates:
            try:
                tid = item['url'].split('/')[-1]
                if self.db.exists(tid): continue

                if not any(x in item['text_preview'].lower() for x in ["click", "link", "official", "claim", "mint", "airdrop"]):
                    continue

                self.driver.get(item['url'])
                self.browser.wait_for(Config.SELECTORS["TWEET_INPUT"])
                
                try:
                    article = self.driver.find_element(By.TAG_NAME, "article")
                    full_text = article.text
                    handle = "@" + item['url'].split('/')[3]
                except: continue

                stats = self.browser.get_profile_stats(handle)
                self.driver.get(item['url']) 
                self.browser.wait_for(Config.SELECTORS["TWEET_INPUT"])

                is_sus_ratio = False
                if stats['followers'] > 2000 and stats['tweets'] < 50: is_sus_ratio = True
                if stats['followers'] > 10000 and stats['tweets'] < 200: is_sus_ratio = True

                token_report = {"risk": "UNKNOWN", "reason": "No ticker"}
                ticker_match = re.search(r'\$([a-zA-Z]{2,10})', full_text)
                if ticker_match:
                    ticker = ticker_match.group(1)
                    token_report = self.market.analyze_token_security(ticker)

                evidence = f"User: {stats['followers']} followers, {stats['tweets']} tweets. Ratio Sus: {is_sus_ratio}. Token Risk: {token_report['risk']}."
                analysis = self.brain.think_scam_analysis(full_text, evidence)

                # TRIGGER
                if analysis.get('is_scam', False) and (token_report['risk'] == "CRITICAL_SCAM" or is_sus_ratio or analysis.get('confidence', 0) > 90):
                    
                    Logger.log("SCAM", f"CONFIRMED THREAT: {handle}")
                    
                    # 1. Reply
                    self._interact(article, f"⚠️ {analysis['reply_text']}")
                    self.db.save_interaction(tid, handle, "SCAM_WARNING", "SCAM_REPLY")
                    
                    # 2. Broadcast (POPRAWIONY TEKST I OBRAZ)
                    # Skracamy tekst, żeby zmieścił się w limicie
                    alert_text = f"PATHOGEN DETECTED.\nVECTOR: {handle}\nTHREAT: {analysis['broadcast_text'][:100]}\nDIAGNOSIS: {token_report.get('risk', 'MALWARE')}.\nProtocol: ISOLATION."
                    
                    # Generowanie obrazka: Używamy słów kluczowych dla Twojego stylu
                    # Zamiast "Warning" dajemy "Analysis/Hud/Shield"
                    img = self.visual.generate()
                    self._post_tweet(alert_text, img)
                    return 
                else:
                    self.db.save_interaction(tid, handle, "CLEAN", "SCAM_CHECK_PASSED")

            except Exception as e:
                Logger.error(f"Scam Check Failed: {e}")
                continue

    def _market_diagnostics(self):
        report = self.market.get_macro_pulse()
        self.last_market_status = report
        Logger.log("MARKET", report)
        
        potential_rugs = self.market.scan_for_rugs()
        if potential_rugs:
            target = potential_rugs[0]
            # Sprawdź czy już o tym nie pisaliśmy
            self.driver.get(f"https://twitter.com/search?q=${target['symbol']}&src=typed_query&f=live")
            try: self.browser.wait_for(Config.SELECTORS["TIMELINE_TWEET"])
            except: pass
            
            res = self.brain.think_warning(target)
            if res.get('content'):
                self._post_tweet(f"{res['content']}\n\nProof: {target['chart']}")
                self.db.save_interaction(str(time.time()), "SELF", res['content'], "RUG_WARNING")

    def _rug_patrol(self):
        query = random.choice(Config.RUG_QUERIES)
        self.driver.get(f"https://twitter.com/search?q={query}&src=typed_query&f=live")
        try:
            self.browser.wait_for(Config.SELECTORS["TIMELINE_TWEET"])
            tweets = self.driver.find_elements(By.CSS_SELECTOR, Config.SELECTORS["TIMELINE_TWEET"])
        except: return
        
        for tweet in tweets[:8]:
            try:
                link_el = tweet.find_element(By.XPATH, Config.SELECTORS["LINK_TO_TWEET"])
                tid = link_el.get_attribute('href').split('/')[-1]
                if self.db.exists(tid): continue
                
                user = tweet.text.split('\n')[0]
                text = tweet.text
                if "bot" in text.lower(): continue

                # Tu nie trzeba wchodzić w wątek, bo zazwyczaj to pojedynczy krzyk o pomoc
                res = self.brain.think_reply(text, "User needs help")
                if res.get('decision') == 'REPLY':
                    self._interact(tweet, res['content'])
                    self.db.save_interaction(tid, user, res['content'], "RUG_RESCUE")
                    return
                else:
                    self.db.save_interaction(tid, user, "IGNORE", "SKIPPED")
            except: continue

    def _check_mentions(self):
        Logger.log("ACTION", "Checking Mentions (Deep Context Mode)...")
        self.driver.get("https://twitter.com/notifications/mentions")
        try:
            self.browser.wait_for(Config.SELECTORS["TIMELINE_TWEET"])
            # Zbieramy linki, żeby nie zgubić elementów przy nawigacji
            links = []
            elements = self.driver.find_elements(By.CSS_SELECTOR, Config.SELECTORS["TIMELINE_TWEET"])
            for el in elements[:5]:
                try:
                    href = el.find_element(By.XPATH, Config.SELECTORS["LINK_TO_TWEET"]).get_attribute('href')
                    links.append(href)
                except: continue
        except: return

        for link in links:
            try:
                tid = link.split('/')[-1]
                if self.db.exists(tid): continue
                
                # 1. WCHODZIMY W WĄTEK
                self.driver.get(link)
                self.browser.wait_for(Config.SELECTORS["TWEET_INPUT"])
                
                # 2. Czytamy historię rozmowy
                thread_context = ""
                articles = self.driver.find_elements(By.TAG_NAME, "article")
                for art in articles:
                    thread_context += art.text + "\n---\n"
                
                # 3. Decyzja z pełnym kontekstem
                res = self.brain.think_reply(thread_context, "Direct Mention in Thread")
                
                if res.get('decision') == 'REPLY':
                    # Jesteśmy w wątku, pole tekstowe jest dostępne
                    box = self.browser.wait_for(Config.SELECTORS["TWEET_INPUT"])
                    self.browser.type_human(box, res['content'])
                    btn = self.browser.wait_clickable(Config.SELECTORS["TWEET_BTN"])
                    self.browser.click_safe(btn)
                    
                    self.db.save_interaction(tid, "MENTION", res['content'], "MENTION_REPLY")
                    Logger.log("ACTION", "Replied within thread.")
                    time.sleep(5) # Odczekaj chwilę po wysłaniu
                else:
                    self.db.save_interaction(tid, "MENTION", "IGNORE", "TERMINATED")
                    
            except Exception as e:
                Logger.error(f"Mention error: {e}")
                continue

    def _broadcast(self):
        topic = random.choice(["Wallet Security", "Rug Pull Signs", "Smart Contract Hygiene"])
        Logger.log("ACTION", f"Broadcasting: {topic}")
        res = self.brain.think_post(topic, market_context=self.last_market_status)
        if res.get('content'):
            img_path = self.visual.generate(res['content'])
            self._post_tweet(res['content'], img_path)
            self.db.save_interaction(str(time.time()), "SELF", res['content'], "BROADCAST")

    def _scout_partners(self):
        self.driver.get("https://twitter.com/home")
        try: self.browser.wait_for(Config.SELECTORS["TIMELINE_TWEET"])
        except: return
        self.browser.scroll_search()
        tweets = self.driver.find_elements(By.CSS_SELECTOR, Config.SELECTORS["TIMELINE_TWEET"])
        for tweet in tweets[:4]:
            try:
                handle = tweet.find_element(By.XPATH, Config.SELECTORS["HANDLE"]).text
                if self.db.cursor.execute("SELECT 1 FROM partners WHERE screen_name=?", (handle,)).fetchone(): continue
                self.db.cursor.execute("INSERT INTO partners VALUES (?, ?, ?, ?, ?, ?)", 
                                     (handle, "DISCOVERED", 0, "", "", datetime.now().isoformat()))
                self.db.conn.commit()
            except: continue

    def _vet_partner(self):
        target = self.db.get_partner_to_vet()
        if not target: return
        handle = target[0]
        try:
            self.driver.get(f"https://twitter.com/{handle[1:]}")
            self.browser.wait_for(Config.SELECTORS["USER_BIO"])
            bio = self.driver.find_element(By.CSS_SELECTOR, Config.SELECTORS["USER_BIO"]).text
            res = self.brain.think_vetting(bio)
            try: score = int(res.get('content', '0').strip())
            except: score = 0
            status = "VETTED" if score > 6 else "IGNORE"
            self.db.cursor.execute("UPDATE partners SET status=?, score=? WHERE screen_name=?", (status, score, handle))
            self.db.conn.commit()
        except: 
            self.db.cursor.execute("UPDATE partners SET status='FAILED' WHERE screen_name=?", (handle,))
            self.db.conn.commit()

    def _post_tweet(self, text, img_path=None):
        """
        Naprawiona funkcja postowania.
        Kolejność: Tekst -> Czekaj -> Obrazek -> Tweet.
        """
        if not text: return
        Logger.log("ACTION", "Navigating to Compose...")
        self.driver.get("https://twitter.com/compose/tweet")
        
        try:
            # 1. Wpisz tekst
            box = self.browser.wait_for(Config.SELECTORS["TWEET_INPUT"])
            self.browser.type_human(box, text)
            Logger.log("ACTION", "Text entered.")
            
            # 2. Upload obrazka (jeśli jest)
            if img_path and os.path.exists(img_path):
                Logger.log("ACTION", "Uploading visual...")
                self.browser.upload_image(img_path)
                time.sleep(3) # Ważne: Czekamy aż obrazek się przetworzy na X
            
            # 3. Sprawdź czy przycisk jest aktywny i kliknij
            btn = self.browser.wait_clickable(Config.SELECTORS["TWEET_BTN"])
            self.browser.click_safe(btn)
            Logger.log("ACTION", "Tweet sent successfully.")
            
        except Exception as e:
            Logger.error(f"Post failed: {e}")

    def _interact(self, element, text):
        try:
            reply_icon = element.find_element(By.CSS_SELECTOR, Config.SELECTORS["REPLY_ICON"])
            self.browser.click_safe(reply_icon)
            box = self.browser.wait_for(Config.SELECTORS["TWEET_INPUT"])
            self.browser.type_human(box, text)
            btn = self.browser.wait_clickable(Config.SELECTORS["TWEET_BTN"])
            self.browser.click_safe(btn)
        except: ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()

if __name__ == "__main__":
    agent = PathogenAgent()
    agent.run()