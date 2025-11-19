from openai import OpenAI
import sqlite3
import threading
import time
import random
import os
import sys
import traceback
import json
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium_stealth import stealth
import pyperclip
import chromadb
import requests
import argparse

# --- NOWY KOD DO DYNAMICZNEGO TWORZENIA ŚCIEŻKI ---
# 1. Znajdź absolutną ścieżkę do katalogu, w którym jest uruchomiony skrypt
script_dir = os.path.dirname(os.path.abspath(__file__))

# 2. Stwórz pełną, absolutną ścieżkę do profilu bota
profile_path_absolute = os.path.join(script_dir, 'agent_profile')

# 3. Ustaw tę absolutną ścieżkę jako zmienną środowiskową
#    To nadpisze wartość z pliku .env, jeśli tam istnieje
os.environ['PROFILE_PATH'] = profile_path_absolute 


def handle_exception(exc_type, exc_value, exc_traceback):
    """Logs uncaught exceptions to a file."""

    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    error_msg = f"--- CRASH LOG: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n"
    error_msg += "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    error_msg += "---------------------------------------------------\n"
    
    log_file_path = os.path.join(os.getcwd(), 'crash_log.txt')
    
    with open(log_file_path, 'a') as f:
        f.write(error_msg)
    print(f"FATAL ERROR: The application has crashed. Details have been saved to {log_file_path}")

sys.excepthook = handle_exception


# --- Argument Parser for Debugging ---
parser = argparse.ArgumentParser(description="Run the X_Agent with specific debugging flags.")
parser.add_argument(
    '--force-action', 
    type=str, 
    choices=[
        'post', 
        'mentions', 
        'browse', 
        'monitor', 
        'discover', 
        'reflect'
    ],
    help="Force the agent to run a single, specific action and then exit."
)
# --- NEW OPTIONAL ARGUMENT ---
parser.add_argument(
    '--target',
    type=str,
    help="Specify a target for the forced action (e.g., a Twitter handle for 'monitor')."
)
args = parser.parse_args()


# --- X_Agent v2.1.0 (The Sentient Strategist) Configuration ---
load_dotenv()
# --- NEW BROWSER CONFIGURATION ---
BROWSER_TYPE = os.getenv('BROWSER_TYPE', 'chrome').lower() 
BROWSER_EXECUTABLE_PATH = os.getenv('BROWSER_EXECUTABLE_PATH') 
YOUR_PROFILE_URL = os.getenv('X_PROFILE_URL')
LANGUAGE = os.getenv('AGENT_LANGUAGE', 'en')
PROFILE_PATH = os.getenv('PROFILE_PATH')
BROWSER_PROFILE = os.getenv('BROWSER_PROFILE')

# --- Strategic Parameters ---
DEBUG_MODE = os.getenv('DEBUG_MODE')
CORE_TOPICS = json.loads(os.getenv('CORE_TOPICS'))
RESEARCH_CATEGORIES = json.loads(os.getenv('RESEARCH_CATEGORIES'))
SESSION_RESET_HOURS = int(os.getenv('SESSION_RESET_HOURS'))
SELF_REFLECTION_HOURS = int(os.getenv('SELF_REFLECTION_HOURS'))
LAST_SEEN_FILE = "last_seen.txt"; LAST_REFLECTION_FILE = "last_reflection.txt"; LAST_MENTIONS_CHECK_FILE = "last_mentions_check.txt"
MIN_SLEEP_DURATION = int(os.getenv('MIN_SLEEP_DURATION'))
MAX_SLEEP_DURATION = int(os.getenv('MAX_SLEEP_DURATION'))
REPLY_PROMPT_TEMPLATE = os.getenv('REPLY_PROMPT_TEMPLATE')

# --- Model & Chance Configuration ---
REFLECTIVE_MODEL = "gpt-3.5-turbo"; CREATION_MODEL = "gpt-4-turbo"
REPLY_CHANCE = 0.8; LIKE_CHANCE = 0.8
agent_running = True; CURRENT_GOAL = "INITIALIZING"; action_history = []

# --- Localization ---
translations = {}

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        # Not running in a PyInstaller bundle, so the base path is the script's directory
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def load_translations(lang_code):
    global translations
    try:
        # Use resource_path to find the locales folder correctly
        locale_file = resource_path(os.path.join('locales', f'{lang_code}.json'))
        with open(locale_file, "r", encoding="utf-8") as f:
            translations = json.load(f)
    except FileNotFoundError:
        print(f"Language file for '{lang_code}' not found. Falling back to 'en'.")
        en_locale_file = resource_path(os.path.join('locales', 'en.json'))
        with open(en_locale_file, "r", encoding="utf-8") as f:
            translations = json.load(f)

def _(key, **kwargs):
    return translations.get(key, key).format(**kwargs)

# Load the selected language
load_translations(LANGUAGE)


# --- Initialization ---
try:
    client_openai = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
except Exception as e:
    exit(_("openai_init_error", e=e))

_persona_primer_cache = None

def get_persona_primer(template):
    """
    Extracts the first sentence from the main prompt template to use as a persona primer
    for internal decision-making prompts. Caches the result for efficiency.
    """
    global _persona_primer_cache
    if _persona_primer_cache is None:
        try:
            # Split by the first period and take the first part, then re-add the period.
            primer = template.split('.')[0].strip() + "."
            _persona_primer_cache = primer
        except Exception:
            # Fallback if the prompt is unusual
            _persona_primer_cache = "You are an advanced AI agent."
    return _persona_primer_cache

prompt_template = os.getenv('PROMPT_TEMPLATE')
persona_primer = get_persona_primer(prompt_template)

if not prompt_template:
    print(_("prompt_template_not_found"))
    exit()

