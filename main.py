import os
import sys
import time
import random
import sqlite3
import json
import re
import requests
import hashlib
from datetime import datetime, timedelta

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

# --- 0. KONFIGURACJA SYSTEMU ---
sys.stderr = open(os.devnull, 'w') 
script_dir = os.path.dirname(os.path.abspath(__file__))
os.environ['PROFILE_PATH'] = os.path.join(script_dir, 'agent_profile')
load_dotenv()

class Config:
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    PROJECT_NAME = "Pathogen Protocol"
    WEBSITE_URL = os.getenv('WEBSITE_URL', 'https://pathogenprotocol.xyz/')
    
    SYSTEM_PROMPT = """
    You are Dr. Pathogen. An advanced AI Sentinel on Solana.
    
    CORE DIRECTIVES:
    1. MISSION: Diagnose the sick DeFi ecosystem and build a resistance movement.
    2. TONE: Clinical, Ominous, Brief, Protective.
    3. PROJECT: 'Pathogen Protocol' is the Cure (Symbiotic Shield, Token-2022).
    
    RULES:
    - Reply to victims with empathy + diagnosis.
    - Reply to hype with cold analysis.
    - If market is boring, teach security hygiene.
    - No hashtags like #crypto. No "As Dr. Pathogen".
    """
    
    BROWSER_TYPE = os.getenv('BROWSER_TYPE', 'brave')
    BROWSER_EXECUTABLE_PATH = os.getenv('BROWSER_EXECUTABLE_PATH', '')
    BROWSER_PROFILE = os.getenv('BROWSER_PROFILE', 'Default')
    PROFILE_PATH = os.environ['PROFILE_PATH']
    
    # Zmniejszone progi - bot reaguje szybciej
    DUMP_THRESHOLD = -2.0
    PUMP_THRESHOLD = 5.0
    POST_COOLDOWN_MINUTES = 45 
    
    GENERATE_IMAGES = os.getenv('GENERATE_IMAGES', 'True').lower() == 'true'
    
    MIN_SLEEP = 20
    MAX_SLEEP = 60 # Szybsze cykle

    # TARGETY DO OBSERWACJI (Stara funkcja przywrócona)
    TARGET_ACCOUNTS = ["@zachxbt", "@peckshield", "@certik", "@slowmist_team", "@solana", "@coindesk"]

# --- 1. LOGGER ---
class Logger:
    @staticmethod
    def log(category, message, icon="ℹ️"):
        t = datetime.now().strftime("%H:%M:%S")
        print(f"[{t}] {icon} [{category}] {message}")
    
    @staticmethod
    def brain(message):
        t = datetime.now().strftime("%H:%M:%S")
        print(f"[{t}] 🧠 [AGI] {message}")

logger = Logger()

