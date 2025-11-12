# X_Agent v2.0.0 - "The Functional Strategist"

**X_Agent** is a sophisticated, autonomous AI agent designed to manage a Twitter (X) presence with a high degree of strategic intelligence. Unlike typical bots that rely on the official (and costly) API, X_Agent operates through a browser, simulating human-like behavior to build a genuine, context-aware presence on the platform.

The agent's personality and behavior are fully customizable through a powerful and detailed prompt template in the configuration file, allowing you to tailor it to any niche or communication style.

---

## ✨ Core Features

*   **🧠 Intelligent Strategy Engine:** The agent doesn't just act randomly. It evaluates its state and sets goals like `EXPAND_REACH`, `NURTURE_ENGAGEMENT`, or `SELF_REFLECTION` based on timing and past actions.
*   **Vector Memory (ChromaDB):** Remembers its most successful posts and uses them as a "style guide" to maintain a consistent and effective tone, learning from its own experience.
*   **🔄 Self-Reflection Loop:** Periodically reviews its own tweet performance (likes) to learn what content resonates with the audience and adjusts its strategy accordingly.
*   **Human-like Browser Automation:** Uses `selenium-stealth` to avoid bot detection and performs all actions with randomized delays, mimicking a real user's rhythm.
*   **Modular & Configurable:** Easily configure the agent's persona, target topics, browser choice, and behavior through a simple `.env` file. No code changes are needed.
*   **Multi-Faceted Engagement:**
    *   Publishes original content based on real-time market analysis or predefined core topics.
    *   Scans the "Following" feed to engage with relevant conversations.
    *   Monitors key subject profiles to discover new potential partners and topics.
    *   Replies to mentions to nurture community interaction.
    *   Conducts "curiosity-driven" research on emerging trends.

---

## ⚠️ Important Disclaimer & Ethical Considerations

This project automates actions on the X platform. While it is designed to simulate human behavior, using automation tools may be against the platform's Terms of Service. **Use this agent responsibly and at your own risk.**

*   **Human Supervision is Key:** The agent is designed to run in a dedicated, visible browser window. It is crucial that you **do not touch or minimize the browser** while the agent is active. Any interference can break the automation flow.
*   **Authenticity:** The goal of this project is to create an authentic, strategic presence, not to spam or manipulate. The default prompt is a starting point for creating insightful commentary, not for spreading misinformation.
*   **Cost:** This agent does **not** use the official, paid X API. It operates entirely through browser automation. Your only operational cost is for OpenAI API usage.

---

## 🚀 Getting Started

### Prerequisites

1.  **Python 3.10+**
2.  **A compatible web browser:** Google Chrome, Brave, or Microsoft Edge.
3.  **An existing X/Twitter account:** You must be logged into your account in the browser profile you intend to use.
4.  **An OpenAI API Key.**

### 1. Installation

Clone the repository and install the required Python packages:

```bash
git clone https://github.com/EmCeLDZ/XBot.git
cd XBot
pip install -r requirements.txt
```

### 2. Configuration

The agent is configured entirely through an `.env` file.

1.  **Create your config file:** Make a copy of the example file and name it `.env`.
    ```bash
    # On Windows
    copy .env.example .env

    # On macOS/Linux
    cp .env.example .env
    ```

2.  **Edit the `.env` file:** Open the new `.env` file and fill in the values. The file contains detailed comments explaining each variable. The most critical ones are:
    *   `OPENAI_API_KEY`: Your secret key from OpenAI.
    *   `X_PROFILE_URL`: The full URL to your X profile (e.g., `https://twitter.com/YourProfileName`).
    *   `BROWSER_TYPE`: Set to `chrome`, `brave`, or `edge`.
    *   `BROWSER_EXECUTABLE_PATH`: The full, absolute path to your browser's executable file.
    *   `PROFILE_PATH`: The path to your browser's user data directory. This is crucial for the agent to use your logged-in session.

    > **💡 Tip:** To find your browser profile path, you can typically navigate to `chrome://version`, `brave://version`, or `edge://version` in your browser.

### 3. First Run & Login

Before running the agent for the first time, you need to ensure it's logged into X.

1.  Run the script once. The browser will open.
2.  **Manually log into your X account** within that browser window. Be sure to check the "Remember me" box.
3.  Once logged in, close the browser and terminate the script (`Ctrl+C` or by typing `exit`).
4.  Thanks to the `PROFILE_PATH` setting, the agent will now use this logged-in session for all future runs.

### 4. Running the Agent

Launch the agent from your terminal:

```bash
python x_agent.py
```

The agent will initialize, open a browser window, and begin its operational cycle. You can terminate it at any time by typing `exit` in the console and pressing Enter, or by pressing `Ctrl+C`.

**Remember: For reliable operation, do not interact with or minimize the browser window while the agent is running!**
