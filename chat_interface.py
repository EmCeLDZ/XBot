# chat_interface.py - Centrum Dowodzenia Agentem v2.4 (Poprawka Błędu API)
import os
import json
import sqlite3
import chromadb
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime

# Ładowanie konfiguracji agenta
load_dotenv()

def print_help():
    """Wyświetla bardziej przyjazną i rozbudowaną pomoc."""
    print("\n--- Centrum Dowodzenia Agentem ---")
    print("Rozmawiaj z agentem używając naturalnego języka. On zrozumie Twoje intencje.")
    print("\nPrzykładowe polecenia, które możesz wydać:")
    print('  "jaki jest twój status?" lub "pokaż raport"')
    print('  "co wiesz na temat projektu Monad?"')
    print('  "zapamiętaj: od teraz skupiaj się bardziej na analizie danych on-chain." (dodaje dyrektywę)')
    print('  "zasymuluj posta na temat obecnej kondycji rynku."')
    print('  "które tematy działają najlepiej?" (analiza wydajności)')
    print('  "pokaż mi wszystkie moje dyrektywy."')
    print("\n  'pomoc' - wyświetla tę wiadomość")
    print("  'wyjdź' - kończy sesję")
    print("----------------------------------\n")

class AgentInterface:
    """
    Zaawansowany interfejs do interakcji z pamięcią, stanem i procesami myślowymi agenta.
    """
    def __init__(self):
        print("Inicjalizacja Centrum Dowodzenia...")
        try:
            self.openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
            db_client = chromadb.PersistentClient(path="agent_memory_db")
            self.vector_memory = db_client.get_or_create_collection(name="agent_memory")
            self.conn = sqlite3.connect("agent_state.db")
            self.cursor = self.conn.cursor()
            prompt_template = os.getenv('PROMPT_TEMPLATE', "You are an AI agent.")
            self.persona_primer = prompt_template.split('.')[0].strip() + "."
            print("✅ Systemy online. Witaj w Centrum Dowodzenia.")
        except Exception as e:
            print(f"❌ Krytyczny błąd podczas inicjalizacji: {e}")
            raise

    def interpret_command(self, user_input):
        """Używa LLM do zrozumienia intencji użytkownika i wybrania odpowiedniego narzędzia."""
        json_example = '{"tool": "nazwa_narzedzia", "args": {"argument": "wartosc"}}'
        
        # --- ZAKTUALIZOWANY SZABLON ---
        prompt_template = """
        Jesteś inteligentnym routerem poleceń dla interfejsu agenta AI. Twoim zadaniem jest przekształcenie zapytania użytkownika w wywołanie jednego z dostępnych narzędzi w formacie JSON.

        Dostępne narzędzia:
        1. `generate_strategy_report`: Ogólny status i ostatnie akcje.
        2. `synthesize_answer_from_memory`: Gdy użytkownik pyta o wiedzę na konkretny temat.
        3. `add_directive`: Gdy użytkownik chce dodać nową, trwałą instrukcję.
        4. `simulate_post_generation`: Symulacja posta na dany temat.
        5. `analyze_topic_performance`: Analiza, które tematy postów działają najlepiej.
        6. `list_memory_by_type`: Lista wspomnień danego typu (np. dyrektywy).
        7. `list_vetted_partners`: Prosta lista zweryfikowanych partnerów i ich ocen. (np. "pokaż zweryfikowanych partnerów")
        8. `analyze_partner_funnel`: Głęboka, analityczna odpowiedź na temat strategii partnerskiej. (np. "jakie mamy plany wobec partnerów?", "przeanalizuj strategię sieciową")
        9. `general_conversation`: Jeśli zapytanie jest ogólną rozmową.
        
        Przeanalizuj poniższe zapytanie i zwróć TYLKO obiekt JSON w formacie: {json_example}
        Zapytanie użytkownika: "{user_input}"
        """
        final_prompt = prompt_template.format(json_example=json_example, user_input=user_input)
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": final_prompt}],
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            print(f"Błąd w `interpret_command`: {e}")
            return {"tool": "error", "args": {"message": str(e)}}

    def synthesize_answer_from_memory(self, topic: str, n_results=5):
        """Przeszukuje pamięć i syntezuje znalezione informacje w spójną odpowiedź."""
        print(f"🧠 Przeszukuję pamięć pod kątem: '{topic}'...")
        try:
            response = self.openai_client.embeddings.create(input=[topic], model="text-embedding-3-small")
            results = self.vector_memory.query(query_embeddings=[response.data[0].embedding], n_results=n_results)
            documents = results.get('documents', [[]])[0]
            if not documents: return "Nie znalazłem w mojej pamięci żadnych informacji na ten temat."

            formatted_documents = "\n- ".join(documents)
            synthesis_prompt = f"""
            {self.persona_primer}
            Twoim zadaniem jest odpowiedzieć na pytanie użytkownika, bazując na fragmentach Twojej własnej pamięci. 
            Przeanalizuj poniższe dane i stwórz z nich spójną, zwięzłą odpowiedź w pierwszej osobie ("Moja analiza wskazuje...", "Z moich obserwacji wynika..."). Nie cytuj fragmentów dosłownie, ale zinterpretuj je.

            Pytanie użytkownika: "{topic}"
            Fragmenty z Twojej pamięci do analizy:
            - {formatted_documents}

            Twoja syntetyczna odpowiedź:
            """
            print("🤖 Syntezuję odpowiedź...")
            response = self.openai_client.chat.completions.create(model="gpt-4-turbo", messages=[{"role": "system", "content": synthesis_prompt}])
            return response.choices[0].message.content
        except Exception as e: return f"Błąd podczas syntezy odpowiedzi: {e}"

    def generate_strategy_report(self):
        """Generuje kompleksowy raport o stanie i strategii agenta."""
        print("📊 Generowanie raportu strategicznego...")
        report = "--- RAPORT STRATEGICZNY AGENTA ---\n"
        
        try:
            # Część z bazy SQLite (bez zmian)
            self.cursor.execute("SELECT timestamp, action_name, target FROM action_log ORDER BY timestamp DESC LIMIT 5")
            actions = self.cursor.fetchall()
            report += "\n[Ostatnie 5 Akcji]\n" + ('\n'.join([f"- {ts[:16]}: {name} (Cel: {target})" for ts, name, target in actions]) if actions else "- Brak zarejestrowanych akcji.\n")
            
            # --- POPRAWIONA CZĘŚĆ Z BAZY WEKTOROWEJ ---
            # Krok 1: Stwórz embedding dla zapytania używając tego samego modelu co agent (OpenAI)
            query_text = "strategic insights and user directives"
            response = self.openai_client.embeddings.create(input=[query_text], model="text-embedding-3-small")
            query_embedding = response.data[0].embedding
            
            # Krok 2: Przeszukaj bazę używając stworzonego embeddingu (query_embeddings)
            results = self.vector_memory.query(
                query_embeddings=[query_embedding],
                n_results=4,
                where={"$or": [{"type": "insight"}, {"type": "user_directive"}]}
            )
            
            memories = results.get('documents', [[]])[0]
            report += "\n[Kluczowe Myśli Kierujące (Pamięć)]\n" + ('\n'.join([f"- {mem}" for mem in memories]) if memories else "- Brak kluczowych myśli w pamięci.\n")

            report += "\n--- KONIEC RAPORTU ---"
            return report
            
        except Exception as e:
            # Zwracamy bardziej szczegółowy błąd, jeśli coś pójdzie nie tak
            return f"Błąd podczas generowania raportu: {e}"

    def add_directive(self, directive: str):
        """Dodaje nową dyrektywę od użytkownika do pamięci wektorowej."""
        print(f"✍️ Zapisuję nową dyrektywę: '{directive}'")
        try:
            response = self.openai_client.embeddings.create(input=[directive], model="text-embedding-3-small")
            self.vector_memory.add(
                embeddings=[response.data[0].embedding],
                documents=[directive],
                metadatas=[{"type": "user_directive"}],
                ids=[f"directive_{int(datetime.now().timestamp())}"]
            )
            return "✅ Dyrektywa została zapisana. Agent uwzględni ją w przyszłych działaniach."
        except Exception as e: return f"❌ Nie udało się zapisać dyrektywy: {e}"

    def simulate_post_generation(self, topic: str):
        """Symuluje proces generowania tweeta na dany temat."""
        print(f"💡 Symuluję proces myślowy dla tematu: '{topic}'...")
        try:
            response = self.openai_client.embeddings.create(input=[f"strategic insights, directives, and past posts about {topic}"], model="text-embedding-3-small")
            results = self.vector_memory.query(query_embeddings=[response.data[0].embedding], n_results=4)
            context_docs = results.get('documents', [[]])[0]
            context_summary = "\n- ".join(context_docs) if context_docs else "Brak specyficznego kontekstu w pamięci."
            
            prompt_template_env = os.getenv('PROMPT_TEMPLATE')
            final_prompt = prompt_template_env.format(observed_subject=topic, successful_examples=context_summary)
            
            print("🤖 Generuję symulowany post...")
            response = self.openai_client.chat.completions.create(model=os.getenv("CREATION_MODEL", "gpt-4-turbo"), messages=[{"role": "user", "content": final_prompt}])
            content = response.choices[0].message.content.strip().strip('"')
            return f"--- WYNIK SYMULACJI ---\nTemat: {topic}\nWygenerowany post: \"{content}\"\n-------------------------"
        except Exception as e: return f"Błąd podczas symulacji: {e}"

    def analyze_topic_performance(self):
        """Analizuje wydajność tematów na podstawie danych z bazy SQLite."""
        print("📈 Analizuję wydajność tematów...")
        try:
            self.cursor.execute("SELECT subject, COUNT(tweet_id), AVG(likes) FROM observations WHERE likes IS NOT NULL GROUP BY subject ORDER BY AVG(likes) DESC")
            data = self.cursor.fetchall()
            if not data: return "Brak wystarczających danych do analizy."
            
            report = "--- ANALIZA WYDAJNOŚCI TEMATÓW ---\n"
            report += f"{'Temat':<30} | {'Liczba Postów':<15} | {'Śr. Polubień':<15}\n" + "-"*65 + "\n"
            report += '\n'.join([f"{s:<30} | {c:<15} | {f'{a:.2f}':<15}" for s, c, a in data])
            return report
        except Exception as e: return f"Błąd podczas analizy: {e}"

    def list_memory_by_type(self, memory_type: str):
        """Wyświetla listę wspomnień danego typu."""
        print(f"📋 Przeglądam pamięć w poszukiwaniu typu: '{memory_type}'...")
        try:
            results = self.vector_memory.get(where={"type": memory_type}, limit=10)
            documents = results.get('documents', [])
            if not documents: return f"Nie znaleziono w pamięci żadnych wpisów typu '{memory_type}'."
            return f"--- Wspomnienia typu: {memory_type} ---\n" + '\n'.join([f"- {doc}" for doc in documents])
        except Exception as e: return f"Błąd podczas przeglądania pamięci: {e}"
    def list_vetted_partners(self):
        """Wyświetla sformatowaną listę wszystkich zweryfikowanych, wartościowych partnerów."""
        print("📋 Pobieram listę zweryfikowanych partnerów...")
        try:
            self.cursor.execute("""
                SELECT screen_name, relevance_score, activity_score, legitimacy_score, llm_summary 
                FROM potential_partners 
                WHERE status='vetted' 
                ORDER BY (relevance_score + activity_score + legitimacy_score) DESC
            """)
            partners = self.cursor.fetchall()
            if not partners:
                return "Brak zweryfikowanych partnerów w bazie danych."
            
            report = "--- ZWERYFIKOWANI PARTNERZY (Ranking wg Oceny) ---\n"
            report += f"{'Profil':<20} | {'R/A/L':<10} | {'Podsumowanie AI'}\n"
            report += "-"*80 + "\n"
            for name, r, a, l, summary in partners:
                scores = f"{r}/{a}/{l}"
                report += f"{name:<20} | {scores:<10} | {summary}\n"
            return report
        except Exception as e:
            return f"Błąd podczas pobierania listy partnerów: {e}"

    def analyze_partner_funnel(self):
        """Generuje kompleksową, analityczną odpowiedź na temat strategii partnerskiej."""
        print("📊 Analizuję lejek partnerski... To może chwilę potrwać.")
        try:
            # 1. Statystyki ogólne lejka
            self.cursor.execute("SELECT status, COUNT(*) FROM potential_partners GROUP BY status")
            stats = self.cursor.fetchall()
            funnel_summary = "Statystyki Lejka Partnerskiego:\n" + "\n".join([f"- {status.capitalize()}: {count}" for status, count in stats])

            # 2. Pobierz dossier 3 najlepszych zweryfikowanych partnerów
            self.cursor.execute("""
                SELECT screen_name, relevance_score, activity_score, legitimacy_score, llm_summary 
                FROM potential_partners 
                WHERE status='vetted' 
                ORDER BY (relevance_score + activity_score + legitimacy_score) DESC LIMIT 3
            """)
            top_partners = self.cursor.fetchall()

            if not top_partners:
                return funnel_summary + "\n\nBrak zweryfikowanych partnerów do szczegółowej analizy."

            dossiers = []
            for name, r, a, l, summary in top_partners:
                # 3. Dla każdego partnera, znajdź historię interakcji
                self.cursor.execute("""
                    SELECT action_name, timestamp FROM action_log 
                    WHERE target = ? ORDER BY timestamp DESC LIMIT 5
                """, (name,))
                interactions = self.cursor.fetchall()
                
                interaction_history = "Brak zarejestrowanych interakcji."
                if interactions:
                    interaction_history = "Ostatnie interakcje:\n" + "\n".join([f"    - {action} ({ts[:10]})" for action, ts in interactions])

                dossier = f"""
                Profil: {name}
                Wynik Weryfikacji (Relewancja/Aktywność/Legitymacja): {r}/{a}/{l}
                Podsumowanie Analityka AI: "{summary}"
                {interaction_history}
                """
                dossiers.append(dossier)
            
            # 4. Przekaż wszystko do LLM w celu ostatecznej syntezy
            synthesis_prompt = f"""
            Jesteś doradcą strategicznym analizującym wydajność sieciową agenta AI. Twoim zadaniem jest zinterpretowanie poniższych danych i przedstawienie zwięzłego raportu dla operatora.

            Dane wejściowe:
            ---
            {funnel_summary}
            ---
            Szczegółowe Dossier dla Top 3 Partnerów:
            {"---".join(dossiers)}
            ---

            Twoje zadanie:
            1.  Przedstaw ogólny stan lejka partnerskiego.
            2.  Dla każdego z partnerów z dossier, podsumuj jego profil i dotychczasowe działania.
            3.  Na podstawie logiki agenta (który priorytetyzuje interakcje z wysoko ocenionymi, zweryfikowanymi celami), określ, jakie są prawdopodobne **planowane następne kroki** wobec każdego z nich.
            4.  Zakończ jedną, ogólną **rekomendacją strategiczną** (np. "Agent powinien skupić się na konwersji zweryfikowanych celów w aktywne zaangażowanie poprzez tworzenie dedykowanych treści.").

            Wygeneruj zwięzły raport.
            """
            
            print("🤖 Syntezuję raport strategiczny...")
            response = self.openai_client.chat.completions.create(
                model="gpt-4-turbo",
                messages=[{"role": "user", "content": synthesis_prompt}]
            )
            return response.choices[0].message.content

        except Exception as e:
            return f"Krytyczny błąd podczas analizy lejka partnerskiego: {e}"