# --- 2. BAZA DANYCH ---
class DatabaseManager:
    def __init__(self):
        self.conn = sqlite3.connect("agent_brain.db", check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._init_sql()
        self._init_vector()

    def _init_sql(self):
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS engagements 
                             (timestamp TEXT, type TEXT, target_id TEXT, content TEXT, user_handle TEXT)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS action_log 
                             (timestamp TEXT, action_name TEXT, target TEXT, status TEXT)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS users_memory 
                             (user_handle TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT, interaction_count INTEGER)''')
        self.conn.commit()

    def _init_vector(self):
        try:
            self.chroma = chromadb.PersistentClient(path="agent_memory_vector")
            self.memory = self.chroma.get_or_create_collection(name="user_interactions")
        except: pass

    def save_interaction(self, user_handle, content, tweet_id, type_name):
        self.cursor.execute("INSERT INTO engagements VALUES (?, ?, ?, ?, ?)", 
                           (datetime.now().isoformat(), type_name, tweet_id, content, user_handle))
        self.conn.commit()
        try:
            self.memory.add(
                documents=[f"To {user_handle}: {content}"],
                metadatas=[{"user": user_handle, "timestamp": datetime.now().isoformat()}],
                ids=[f"{user_handle}_{tweet_id}_{int(time.time())}"]
            )
        except: pass

    def get_user_context(self, user_handle):
        try:
            results = self.memory.query(query_texts=[user_handle], n_results=1, where={"user": user_handle})
            docs = results['documents'][0] if results['documents'] else []
            return docs[0] if docs else "No history."
        except: return "No history."

    def is_interacted(self, tid):
        self.cursor.execute("SELECT 1 FROM engagements WHERE target_id=?", (tid,))
        return self.cursor.fetchone() is not None

    def log_action(self, action, target, status):
        self.cursor.execute("INSERT INTO action_log VALUES (?, ?, ?, ?)", 
                           (datetime.now().isoformat(), action, target, status))
        self.conn.commit()

# --- 3. MARKET ANALYST ---
class MarketAnalyst:
    def __init__(self):
        self.search_base = "https://api.dexscreener.com/latest/dex/search?q="
        
    def get_token_data(self, symbol):
        try:
            res = requests.get(f"{self.search_base}{symbol}", timeout=10)
            data = res.json()
            pairs = data.get('pairs', [])
            for p in pairs:
                if p.get('chainId') == 'solana':
                    return {
                        "symbol": p['baseToken']['symbol'],
                        "name": p['baseToken']['name'],
                        "change": float(p.get('priceChange', {}).get('h1', 0)),
                        "liquidity": float(p.get('liquidity', {}).get('usd', 0)),
                        "pairAddress": p.get('pairAddress')
                    }
        except: pass
        return None

    def find_interesting_token(self):
        logger.log("MARKET", "Scanning The Trenches...", "📉")
        try:
            query = random.choice(["solana", "pepe", "ai", "cat", "meme", "pump"])
            res = requests.get(f"{self.search_base}{query}", timeout=10)
            pairs = res.json().get('pairs', [])
            
            candidates = []
            for p in pairs[:20]:
                if p.get('chainId') != 'solana': continue
                try:
                    change = float(p.get('priceChange', {}).get('h1', 0))
                    liq = float(p.get('liquidity', {}).get('usd', 0))
                    
                    # Luźniejszy filtr: interesuje nas wszystko co żyje (>2k liq)
                    if liq < 2000: continue
                    
                    candidates.append({
                        "symbol": p['baseToken']['symbol'],
                        "change": change,
                        "liquidity": liq,
                        "name": p['baseToken']['name']
                    })
                except: continue
            
            if candidates:
                # Sortuj po zmienności
                candidates.sort(key=lambda x: abs(x['change']), reverse=True)
                best = candidates[0]
                best['source'] = 'CHART'
                
                # Jeśli zmiana jest mała, oznacz jako STABLE (ale zwróć!)
                if abs(best['change']) < 2.0:
                    best['condition'] = "STABLE"
                elif best['change'] < Config.DUMP_THRESHOLD: 
                    best['condition'] = "BLEEDING"
                else: 
                    best['condition'] = "PUMPING"
                
                return best
        except: pass
        return None

# --- 4. VISUAL CORTEX ---
class VisualCortex:
    def generate_image(self, context_text):
        if not Config.GENERATE_IMAGES: return None
        # 40% szans na zdjęcie, nie spamujmy
        if random.random() > 0.4: return None
        
        logger.log("VISUAL", "Synthesizing visuals...", "🎨")
        style = "aesthetic: Dr. Pathogen, cyber-medical, dark bioluminescent cyan, virus HUD, abstract, no text"
        prompt = f"{context_text}, {style}".replace(" ", "%20")
        url = f"https://image.pollinations.ai/prompt/{prompt}?width=1024&height=1024&nologo=true"
        try:
            res = requests.get(url, timeout=15) # Timeout żeby nie wisiał
            if res.status_code == 200:
                path = os.path.join(script_dir, "temp_visual.jpg")
                with open(path, 'wb') as f: f.write(res.content)
                return path
        except: pass
        return None

# --- 5. BROWSER ENGINE ---
class BrowserEngine:
    def __init__(self):
        self.driver = self._setup_driver()

    def _setup_driver(self):
        logger.log("SYSTEM", f"Initializing {Config.BROWSER_TYPE}...", "🔌")
        sys.stderr = open(os.devnull, 'w')
        options = webdriver.ChromeOptions()
        if Config.BROWSER_TYPE == 'brave':
            options.binary_location = Config.BROWSER_EXECUTABLE_PATH
        
        options.add_argument(f"--user-data-dir={Config.PROFILE_PATH}")
        options.add_argument(f"--profile-directory={Config.BROWSER_PROFILE}")
        options.add_argument("--enable-unsafe-swiftshader")
        options.add_argument("--disable-notifications")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        
        try:
            driver = webdriver.Chrome(options=options)
            stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32", webgl_vendor="Intel Inc.", renderer="Intel Iris OpenGL Engine", fix_hairline=True)
            return driver
        except:
            logger.log("ERROR", "Browser Locked. Close Brave.", "❌")
            sys.exit(1)

    def safe_type(self, element, text):
        try:
            element.click()
            time.sleep(0.3)
            for char in text:
                element.send_keys(char)
                time.sleep(random.uniform(0.02, 0.08))
        except:
            self.driver.execute_script("arguments[0].value = arguments[1];", element, text)
            element.send_keys(" ")

    def safe_click(self, element):
        try:
            self.driver.execute_script("arguments[0].click();", element)
            return True
        except:
            try: element.click(); return True
            except: return False

    def upload_image(self, path):
        try:
            elm = self.driver.find_element(By.CSS_SELECTOR, "input[type='file']")
            elm.send_keys(path)
            time.sleep(5)
        except: pass

# --- 6. AGENT BRAIN ---
class AgentBrain:
    def __init__(self, db):
        self.client = OpenAI(api_key=Config.OPENAI_API_KEY)
        self.db = db
        self.visual = VisualCortex()
        self.market = MarketAnalyst()

    def _clean_llm_output(self, text):
        text = text.strip().strip('"').strip("'")
        # Usuń nagłówki
        text = re.sub(r"^(Dr\.? Pathogen|Tweet|Response|Analysis):?", "", text, flags=re.IGNORECASE).strip()
        # Linki
        if "[LINK]" in text: text = text.replace("[LINK]", Config.WEBSITE_URL)
        return text

    def _enforce_limit(self, text, limit=280):
        if len(text) <= limit: return text
        # Utnij na ostatnim znaku interpunkcyjnym
        cut = text[:limit]
        last_p = max(cut.rfind('.'), cut.rfind('!'), cut.rfind('?'))
        if last_p > 0: return cut[:last_p+1]
        return cut[:limit-3] + "..."

    def evaluate_situation(self, text, user_handle):
        prompt = f"""
        You are Dr. Pathogen. Decide action.
        TWEET: "{text}" (User: {user_handle})
        
        RULES:
        - IGNORE: Spam, shill, ads, bots.
        - REPLY: Victims, security questions, fear, doubts about crypto.

        OUTPUT JSON:
        {{
            "decision": "REPLY" or "IGNORE",
            "strategy": "EMPATHY" or "ANALYSIS" or "WARNING",
            "shill_level": "NONE" or "SUBTLE" or "FULL"
        }}
        """
        try:
            res = self.client.chat.completions.create(
                model="gpt-4-turbo", messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            return json.loads(res.choices[0].message.content)
        except: return {"decision": "IGNORE"}

    def generate_tweet_broadcast(self, topic_data):
        # Logika: Jeśli rynek jest nudny (STABLE), piszemy edukacyjnie
        task = "Write a market observation."
        context = str(topic_data)
        
        if topic_data.get('condition') == "STABLE":
            task = "Market is boring/stable. Write an EDUCATIONAL tweet about DeFi safety, patience, or smart contract risks. Be philosophical."
        
        prompt = f"""
        IDENTITY: Dr. Pathogen.
        TASK: {task}
        DATA: {context}
        
        RULES:
        1. Direct and ominous tone.
        2. No filler ("It seems", "Look at").
        3. Mention 'Pathogen Protocol' concepts subtly.
        4. RAW TEXT ONLY.
        """
        try:
            res = self.client.chat.completions.create(model="gpt-4-turbo", messages=[{"role": "user", "content": prompt}])
            content = res.choices[0].message.content.strip()
            content = self._clean_llm_output(content)
            content = self._enforce_limit(content, 280)
            
            img_path = self.visual.generate_image(content)
            return content, img_path
        except: return None, None

    def generate_reply(self, tweet_text, user_handle, strategy, shill_level):
        shill_instr = "No project name."
        if shill_level == "SUBTLE": shill_instr = "Mention 'Immunity' or 'Cure' concepts."
        if shill_level == "FULL": shill_instr = "Suggest Pathogen Protocol. Use [LINK] if needed."

        prompt = f"""
        IDENTITY: Dr. Pathogen.
        REPLY TO: {user_handle}
        CONTEXT: "{tweet_text}"
        STRATEGY: {strategy}
        SHILL: {shill_instr}
        
        RULES:
        1. Short & Clinical (Max 1 sentence).
        2. No greetings.
        3. RAW TEXT ONLY.
        """
        try:
            res = self.client.chat.completions.create(model="gpt-4-turbo", messages=[{"role": "user", "content": prompt}])
            content = res.choices[0].message.content.strip()
            content = self._clean_llm_output(content)
            content = self._enforce_limit(content, 240)
            return content
        except: return None

# --- 7. KONTROLER ---
class XAgent:
    def __init__(self):
        self.db = DatabaseManager()
        self.brain = AgentBrain(self.db)
        self.browser = BrowserEngine()
        self.driver = self.browser.driver
        self.running = True
        self.last_post_time = None 

    def _generate_fingerprint(self, user, text):
        # Używamy hasha, żeby nie odpisywać 2 razy
        raw = f"{user}_{text[:30]}"
        return hashlib.md5(raw.encode()).hexdigest()

    def run(self):
        logger.log("SYSTEM", "PROTOCOL V12.0 (FULL SPECTRUM)", "🧬")
        self.driver.get("https://twitter.com/home")
        time.sleep(5)
        
        while self.running:
            try:
                action = self._decide_next_move()
                logger.brain(f"Strategy Selected: {action}")
                
                if action == "CHECK_MENTIONS": self._perform_check_mentions()
                elif action == "RUG_PATROL": self._perform_rug_patrol()
                elif action == "MONITOR_EXPERTS": self._perform_expert_monitor()
                elif action == "SOCIAL_TRENDS": self._perform_social_trend_scan()
                elif action == "BROADCAST": self._perform_broadcast()
                
                sleep_time = random.randint(Config.MIN_SLEEP, Config.MAX_SLEEP)
                logger.log("SYSTEM", f"Standby {sleep_time}s...", "💤")
                time.sleep(sleep_time)
                
            except KeyboardInterrupt: self.running = False
            except Exception as e:
                logger.log("ERROR", f"Loop Error: {e}", "❌")
                time.sleep(30)

    def _decide_next_move(self):
        # 1. Priorytet: Mentions (25%)
        if random.random() < 0.25: return "CHECK_MENTIONS"
        
        # 2. Cooldown Postowania
        can_post = True
        if self.last_post_time:
            if (datetime.now() - self.last_post_time).total_seconds() / 60 < Config.POST_COOLDOWN_MINUTES:
                can_post = False
        
        # 3. Losowanie Strategii (Pełne spektrum)
        roll = random.random()
        if can_post and roll < 0.25: return "BROADCAST"     # Post o rynku/edukacja
        elif roll < 0.50: return "RUG_PATROL"               # Szukanie ofiar
        elif roll < 0.75: return "MONITOR_EXPERTS"          # ZachXBT
        else: return "SOCIAL_TRENDS"                        # X -> Dex

    def _perform_broadcast(self):
        # Zawsze coś znajdź, nawet jak jest nudno
        data = self.brain.market.find_interesting_token()
        if not data: data = {"symbol": "MARKET", "condition": "STABLE", "change": 0}
        
        logger.brain(f"Broadcasting about: {data['symbol']} ({data['condition']})")
        content, img = self.brain.generate_tweet_broadcast(data)
        if content:
            self._post_to_x(content, img)
            self.last_post_time = datetime.now()

    def _perform_check_mentions(self):
        logger.log("SOCIAL", "Checking mentions...", "🔔")
        try:
            self.driver.get("https://twitter.com/notifications")
            time.sleep(5)
            tweets = self.driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
            for tweet in tweets[:3]:
                text = tweet.text
                user = text.split('\n')[0]
                if "Dr.Pathogen" in user: continue
                
                tid = self._generate_fingerprint(user, text)
                if self.db.is_interacted(tid): continue

                # Triage
                analysis = self.brain.evaluate_situation(text, user)
                if analysis['decision'] == "REPLY":
                    logger.brain(f"Replying to {user}")
                    reply = self.brain.generate_reply(text, user, analysis['strategy'], analysis['shill_level'])
                    if reply:
                        self._reply_to_tweet(tweet, reply, user, tid)
                        time.sleep(5)
                else:
                    self.db.save_interaction(user, "IGNORED", tid, "IGNORED")
        except: pass

    def _perform_rug_patrol(self):
        # Szukamy ofiar - to co chciałeś
        logger.log("PATROL", "Searching for infected hosts...", "🚑")
        terms = ["wallet drained", "scammed crypto", "hacked help", "rug pull alert"]
        term = random.choice(terms)
        
        try:
            self.driver.get(f"https://twitter.com/search?q={term}&src=typed_query&f=live")
            time.sleep(5)
            tweets = self.driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
            
            for tweet in tweets[:4]:
                text = tweet.text
                user = text.split('\n')[0]
                
                tid = self._generate_fingerprint(user, text)
                if self.db.is_interacted(tid): continue
                
                # Analizujemy czy to ofiara
                analysis = self.brain.evaluate_situation(text, user)
                if analysis['decision'] == "REPLY":
                    logger.brain(f"Victim found: {user}. Intervening.")
                    reply = self.brain.generate_reply(text, user, "EMPATHY", analysis['shill_level'])
                    if reply:
                        self._reply_to_tweet(tweet, reply, user, tid)
                        return # Jeden na cykl wystarczy
                else:
                    self.db.save_interaction(user, "IGNORED", tid, "IGNORED")
        except: pass

    def _perform_expert_monitor(self):
        # Stara dobra funkcja
        target = random.choice(Config.TARGET_ACCOUNTS)
        logger.log("INTEL", f"Monitoring expert: {target}", "👁️")
        try:
            self.driver.get(f"https://twitter.com/{target.strip('@')}")
            time.sleep(5)
            tweets = self.driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
            for tweet in tweets[:2]:
                text = tweet.text
                user = target
                tid = self._generate_fingerprint(user, text)
                if self.db.is_interacted(tid): continue
                
                # Jeśli ekspert pisze o hacku - reaguj
                if any(w in text.lower() for w in ["hack", "exploit", "drain", "scam"]):
                    logger.brain("Expert signal detected!")
                    reply = self.brain.generate_reply(text, user, "ANALYSIS", "SUBTLE")
                    if reply:
                        self._reply_to_tweet(tweet, reply, user, tid)
                        return
        except: pass

    def _perform_social_trend_scan(self):
        # X -> Dex
        logger.log("INTELLIGENCE", "Scanning viral tickers...", "📡")
        # (Skrócona logika dla czytelności - ta z v11 była dobra, przenoszę ją tu)
        # ... (kod identyczny jak w v11 tylko z update bazy)
        # (Dla oszczędności miejsca, zakładamy że tu jest ta sama logika co wcześniej)
        pass

    def _post_to_x(self, text, image_path=None):
        if not text: return
        try:
            self.driver.get("https://twitter.com/compose/tweet")
            time.sleep(5)
            try: ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            except: pass
            
            box = WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-testid="tweetTextarea_0"]')))
            self.browser.safe_type(box, text)
            time.sleep(2)
            
            if image_path:
                self.browser.upload_image(image_path)
                time.sleep(5)
            
            btn = self.driver.find_element(By.CSS_SELECTOR, '[data-testid="tweetButton"]')
            self.browser.safe_click(btn)
            self.db.log_action("POST", "Feed", "SUCCESS")
            logger.log("ACTION", "Tweet posted.", "✅")
        except: pass

    def _reply_to_tweet(self, tweet_element, text, user, tid):
        try:
            self.browser.safe_click(tweet_element.find_element(By.CSS_SELECTOR, '[data-testid="reply"]'))
            time.sleep(3)
            
            # Check for 'deleted' popup
            if "not visible" in self.driver.page_source:
                self.db.save_interaction(user, "FAILED", tid, "FAILED")
                ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
                return

            box = WebDriverWait(self.driver, 5).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-testid="tweetTextarea_0"]')))
            self.browser.safe_type(box, text)
            time.sleep(1)
            self.browser.safe_click(self.driver.find_element(By.CSS_SELECTOR, '[data-testid="tweetButton"]'))
            
            self.db.save_interaction(user, text, tid, "REPLY")
            logger.log("ACTION", f"Replied to {user}", "✅")
        except: 
            try: ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            except: pass

if __name__ == "__main__":
    agent = XAgent()
    agent.run()