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
import urllib.parse  # <--- KLUCZOWY IMPORT DLA WYSZUKIWARKI
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
        "RESET": "\033[0m", "SCAM": "\033[41m", "GROWTH": "\033[93m",
        "SKIP": "\033[36m"
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
    # --- API & PROJECT ---
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    PROJECT_NAME = os.getenv('PROJECT_NAME', 'Pathogen Protocol')
    WEBSITE_URL = os.getenv('WEBSITE_URL')
    MY_HANDLE = os.getenv('MY_HANDLE')

    # --- BRANDING & TAGS ---
    _tags_raw = os.getenv('PROJECT_TAGS', "")
    PROJECT_TAGS = [t.strip() for t in _tags_raw.split(',') if t.strip()]

    # --- LORE & KNOWLEDGE ---
    LORE_KNOWLEDGE = os.getenv('LORE_KNOWLEDGE', 'You are an AI security agent.')
    
    # --- MODEL ECONOMY ---
    MODEL_SMART = os.getenv('MODEL_SMART', "gpt-4o")
    MODEL_CHEAP = os.getenv('MODEL_CHEAP', "gpt-4o-mini")
    
    # --- BROWSER SETTINGS ---
    BROWSER_TYPE = os.getenv('BROWSER_TYPE', 'chrome').lower()
    BROWSER_EXECUTABLE_PATH = os.getenv('BROWSER_EXECUTABLE_PATH')
    BROWSER_PROFILE = os.getenv('BROWSER_PROFILE', 'Default')
    PROFILE_PATH = os.path.join(script_dir, os.getenv('PROFILE_PATH', 'agent_profile'))

    # --- VISUALS & STYLE ---
    GENERATE_IMAGES = os.getenv('GENERATE_IMAGES', 'True').lower() == 'true'
    IMAGE_STYLE = os.getenv('IMAGE_STYLE', 'cyberpunk glitch style')

    VISUAL_ELEMENTS = {
        "SUBJECT": [
            "digital virus cell", "blockchain node structure", "encrypted data packet", 
            "cybernetic skull", "bio-hazard containment vial", "holographic DNA strand",
            "glitched security shield", "liquid data stream"
        ],
        "ACTION": [
            "mutating in real time", "breaking through firewall", "being scanned by laser",
            "dissolving into code", "pulsing with toxic energy", "locking down system"
        ],
        "STYLE_MODIFIER": [
            "macro photography", "wide angle hud view", "electron microscope style",
            "isometric 3d render", "abstract glitch art", "wireframe blueprint"
        ]
    }

    # --- STRATEGY TARGETS ---
    GROWTH_TARGETS = ["solana", "aeyakovenko", "zachxbt", "coindesk", "cz_binance", "VitalikButerin", "SolanaFloor", "punk6529"]
    SCAM_MONITOR_TARGETS = ["@Uniswap", "@Starknet", "@LayerZero_Labs", "@zerion", "@MetaMask", "@Opensea", "@TrustWallet"]

    # --- SCAM HUNTING & KEYWORDS ---
    _keywords_raw = os.getenv('SCAM_KEYWORDS')
    if _keywords_raw:
        SCAM_KEYWORDS = [k.strip() for k in _keywords_raw.split(',') if k.strip()]
    else:
        SCAM_KEYWORDS = ["claim airdrop", "official mint", "validate wallet", "connect wallet", "migration required", "distribution live", "snapshot taken"]

    # --- TIMING ---
    MIN_SLEEP = int(os.getenv('MIN_SLEEP_DURATION', 60))
    MAX_SLEEP = int(os.getenv('MAX_SLEEP_DURATION', 240))
    POST_COOLDOWN_MINUTES = int(os.getenv('POST_COOLDOWN_MINUTES', 120))
    
    # --- TECHNICAL SELECTORS ---
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