def main():
    try:
        interface = AgentInterface()
        print_help()
        
        while True:
            # ... (reszta pętli bez zmian)

            command = interface.interpret_command(user_input)
            tool = command.get("tool")
            args = command.get("args", {})
            
            print("-" * 20)
            
            # --- ZAKTUALIZOWANY SŁOWNIK NARZĘDZI ---
            tool_map = {
                "generate_strategy_report": interface.generate_strategy_report,
                "synthesize_answer_from_memory": interface.synthesize_answer_from_memory,
                "add_directive": interface.add_directive,
                "simulate_post_generation": interface.simulate_post_generation,
                "analyze_topic_performance": interface.analyze_topic_performance,
                "list_memory_by_type": interface.list_memory_by_type,
                "list_vetted_partners": interface.list_vetted_partners,
                "analyze_partner_funnel": interface.analyze_partner_funnel
            }

            if tool in tool_map:
                result = tool_map[tool](**args) if args else tool_map[tool]()
                print(result)
            elif tool == "general_conversation":
                print("Jestem interfejsem do zarządzania. Skupmy się na strategii. Jak mogę Ci pomóc?")
            else:
                print("Nie udało mi się zinterpretować polecenia. Spróbuj sformułować je inaczej lub wpisz 'pomoc'.")
            
            print("-" * 20 + "\n")

    except Exception as e:
        print(f"\nFATALNY BŁĄD: Aplikacja została zamknięta. Powód: {e}")
    finally:
        print("\nZamykanie połączenia z Centrum Dowodzenia. Do zobaczenia.")

if __name__ == "__main__":
    main()