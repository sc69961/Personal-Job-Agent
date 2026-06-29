# ============================================================
# JOB AGENT CONFIG — Personalize this file, then run main.py
# ============================================================

# ---- YOUR INFO ----
YOUR_NAME = "Steve Christian"
YOUR_EMAIL = "steve.christianmba@gmail.com"
YOUR_PHONE = "(919) 614-0875"
YOUR_LOCATION = "Denver, CO"
YOUR_LINKEDIN = "https://www.linkedin.com/in/steve-christian-mba/"

DIGEST_EMAIL_TO = "steve.christianmba@gmail.com"

# ---- ANTHROPIC API ----
# Set this in your shell: export ANTHROPIC_API_KEY="sk-ant-..."
# Or paste it here (not recommended for shared machines)
ANTHROPIC_API_KEY = ""  # leave blank to use env var

# ---- GOOGLE CREDENTIALS ----
# Path to your Google service account JSON (for Sheets + Gmail)
# See SETUP.md for how to get this
GOOGLE_CREDENTIALS_PATH = "./config/google_credentials.json"
GOOGLE_SHEET_ID = "1kUMStZH6EOdqY7iJFJYPbuyQw5stLXcGETdE5u-mWAo"  # Paste your Sheet ID after creating it (see SETUP.md)
GMAIL_SENDER = "steve.christianmba@gmail.com"

# ---- SCORING CRITERIA ----
SALARY_FLOOR = 130000

# Location: jobs must be remote, or hybrid in these metros
ALLOWED_LOCATIONS = [
    "remote", "denver", "boulder", "colorado", "co", "hybrid"
]

# Preferred job titles (get a score bonus)
PREFERRED_TITLES = [
    # Core PM titles
    "senior product manager", "sr. product manager",
    "group product manager", "staff product manager",
    "principal product manager",
    # Leadership titles
    "director of product", "director of product management",
    "head of product", "vp of product", "vice president of product",
    # Role-type matches (platform, growth, 0-to-1)
    "platform product manager", "api product manager",
    "growth product manager", "product lead",
]

# Keywords that signal a strong fit for your background
HIGH_SIGNAL_KEYWORDS = [
    # Energy / climate (strongest match)
    "DER", "DERMS", "VPP", "virtual power plant", "demand response",
    "distributed energy", "grid", "energy", "utilities", "IoT",
    "HEMS", "home energy", "grid edge", "grid modernization", "climate tech",
    "energy management", "energy markets",
    # Platform / AI (strong match)
    "platform", "API", "SaaS", "AI", "machine learning", "LLM",
    "data platform", "predictive analytics", "automation", "AI-first",
    "enterprise platform", "microservices",
    # Role signals (strong match)
    "0 to 1", "zero to one", "0->1", "incubation", "new venture",
    "product-led", "product strategy", "strategic ownership",
    "experimentation", "hypothesis", "product discovery",
    # Fintech (moderate match)
    "fintech", "payments", "financial platform", "transaction",
    # Company signals
    "startup", "Series A", "Series B", "Series C", "growth stage",
    "innovation", "emerging technology",
]

# Keywords that signal poor fit — auto-downweight
NEGATIVE_KEYWORDS = [
    # Seniority mismatches
    "hardware engineer", "electrical engineer", "field technician",
    "junior", "associate pm", "internship", "intern",
    # Location mismatches
    "new york only", "san francisco only", "on-site only",
    # Industry rule-outs (explicit)
    "healthcare", "medical device", "pharma", "pharmaceutical",
    "telecom", "telecommunications", "mining", "medtech", "clinical",
    # Role type mismatches — no strategic ownership
    "operations analyst", "program coordinator", "process manager",
    "project manager", "program manager", "scrum master",
    "backlog management", "delivery manager", "release manager",
    "feature factory", "it project",
]

# Company size preferences (startups/smaller weighted higher)
PREFERRED_COMPANY_SIZES = ["startup", "series a", "series b", "small", "mid-size"]