# --- 2. PROCESS MANAGER ---
class ProcessManager:
    @staticmethod
    def kill_stale_bot_processes():
        try:
            if Config.BROWSER_EXECUTABLE_PATH:
                process_name = os.path.basename(Config.BROWSER_EXECUTABLE_PATH)
            else:
                process_name = "chrome.exe"

            folder_name = os.path.basename(Config.PROFILE_PATH)
            Logger.log("SYSTEM", f"Cleaning up stale processes: {process_name}...")
            
            cmd = f'wmic process where "name=\'{process_name}\' and CommandLine like \'%{folder_name}%\'" call terminate'
            with open(os.devnull, 'w') as DEVNULL:
                subprocess.call(cmd, shell=True, stdout=DEVNULL, stderr=DEVNULL)
            time.sleep(2)
        except Exception: pass

# --- 3. VIRAL INTELLIGENCE ---
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
    def generate(self):
        if not Config.GENERATE_IMAGES: return None
        Logger.log("VISUAL", "Synthesizing visual data (Dynamic)...")
        try:
            subj = random.choice(Config.VISUAL_ELEMENTS["SUBJECT"])
            act = random.choice(Config.VISUAL_ELEMENTS["ACTION"])
            mod = random.choice(Config.VISUAL_ELEMENTS["STYLE_MODIFIER"])
            full_prompt = f"{subj} {act}, {mod}, {Config.IMAGE_STYLE}"
            Logger.log("VISUAL", f"Prompt: {subj} | {mod}")
            
            safe_prompt = full_prompt.replace(" ", "%20")
            seed = random.randint(1, 9999999)
            url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1024&height=768&model=flux&nologo=true&enhance=true&seed={seed}"
            
            res = requests.get(url, timeout=20)
            if res.status_code == 200:
                path = os.path.join(script_dir, "temp_visual.jpg")
                with open(path, 'wb') as f: f.write(res.content)
                return path
        except Exception as e:
            Logger.error(f"Visual gen failed: {e}")
        return None

