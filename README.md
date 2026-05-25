# Atlas — Agent IA Autonome pour SEO & WordPress

> Agent IA qui audite la santé SEO d'un site web, fait de la recherche de mots-clés, génère des articles optimisés et les publie sur WordPress. **100% open source, zéro API payante.**

Projet de stage — May 2026.

---

## Vue d'ensemble

Atlas est un agent IA qui orchestre plusieurs outils SEO via un LLM (Llama 3.3 70B sur Groq ou Qwen 2.5 en local via Ollama). On lui donne une mission en langage naturel — *"audite ce site, identifie un sujet d'article qui correspond à une lacune, génère-le et publie-le"* — et il choisit lui-même quels outils utiliser et dans quel ordre.

### Démo en une commande

```bash
python -m atlas.agent "Audite http://exemple.com, identifie un sujet d'article qui correspond à une lacune, génère-le et publie-le en draft sur WordPress."
```

L'agent enchaîne :
1. **Audit SEO complet** : crawl HTML + Lighthouse + robots.txt + sitemap + priorisation LLM des issues
2. **Keyword research** : Google autocomplete + clustering sémantique par LLM
3. **Génération d'article** : prompt chaining (plan → sections → assemblage HTML + FAQ JSON-LD)
4. **Publication** : WordPress REST API avec auth Application Password

Tout est restitué en français business, prêt à être livré à un client.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│      AGENT BRAIN (Llama 3.3 + tool use)         │
│  Reçoit objectif → planifie → exécute → résume  │
└──────────┬──────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────┐
│                  OUTILS                          │
│                                                  │
│  audit_site()                keyword_research()  │
│  generate_and_publish_article()                  │
│                                                  │
│  En interne : crawl_url, run_lighthouse,         │
│  fetch_robots, fetch_sitemap, generate_article,  │
│  publish_article, generate_seo_report            │
└──────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────┐
│  STOCKAGE  →  SQLite (audits historiques)        │
│  UI        →  Streamlit (dashboard, formulaires) │
│  RAPPORT   →  HTML pro via Jinja2 (PDF optionnel)│
└──────────────────────────────────────────────────┘
```

---

## Stack technique (100% open source)

| Composant | Choix | Pourquoi |
|---|---|---|
| LLM (cloud free tier) | Groq + Llama 3.3 70B | API OpenAI-compatible, free tier généreux, modèle ouvert (Meta) |
| LLM (local, fallback) | Ollama + Qwen 2.5 / Mistral | 100% offline, aucune dépendance externe |
| Framework agent | Direct API + boucle tool calling maison | Pas de LangChain : compréhension profonde du pattern agent |
| Crawl HTML | `httpx` + `selectolax` | Parser HTML 10x plus rapide que BeautifulSoup |
| Audit performance | Lighthouse CLI (Google, OSS) | Référence du marché, données identiques à PageSpeed Insights |
| Sitemap | `ultimate-sitemap-parser` | Gère les sitemap index imbriqués |
| Keyword research | Google autocomplete + clustering LLM | Zéro API payante, intent classification par LLM |
| Templates | `jinja2` | Standard Python pour HTML templating |
| PDF (optionnel) | WeasyPrint, ou Chrome print-to-pdf | Le HTML reste autonome et imprimable |
| Storage | SQLite + SQLAlchemy 2.x | Zéro setup, parfait pour ce scope |
| UI | Streamlit | Prototype d'interface web en quelques heures |
| HTTP | `httpx` | Successeur moderne de requests, supporte async natif |

**Aucune des dépendances n'est payante** et **aucune n'est propriétaire** (au sens "closed source SaaS").

---

## Fonctionnalités principales

### Audit SEO complet

- Crawl HTML : titre, meta, h1-h6, liens internes/externes, images, JSON-LD, Open Graph, Twitter Cards
- Audit performance Lighthouse : Core Web Vitals (LCP, CLS, INP), scores Performance/SEO/A11y/BP, opportunités d'optimisation
- robots.txt : présence, user-agents, sitemaps déclarés, crawl-delay
- Sitemap : nombre d'URLs, sample, dates de modification
- Priorisation par LLM : 10 issues max classées critique / important / nice_to_have, avec impact business + action concrète

### Génération d'articles SEO

- Prompt chaining (qualité supérieure à un seul gros prompt)
- 1200-1800 mots, 5-7 sections H2, FAQ JSON-LD schema.org
- Meta title (50-60 chars), meta description (150-160 chars), slug URL
- Intégration naturelle du mot-clé cible + secondaires

### Publication WordPress

- WP REST API native (depuis WP 4.7, pas de plugin requis)
- Auth Application Password (Basic Auth)
- Catégories + tags auto-créés si absents
- Status draft / publish / scheduled

### Rapport SEO HTML

- Page de couverture
- Grille de 4 scores colorés
- Plan d'action priorisé (rouge / orange / vert)
- Détails techniques + Lighthouse + indexabilité
- Convertible en PDF via Chrome (Ctrl+P) ou WeasyPrint

### UI Streamlit

- Tableau de bord avec historique des audits
- Formulaires : nouvel audit, génération d'article
- Page "Agent libre" pour parler à l'agent en langage naturel
- Téléchargement des rapports HTML

---

## Setup

### Prérequis

- Python 3.11+
- Node.js (pour Lighthouse CLI)
- Chrome installé
- (Optionnel) Ollama si tu veux du LLM local

### Installation

```bash
# Cloner
git clone https://github.com/Tediuos/atlas-wordpress-agent.git
cd atlas-wordpress-agent

