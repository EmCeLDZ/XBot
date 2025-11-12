# X_Agent v2.1.0 - "The Sentient Strategist"

**X_Agent** is a sophisticated, autonomous AI agent designed to manage a Twitter (X) presence with a high degree of strategic intelligence. Evolving beyond simple automation, this agent operates as a **learning entity**, using a browser to simulate human-like behavior, build a context-aware presence, and adapt its strategy based on real-time feedback.

The agent's personality and behavior are fully customizable through a powerful and detailed prompt template, allowing you to deploy a unique, intelligent persona for any niche or communication style.

## ✨ Core Features

*   **🧠 Sentient Strategy Engine:** The agent operates on a goal-oriented architecture, choosing actions like `EXPAND_REACH`, `NURTURE_ENGAGEMENT`, or `SELF_REFLECTION`. Its decisions are now enhanced by an **action cooldown** mechanism to ensure behavioral diversity and prevent repetitive loops.
*   **💡 Self-Awareness Module:** Before engaging in any conversation, the agent consults its vector memory to recall its **own past statements**. This ensures all interactions are thematically consistent, building a coherent and evolving persona.
*   **🌱 Adaptive Learning Loop:** The agent periodically reviews its own tweet performance (likes) to understand what resonates with its audience. It then **dynamically adjusts its own interests**, prioritizing research into topics that prove to be successful.
*   **🤝 Proactive Networking:** The agent doesn't just talk; it listens. It actively monitors key profiles, discovers new potential partners in its ecosystem, and nurtures these connections through subtle, strategic interactions.
*   **👻 Human-like Browser Automation:** Utilizes `selenium-stealth` to avoid bot detection and performs all actions with randomized delays, mimicking a real user's rhythm and operational tempo.
*   **🔧 Fully Configurable Persona:** The agent's entire identity—from its core personality to its strategic interests—is controlled via a simple `.env` file. No code changes are needed to completely transform the agent.
*   ** multi-faceted Engagement:**
    *   Publishes original content based on real-time market analysis or its evolving core topics.
    *   Scans the "Following" feed to engage with relevant, high-quality conversations.
    *   Replies to mentions to nurture community interaction.
    *   Conducts "curiosity-driven" research expeditions to stay ahead of emerging trends.

---

## ⚠️ Important Disclaimer & Ethical Considerations

This project automates actions on the X platform. While it is designed to simulate human behavior, using automation tools may be against the platform's Terms of Service. **Use this agent responsibly and at your own risk.**

*   **Human Supervision is Key:** The agent is designed to run in a dedicated, visible browser window. It is crucial that you **do not touch or minimize the browser** while the agent is active. Any interference can break the automation flow.
*   **Authenticity:** The goal of this project is to create an authentic, strategic presence, not to spam or manipulate. The default prompt is a starting point for creating insightful commentary, not for spreading misinformation.
*   **Cost:** This agent does not use the official, paid X API. It operates entirely through browser automation. Your only operational cost is for **OpenAI API usage**.

## 🚀 Getting Started

### Prerequisites
*   Python 3.10+
*   A compatible web browser: Google Chrome, Brave, or Microsoft Edge.
*   An existing X/Twitter account: You must be logged into your account in the browser profile you intend to use.
*   An OpenAI API Key.

### 1. Installation
Clone the repository and install the required Python packages:
```bash
git clone https://github.com/EmCeLDZ/XBot.git
cd XBot
pip install -r requirements.txt
2. Configuration
The agent is configured entirely through an .env file.
Create your config file: Make a copy of the example file and name it .env.
code
Bash
# On Windows
copy .env.example .env

# On macOS/Linux
cp .env.example .env
Edit the .env file: Open the new .env file and fill in the values. The file contains detailed comments explaining each variable. The most critical ones are:
OPENAI_API_KEY: Your secret key from OpenAI.
X_PROFILE_URL: The full URL to your X profile (e.g., https://twitter.com/YourProfileName).
BROWSER_TYPE: Set to chrome, brave, or edge.
BROWSER_EXECUTABLE_PATH: The full, absolute path to your browser's executable file.
PROFILE_PATH: The path to your browser's user data directory. This is crucial for the agent to use your logged-in session.
💡 Tip: To find your browser profile path, you can typically navigate to chrome://version, brave://version, or edge://version in your browser.
3. First Run & Login
Before running the agent for the first time, you need to ensure it's logged into X.
Run the script once. The browser will open.
Manually log into your X account within that browser window. Be sure to check the "Remember me" box.
Once logged in, close the browser and terminate the script (Ctrl+C or by typing exit).
Thanks to the PROFILE_PATH setting, the agent will now use this logged-in session for all future runs.
4. Running the Agent
Launch the agent from your terminal:
code
Bash
python x_agent.py
The agent will initialize, open a browser window, and begin its operational cycle. You can terminate it at any time by typing exit in the console and pressing Enter, or by pressing Ctrl+C.
Remember: For reliable operation, do not interact with or minimize the browser window while the agent is running!