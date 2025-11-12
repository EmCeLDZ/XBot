from openai import OpenAI
import sqlite3
import time
import random
import os
import threading
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


# --- X_Agent v2.0.0 "The Functional Strategist" Configuration ---
load_dotenv()
# --- NEW BROWSER CONFIGURATION ---
BROWSER_TYPE = os.getenv('BROWSER_TYPE', 'chrome').lower() 
BROWSER_EXECUTABLE_PATH = os.getenv('BROWSER_EXECUTABLE_PATH') 
YOUR_PROFILE_URL = os.getenv('X_PROFILE_URL')
LANGUAGE = os.getenv('AGENT_LANGUAGE', 'en')
PROFILE_PATH = os.getenv('PROFILE_PATH')

# --- Strategic Parameters ---
DEBUG_MODE = os.getenv('DEBUG_MODE')
CORE_TOPICS = json.loads(os.getenv('CORE_TOPICS'))
RESEARCH_CATEGORIES = json.loads(os.getenv('RESEARCH_CATEGORIES'))
SESSION_RESET_HOURS = int(os.getenv('SESSION_RESET_HOURS'))
SELF_REFLECTION_HOURS = int(os.getenv('SELF_REFLECTION_HOURS'))
LAST_SEEN_FILE = "last_seen.txt"; LAST_REFLECTION_FILE = "last_reflection.txt"; LAST_MENTIONS_CHECK_FILE = "last_mentions_check.txt"

# --- Model & Chance Configuration ---
REFLECTIVE_MODEL = "gpt-3.5-turbo"; CREATION_MODEL = "gpt-4-turbo"
REPLY_CHANCE = 0.8; LIKE_CHANCE = 0.8
agent_running = True; CURRENT_GOAL = "INITIALIZING"; action_history = []

# --- Localization ---
translations = {}

def load_translations(lang_code):
    global translations
    try:
        with open(f"locales/{lang_code}.json", "r", encoding="utf-8") as f:
            translations = json.load(f)
    except FileNotFoundError:
        print(f"Language file for '{lang_code}' not found. Falling back to 'en'.")
        with open("locales/en.json", "r", encoding="utf-8") as f:
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

prompt_template = os.getenv('PROMPT_TEMPLATE')
if not prompt_template:
    print(_("prompt_template_not_found"))
    exit()

