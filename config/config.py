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
ANTHROPIC_API_KEY = ""  # leave blank — real value in ANTHROPIC_API_KEY GitHub Secret

# ---- GOOGLE CREDENTIALS ----
# Path to your Google service account JSON (for Sheets + Gmail)
# See SETUP.md for how to get this
GOOGLE_CREDENTIALS_PATH = "./config/google_credentials.json"
GOOGLE_SHEET_ID = "1kUMStZH6EOdqY7iJFJYPbuyQw5stLXcGETdE5u-mWAo"  # Paste your Sheet ID after creating it (see SETUP.md)
GMAIL_SENDER = "steve.christianmba@gmail.com"

# ---- GMAIL APP PASSWORD (for sending the digest email) ----
# Generate at: myaccount.google.com/apppasswords  (requires 2-Step Verification)
# Select "Other (Custom name)", name it "Job Agent", copy the 16-char password.
# In GitHub Secrets, store it as GMAIL_APP_PASSWORD.
GMAIL_APP_PASSWORD = ""  # leave blank — real value in GMAIL_APP_PASSWORD GitHub Secret

# ---- AWS S3 (persistent storage — never expires unlike GitHub Actions cache) ----
# IAM user: job-agent-s3  |  Policy: job-agent-s3-policy (GetObject, PutObject, ListBucket)
# Generate keys at: AWS Console → IAM → Users → job-agent-s3 → Security credentials
S3_BUCKET_NAME     = "stevechristian-job-agent"
AWS_REGION         = "us-east-2"
AWS_ACCESS_KEY_ID     = ""  # leave blank — real value in AWS_ACCESS_KEY_ID GitHub Secret
AWS_SECRET_ACCESS_KEY = ""  # leave blank — real value in AWS_SECRET_ACCESS_KEY GitHub Secret

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

# ---- SCORING RESUME (used by Claude for job scoring — scoring-optimized brief) ----
# This is separate from RESUME_TEXT above. RESUME_TEXT is the human-readable version
# for cover letters. SCORING_RESUME is calibrated for Claude: includes skill-gap warnings,
# domain exclusions, and comp targets so scores are accurate and actionable.
# Update this whenever your experience, gaps, or comp targets change.
SCORING_RESUME = """
Steve Christian | Senior Product Leader | Denver, CO (remote or Denver hybrid only)
12+ years total PM experience (Accenture 2013+). ~4-5 years in energy as most recent chapter (Verizon 2021-2025). Prior chapters: fintech/payments (Airbnb, ~13 months) and enterprise/consumer platforms (Disney Parks, Accenture consulting).

EXPERIENCE:
Verizon (2021-2025): Incubated 5 x 0->1 products, secured $6M executive funding. Led AI-driven DER/VPP orchestration platform (demand response, grid-edge optimization). Patent: energy usage optimization. Python analytics dashboards.
Accenture (2013-2020): Airbnb global payments platform ($10B+ annual volume, pre-IPO). Disney Parks app (1M+ downloads, 30K Cast Member platform). Fortune 100 consulting engagements.

DOMAIN DEPTH: DER, DERMS, VPP, HEMS, grid modernization, demand response, V2G, IoT, residential electrification, smart home energy, fintech payments, enterprise SaaS, AI/ML products, data platforms.
TECH: APIs (REST/GraphQL), Python (current), SQL (foundational — not independent querying), microservices, cloud, LLM-enabled products, Jira, Figma.
APPROACH: Hypothesis-driven, JTBD methodology, systems thinking, comfortable with ambiguity, strong executive communication.

CRITICAL — ENERGY EXPERTISE CONTEXT: Steve has ~4-5 years in energy as a SOFTWARE PRODUCT MANAGER building platforms for energy companies. He is NOT an energy developer, energy financier, power trader, or infrastructure investor. He has NEVER: negotiated PPAs or offtake agreements, managed EPC contractors, developed utility-scale generation projects, built technoeconomic models, structured project finance or infrastructure investments, or commercialized generation technologies. Roles requiring those skills are a POOR FIT.

CRITICAL — NO DEEP SCIENTIFIC/TECHNICAL DOMAIN EXPERTISE: Steve does not have specialized expertise in: meteorology, atmospheric science, weather modeling (NWP, GNSS-RO, mesoscale), geospatial/remote sensing, genomics, materials science, semiconductor physics, or other hard science/engineering fields. Roles that require "8+ years in [scientific domain]" or "deep expertise in [scientific discipline]" as a hard requirement are a POOR FIT even if the PM function looks right. This includes: semiconductor/EE/ME/Physics degree required, RF/antenna engineering, hardware/chip design.

CRITICAL — SKILL GAPS (score down when these are hard requirements):
- SQL as primary data tool: Steve's SQL is foundational. Roles requiring "independent SQL querying without a data analyst" or "write complex queries daily" are a real gap. Python is the current tool.
- Payments specialization: One ~13-month Airbnb role. Not 3+ years depth. ACH flows specifically confirmed; payments regulatory (MTL/PayFac), PSP vendor management, multi-rail expertise are gaps.
- ISO/RTO dispatch or settlement system ownership: No direct ownership. The DER/VPP patent covers optimization logic but not direct market dispatch or settlement operations.
- Energy regulatory expertise: No utility-sector regulatory or tariff experience. Do not conflate with general energy software experience.

STRONG FIT: 0->1 ownership, platform/API products, AI-first orgs, energy/climate/utilities SOFTWARE companies, residential electrification software, high strategic ownership, product-led orgs, growth/monetization.
MODERATE FIT: Enterprise SaaS, fintech, data platforms, digital transformation, customer data products with clear business-outcomes framing.
NOT A FIT: Pure project/program management, feature delivery only, no strategic ownership, healthcare, pharma, telecom, mining. Also NOT a fit: energy project development, energy finance/commercialization, PPA/offtake negotiation, EPC management, utility-scale project development, technoeconomic modeling, infrastructure investment diligence, generation technology commercialization. Roles requiring deep scientific domain expertise (meteorology, atmospheric science, geospatial, genomics, semiconductor/EE, etc.).

COMP TARGETS: Sr PM $180K-240K TC | Principal/Group PM $220K-325K TC | Director $275K-400K+ TC
BASE FLOOR: ~$160K (flexible for strong energy/climate domain fit; less flexible for adjacent industries)
""".strip()

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
MAX_NEW_SCORES_PER_RUN = 80    # Hard cap on new Claude scoring calls per run.
                               # Prevents runaway spend if a cache wipe + large scrape
                               # batch hits on the same day. Deferred jobs are scored
                               # on the next daily run. Set higher if you want faster
                               # catch-up after a manual cache clear.
MIN_SCORE_TO_INCLUDE = 40      # Jobs below this score are dropped (40-54 go to "Maybe" section)
TOP_N_FOR_EMAIL = 15           # How many jobs go in the daily digest email
DAYS_TO_KEEP_IN_SHEET = 30     # Jobs older than this get archived