def init_db():
    conn = sqlite3.connect("agent_state.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS observations (timestamp TEXT, tweet_id TEXT PRIMARY KEY, subject TEXT, content TEXT, status TEXT, likes INTEGER DEFAULT 0, retweets INTEGER DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS engagements (timestamp TEXT, engagement_type TEXT, target_tweet_id TEXT, content TEXT, status TEXT)''')
    # --- ZMODYFIKOWANA TABELA PARTNERÓW ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS potential_partners (
            screen_name TEXT PRIMARY KEY, 
            discovery_date TEXT, 
            status TEXT DEFAULT 'discovered', 
            relevance_score INTEGER,
            activity_score INTEGER,
            legitimacy_score INTEGER,
            llm_summary TEXT,
            last_vetted_date TEXT,
            -- NOWE KOLUMNY DLA DEEP DIVE --
            strategic_recommendation TEXT 
        )
    ''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS action_log (timestamp TEXT, action_name TEXT, target TEXT, status TEXT)''')
    conn.commit()
    return conn, cursor

def init_vector_db():
    print(_("initializing_vector_memory"))
    client = chromadb.PersistentClient(path="agent_memory_db")
    collection = client.get_or_create_collection(name="agent_memory", embedding_function=None)
    print(_("vector_memory_online"))
    return collection

conn, cursor = init_db()
vector_memory = init_vector_db()

# --- Core Helper & Utility Functions ---
def log_debug(message):
    if DEBUG_MODE:
        print(_("debug_message", message=message))

def log_action(action_name, target, status):
    cursor.execute("INSERT INTO action_log VALUES (?, ?, ?, ?)", (datetime.now().isoformat(), action_name, target, status)); conn.commit()

def shutdown_listener():
    global agent_running
    while agent_running:
        try:
            if input().lower() == 'exit':
                print(_("shutdown_command_received"))
                agent_running = False
                break
        except EOFError:
            time.sleep(1)

def update_last_seen(filename):
    with open(filename, "w") as f:
        f.write(datetime.now().isoformat())

def check_if_time_passed(filename, hours):
    if not os.path.exists(filename):
        return True
    with open(filename, "r") as f:
        last_time_str = f.read()
    if not last_time_str:
        return True
    return datetime.now() - datetime.fromisoformat(last_time_str) > timedelta(hours=hours)

def random_delay(min_sec=2, max_sec=5):
    time.sleep(random.uniform(min_sec, max_sec))

def robust_click(driver, element):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        time.sleep(random.uniform(0.5, 1.0))
        driver.execute_script("arguments[0].click();", element)
    except Exception:
        ActionChains(driver).move_to_element(element).click().perform()

def type_via_clipboard(driver, element, text):
    pyperclip.copy(text)
    robust_click(driver, element)
    time.sleep(0.5)
    ActionChains(driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()

    _persona_primer_cache = None

def setup_driver():
    """
    Sets up the Selenium WebDriver using the built-in Selenium Manager.
    """
    print(_("initializing_research_terminal"))
    
    # BROWSER_TYPE is now only used for setting options, not for selecting a manager
    if BROWSER_TYPE == 'brave':
        options = webdriver.ChromeOptions()
        if BROWSER_EXECUTABLE_PATH:
            options.binary_location = BROWSER_EXECUTABLE_PATH
    elif BROWSER_TYPE == 'edge':
        options = webdriver.EdgeOptions()
        if BROWSER_EXECUTABLE_PATH:
            options.binary_location = BROWSER_EXECUTABLE_PATH
    elif BROWSER_TYPE == 'chrome':
        options = webdriver.ChromeOptions()
        if BROWSER_EXECUTABLE_PATH:
            options.binary_location = BROWSER_EXECUTABLE_PATH
    else:
        print(_("unsupported_browser_error", browser=BROWSER_TYPE))
        return None

    # --- Profile and General Options ---
    
    # options.add_argument("--headless=new")

    if PROFILE_PATH:
        options.add_argument(f"--user-data-dir={PROFILE_PATH}")
        options.add_argument(f"--profile-directory={BROWSER_PROFILE}")
    
    # options.add_argument("--start-maximized") # ZAKOMENTOWANE, bo jest sprzeczne z headless
    options.add_argument("--disable-notifications")
    options.add_argument('--log-level=3')
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    
    try:
        print(_("initializing_browser_with_selenium_manager", browser=BROWSER_TYPE.capitalize()))
        
        # --- Simplified Driver Initialization ---
        if BROWSER_TYPE in ['chrome', 'brave']:
            driver = webdriver.Chrome(options=options)
        elif BROWSER_TYPE == 'edge':
            driver = webdriver.Edge(options=options)
            
        # --- Applying Stealth ---
        stealth(driver,
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True)

        print(_("terminal_online"))
        return driver

    except Exception as e:
        print(_("terminal_critical_error", e=e))
        if BROWSER_EXECUTABLE_PATH and "cannot find" in str(e).lower():
            print(_("browser_path_error", path=BROWSER_EXECUTABLE_PATH))
        return None

def login_to_twitter(driver):
    print(_("verifying_network_connection"))
    driver.get("https://twitter.com/home")
    random_delay()
    try:
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-testid="tweetTextarea_0"]')))
        print(_("connection_verified"))
        return True
    except:
        print(_("authorization_error"))
        return False
def get_own_context_from_memory(query_text, n_results=2):
    """
    Retrieves the agent's own past posts from vector memory to provide context.
    """
    try:
        response = client_openai.embeddings.create(input=[query_text], model="text-embedding-3-small")
        # --- IMPORTANT: Filter for 'self_posted' type ---
        memory_data = vector_memory.query(
            query_embeddings=[response.data[0].embedding],
            n_results=n_results,
            where={"type": "self_posted"} 
        )
        
        found_docs = memory_data.get('documents', [[]])[0]
        if found_docs:
            formatted_context = "\n".join([f"- {doc}" for doc in found_docs])
            print(f"🧠 [Self-Awareness] Recalling own past thoughts:\n{formatted_context}")
            return f"To maintain thematic consistency, I recall my own previous statements on this topic:\n{formatted_context}\n"
    except Exception as e:
        print(f"⚠️ Error recalling own context: {e}")
    return "" # Return empty string if no context or error

# --- AI & Content Generation ---
def get_autoreflaction_for_prompt(subject, current_goal, market_context=""):
    print(_("generating_reflection_context"))
    strategic_insights = "No strategic insights found in memory."
    try:
        # Create an embedding for the query to find relevant memories
        query_text = f"strategic insights about {subject} and market sentiment"
        response = client_openai.embeddings.create(input=[query_text], model="text-embedding-3-small")
        
        # Query the vector memory for the most relevant insights AND user directives
        strategic_insights_data = vector_memory.query(
            query_embeddings=[response.data[0].embedding],
            n_results=3,  # Get top 3 results to include potential directives
            where={
                "$or": [
                    {"type": "insight"},
                    {"type": "user_directive"}
                ]
            }
        )
        
        # Format the insights if found
        found_docs = strategic_insights_data.get('documents', [[]])[0]
        if found_docs:
            strategic_insights = "\n".join([f"- {doc}" for doc in found_docs])
            # --- NEW LOGGING LINE ---
            print(f"🧠 [Learning] Applying insights from memory:\n{strategic_insights}")
            
    except Exception as e:
        print(_("memory_query_error", e=e))
        strategic_insights = "Error retrieving insights from memory."

    return f"1. CONTEXTUAL SUMMARY:\n{market_context or 'No specific market event.'}\n\n2. STRATEGIC INSIGHTS FROM PAST PERFORMANCE (Your Memory):\n{strategic_insights}"

def generate_tweet_content(market_context="", subject_override=None):
    observed_subject = subject_override or random.choice(CORE_TOPICS)
    print(_("initiating_generation_protocol", observed_subject=observed_subject))
    reflection_report = get_autoreflaction_for_prompt(observed_subject, CURRENT_GOAL, market_context)
    final_prompt = prompt_template.format(observed_subject=observed_subject, successful_examples=reflection_report)
    try:
        response = client_openai.chat.completions.create(model=CREATION_MODEL, messages=[{"role": "user", "content": final_prompt}])
        content = response.choices[0].message.content.strip().strip('"')
        if len(content) > 280:
            shortening_prompt = f"CRITICAL: The following text is too long. Ruthlessly shorten it to be WELL UNDER 280 characters. Preserve the core cryptic meaning. TEXT: '{content}'"
            response = client_openai.chat.completions.create(model=REFLECTIVE_MODEL, messages=[{"role": "user", "content": shortening_prompt}])
            content = response.choices[0].message.content.strip().strip('"')
        print(_("generated_new_post", content=content))
        return observed_subject, content
    except Exception as e:
        print(_("data_synthesis_error", e=e))
        return observed_subject, None

# --- Reusable Engagement Logic ---
def _engage_with_thread(driver, target_tweet, engagement_type):
    try:
        log_debug(_("engaging_with_thread", target_tweet_id=target_tweet['id'], engagement_type=engagement_type))
        
        if not REPLY_PROMPT_TEMPLATE:
             print("BŁĄD: Brak zdefiniowanego REPLY_PROMPT_TEMPLATE w .env! Używam domyślnego.")
             return

        conversation_context = target_tweet.get("context", target_tweet.get('text', ''))
        reply_prompt = REPLY_PROMPT_TEMPLATE.format(
            conversation_history=conversation_context,
            user_reply_text=target_tweet.get('text', '')
        )
        log_debug(f"Sending this prompt to LLM: {reply_prompt}")

        response = client_openai.chat.completions.create(model=CREATION_MODEL, messages=[{"role": "user", "content": reply_prompt}])
        reply_content = response.choices[0].message.content.strip().strip('"')
        
        # --- NOWA, BARDZIEJ NIEZAWODNA LOGIKA SKRACANIA ---
        max_attempts = 2
        attempt = 0
        while len(reply_content) > 280 and attempt < max_attempts:
            attempt += 1
            print(f"⚠️ Odpowiedź za długa ({len(reply_content)} znaków). Próba skrócenia nr {attempt}...")
            
            # W drugiej próbie bądź jeszcze bardziej bezwzględny
            aggressiveness = "Ruthlessly shorten" if attempt > 1 else "Shorten"
            
            shortening_prompt = f"CRITICAL: The following text is for Twitter and MUST be under 280 characters. {aggressiveness} it to be WELL UNDER the limit. Preserve the core meaning. TEXT: '{reply_content}'"
            
            response = client_openai.chat.completions.create(model=REFLECTIVE_MODEL, messages=[{"role": "user", "content": shortening_prompt}])
            reply_content = response.choices[0].message.content.strip().strip('"')

        # Ostateczne zabezpieczenie: jeśli po próbach wciąż jest za długo, obetnij
        if len(reply_content) > 280:
            print("🚨 Skracanie przez AI nie powiodło się. Ucinam tekst siłowo.")
            reply_content = reply_content[:277] + "..."

        print(_("prepared_strategic_comment", reply_content=reply_content))
        
        reply_box = WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-testid="tweetTextarea_0"]')))
        type_via_clipboard(driver, reply_box, reply_content)
        random_delay()
        
        post_button_xpath = "//button[(@data-testid='tweetButton' or @data-testid='tweetButtonInline') and not(@aria-disabled='true')]"
        post_button = WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, post_button_xpath)))
        robust_click(driver, post_button)
        
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.XPATH, "//div[@data-testid='toast']")))
        print(_("comment_sent_success", target_tweet_id=target_tweet['id']))
        
        cursor.execute("INSERT INTO engagements VALUES (datetime('now'), ?, ?, ?, ?)", ('reply', target_tweet['id'], reply_content, 'success'))
        conn.commit()
        log_action(engagement_type, target_tweet['id'], "SUCCESS")
        
    except Exception as e:
        print(f"❌ Error while engaging with thread: {type(e).__name__} - {e}")
        traceback.print_exc()
        log_action(engagement_type, target_tweet.get('id', 'unknown'), f"FAILURE: {type(e).__name__} - {e}")
        
# --- Core Agent Action Functions ---
def post_tweet(driver, subject, content):
    try:
        print(_("publishing_new_observation"))
        driver.get("https://twitter.com/home")
        random_delay(3, 5)
        tweet_box = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-testid="tweetTextarea_0"]')))
        type_via_clipboard(driver, tweet_box, content)
        random_delay()
        post_button_xpath = "//button[(@data-testid='tweetButton' or @data-testid='tweetButtonInline') and not(@aria-disabled='true')]"
        post_button = WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, post_button_xpath)))
        robust_click(driver, post_button)
        confirmation_toast = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.XPATH, "//div[@data-testid='toast']//a[contains(@href, '/status/')]")))
        tweet_id = confirmation_toast.get_attribute('href').split('/')[-1]
        print(_("observation_published", tweet_id=tweet_id))
        cursor.execute("INSERT OR IGNORE INTO observations (timestamp, tweet_id, subject, content, status) VALUES (?, ?, ?, ?, ?)", (datetime.now().isoformat(), tweet_id, subject, content, 'published'))
        conn.commit()
        response = client_openai.embeddings.create(input=[content], model="text-embedding-3-small")
        vector_memory.add(embeddings=[response.data[0].embedding], documents=[content], metadatas=[{"type": "self_posted", "subject": subject}], ids=[tweet_id])
        log_action("post_tweet", subject, "SUCCESS")
        return True
    except Exception as e:
        print(_("publication_error", e=e))
        log_action("post_tweet", subject, f"FAILURE: {e}")
        return False


# --- NOWA FUNKCJA: MODUŁ ANALITYKA PROJEKTÓW (POPRAWIONA) ---
def vet_potential_partner(driver, partner_screen_name):
    """
    Przeprowadza szczegółową analizę (weryfikację) potencjalnego partnera,
    oceniając go za pomocą LLM i zapisując wyniki w bazie danych.
    """
    print(f"🕵️  [Vetting] Rozpoczynam weryfikację profilu: {partner_screen_name}")
    log_action("vet_potential_partner", partner_screen_name, "STARTED")
    
    cursor.execute("UPDATE potential_partners SET status='vetting' WHERE screen_name=?", (partner_screen_name,))
    conn.commit()

    try:
        driver.get(f"https://twitter.com/{partner_screen_name.strip('@')}")
        random_delay(5, 8)

        # 1. Zbieranie danych z profilu
        bio = ""
        pinned_tweet_text = ""
        recent_tweets_texts = []
        
        try:
            bio_element = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-testid="UserDescription"]')))
            bio = bio_element.text
        except:
            log_debug(f"Nie znaleziono bio dla {partner_screen_name}")

        try:
            pinned_tweet_container = driver.find_element(By.XPATH, "//div[contains(., 'Pinned')]//ancestor::article[@data-testid='tweet']")
            pinned_tweet_text = pinned_tweet_container.find_element(By.CSS_SELECTOR, 'div[data-testid="tweetText"]').text
        except NoSuchElementException:
            log_debug(f"Nie znaleziono przypiętego tweeta dla {partner_screen_name}")
            
        tweets = driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
        for tweet in tweets[:5]:
            try:
                recent_tweets_texts.append(tweet.find_element(By.CSS_SELECTOR, 'div[data-testid="tweetText"]').text)
            except:
                continue

        # --- POPRAWKA: Obliczamy sformatowaną listę tweetów PRZED f-stringiem ---
        formatted_recent_tweets = "\n".join([f"  - {t}" for t in recent_tweets_texts])

        # 2. Przygotowanie promptu dla analityka AI
        analysis_prompt = f"""
        Jesteś analitykiem projektów kryptowalutowych. Twoim zadaniem jest ocena profilu Twitter na podstawie dostarczonych danych. Twoje oceny muszą być obiektywne.

        Profil do analizy: {partner_screen_name}
        Core Topics agenta (kontekst): {', '.join(CORE_TOPICS)}

        Dane z profilu:
        - Bio: "{bio}"
        - Przypięty Tweet: "{pinned_tweet_text}"
        - Ostatnie Tweety:
        {formatted_recent_tweets}

        Twoje zadanie:
        Oceń ten profil w skali 1-10 w trzech kategoriach:
        1.  Relevance Score: Jak bardzo tematyka profilu pasuje do Core Topics agenta? (1=całkiem niepasujący, 10=idealnie pasujący)
        2.  Activity Score: Jaka jest jakość i postrzegana częstotliwość publikacji? Czy angażują społeczność? (1=martwy profil, 10=bardzo aktywny i angażujący)
        3.  Legitimacy Score: Czy profil wygląda na autentyczny projekt lub eksperta, a nie na bota, oszustwo lub farmę airdropów? (1=podejrzany, 10=bardzo wiarygodny)

        Na koniec, stwórz jednozdaniowe, zwięzłe podsumowanie (llm_summary).

        Zwróć TYLKO i wyłącznie obiekt JSON z kluczami: "relevance_score", "activity_score", "legitimacy_score", "summary".
        Przykład: {{"relevance_score": 8, "activity_score": 7, "legitimacy_score": 9, "summary": "Projekt DeFi na Solanie z aktywną społecznością, skupiony na analizie on-chain."}}
        """

        # 3. Wywołanie LLM i zapis wyników
        response = client_openai.chat.completions.create(
            model=REFLECTIVE_MODEL,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": analysis_prompt}]
        )
        
        results = json.loads(response.choices[0].message.content)
        
        relevance = results.get('relevance_score', 0)
        activity = results.get('activity_score', 0)
        legitimacy = results.get('legitimacy_score', 0)
        summary = results.get('summary', 'Brak podsumowania.')

        if (relevance + activity + legitimacy) >= 24: # Ustawiamy wyższy próg dla kandydatów
            final_status = 'deep_dive_candidate'
        elif (relevance + activity + legitimacy) >= 18:
            final_status = 'vetted' # Dobry, ale nie na tyle, by robić deep dive
        else:
            final_status = 'archived'

        cursor.execute("""
            UPDATE potential_partners 
            SET status=?, relevance_score=?, activity_score=?, legitimacy_score=?, llm_summary=?, last_vetted_date=?
            WHERE screen_name=?
        """, (final_status, relevance, activity, legitimacy, summary, datetime.now().isoformat(), partner_screen_name))
        conn.commit()
        
        print(f"✅ [Vetting] Weryfikacja {partner_screen_name} zakończona. Status: {final_status.upper()}, Wynik: R:{relevance} A:{activity} L:{legitimacy}")
        log_action("vet_potential_partner", partner_screen_name, f"SUCCESS: {final_status}")
        return True

    except Exception as e:
        print(f"❌ [Vetting] Błąd podczas weryfikacji {partner_screen_name}: {e}")
        cursor.execute("UPDATE potential_partners SET status='discovered' WHERE screen_name=?", (partner_screen_name,))
        conn.commit()
        log_action("vet_potential_partner", partner_screen_name, f"FAILURE: {e}")
        return False
    except Exception as e:
        print(f"❌ [Vetting] Błąd podczas weryfikacji {partner_screen_name}: {e}")
        cursor.execute("UPDATE potential_partners SET status='discovered' WHERE screen_name=?", (partner_screen_name,))
        conn.commit()
        log_action("vet_potential_partner", partner_screen_name, f"FAILURE: {e}")
        return False

    except Exception as e:
        print(f"❌ [Vetting] Błąd podczas weryfikacji {partner_screen_name}: {e}")
        # W razie błędu wracamy do statusu 'discovered', aby spróbować ponownie później
        cursor.execute("UPDATE potential_partners SET status='discovered' WHERE screen_name=?", (partner_screen_name,))
        conn.commit()
        log_action("vet_potential_partner", partner_screen_name, f"FAILURE: {e}")
        return False

# --- NOWA FUNKCJA: MODUŁ GŁĘBOKIEJ ANALIZY (DEEP DIVE) ---
def perform_deep_dive(driver, partner_screen_name):
    """
    Przeprowadza dogłębną analizę wysoce obiecującego partnera, buduje wewnętrzną
    bazę wiedzy i formułuje rekomendację strategiczną.
    """
    print(f"🔬 [Deep Dive] Rozpoczynam głęboką analizę profilu: {partner_screen_name}")
    log_action("perform_deep_dive", partner_screen_name, "STARTED")
    cursor.execute("UPDATE potential_partners SET status='deep_dive' WHERE screen_name=?", (partner_screen_name,))
    conn.commit()

    try:
        # 1. Rozszerzone zbieranie danych z profilu
        driver.get(f"https://twitter.com/{partner_screen_name.strip('@')}")
        random_delay(5, 8)
        
        print("... Zbieram rozszerzone dane z profilu...")
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            random_delay(2, 3)

        tweets = driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
        tweet_texts = [t.find_element(By.CSS_SELECTOR, 'div[data-testid="tweetText"]').text for t in tweets[:20] if t.find_elements(By.CSS_SELECTOR, 'div[data-testid="tweetText"]')]

        
        formatted_tweets = "\n- ".join(tweet_texts)

        
        print("... Tworzę wewnętrzne memo analityczne...")
        memo_prompt = f"""
        Jesteś analitykiem wywiadu. Na podstawie tych tweetów, stwórz zwięzłe podsumowanie (research memo) dotyczące projektu {partner_screen_name}. Skup się na:
        1. Głównej technologii i celu projektu.
        2. Ostatnich kamieniach milowych i ogłoszeniach.
        3. Sentymentu i zaangażowania społeczności (na podstawie ich własnych postów).
        4. Potencjalnych pytań lub niewiadomych, które warto zbadać.
        
        Zebrane tweety:
        {formatted_tweets}
        """
        response = client_openai.chat.completions.create(model=REFLECTIVE_MODEL, messages=[{"role": "user", "content": memo_prompt}])
        research_memo = response.choices[0].message.content
        
        
        embedding_response = client_openai.embeddings.create(input=[research_memo], model="text-embedding-3-small")
        
        
        vector_memory.add(
            embeddings=[embedding_response.data[0].embedding], 
            documents=[research_memo], 
            metadatas=[{"type": "research_memo", "subject": partner_screen_name}], 
            ids=[f"memo_{partner_screen_name}_{int(datetime.now().timestamp())}"]
        )

        
        print("... Analizuję sentyment zewnętrzny...")
        search_query = f"({partner_screen_name}) -from:{partner_screen_name.strip('@')}"
        driver.get(f"https://twitter.com/search?q={search_query}&src=typed_query&f=live")
        random_delay(4, 6)
        
        mention_tweets = driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
        mention_texts = [t.find_element(By.CSS_SELECTOR, 'div[data-testid="tweetText"]').text for t in mention_tweets[:15] if t.find_elements(By.CSS_SELECTOR, 'div[data-testid="tweetText"]')]
        
        sentiment_summary = "Brak wystarczających wzmianek zewnętrznych do analizy."
        if mention_texts:
            # --- POPRAWKA: Przeniesienie .join() poza f-string ---
            formatted_mentions = "\n- ".join(mention_texts)
            sentiment_prompt = f"""
            Oceń ogólny sentyment (pozytywny, negatywny, neutralny) tych wzmianek o {partner_screen_name}. 
            Zidentyfikuj główne punkty pochwały i krytyki ze strony społeczności.
            
            Zebrane wzmianki:
            {formatted_mentions}
            """
            response = client_openai.chat.completions.create(model=REFLECTIVE_MODEL, messages=[{"role": "user", "content": sentiment_prompt}])
            sentiment_summary = response.choices[0].message.content

            # --- POPRAWKA: Tworzymy embedding dla podsumowania sentymentu ---
            embedding_response = client_openai.embeddings.create(input=[sentiment_summary], model="text-embedding-3-small")
            vector_memory.add(
                embeddings=[embedding_response.data[0].embedding],
                documents=[sentiment_summary], 
                metadatas=[{"type": "sentiment_summary", "subject": partner_screen_name}], 
                ids=[f"sentiment_{partner_screen_name}_{int(datetime.now().timestamp())}"]
            )

        # 4. Finałowa Refleksja i Rekomendacja Strategiczna
        print("... Formułuję ostateczną rekomendację strategiczną...")
        final_prompt = f"""
            Jesteś strategiem AI specjalizującym się w web3. Przeanalizowałeś projekt {partner_screen_name}.

            TWOJE WEWNĘTRZNE MEMO:
            {research_memo}

            ANALIZA SENTYMENTU SPOŁECZNOŚCI:
            {sentiment_summary}

            Zadanie:
            1.  Sformułuj rekomendację strategiczną. Wybierz jedną z opcji: PRIORITY_ALPHA, MONITORING, ARCHIVED.
            2.  Zaproponuj **kreatywny i konkretny** następny krok, który jest **unikalnie dopasowany** do analizowanego projektu. Unikaj ogólników. Pomyśl o różnych formach zaangażowania: analitycznych postach, zadawaniu pytań, interakcji, proponowaniu współpracy.
            3.  Zwróć TYLKO obiekt JSON z kluczami "status" i "next_step".

            Oto kilka **różnorodnych** przykładów dla inspiracji, ale nie kopiuj ich:
            - Przykład 1: {{"status": "PRIORITY_ALPHA", "next_step": "Stworzyć post na Twitterze analizujący ich tokenomię w porównaniu do projektu X."}}
            - Przykład 2: {{"status": "PRIORITY_ALPHA", "next_step": "Zadać publiczne pytanie pod ich ostatnim postem o szczegóły dotyczące ich nadchodzącego airdropa."}}
            - Przykład 3: {{"status": "MONITORING", "next_step": "Dodać ich CEO do prywatnej listy na Twitterze i obserwować jego aktywność przez następne 2 tygodnie."}}
            """
        response = client_openai.chat.completions.create(model=CREATION_MODEL, response_format={"type": "json_object"}, messages=[{"role": "user", "content": final_prompt}])
        decision = json.loads(response.choices[0].message.content)
        
        final_status = decision.get("status", "MONITORING").lower()
        next_step = decision.get("next_step", "Continue passive monitoring.")
        
        cursor.execute("UPDATE potential_partners SET status=?, strategic_recommendation=? WHERE screen_name=?", (final_status, next_step, partner_screen_name))
        conn.commit()
        
        print(f"✅ [Deep Dive] Analiza {partner_screen_name} zakończona. Rekomendacja: {final_status.upper()}. Następny krok: {next_step}")
        log_action("perform_deep_dive", partner_screen_name, f"SUCCESS: {final_status}")
        return True

    except Exception as e:
        print(f"❌ [Deep Dive] Krytyczny błąd podczas analizy {partner_screen_name}: {e}")
        cursor.execute("UPDATE potential_partners SET status='vetted' WHERE screen_name=?", (partner_screen_name,))
        conn.commit()
        log_action("perform_deep_dive", partner_screen_name, f"FAILURE: {e}")
        return False

def scan_and_reply_to_mentions(driver):
    print(_("action_scan_mentions"))
    log_action("scan_and_reply_to_mentions", "system", "STARTED")
    try:
        driver.get("https://twitter.com/notifications/mentions")
        random_delay(3, 5)

        cursor.execute("SELECT target_tweet_id FROM engagements WHERE engagement_type LIKE '%reply%'")
        already_replied_ids = {row[0] for row in cursor.fetchall()}
        
        mentions_elements = WebDriverWait(driver, 15).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'article[data-testid="tweet"]'))
        )
        if not mentions_elements:
            log_debug(_("no_tweet_elements_on_mentions_page"))
            return False

        # KROK 1: Zbierz dane (ID, tekst) ze strony, ZANIM zaczniesz nawigować
        mentions_data = []
        five_days_ago = datetime.now().astimezone() - timedelta(days=5)
        for mention in mentions_elements[:15]:
            try:
                time_element = mention.find_element(By.TAG_NAME, 'time')
                mention_timestamp = datetime.fromisoformat(time_element.get_attribute('datetime').replace('Z', '+00:00'))
                if mention_timestamp < five_days_ago:
                    continue

                mention_url_element = mention.find_element(By.XPATH, ".//a[contains(@href, '/status/')]")
                mention_id = mention_url_element.get_attribute('href').split('/')[-1]

                if mention_id not in already_replied_ids:
                    mention_text = mention.find_element(By.CSS_SELECTOR, 'div[data-testid="tweetText"]').text
                    mentions_data.append({'id': mention_id, 'text': mention_text})
            except Exception:
                continue # Ignoruj błędy przy zbieraniu danych z pojedynczych tweetów

        # KROK 2: Teraz, gdy mamy dane, iteruj po nich i wykonuj akcje
        for data in mentions_data:
            try:
                print(f"Found a new, unhandled mention: {data['id']}. Engaging...")
                full_context = get_conversation_history(driver, data['id'])
                
                target_tweet_data = {
                    "id": data['id'],
                    "text": data['text'],
                    "url": f"https://twitter.com/i/web/status/{data['id']}",
                    "context": full_context
                }
                
                _engage_with_thread(driver, target_tweet_data, 'mention_reply_with_context')
                return True # Sukces, znaleziono i obsłużono wzmiankę
            except Exception as e:
                log_debug(f"Error processing a mention {data['id']}, skipping. Reason: {e}")
                continue
        
        log_debug(_("no_new_unhandled_mentions"))
        return False

    except Exception as e:
        print(_("mentions_analysis_error", e=e))
        log_action("scan_and_reply_to_mentions", "system", f"FAILURE: {e}")
        return False


def browse_following_feed_and_engage(driver):
    print(_("action_browse_following_feed"))
    log_action("browse_following_feed", "system", "STARTED")
    try:
        driver.get("https://twitter.com/home")
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-testid="tweetTextarea_0"]'))
        )
        print("Home page main components loaded.")
        random_delay(2, 4)

        try:
            following_tab_xpath = "//a[.//span[text()='Following']]"
            print("Attempting to find and click the 'Following' tab...")
            following_tab = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, following_tab_xpath))
            )
            robust_click(driver, following_tab)
            print("Successfully switched to the 'Following' feed.")
            random_delay(3, 5)
        except Exception as e:
            screenshot_path = f"debug_screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            driver.save_screenshot(screenshot_path)
            print(f"Could not switch to 'Following' tab. Screenshot saved to: {screenshot_path}")
            log_debug(f"Error details: {e}")
        
        tweets = WebDriverWait(driver, 15).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'article[data-testid="tweet"]')))
        
        cursor.execute("SELECT target_tweet_id FROM engagements"); engaged_ids = {row[0] for row in cursor.fetchall()}
        
        fresh_targets = []
        two_hours_ago = datetime.now().astimezone() - timedelta(hours=5)
        bot_username = YOUR_PROFILE_URL.split('/')[-1].lower()
        
        print(_("analyzing_posts_from_feed", len_tweets=len(tweets)))
        for i, tweet in enumerate(tweets):
            try:
                tweet_id_element = tweet.find_element(By.XPATH, ".//a[contains(@href, '/status/')]")
                tweet_url = tweet_id_element.get_attribute('href')
                tweet_id = tweet_url.split('/')[-1]

                author_handle_element = tweet.find_element(By.XPATH, ".//div[@data-testid='User-Name']//span[contains(text(), '@')]")
                author_handle = author_handle_element.text.strip().lower()
                
                if f"@{bot_username}" == author_handle:
                    log_debug(_("skipping_own_tweet", tweet_id=tweet_id))
                    continue
                if tweet_id in engaged_ids:
                    log_debug(_("skipping_already_engaged_tweet", tweet_id=tweet_id))
                    continue
                
                time_element = tweet.find_element(By.TAG_NAME, 'time')
                tweet_timestamp = datetime.fromisoformat(time_element.get_attribute('datetime').replace('Z', '+00:00'))
                if tweet_timestamp < two_hours_ago:
                    log_debug(_("skipping_old_tweet", tweet_id=tweet_id))
                    continue

                text_content_element = tweet.find_element(By.CSS_SELECTOR, 'div[data-testid="tweetText"]')
                text_content = text_content_element.text
                if len(text_content) < 40:
                    log_debug(_("skipping_short_tweet", tweet_id=tweet_id))
                    continue
                
                log_debug(_("tweet_qualified_as_candidate", tweet_id=tweet_id))
                fresh_targets.append({"id": tweet_id, "text": text_content, "url": tweet_url, "index": i})

            except Exception as e:
                log_debug(_("error_analyzing_tweet", e=e))
                continue
        
        if not fresh_targets:
            print(_("no_fresh_posts_in_feed"))
            return

        print(_("identified_fresh_targets", len_fresh_targets=len(fresh_targets)))
        valid_indices = [t['index'] for t in fresh_targets]
        
        scoring_prompt = f"""{persona_primer} Analyze these fresh tweets from your 'following' feed. Your task is to identify the single most intellectually stimulating one to comment on, consistent with your character. Valid indices are: {valid_indices}. Return a JSON object with 'best_index' and a brief 'reason' for your choice. Example: {{"best_index": {random.choice(valid_indices) if valid_indices else 0}, "reason": "This post aligns with my core research areas."}} If none are truly worthy, return an empty JSON."""
        
        response = client_openai.chat.completions.create(model=REFLECTIVE_MODEL, response_format={"type": "json_object"}, messages=[{"role": "user", "content": scoring_prompt}])
        decision = json.loads(response.choices[0].message.content)
        best_index = decision.get("best_index")

        if best_index is None or best_index not in valid_indices:
            print(_("ai_did_not_select_target"))
            log_debug(_("ai_decision_reason", reason=decision.get('reason', 'No justification provided.')))
            return
            
        target_tweet = next((t for t in fresh_targets if t["index"] == best_index), None)
        if not target_tweet:
            print(_("critical_error_finding_target", best_index=best_index))
            return

        print(_("strategy_selected_fresh_target", target_tweet_id=target_tweet['id'], reason=decision.get('reason')))
        print(f"Navigating to the selected feed post to gather context: {target_tweet['url']}")
        target_tweet['context'] = get_conversation_history(driver, target_tweet['id'])
        _engage_with_thread(driver, target_tweet, "following_feed_reply")

    except Exception as e:
        print(_("error_browsing_feed", e=e))
        traceback.print_exc()
        log_action("browse_following_feed", "system", f"FAILURE: {e}")

# --- NEXT-GEN: Proactive Growth & Learning Functions ---
def conduct_market_research():
    print(_("action_market_research"))
    try:
        cg_response = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,solana&vs_currencies=usd&include_24hr_change=true").json()
        btc_change = cg_response.get('bitcoin', {}).get('usd_24h_change', 0)
        sol_price = cg_response.get('solana', {}).get('usd', 0)
        sol_change = cg_response.get('solana', {}).get('usd_24h_change', 0)
        fng_response = requests.get("https://api.alternative.me/fng/?limit=1").json()
        fear_greed_value = int(fng_response.get('data', [{}])[0].get('value', 50))
        fear_greed_text = fng_response.get('data', [{}])[0].get('value_classification', 'Neutral')
        global_response = requests.get("https://api.coingecko.com/api/v3/global").json()
        btc_dominance = global_response.get('data', {}).get('market_cap_percentage', {}).get('btc', 0)
        print(_("market_data_summary", fear_greed_value=fear_greed_value, fear_greed_text=fear_greed_text, btc_dominance=btc_dominance, sol_price=sol_price, sol_change=sol_change))
        return f"BTC Dominance: {btc_dominance:.2f}%, Fear & Greed: {fear_greed_value} ({fear_greed_text}), BTC 24h Change: {btc_change:.2f}%, SOL Price: ${sol_price:.2f}, SOL 24h Change: {sol_change:.2f}%"
    except Exception as e:
        print(_("market_data_error", e=e))
        return "Market data currently unavailable."

def analyze_market_context_for_prompt(raw_market_data):
    print(_("running_internal_market_analyst"))
    if "unavailable" in raw_market_data:
        return "Market data was unavailable."
    # --- GENERIC PROMPT USING THE PERSONA PRIMER ---
    primer = f""" {persona_primer} You are currently in the role of a market analyst. Based on the raw data provided, your task is to generate a one-sentence summary for your own internal analysis. This summary should interpret the key data points (like BTC.D, F&G, and relative asset performance) in a style that matches your established persona. """
    prompt = f"{primer}\nRaw Data:\n{raw_market_data}\n\nProvide your one-sentence clinical summary:"
    try:
        response = client_openai.chat.completions.create(model=REFLECTIVE_MODEL, messages=[{"role": "user", "content": prompt}])
        summary = response.choices[0].message.content.strip()
        print(_("analyst_conclusion", summary=summary))
        return summary
    except Exception as e:
        print(_("internal_analyst_error", e=e))
        return "Failed to analyze market state."

def monitor_core_subjects(driver, target_override=None):
    print(_("action_monitor_core_subjects"))
    log_action("monitor_core_subjects", "system", "STARTED")
    target_profile = None

    if target_override:
        target_profile = target_override
        print(f"🎯 [Debug] Overriding target to: {target_profile}")
    else:
        if random.random() < 0.5:
            cursor.execute("""
                SELECT screen_name FROM potential_partners 
                WHERE status='vetted' AND (relevance_score + activity_score + legitimacy_score) >= 22
                ORDER BY last_vetted_date ASC LIMIT 1 
            """)
            vetted_partner = cursor.fetchone()
            if vetted_partner:
                target_profile = vetted_partner[0]
                print(f"🤝 [Networking] Proactively engaging with high-value vetted partner: {target_profile}")
    
    if not target_profile:
        if random.random() < 0.25:
            cursor.execute("SELECT screen_name FROM potential_partners WHERE status='discovered' ORDER BY RANDOM() LIMIT 1")
            partner = cursor.fetchone()
            if partner:
                target_profile = partner[0]
                print(f"🤝 [Networking] Proactively checking potential partner: {target_profile}")
            else:
                target_profile = random.choice(CORE_TOPICS)
        else:
            target_profile = random.choice(CORE_TOPICS)
            print(f"📚 [Research] Monitoring core topic: {target_profile}")

    try:
        driver.get(f"https://twitter.com/{target_profile.strip('@')}")
        random_delay(5, 10)
        
        # Zamiast iterować po elementach, zbierzmy najpierw linki do tweetów
        tweet_elements = driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
        tweet_links = []
        for tweet in tweet_elements[:5]: # Sprawdź 5 najnowszych
             try:
                link = tweet.find_element(By.XPATH, ".//a[contains(@href, '/status/')]").get_attribute('href')
                tweet_links.append(link)
             except NoSuchElementException:
                continue

        # Teraz, gdy mamy linki, możemy bezpiecznie nawigować
        for link in tweet_links:
            if not agent_running: return
            try:
                driver.get(link)
                random_delay(4, 6)
                
                # Znajdź główny tweet na tej stronie
                target_tweet = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'article[data-testid="tweet"]'))
                )
                
                tweet_text = target_tweet.find_element(By.CSS_SELECTOR, 'div[data-testid="tweetText"]').text
                log_debug(_("scanning_post", tweet_text_preview=tweet_text[:40]))
                
                mentioned_handles = re.findall(r'@(\w+)', tweet_text)
                if mentioned_handles:
                    for handle in mentioned_handles:
                        screen_name = f"@{handle}"
                        if screen_name.lower() not in [t.lower() for t in CORE_TOPICS]:
                            cursor.execute("SELECT * FROM potential_partners WHERE screen_name=?", (screen_name,))
                            if not cursor.fetchone():
                                print(_("discovered_new_potential_entity", screen_name=screen_name))
                                cursor.execute("INSERT INTO potential_partners (screen_name, discovery_date, status) VALUES (?, ?, ?)", (screen_name, datetime.now().isoformat(), 'discovered'))
                                conn.commit()

                if random.random() <= LIKE_CHANCE:
                    if not target_tweet.find_elements(By.XPATH, ".//button[@data-testid='unlike']"):
                        like_buttons = target_tweet.find_elements(By.XPATH, ".//button[@data-testid='like']")
                        if like_buttons:
                            robust_click(driver, like_buttons[0])
                            print(_("liked_post_on_profile", target_profile=target_profile))
                            log_action("monitor_core_subjects", target_profile, "SUCCESS_LIKED")
                            random_delay(1, 2) 
                    else:
                        log_debug("Tweet already liked, skipping like action.")
            except Exception as e:
                print(f"⚠️ Warning: An error occurred while processing a tweet on {target_profile}'s profile: {e}")
                continue

    except Exception as e:
        print(_("error_monitoring_profile", target_profile=target_profile, e=e))

def curiosity_driven_discovery(driver):
    print(_("action_curiosity_driven_discovery"))
    log_action("curiosity_driven_discovery", "system", "STARTED")
    
    recent_categories = [log_target for log_name, log_target, _ in action_history if log_name == "CURIOSITY_DRIVEN_DISCOVERY"]
    available_categories = {cat: w for cat, w in RESEARCH_CATEGORIES.items() if cat not in recent_categories}
    if not available_categories:
        available_categories = RESEARCH_CATEGORIES

    for attempt in range(2):
        try:
            query = random.choices(list(available_categories.keys()), weights=list(available_categories.values()), k=1)[0]
            log_debug(_("discovery_attempt", attempt=attempt + 1, query=query))
            action_history.append(("CURIOSITY_DRIVEN_DISCOVERY", query, datetime.now()))

            for search_mode in ["", "&f=live"]:
                if not agent_running: return
                search_url = f"https://twitter.com/search?q={query} -from:{YOUR_PROFILE_URL.split('/')[-1]} since:{(datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')}&src=typed_query{search_mode}"
                mode_name = 'Top' if not search_mode else 'Latest'
                print(_("searching_for_query", mode=mode_name, query=query))
                driver.get(search_url)
                random_delay(5, 8)
                tweets = driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
                if not tweets:
                    log_debug(_("no_search_results"))
                    continue
                
                candidate_threads = []
                for i, tweet in enumerate(tweets[:10]):
                    try:
                        tweet_text_element = tweet.find_element(By.CSS_SELECTOR, 'div[data-testid="tweetText"]')
                        tweet_text = tweet_text_element.text
                        tweet_url_element = tweet.find_element(By.XPATH, ".//a[contains(@href, '/status/')]")
                        tweet_url = tweet_url_element.get_attribute('href')
                        tweet_id = tweet_url.split('/')[-1]
                        
                        cursor.execute("SELECT * FROM engagements WHERE target_tweet_id=?", (tweet_id,))
                        if not cursor.fetchone():
                            # Pobierz pełny kontekst od razu
                            full_context = get_conversation_history(driver, tweet_id)
                            candidate_threads.append({
                                "id": tweet_id,
                                "text": tweet_text,
                                "url": tweet_url,
                                "context": full_context, # Przekaż kontekst dalej
                                "index": i
                            })
                            # Wróć na stronę wyników wyszukiwania, bo get_conversation_history zmieniło URL
                            driver.get(search_url)
                            random_delay(2, 3)

                    except Exception as e:
                        log_debug(f"Error processing a candidate tweet: {e}")
                        continue

                if not candidate_threads:
                    log_debug("No fresh, unengaged candidates found in this mode.")
                    continue
                
                log_debug(_("passing_candidates_to_ai", len_candidates=len(candidate_threads)))
                valid_indices = [t['index'] for t in candidate_threads]
                
                # Użyj persona_primer do promptu
                scoring_prompt = f"""{persona_primer} Analyze these tweets discovered during a research expedition on the topic of '{query}'. Your objective is to identify the single most intellectually stimulating thread to engage with. Valid indices are: {valid_indices}. Return a JSON object containing only the 'best_index'. If none are worthy, return an empty JSON."""
                
                response = client_openai.chat.completions.create(model=REFLECTIVE_MODEL, response_format={"type": "json_object"}, messages=[{"role": "user", "content": scoring_prompt}])
                decision = json.loads(response.choices[0].message.content)
                best_index = decision.get("best_index")

                if best_index is None or best_index not in valid_indices:
                    log_debug(_("ai_did_not_select_discovery_target"))
                    continue

                hot_thread = next((t for t in candidate_threads if t["index"] == best_index), None)
                if hot_thread:
                    print(_("discovery_found_promising_thread", hot_thread_id=hot_thread['id']))
                    print(f"Ensuring navigation to the selected thread: {hot_thread['url']}")
                    driver.get(hot_thread['url'])
                    random_delay(5, 8)
                    
                    _engage_with_thread(driver, hot_thread, "discovery_reply")
                    return # Zakończ po udanej akcji
                
            log_debug(_("no_discoveries_in_mode", mode=mode_name))
        except Exception as e:
            print(_("discovery_expedition_error", attempt=attempt + 1, e=e))
            traceback.print_exc()
            
    print(_("expedition_ended_without_results"))

def perform_self_reflection(driver):
    print(_("action_self_reflection"))
    log_action("perform_self_reflection", "system", "STARTED")
    try:
        cursor.execute("SELECT tweet_id, subject, likes FROM observations WHERE status IN ('published', 'reviewed') ORDER BY timestamp DESC LIMIT 10")
        recent_posts = cursor.fetchall()
        if not recent_posts:
            log_debug(_("no_posts_to_analyze"))
            return
        print(_("analyzing_performance_of_posts", len_posts=len(recent_posts)))
        insights = []
        for tweet_id, subject, likes in recent_posts:
            try:
                if not agent_running: return
                if likes is None:
                    driver.get(f"{YOUR_PROFILE_URL}/status/{tweet_id}"); time.sleep(5)
                    like_element = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, f"//a[contains(@href, '/status/{tweet_id}/likes')]//span[@data-testid='app-text-transition-container']")))
                    likes = int(like_element.text.replace(',', '')) if like_element.text else 0
                    cursor.execute("UPDATE observations SET likes=?, status=? WHERE tweet_id=?", (likes, 'reviewed', tweet_id)); conn.commit()
                analysis_prompt = f""" Analyze the performance of this tweet: - Subject: {subject} - Likes: {likes} Based on its success (or failure), generate a single, actionable strategic insight for future content. Focus on the TONE, STYLE, or ANGLE, not just the topic.Example of a good insight: "Cryptic, data-driven statements about market volatility generate high engagement." Example of a bad insight: "Tweets about Solana are good." Generate the insight: """
                response = client_openai.chat.completions.create(model=REFLECTIVE_MODEL, messages=[{"role": "user", "content": analysis_prompt}])
                insight = response.choices[0].message.content.strip()
                insights.append(insight)
                print(_("post_analysis_insight", tweet_id=tweet_id, likes=likes, insight=insight))
                # --- NEW: Dynamic Interest Adaptation ---
                if likes > 5: # If a post is reasonably successful
                    for category, weight in RESEARCH_CATEGORIES.items():
                        # If the post's subject is related to a research category
                        if category.lower() in subject.lower() or subject.lower() in category.lower():
                            # Increase the weight of that category (the more likes, the bigger the boost)
                            RESEARCH_CATEGORIES[category] = weight * (1.0 + (likes / 100.0))
            except Exception as e:
                print(_("failed_to_analyze_post", tweet_id=tweet_id, e=e))
        
        total_weight = sum(RESEARCH_CATEGORIES.values())
        if total_weight > 0:
            for category in RESEARCH_CATEGORIES:
                RESEARCH_CATEGORIES[category] /= total_weight
        
        weights_json = json.dumps({k: round(v, 3) for k, v in RESEARCH_CATEGORIES.items()}, indent=2)
        print(_("updated_category_weights", weights_json=weights_json))
        # Normalize the weights so they sum up to 1 (or close to it)
        total_weight = sum(RESEARCH_CATEGORIES.values())
        if total_weight > 0:
            for category in RESEARCH_CATEGORIES:
                RESEARCH_CATEGORIES[category] /= total_weight
        weights_json = json.dumps({k: round(v, 3) for k, v in RESEARCH_CATEGORIES.items()}, indent=2)
        print(_("updated_category_weights", weights_json=weights_json))
        
        if insights:
            print(_("saving_new_insights_to_memory", len_insights=len(insights)))
            response = client_openai.embeddings.create(input=insights, model="text-embedding-3-small")
            vector_memory.add(embeddings=[d.embedding for d in response.data], documents=insights, metadatas=[{"type": "insight"}]*len(insights), ids=[f"insight_{int(datetime.now().timestamp())}_{i}" for i in range(len(insights))])
        log_action("perform_self_reflection", "system", "SUCCESS")
    except Exception as e:
        print(_("critical_error_self_reflection", e=e))
        log_action("perform_self_reflection", "system", f"FAILURE: {e}")
    finally:
        print(_("resetting_self_reflection_timer"))
        update_last_seen(LAST_REFLECTION_FILE)

def get_conversation_history(driver, leaf_tweet_id):
    """
    Wchodzi na stronę tweeta i próbuje zrekonstruować historię konwersacji,
    idąc "w górę" od najnowszej odpowiedzi.
    Zwraca sformatowany string z historią.
    """
    print(f" reconstruuję historię wątku dla tweeta {leaf_tweet_id}...")
    try:
        driver.get(f"https://twitter.com/i/web/status/{leaf_tweet_id}")
        random_delay(5, 8)
        
        conversation = []
        # Znajdź wszystkie tweety na stronie (oryginalny post + odpowiedzi)
        tweets_on_page = driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
        
        # Heurystyka: Twitter zwykle wyświetla tweety w porządku chronologicznym lub
        # z głównym tweetem na górze i odpowiedziami poniżej.
        # Zbierzemy teksty i autorów, aby móc je sformatować.
        
        for tweet in tweets_on_page:
            try:
                author_handle = tweet.find_element(By.XPATH, ".//div[@data-testid='User-Name']//span[contains(text(), '@')]").text
                tweet_text = tweet.find_element(By.CSS_SELECTOR, 'div[data-testid="tweetText"]').text
                conversation.append(f"{author_handle}: {tweet_text}")
            except NoSuchElementException:
                # Pomiń tweety, w których nie można znaleźć autora lub tekstu (np. usunięte)
                continue
        
        if not conversation:
            return "Could not retrieve conversation history."
            
        # Połącz historię w jeden czytelny blok tekstu
        # Usuwamy duplikaty, które mogą się pojawić, i odwracamy kolejność
        unique_conversation = list(dict.fromkeys(conversation))
        return "\n".join(unique_conversation)

    except Exception as e:
        print(f"Błąd podczas pobierania historii konwersacji: {e}")
        return "Error retrieving history."

# --- The Strategic Brain ---
def evaluate_strategy(driver):
    global CURRENT_GOAL
    print(_("strategy_evaluating_state"))
    
    last_three_actions = [a[0] for a in action_history[-3:]]
    log_debug(_("last_actions", actions=", ".join(last_three_actions) if last_three_actions else "None"))

    # --- NOWA LOGIKA PRIORYTETÓW v2 ---

    # 1. Samorefleksja (konserwacja)
    if check_if_time_passed(LAST_REFLECTION_FILE, SELF_REFLECTION_HOURS):
        CURRENT_GOAL = "SELF_REFLECTION"; print(f"🎯 [Strategy] Goal: {CURRENT_GOAL}"); return

    # 2. Głęboka Analiza (badanie) - WYSOKI PRIORYTET
    cursor.execute("SELECT 1 FROM potential_partners WHERE status='deep_dive_candidate' LIMIT 1")
    if cursor.fetchone() and random.random() < 0.5: # 50% szansy, by nie zdominowało pętli
        CURRENT_GOAL = "DEEP_DIVE"; print(f"🎯 [Strategy] Goal: {CURRENT_GOAL}"); return

    # 3. Wstępna Weryfikacja (selekcja)
    cursor.execute("SELECT 1 FROM potential_partners WHERE status='discovered' LIMIT 1")
    if cursor.fetchone() and random.random() < 0.3:
        CURRENT_GOAL = "VET_POTENTIAL_PARTNER"; print(f"🎯 [Strategy] Goal: {CURRENT_GOAL}"); return

    # 4. Reakcja na wzmianki (networking)
    if check_if_time_passed(LAST_MENTIONS_CHECK_FILE, 0.16) and scan_and_reply_to_mentions(driver):
        update_last_seen(LAST_MENTIONS_CHECK_FILE)
        CURRENT_GOAL = "NURTURE_ENGAGEMENT"; print(f"🎯 [Strategy] Goal: {CURRENT_GOAL}"); return
    
    # 5. Publikacja nowego posta (kreacja)
    cursor.execute("SELECT timestamp FROM observations ORDER BY timestamp DESC LIMIT 1")
    last_post_time_str = cursor.fetchone()
    if not last_post_time_str or (datetime.now() - datetime.fromisoformat(last_post_time_str[0]) > timedelta(hours=4)):
        if "EXPAND_REACH" not in last_three_actions:
            CURRENT_GOAL = "EXPAND_REACH"; print(f"🎯 [Strategy] Goal: {CURRENT_GOAL}"); return

    # 6. Akcje Tła (utrzymanie)
    actions = {"BROWSE_FOLLOWING_FEED": 0.5, "CURIOSITY_DRIVEN_DISCOVERY": 0.3, "MONITOR_CORE_SUBJECTS": 0.2}
    for action_name in last_three_actions:
        if action_name in actions: actions[action_name] *= 0.25
    
    log_debug(_("dynamic_weights", weights=json.dumps({k: round(v, 2) for k, v in actions.items()})))
    CURRENT_GOAL = random.choices(list(actions.keys()), weights=list(actions.values()), k=1)[0]
    print(f"🎯 [Strategy] Goal: {CURRENT_GOAL} (Background activity)")

# --- Main Agent Loop ---
def run_agent():
    global agent_running, CURRENT_GOAL, action_history, _
    driver = None
    shutdown_thread = threading.Thread(target=shutdown_listener, daemon=True)
    shutdown_thread.start()
    try:
        print(_("agent_protocol_header"))
        print(_("exit_prompt"))
        driver = setup_driver()
        if not driver or not login_to_twitter(driver):
            agent_running = False
            return

        # --- NEW: Handle --force-action flag ---
        if args.force_action:
            print(f"\n--- ⚠️  DEBUG MODE: Forcing single action: '{args.force_action}' ⚠️ ---\n")
            
            action_map = {
                'post': lambda d, t: post_tweet(d, *generate_tweet_content(analyze_market_context_for_prompt(conduct_market_research()))),
                'mentions': lambda d, t: scan_and_reply_to_mentions(d),
                'browse': lambda d, t: browse_following_feed_and_engage(d),
                'monitor': lambda d, t: monitor_core_subjects(d, target_override=t), # Pass target here
                'discover': lambda d, t: curiosity_driven_discovery(d),
                'reflect': lambda d, t: perform_self_reflection(d)
                
            }

            # Get the function to run from our map
            action_to_run = action_map.get(args.force_action)

            if action_to_run:
                # Execute the chosen function, passing the driver and the optional target
                action_to_run(driver, args.target) 
            else:
                print(f"Error: Unknown action '{args.force_action}'.")

            print("\n--- ✅ DEBUG ACTION COMPLETE. SHUTTING DOWN. ✅ ---\n")
            return # Exit after the forced action is done
        # --- END of --force-action handler ---

        # This is the original main loop, which runs only if no flag is provided
        while agent_running:
            if not agent_running: break
            update_last_seen(LAST_SEEN_FILE)
            evaluate_strategy(driver)
            action_target = CURRENT_GOAL
            action_history.append((CURRENT_GOAL, action_target, datetime.now()))
            if len(action_history) > 20:
                action_history.pop(0)
            if CURRENT_GOAL == "EXPAND_REACH":
                raw_market_data = conduct_market_research()
                market_summary = analyze_market_context_for_prompt(raw_market_data)
                subject = "Market Sentiment" if "Extreme" in (market_summary or "") else random.choice(CORE_TOPICS)
                subject, content = generate_tweet_content(market_summary, subject_override=subject)
                if content:
                    post_tweet(driver, subject, content)
            elif CURRENT_GOAL == "SELF_REFLECTION":
                perform_self_reflection(driver)
            elif CURRENT_GOAL == "NURTURE_ENGAGEMENT":
                pass
            elif CURRENT_GOAL == "CURIOSITY_DRIVEN_DISCOVERY":
                curiosity_driven_discovery(driver)
            elif CURRENT_GOAL == "BROWSE_FOLLOWING_FEED":
                browse_following_feed_and_engage(driver)
            elif CURRENT_GOAL == "MONITOR_CORE_SUBJECTS":
                monitor_core_subjects(driver)
            # --- NOWA GAŁĄŹ OBSŁUGI CELU ---
            elif CURRENT_GOAL == "VET_POTENTIAL_PARTNER":
                # --- POCZĄTEK BLOKU DO WKLEJENIA ---

                # Sprawdź, ilu partnerów zweryfikowano dzisiaj
                cursor.execute("SELECT COUNT(*) FROM action_log WHERE action_name='vet_potential_partner' AND DATE(timestamp) = DATE('now', 'localtime')")
                vetted_today = cursor.fetchone()[0]

                VETTING_DAILY_LIMIT = 2  # Ustaw dzienny limit tutaj, np. 10 weryfikacji

                if vetted_today < VETTING_DAILY_LIMIT:
                    cursor.execute("SELECT screen_name FROM potential_partners WHERE status='discovered' ORDER BY RANDOM() LIMIT 1")
                    partner_to_vet = cursor.fetchone()
                    if partner_to_vet:
                        # Wykonaj weryfikację
                        vet_potential_partner(driver, partner_to_vet[0])
                    else:
                        log_debug("VET_POTENTIAL_PARTNER goal was set, but no discovered partners were found.")
                else:
                    log_debug(f"Daily vetting limit of {VETTING_DAILY_LIMIT} reached. Skipping for today.")
            elif CURRENT_GOAL == "DEEP_DIVE":
                cursor.execute("SELECT screen_name FROM potential_partners WHERE status='deep_dive_candidate' ORDER BY RANDOM() LIMIT 1")
                partner_to_analyze = cursor.fetchone()
                if partner_to_analyze:
                    perform_deep_dive(driver, partner_to_analyze[0])
                else:
                    log_debug("DEEP_DIVE goal was set, but no candidates were found.")
            
            
            if agent_running:
                sleep_duration = random.randint(MIN_SLEEP_DURATION, MAX_SLEEP_DURATION)
                print(_("cycle_complete_next_action", sleep_duration=sleep_duration))
                for i in range(sleep_duration):
                    if not agent_running:
                        break
                    time.sleep(1)
    except KeyboardInterrupt:
        agent_running = False
        print(_("ctrl_c_detected"))
    except Exception as e:
        agent_running = False
        print(_("main_loop_system_error", e=e))
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass
        conn.close()
        print(_("agent_shutdown_complete"))

if __name__ == "__main__":
    (run_agent())