def init_db():
    conn = sqlite3.connect("agent_state.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS observations (timestamp TEXT, tweet_id TEXT PRIMARY KEY, subject TEXT, content TEXT, status TEXT, likes INTEGER DEFAULT 0, retweets INTEGER DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS engagements (timestamp TEXT, engagement_type TEXT, target_tweet_id TEXT, content TEXT, status TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS potential_partners (screen_name TEXT PRIMARY KEY, discovery_date TEXT, status TEXT)''')
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

def setup_driver():
    """
    Sets up the Selenium WebDriver using the built-in Selenium Manager.
    Selenium Manager automatically detects the browser, downloads the correct driver,
    and configures it without any external libraries.
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
    if PROFILE_PATH:
        options.add_argument(f"--user-data-dir={PROFILE_PATH}")
        options.add_argument("--profile-directory=Default")
    
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument('--log-level=3')
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    
    try:
        print(_("initializing_browser_with_selenium_manager", browser=BROWSER_TYPE.capitalize()))
        
        # --- Simplified Driver Initialization ---
        # We no longer create a 'Service' object. Selenium Manager handles it automatically.
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

# --- AI & Content Generation ---
def get_autoreflaction_for_prompt(subject, current_goal, market_context=""):
    print(_("generating_reflection_context"))
    try:
        query_text = "strategic insights about tweet performance"
        response = client_openai.embeddings.create(input=[query_text], model="text-embedding-3-small")
        strategic_insights_data = vector_memory.query(query_embeddings=[response.data[0].embedding], n_results=3, where={"type": "insight"})
        strategic_insights = "\n".join([f"- {doc}" for doc in (strategic_insights_data.get('documents', [[]])[0])])
    except Exception as e:
        print(_("memory_query_error", e=e))
        strategic_insights = "Error."
    return f"1. CONTEXTUAL SUMMARY:\n{market_context or 'No specific market event.'}\n\n2. STRATEGIC INSIGHTS:\n{strategic_insights or 'None.'}"

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
        print(_("navigating_to_tweet", url=target_tweet['url']))
        driver.get(target_tweet['url'])
        random_delay(5, 8)
        if not agent_running: return
        reflection_report = get_autoreflaction_for_prompt(f"Engage with {engagement_type}", CURRENT_GOAL, target_tweet['text'])
        reply_prompt = prompt_template.format(observed_subject=f"a comment on a post: '{target_tweet['text']}'", successful_examples=reflection_report)
        response = client_openai.chat.completions.create(model=CREATION_MODEL, messages=[{"role": "user", "content": reply_prompt}])
        reply_content = response.choices[0].message.content.strip().strip('"')
        if len(reply_content) > 280:
            shortening_prompt = f"CRITICAL: Shorten this reply to WELL UNDER 280 characters. TEXT: '{reply_content}'"
            response = client_openai.chat.completions.create(model=REFLECTIVE_MODEL, messages=[{"role": "user", "content": shortening_prompt}])
            reply_content = response.choices[0].message.content.strip().strip('"')
        print(_("prepared_strategic_comment", reply_content=reply_content))
        reply_box = WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-testid="tweetTextarea_0"]')))
        type_via_clipboard(driver, reply_box, reply_content)
        random_delay()
        post_button_xpath = "//button[(@data-testid='tweetButton' or @data-testid='tweetButtonInline') and not(@aria-disabled='true')]"
        post_button = WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, post_button_xpath)))
        robust_click(driver, post_button)
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.XPATH, "//div[@data-testid='toast']")))
        print(_("comment_sent_success", target_tweet_id=target_tweet['id']))
        cursor.execute("INSERT INTO engagements VALUES (datetime('now'), ?, ?, ?, ?)", (engagement_type, target_tweet['id'], reply_content, 'success')); conn.commit()
        log_action(engagement_type, target_tweet['id'], "SUCCESS")
    except Exception as e:
        print(_("thread_engagement_error", e=e))
        log_action(engagement_type, target_tweet.get('id', 'unknown'), f"FAILURE: {e}")

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

def scan_and_reply_to_mentions(driver):
    print(_("action_scan_mentions"))
    log_action("scan_and_reply_to_mentions", "system", "STARTED")
    try:
        driver.get("https://twitter.com/notifications/mentions")
        random_delay()
        cursor.execute("SELECT target_tweet_id FROM engagements WHERE engagement_type='reply'")
        already_replied_ids = {row[0] for row in cursor.fetchall()}
        mentions = driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
        if not mentions:
            log_debug(_("no_tweet_elements_on_mentions_page"))
            return False
        new_mentions = []
        one_day_ago = datetime.now().astimezone() - timedelta(days=1)
        for mention in mentions[:5]:
            try:
                time_element = mention.find_element(By.TAG_NAME, 'time')
                if datetime.fromisoformat(time_element.get_attribute('datetime').replace('Z', '+00:00')) < one_day_ago:
                    log_debug(_("skipping_old_mention"))
                    continue
                mention_id = mention.find_element(By.XPATH, ".//a[contains(@href, '/status/')]").get_attribute('href').split('/')[-1]
                if mention_id not in already_replied_ids:
                    new_mentions.append({"id": mention_id, "text": mention.find_element(By.CSS_SELECTOR, 'div[data-testid="tweetText"]').text, "element": mention})
            except:
                continue
        if not new_mentions:
            log_debug(_("no_new_unhandled_mentions"))
            return False
        target_mention = new_mentions[0]
        print(_("found_new_mention", target_mention_id=target_mention['id']))
        if random.random() > REPLY_CHANCE:
            log_debug(_("skipped_mention_reply_by_chance", target_mention_id=target_mention['id']))
            return True
        _engage_with_thread(driver, {"id": target_mention['id'], "text": target_mention['text'], "url": f"https://twitter.com/i/web/status/{target_mention['id']}"}, 'mention_reply')
        return True
    except Exception as e:
        print(_("mentions_analysis_error", e=e))
        log_action("scan_and_reply_to_mentions", "system", f"FAILURE: {e}")
        return False

# --- RESTORED AND IMPROVED FUNCTION ---
def browse_following_feed_and_engage(driver):
    print(_("action_browse_following_feed"))
    log_action("browse_following_feed", "system", "STARTED")
    try:
        driver.get("https://twitter.com/home")
        # Wait for a core element of the page to be visible, like the tweet composer
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-testid="tweetTextarea_0"]'))
        )
        print("Home page main components loaded.")
        random_delay(2, 4) # Extra delay for dynamic elements to settle

        try:
            # --- START OF THE NEW, FINAL STRATEGY ---
            # This XPath finds any link (<a> tag) that has a descendant element (<span>)
            # which contains the exact text "Following". This is the most robust method
            # when other attributes like href or data-testid are unreliable.
            following_tab_xpath = "//a[.//span[text()='Following']]"
            
            print("Attempting to find and click the 'Following' tab...")
            following_tab = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, following_tab_xpath))
            )
            
            robust_click(driver, following_tab)
            print("Successfully switched to the 'Following' feed.")
            random_delay(3, 5) # Wait for the new feed to load
            # --- END OF THE NEW, FINAL STRATEGY ---
        except Exception as e:
            # Taking a screenshot on failure for debugging purposes
            screenshot_path = f"debug_screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            driver.save_screenshot(screenshot_path)
            print(f"Could not switch to 'Following' tab. A screenshot has been saved to: {screenshot_path}")
            log_debug(f"Error details: {e}")
        
        # Instead of scrolling, we simply fetch a solid pool of tweets from the top of the page
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

                # --- IMPROVED FILTERING LOGIC WITH FULL LOGGING ---
                author_handle = tweet.find_element(By.XPATH, ".//div[@data-testid='User-Name']//span[contains(text(), '@')]").text.strip().lower()
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

                text_content = tweet.find_element(By.CSS_SELECTOR, 'div[data-testid="tweetText"]').text
                if len(text_content) < 40:
                    log_debug(_("skipping_short_tweet", tweet_id=tweet_id))
                    continue
                
                # If it passed all filters, it's a good candidate
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
        
        # --- IMPROVED PROMPT WITH A REQUEST FOR JUSTIFICATION ---
        scoring_prompt = f"""
        You are Dr. Pathogen. Analyze these FRESH tweets from your 'following' feed. Identify the single most intellectually stimulating one to comment on.
        Valid indices are: {valid_indices}.

        Return a JSON object with 'best_index' and a 'reason' for your choice.
        Example: {{"best_index": {random.choice(valid_indices) if valid_indices else 0}, "reason": "This post discusses on-chain data, which is a core research area."}}
        If none are truly worthy, return an empty JSON.
        """
        
        response = client_openai.chat.completions.create(model=REFLECTIVE_MODEL, response_format={"type": "json_object"}, messages=[{"role": "user", "content": scoring_prompt}])
        decision = json.loads(response.choices[0].message.content)
        best_index = decision.get("best_index")

        # --- IMPROVED AI DECISION LOGGING ---
        if best_index is None or best_index not in valid_indices:
            print(_("ai_did_not_select_target"))
            log_debug(_("ai_decision_reason", reason=decision.get('reason', 'No justification provided.')))
            return
            
        target_tweet = next((t for t in fresh_targets if t["index"] == best_index), None)
        if not target_tweet:
            print(_("critical_error_finding_target", best_index=best_index))
            return

        print(_("strategy_selected_fresh_target", target_tweet_id=target_tweet['id'], reason=decision.get('reason')))
        _engage_with_thread(driver, target_tweet, "following_feed_reply")

    except Exception as e:
        print(_("error_browsing_feed", e=e))
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
    primer = "You are a market analyst. Based on raw data, provide a one-sentence clinical summary for Dr. Pathogen. Interpret BTC.D, F&G, and SOL's relative performance to BTC."
    prompt = f"{primer}\nRaw Data:\n{raw_market_data}\n\nProvide your one-sentence clinical summary:"
    try:
        response = client_openai.chat.completions.create(model=REFLECTIVE_MODEL, messages=[{"role": "user", "content": prompt}])
        summary = response.choices[0].message.content.strip()
        print(_("analyst_conclusion", summary=summary))
        return summary
    except Exception as e:
        print(_("internal_analyst_error", e=e))
        return "Failed to analyze market state."

def monitor_core_subjects(driver):
    print(_("action_monitor_core_subjects"))
    log_action("monitor_core_subjects", "system", "STARTED")
    target_profile = random.choice(CORE_TOPICS)
    try:
        driver.get(f"https://twitter.com/{target_profile[1:]}")
        random_delay(5,10)
        tweets = driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
        if not tweets:
            log_debug(_("no_tweets_on_profile", target_profile=target_profile))
            return

        # Analyze more tweets by increasing the sample size and removing the break
        for target_tweet in random.sample(tweets, min(len(tweets), 5)): # Increased sample size to 5
            try:
                tweet_text = target_tweet.find_element(By.CSS_SELECTOR, 'div[data-testid="tweetText"]').text
                log_debug(_("scanning_post", tweet_text_preview=tweet_text[:40]))
                
                # ... (logic for finding partners remains the same) ...
                mentioned_handles = re.findall(r'@(\w+)', tweet_text)
                if not mentioned_handles:
                    log_debug("No mentions found in this tweet.")

                for handle in mentioned_handles:
                    screen_name = f"@{handle}"
                    if screen_name not in CORE_TOPICS:
                        cursor.execute("SELECT * FROM potential_partners WHERE screen_name=?", (screen_name,))
                        if not cursor.fetchone():
                            print(_("discovered_new_potential_entity", screen_name=screen_name))
                            cursor.execute("INSERT INTO potential_partners (screen_name, discovery_date, status) VALUES (?, ?, ?)", (screen_name, datetime.now().isoformat(), 'discovered'))
                            conn.commit()

                if random.random() <= LIKE_CHANCE:
                    # Check if the tweet is already liked (contains an 'unlike' button)
                    if target_tweet.find_elements(By.XPATH, ".//button[@data-testid='unlike']"):
                         log_debug("Tweet already liked, skipping like action.")
                         continue # Move to the next tweet in the loop

                    like_buttons = target_tweet.find_elements(By.XPATH, ".//button[@data-testid='like']")
                    if like_buttons:
                        robust_click(driver, like_buttons[0])
                        print(_("liked_post_on_profile", target_profile=target_profile))
                        log_action("monitor_core_subjects", target_profile, "SUCCESS_LIKED")
                
                # The 'break' is removed, so the loop will continue for all sampled tweets

            except NoSuchElementException:
                log_debug(_("skipping_post_no_text", target_profile=target_profile))
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
                        tweet_text = tweet.find_element(By.CSS_SELECTOR, 'div[data-testid="tweetText"]').text
                        tweet_id = tweet.find_element(By.XPATH, ".//a[contains(@href, '/status/')]").get_attribute('href').split('/')[-1]
                        cursor.execute("SELECT * FROM engagements WHERE target_tweet_id=?", (tweet_id,))
                        if not cursor.fetchone():
                            candidate_threads.append({"id": tweet_id, "text": tweet_text, "url": tweet.find_element(By.XPATH, ".//a[contains(@href, '/status/')]").get_attribute('href'), "index": i})
                    except:
                        continue

                if not candidate_threads:
                    log_debug("No fresh, unengaged candidates.")
                    continue
                
                log_debug(_("passing_candidates_to_ai", len_candidates=len(candidate_threads)))
                valid_indices = [t['index'] for t in candidate_threads]
                scoring_prompt = f"You are Dr. Pathogen. Analyze these tweets about '{query}'. Identify the single most intellectually stimulating one. Valid indices are: {valid_indices}. Return JSON with 'best_index'."
                response = client_openai.chat.completions.create(model=REFLECTIVE_MODEL, response_format={"type": "json_object"}, messages=[{"role": "user", "content": scoring_prompt}])
                decision = json.loads(response.choices[0].message.content)
                best_index = decision.get("best_index")

                if best_index is None or best_index not in valid_indices:
                    log_debug(_("ai_did_not_select_discovery_target"))
                    continue

                hot_thread = next(t for t in candidate_threads if t["index"] == best_index)
                print(_("discovery_found_promising_thread", hot_thread_id=hot_thread['id']))
                _engage_with_thread(driver, hot_thread, "discovery_reply")
                return
            log_debug(_("no_discoveries_in_mode", mode=mode_name))
        except Exception as e:
            print(_("discovery_expedition_error", attempt=attempt + 1, e=e))
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
                analysis_prompt = f"Analyze tweet performance:\n- Subject: {subject}\n- Likes: {likes}\nGenerate a single, concise strategic insight for future posts. What subject categories perform best?"
                response = client_openai.chat.completions.create(model=REFLECTIVE_MODEL, messages=[{"role": "user", "content": analysis_prompt}])
                insight = response.choices[0].message.content.strip()
                insights.append(insight)
                print(_("post_analysis_insight", tweet_id=tweet_id, likes=likes, insight=insight))
                if likes > 5:
                    for category, weight in RESEARCH_CATEGORIES.items():
                        if category.lower() in subject.lower() or subject.lower() in category.lower():
                            RESEARCH_CATEGORIES[category] = weight * (1.0 + (likes / 100.0))
            except Exception as e:
                print(_("failed_to_analyze_post", tweet_id=tweet_id, e=e))
        
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

# --- The Strategic Brain ---
def evaluate_strategy(driver):
    global CURRENT_GOAL
    print(_("strategy_evaluating_state"))
    last_action_info = action_history[-1] if action_history else (_("no_last_action"),)
    log_debug(_("last_action", last_action=last_action_info[0]))

    if check_if_time_passed(LAST_REFLECTION_FILE, SELF_REFLECTION_HOURS):
        cursor.execute("SELECT 1 FROM observations WHERE status IN ('published', 'reviewed') LIMIT 1")
        if cursor.fetchone():
            CURRENT_GOAL = "SELF_REFLECTION"
            print(_("strategy_goal_self_reflection", goal=CURRENT_GOAL))
            return
        else:
            update_last_seen(LAST_REFLECTION_FILE)

    if check_if_time_passed(LAST_MENTIONS_CHECK_FILE, 0.16):
        update_last_seen(LAST_MENTIONS_CHECK_FILE)
        if scan_and_reply_to_mentions(driver):
            CURRENT_GOAL = "NURTURE_ENGAGEMENT"
            print(_("strategy_goal_nurture_engagement", goal=CURRENT_GOAL))
            return
        else:
            log_debug(_("mention_scan_completed"))

    cursor.execute("SELECT timestamp FROM observations ORDER BY timestamp DESC LIMIT 1")
    last_post_time_str = cursor.fetchone()
    if not last_post_time_str or (datetime.now() - datetime.fromisoformat(last_post_time_str[0]) > timedelta(hours=4)):
        if 'EXPAND_REACH' not in [a[0] for a in action_history[-3:]]:
            CURRENT_GOAL = "EXPAND_REACH"
            print(_("strategy_goal_expand_reach", goal=CURRENT_GOAL))
            return

    actions = {"BROWSE_FOLLOWING_FEED": 0.5, "CURIOSITY_DRIVEN_DISCOVERY": 0.3, "MONITOR_CORE_SUBJECTS": 0.2}
    CURRENT_GOAL = random.choices(list(actions.keys()), weights=list(actions.values()), k=1)[0]
    print(_("strategy_goal_weighted_random", goal=CURRENT_GOAL))

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
        while agent_running:
            if not agent_running: break
            update_last_seen(LAST_SEEN_FILE)
            evaluate_strategy(driver)
            
            action_target = CURRENT_GOAL 
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
            
            action_history.append((CURRENT_GOAL, action_target, datetime.now()))
            if len(action_history) > 20:
                action_history.pop(0)

            if agent_running:
                sleep_duration = random.randint(5, 10)
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