# Virtual env
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
.\.venv\Scripts\Activate.ps1  # Windows

# Dépendances Python
pip install -r requirements.txt

# Lighthouse CLI
npm install -g lighthouse

# Variables d'environnement
cp .env.example .env
# Édite .env avec ta clé Groq + tes credentials WordPress
```

### Configuration

Édite `.env` :

```env
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile

OLLAMA_MODEL=qwen2.5:7b

WP_URL=http://ton-site.local
WP_USER=admin
WP_APP_PASSWORD=xxxx xxxx xxxx xxxx xxxx xxxx
```

Récupère ta clé Groq sur https://console.groq.com/keys (gratuit).

---

## Utilisation

### Mode CLI

```bash
# Audit standalone
python -m atlas.tools.auditor http://exemple.com

# Keyword research
python -m atlas.tools.keywords "wordpress seo" fr

# Génération + publication
python -m atlas.tools.wordpress "Sujet de l'article" "mot-cle cible"

# Rapport SEO depuis le dernier audit
python -m atlas.tools.seo_report

# Agent autonome (mission en langage naturel)
python -m atlas.agent "Audite http://exemple.com et donne-moi les 3 actions prioritaires."
```

### Mode UI web

```bash
streamlit run ui/streamlit_app.py
```

L'app s'ouvre sur http://localhost:8501.

---

## Structure du projet

```
atlas-wordpress-agent/
├── atlas/
│   ├── llm.py              # Wrapper Groq/Ollama
│   ├── db.py               # Modèles SQLAlchemy
│   ├── agent.py            # Boucle agent + tools
│   ├── tools/
│   │   ├── crawler.py
│   │   ├── lighthouse.py
│   │   ├── robots_sitemap.py
│   │   ├── auditor.py
│   │   ├── keywords.py
│   │   ├── article_writer.py
│   │   ├── wordpress.py
│   │   └── seo_report.py
│   └── templates/
│       └── seo_report.html.j2
├── ui/
│   └── streamlit_app.py
├── data/                   # SQLite + rapports (gitignored)
├── requirements.txt
├── .env.example
└── README.md
```

---

## Choix techniques notables

### Pourquoi pas LangChain ?

Pour ce stage, on voulait **comprendre le pattern agent en profondeur** plutôt que cacher la complexité derrière une lib. La boucle agent (`atlas/agent.py`) fait 80 lignes et permet de tout maîtriser : sérialisation des outils, gestion d'erreurs, troncature de contexte. Atlas est facilement portable vers n'importe quel autre LLM OpenAI-compatible.

### Pourquoi Groq plutôt qu'OpenAI / Anthropic ?

Trois raisons : (1) **free tier généreux** , (2) **modèles open source** (Llama 3.3 70B, Qwen 2.5), donc reproductibilité parfaite, (3) **bascule triviale vers Ollama local** via une variable d'env, pour une démo offline.

### Pourquoi pas d'API SEO payante (Ahrefs / SEMrush / DataForSEO) ?

Contrainte du projet : zéro budget. Stratégie de contournement : Google autocomplete (gratuit) pour collecter 100-200 mots-clés, LLM pour le clustering sémantique et la classification d'intent. On n'a pas les volumes exacts, mais on a la **structure thématique** et l'**intent** — suffisant pour orienter une stratégie de contenu.

### Pourquoi prompt chaining pour les articles ?

Un seul gros prompt "écris-moi un article complet sur X" produit du contenu plat et générique. En faisant 2 passes (plan global → puis chaque section avec son brief), on obtient des articles structurés et plus longs sans tomber dans la répétition.

---

## Limitations connues

- **Pas de volume mensuel de recherche** (nécessiterait Ahrefs / SEMrush / DataForSEO payants).
- **Pas de génération d'image featured automatique** (peut être ajouté via Stable Diffusion local ou Unsplash API).
- **Single-site WordPress** (Wix, Shopify, PrestaShop, HubSpot sont des chantiers v2).
- **Pas de support multi-utilisateurs / auth dans l'UI** (Streamlit en local-only).
- **Lighthouse local lent** (~30-60s par audit). Acceptable mais bloque l'UI pendant ce temps.

---

## Roadmap v2

- Multi-CMS (Wix, Shopify, PrestaShop, HubSpot)
- Génération d'image featured via SD local
- Scheduling périodique avec APScheduler + envoi email du rapport
- Comparaison d'audits dans le temps (graph d'évolution des scores)
- Auth multi-tenant pour SaaS-iser

---

## Licence

Code source libre pour usage interne et démonstration.

---

## Crédits

Stage May 2026 — Mohamed Yassine Aouidet.

Modèles utilisés : Meta Llama 3.3 (via Groq), Alibaba Qwen 2.5 (via Ollama).