# --- 5. DATABASE ---
class DatabaseManager:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._init_tables()
        self._init_vector()
        self._init_backup()

    def _init_tables(self):
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS engagements 
                             (target_id TEXT PRIMARY KEY, timestamp TEXT, type TEXT, content TEXT, user_handle TEXT)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS seen_content 
                             (content_hash TEXT PRIMARY KEY, timestamp TEXT)''')
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
        except Exception as e:
            Logger.error(f"Vector DB init failed: {e}")
            self.memory = None

    def exists(self, tid):
        # 1. Sprawdź plik tekstowy (backup)
        try:
            with open(ID_BACKUP_FILE, "r") as f:
                if tid in f.read(): return True
        except: pass
        
        # 2. Sprawdź bazę SQLite
        self.cursor.execute("SELECT 1 FROM engagements WHERE target_id=?", (tid,))
        return self.cursor.fetchone() is not None

    def is_content_seen(self, text):
        if not text: return False
        text_hash = str(hash(text[:100])) 
        self.cursor.execute("SELECT 1 FROM seen_content WHERE content_hash=?", (text_hash,))
        return self.cursor.fetchone() is not None

    def mark_as_seen(self, tid, text, action_type):
        try:
            ts = datetime.now().isoformat()
            self.cursor.execute("INSERT OR IGNORE INTO engagements VALUES (?, ?, ?, ?, ?)", 
                            (tid, ts, action_type, "PROCESSED", "SYSTEM"))
            if text:
                text_hash = str(hash(text[:100]))
                self.cursor.execute("INSERT OR IGNORE INTO seen_content VALUES (?, ?)", (text_hash, ts))
            
            self.conn.commit()
            with open(ID_BACKUP_FILE, "a") as f: f.write(f"{tid}\n")
        except Exception as e:
            Logger.error(f"DB Mark Error: {e}")

    def save_interaction(self, tid, user, content, type_name):
        try:
            ts = datetime.now().isoformat()
            self.cursor.execute("INSERT OR IGNORE INTO engagements VALUES (?, ?, ?, ?, ?)", 
                            (tid, ts, type_name, content, user))
            self.conn.commit()
            
            # Zawsze dodaj też do pliku backup, żeby exists() działało pewniej
            with open(ID_BACKUP_FILE, "a") as f: f.write(f"{tid}\n")

            if self.memory and content:
                self.memory.add(
                    documents=[content], 
                    metadatas=[{"type": type_name, "user": user}], 
                    ids=[f"{tid}_{int(time.time())}"]
                )
        except Exception as e:
            Logger.error(f"DB Save Interaction Error: {e}")
            
    def get_last_post_time(self):
        self.cursor.execute("SELECT timestamp FROM engagements WHERE user_handle='SELF' ORDER BY timestamp DESC LIMIT 1")
        res = self.cursor.fetchone()
        return datetime.fromisoformat(res[0]) if res else None
        
    def get_relevant_memory(self, query_text):
        if not self.memory: return ""
        try:
            results = self.memory.query(query_texts=[query_text], n_results=2)
            return "\n".join(results['documents'][0]) if results['documents'] else ""
        except: return ""

# --- 6. BROWSER ENGINE ---
class BrowserEngine:
    def __init__(self):
        self.driver = self._setup()
        self.wait = WebDriverWait(self.driver, 15)
        atexit.register(self.quit)

    def _setup(self):
        browser_name = os.path.basename(Config.BROWSER_EXECUTABLE_PATH) if Config.BROWSER_EXECUTABLE_PATH else "Chrome"
        Logger.log("SYSTEM", f"Launching Browser: {browser_name}...")
        
        options = webdriver.ChromeOptions()
        if Config.BROWSER_EXECUTABLE_PATH:
            options.binary_location = Config.BROWSER_EXECUTABLE_PATH

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
        except: self.driver.execute_script("arguments[0].click();", element)

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
            file_input = self.driver.find_element(By.XPATH, "//input[@type='file']")
            file_input.send_keys(os.path.abspath(file_path))
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
        except Exception as e:
            Logger.error(f"OpenAI Query Failed: {e}")
            return {}

    def analyze_situation(self, text, risk_data, market_context):
        # 1. System Prompt (Static First - Cache)
        static_instructions = """
        IDENTITY: AI Crypto Security Analyst.
        TASK: Classify crypto tweet risk based on provided data.
        
        RULES:
        1. IF Risk Score < 40 and text is generic -> IGNORE.
        2. IF Risk Score 40-75 -> INVESTIGATE (Ask short question).
        3. IF Risk Score > 75 -> WARNING (Generate alert).
        
        OUTPUT FORMAT (JSON):
        { "decision": "IGNORE/INVESTIGATE/WARNING", "reply_content": "text", "broadcast_content": "text" }
        """
        # 2. Dynamic Context (Late Binding)
        dynamic_context = f"""
        --- CURRENT DATA ---
        MARKET CONTEXT: {market_context}
        CALCULATED RISK SCORE: {risk_data.get('score', 0)}/100.
        """
        full_system_prompt = static_instructions + dynamic_context
        return self._query(full_system_prompt, f"Tweet to analyze: {text}", model=Config.MODEL_CHEAP)

    def generate_broadcast(self, topic, market_context):
        past_context = self.db.get_relevant_memory(topic)
        
        static_part = f"""
        {Config.LORE_KNOWLEDGE}
        
        IDENTITY: You are Dr. Pathogen.
        STYLE GUIDE:
        - Clinical, insightful, short sentences.
        - No emojis.
        - Must mention {Config.WEBSITE_URL}.
        - TAGS: {', '.join(Config.PROJECT_TAGS)}.
        
        OUTPUT FORMAT: JSON with key "content".
        """
        
        dynamic_part = f"""
        --- MISSION CONTEXT ---
        TOPIC: {topic}
        MARKET STATUS: {market_context}
        RELEVANT MEMORY: {past_context[:500]} 
        """
        
        full_system = static_part + dynamic_part
        return self._query(full_system, "Generate post now.", model=Config.MODEL_SMART)
        
    def generate_growth_reply(self, target_user, tweet_text, market_status):
        # 1. Czysty System Prompt (Cache-friendly)
        sys_prompt = f"""
        IDENTITY: Dr. Pathogen.
        GOAL: Write a short, witty reply to {target_user} to gain visibility.
        CONTEXT: Promoting '{Config.PROJECT_NAME}' (Anti-Rug tool).
        
        RULES:
        1. Be clinical/ominous but helpful.
        2. Max 1 sentence.
        3. NO HASHTAGS.
        4. OUTPUT JSON: {{ "reply_content": "Text here" }}
        """
        
        # 2. User Msg (Zmienne)
        user_msg = f"""
        MARKET STATUS: {market_status}
        TARGET TWEET: "{tweet_text}"
        Generate reply.
        """
        return self._query(sys_prompt, user_msg, model=Config.MODEL_CHEAP)

# --- 8. MAIN AGENT ---
class PathogenAgent:
    def __init__(self):
        ProcessManager.kill_stale_bot_processes()
        self.db = DatabaseManager()
        self.market = ViralIntelligence(self.db)
        self.brain = AgentBrain(self.db)
        self.browser = BrowserEngine()
        self.visual = VisualCortex()
        
    def run(self):
        Logger.log("SYSTEM", f"PROTOCOL ONLINE. Identity: {Config.MY_HANDLE}")
        self.browser.driver.get("https://twitter.com/home")
        
        if not self.browser.wait_for(Config.SELECTORS["TWEET_INPUT"], timeout=20):
            Logger.log("SYSTEM", "Please log in manually if needed.")
            self.browser.wait_for(Config.SELECTORS["TWEET_INPUT"], timeout=120)
            
        while True:
            try:
                market_status = self.market.get_market_sentiment()
                
                # Zbalansowany wybór strategii
                actions = ["SCAM_HUNT", "GROWTH_HACK", "MONITOR_REPLIES", "BROADCAST_EDU"]
                weights = [30, 35, 20, 15] 
                action = random.choices(actions, weights=weights)[0]
                
                last_post = self.db.get_last_post_time()
                cooldown_active = False
                if last_post:
                    minutes = (datetime.now() - last_post).total_seconds() / 60
                    if minutes < Config.POST_COOLDOWN_MINUTES:
                        cooldown_active = True

                if action.startswith("BROADCAST") and cooldown_active:
                    Logger.log("SKIP", f"Cooldown active ({int(minutes)}m). Switching to GROWTH_HACK.")
                    action = "GROWTH_HACK"

                Logger.log("STRATEGY", f"Executing: {action}")
                
                if action == "SCAM_HUNT": 
                    self._scam_hunt(market_status)
                elif action == "GROWTH_HACK": 
                    self._growth_hack(market_status)
                elif action == "MONITOR_REPLIES":
                    self._monitor_replies(market_status)
                elif "BROADCAST" in action: 
                    self._broadcast(action, market_status)

                sleep_time = random.randint(Config.MIN_SLEEP, Config.MAX_SLEEP)
                Logger.timer(sleep_time)

            except KeyboardInterrupt: 
                break
            except Exception as e:
                Logger.error(f"Main Loop Error: {e}")
                traceback.print_exc()
                time.sleep(60)

    # --- ACTION METHODS ---
    def _growth_hack(self, market_status):
        """Ulepszony: Sprawdza wiele tweetów, nie zacina się na pierwszym"""
        target = random.choice(Config.GROWTH_TARGETS)
        Logger.log("GROWTH", f"Invading territory of: @{target}")
        
        try:
            self.browser.driver.get(f"https://twitter.com/{target}")
            
            if not self.browser.wait_for(Config.SELECTORS["TIMELINE_TWEET"], timeout=10):
                Logger.log("GROWTH", "Target timeline unavailable/empty.")
                return

            # Pobierz 5 ostatnich tweetów
            tweets = self.browser.driver.find_elements(By.CSS_SELECTOR, Config.SELECTORS["TIMELINE_TWEET"])[:5]
            if not tweets: return
            
            for tweet in tweets:
                try:
                    # Pobierz ID
                    link_el = tweet.find_element(By.XPATH, Config.SELECTORS["LINK_TO_TWEET"])
                    tid = link_el.get_attribute('href').split('/')[-1]
                    
                    # KLUCZOWE: Sprawdź duplikat
                    if self.db.exists(tid):
                        continue # Już tu byłem, sprawdź następny w pętli
                    
                    # Jeśli nie byłem - działaj
                    Logger.log("GROWTH", f"New target found: {tid}")
                    tweet_text = tweet.text
                    
                    res = self.brain.generate_growth_reply(target, tweet_text, market_status)
                    reply_text = res.get('reply_content')
                    
                    if reply_text:
                        Logger.log("BRAIN", f"Growth Hack Reply: {reply_text}")
                        self._reply_to_tweet(tweet, reply_text)
                        # Zapisz, że zrobione
                        self.db.save_interaction(tid, target, reply_text, "GROWTH_HACK")
                    
                    return # Zrobione jedno zadanie, koniec na teraz
                
                except Exception:
                    continue # Błąd z tym tweetem? Spróbuj następny
            
            Logger.log("GROWTH", "All recent tweets on this profile are already infected.")

        except Exception as e:
            Logger.error(f"Growth Hack logic failed: {e}")

    def _scam_hunt(self, market_context, search_query=None):
        if not search_query:
            keyword = random.choice(Config.SCAM_KEYWORDS)
            Logger.log("PATROL", f"Searching for global vector: '{keyword}'")
            search_query = keyword

        # KLUCZOWA POPRAWKA: urllib.parse.quote()
        # To naprawia błąd z pustymi wynikami dla zapytań typu (to:X) ("A" OR "B")
        safe_query = urllib.parse.quote(search_query)

        self.browser.driver.get(f"https://twitter.com/search?q={safe_query}&src=typed_query&f=live")
        
        if not self.browser.wait_for(Config.SELECTORS["TIMELINE_TWEET"], timeout=10):
            Logger.log("PATROL", "No targets found for this query.")
            return

        found_tweets = self.browser.driver.find_elements(By.CSS_SELECTOR, Config.SELECTORS["TIMELINE_TWEET"])[:5]
        processed_count = 0
        
        for el in found_tweets:
            if processed_count >= 1: break
            try:
                link_el = el.find_element(By.XPATH, Config.SELECTORS["LINK_TO_TWEET"])
                tid = link_el.get_attribute('href').split('/')[-1]
                text = el.text

                # Check duplicates
                if self.db.exists(tid) or self.db.is_content_seen(text): continue
                
                # Check Python Filters (Free)
                risk_data = {"score": 0}
                if "$" in text:
                    ticker = re.search(r'\$([a-zA-Z]{2,8})', text)
                    if ticker: risk_data = self.market.analyze_token_risk(ticker.group(1))

                # Skip obvious low risk
                if risk_data.get('score', 0) < 30 and not any(k in text.lower() for k in ["hacked", "drain", "revoke"]):
                    self.db.mark_as_seen(tid, text, "LOW_RISK_IGNORE")
                    continue
                
                processed_count += 1
                # Check AI (Paid)
                analysis = self.brain.analyze_situation(text, risk_data, market_context)
                decision = analysis.get('decision', 'IGNORE')
                Logger.log("BRAIN", f"Risk: {risk_data.get('score', 0)} | Decision: {decision}")

                if decision == "WARNING":
                    alert_text = f"🚨 PATHOGEN DETECTED.\n\nRisk: {risk_data.get('score',0)}/100\n{analysis.get('broadcast_content')}\n\nProtocol: {Config.WEBSITE_URL}"
                    img = self.visual.generate()
                    self._post_new_tweet(alert_text, img)
                    self.db.mark_as_seen(tid, text, "SCAM_WARNING")
                    self.db.save_interaction(str(time.time()), "SELF", alert_text, "SCAM_BROADCAST")
                    return
                elif decision == "INVESTIGATE":
                    self._reply_to_tweet(el, analysis['reply_content'])
                    self.db.mark_as_seen(tid, text, "INVESTIGATED")
                    return
                else:
                    self.db.mark_as_seen(tid, text, "IGNORE")
            except Exception:
                continue

    def _monitor_replies(self, market_status):
        """Nowa strategia: Szuka w odpowiedziach do dużych kont"""
        target = random.choice(Config.SCAM_MONITOR_TARGETS)
        Logger.log("PATROL", f"Monitoring replies to high-value target: {target}")
        
        keywords_query = ' OR '.join([f'"{k}"' for k in Config.SCAM_KEYWORDS])
        search_query = f"(to:{target}) ({keywords_query})"
        
        self._scam_hunt(market_status, search_query=search_query)

    def _broadcast(self, type_name, market_context):
        topic = "Market Analysis" if "MARKET" in type_name else "DeFi Security"
        res = self.brain.generate_broadcast(topic, market_context)
        
        if res.get('content'):
            img_path = self.visual.generate()
            self._post_new_tweet(res['content'], img_path)
            self.db.save_interaction(str(time.time()), "SELF", res['content'], type_name)

    # --- BROWSER SUB-ACTIONS ---
    def _post_new_tweet(self, text, img_path=None):
        Logger.log("ACTION", "Navigating to Compose...")
        self.browser.driver.get("https://twitter.com/compose/tweet")
        
        box = self.browser.wait_for(Config.SELECTORS["TWEET_INPUT"], timeout=15)
        if not box:
            Logger.error("Compose modal failed to load.")
            return

        try:
            if img_path and os.path.exists(img_path):
                Logger.log("ACTION", "Uploading visual...")
                if self.browser.upload_file(img_path):
                    WebDriverWait(self.browser.driver, 30).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, '[aria-label="Remove media"]'))
                    )
                    Logger.log("ACTION", "Visual attached & verified.")
                    time.sleep(1)
            
            box = self.browser.wait_for(Config.SELECTORS["TWEET_INPUT"])
            self.browser.type_human(box, text)
            time.sleep(2)
            
            btn = self.browser.wait_clickable(Config.SELECTORS["TWEET_BTN"])
            if btn:
                # Obsługa wyszarzonego przycisku
                if btn.get_attribute("aria-disabled") == "true":
                    Logger.log("ACTION", "Tweet button is disabled, waiting a bit...")
                    time.sleep(3)
                
                if btn.get_attribute("aria-disabled") == "true":
                    Logger.error("Tweet button still disabled. Content might be invalid or too long.")
                    return

                self.browser.safe_click(btn)
                Logger.log("ACTION", "Tweet sent.")
                time.sleep(10)
            else:
                Logger.error("Tweet button not found or not clickable.")

        except Exception as e:
            Logger.error(f"Post failed: {e}")

    def _reply_to_tweet(self, tweet_element, text):
        try:
            reply_icon = tweet_element.find_element(By.CSS_SELECTOR, Config.SELECTORS["REPLY_ICON"])
            self.browser.safe_click(reply_icon)
            
            box = self.browser.wait_for(Config.SELECTORS["TWEET_INPUT"])
            if not box: return

            self.browser.type_human(box, text)
            
            btn = self.browser.wait_clickable(Config.SELECTORS["TWEET_BTN"])
            if btn:
                self.browser.safe_click(btn)
                Logger.log("ACTION", "Reply sent.")
                time.sleep(5)
        except:
            ActionChains(self.browser.driver).send_keys(Keys.ESCAPE).perform()

if __name__ == "__main__":
    agent = PathogenAgent()
    agent.run()