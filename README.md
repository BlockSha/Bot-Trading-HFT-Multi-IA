# 🤖 Bot de Trading HFT Multi-IA (Consensus LLM)

Un bot de trading algorithmique haute fréquence (HFT) connecté au Testnet de Binance. Ce projet démontre l'intégration de multiples Modèles de Langage (LLM) dans un environnement financier asynchrone pour la prise de décision en temps réel.

## 🚀 Fonctionnalités Clés

* 🧠 **Consensus Multi-IA :** Interrogation asynchrone de trois fournisseurs d'IA (Google Gemini, OpenAI, Mistral). L'ordre de trading n'est exécuté que si la majorité des modèles valide l'action (ACHETER/VENDRE).
* 🛡️ **Filtre "Anti-Zombie" (Optimisation des requêtes) :** Calcul en local d'indicateurs mathématiques (RSI, SMA). L'IA n'est réveillée que si la cryptomonnaie présente une réelle volatilité (RSI extrême), économisant ainsi 90% des requêtes API et évitant le Rate Limiting (HTTP 429).
* 📊 **Dashboard CLI Temps Réel :** Interface console interactive développée avec `rich` affichant le portefeuille, le PnL (Profit and Loss), le scanner de marché, les logs de communication IA et l'historique des trades.
* 🔄 **Failover & Load Balancing :** Gestion autonome des pannes d'API et des quotas. En cas de surcharge d'un fournisseur, le bot passe automatiquement au suivant ou impose une pause de sécurité sans interrompre le script.
* 💰 **Money Management :** L'IA gère elle-même le pourcentage de capital à allouer à chaque transaction.

## 🛠️ Technologies Utilisées

* **Langage :** Python 3
* **API & Trading :** CCXT (Binance Testnet Spot)
* **Intelligence Artificielle :** SDK `google-generativeai`, SDK `openai` (GPT-3.5 & Mistral)
* **Interface (CLI) :** `rich`
* **Environnement :** `python-dotenv`

## ⚙️ Installation et Configuration

1. **Cloner le dépôt :**
   ```bash
   git clone [https://github.com/blocksha/Bot-Trading-HFT-Multi-IA.git](https://github.com/blocksha/Bot-Trading-HFT-Multi-IA.git)
   cd Bot-Trading-HFT-Multi-IA
   
Créer un environnement virtuel (recommandé) :

python -m venv venv
source venv/bin/activate  # Sur Windows : venv\Scripts\activate
Installer les dépendances :

pip install -r requirements.txt
Configurer les variables d'environnement :
Créer un fichier .env à la racine du projet et ajouter les clés API (ne jamais commiter ce fichier) :

BINANCE_PUBLIC_KEY=votre_cle_publique_testnet
BINANCE_SECRET_KEY=votre_cle_secrete_testnet
GEMINI_API_KEY=votre_cle_gemini
OPENAI_API_KEY=votre_cle_openai
MISTRAL_API_KEY=votre_cle_mistral

🚀 Utilisation

Lancer le bot via la commande suivante :

Bash
python bot.py
Le dashboard s'affichera directement dans le terminal et commencera le scan des paires USDT. Pour arrêter proprement le bot, utilisez Ctrl + C.