# ---- YOUR RESUME (used by Claude for scoring + cover letters) ----
RESUME_TEXT = """
Steve Christian | Denver, CO | (919) 614-0875 | steve.christianmba@gmail.com

PROFESSIONAL SUMMARY
Product leader with 10+ years owning 0 to 1 and platform-scale products across energy, fintech,
and enterprise technology. Proven track record delivering systems supporting $10B+ in transactions,
unlocking $10M+ in revenue, and securing $6M in new venture investment. Deep expertise in DERs,
VPPs, and IoT, translating distributed systems into scalable business outcomes while building
high-performing teams and accelerating product discovery.

PROFESSIONAL EXPERIENCE

Verizon | Senior Manager, Product Strategy | Mar 2021 – Dec 2025
- Identified and incubated five 0→1 product investments across energy and SMB portfolios,
  securing $6M in executive funding to validate new DER and VPP-driven revenue streams
- Owned product strategy and roadmap for an AI-driven DER orchestration platform enabling VPP
  participation, demand response orchestration, and grid-edge optimization across distributed assets
- Incubated and scaled an AI-driven Device Protection Platform with $60M projected revenue
- Led product strategy for Verizon Home Internet energy offerings, enabling VPP integration
- Developed SQL and Python analytics dashboards for customer site performance, energy usage,
  and tariff scenarios
- Inventor on Approved Patent: Systems and methods for optimizing energy usage based on user preferences

Verizon | Manager, Product Management | Feb 2020 – Mar 2021
- Delivered scalable platform capabilities and API services supporting 50+ internal developers
  and MapQuest applications, generating $10M in new revenue
- Led decommissioning of proprietary features, orchestrating migration to HERE and Google Maps

Accenture | Manager, Product Management - Platforms | Nov 2017 – Feb 2020 | Denver, CO
  - Airbnb (Lead Payments Platform PM, Jan 2019 – Feb 2020):
    Led development of global payments microservices platform supporting $10B+ in annual
    transaction volume; defined KPIs and ran A/B tests ahead of Airbnb's IPO
  - Disney Parks & Resorts (Lead Platform PM, Feb 2015 – Sep 2018):
    Drove delivery of "Play Disney Parks" mobile app (1M+ downloads); led 3-year roadmap
    for internal workforce management platform serving 30,000+ Cast Members

EDUCATION
Appalachian State University — MBA 2011 | BSBA Information Systems 2010 | BA Psychology 2010

SKILLS
Product Leadership: 0→1 Product Development, Platform Strategy, Roadmapping, GTM, OKRs/KPIs, Agile
Energy & Grid: DERMS, VPPs, Demand Response, V2G, Microgrid Orchestration, Grid-Edge Optimization
Product Toolkit: Agile/Scrum/SAFe, Jira, Confluence, Aha!, Figma, Tableau
Technical: APIs (REST/GraphQL), SQL, Python, AI/ML (Gemini, Claude), Microservices, Cloud
"""

# ---- SCORING WEIGHTS (must sum to 1.0) ----
# These tune how Claude calculates the final score
SCORE_WEIGHTS = {
    "resume_fit":       0.35,  # How well JD matches your specific experience
    "company_tier":     0.20,  # Climatetech > fintech/AI > other
    "title_seniority":  0.15,  # Senior title match
    "location_remote":  0.15,  # Remote/hybrid Denver-friendly
    "growth_stage":     0.10,  # Startup preference
    "keywords":         0.05,  # High-signal keyword density
}

# ---- SCRAPER SETTINGS ----
MAX_JOBS_PER_SOURCE = 50       # Cap per source per run
MIN_SCORE_TO_INCLUDE = 55      # Jobs below this score are dropped
TOP_N_FOR_EMAIL = 15           # How many jobs go in the daily digest email
DAYS_TO_KEEP_IN_SHEET = 30     # Jobs older than this get archived
