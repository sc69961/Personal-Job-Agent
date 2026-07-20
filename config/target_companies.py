# ============================================================
# TARGET COMPANIES — Edit this list to add/remove companies
# ============================================================

# Tier 1: Climate tech / energy / DER / VPP / DERMS (highest weight: 1.3x score multiplier)
CLIMATETECH_COMPANIES = [
    # VPP / DERMS / Grid platforms
    "Uplight", "AutoGrid", "Virtual Peaker", "Enbala", "Voltus",
    "OhmConnect", "Leap Energy", "Enel X", "CPower", "Itron",
    "Landis+Gyr", "Siemens Energy", "ABB", "GE Vernova", "Schneider Electric",
    "Oracle Utilities", "Tantalus", "Doosan GridTech", "Spirae",
    "Weavegrid", "DERAPI", "Camus Energy", "GridBeyond",
    "Kaluza", "Kraken", "Next Kraftwerke", "Evergen", "Enersponse",
    "Blueprint Power", "David Energy", "Equilibrium Energy", "Habitat Energy",
    "Modo Energy", "GridStatus.io", "Yes Energy", "Ascend Analytics",
    "PCI Energy Solutions", "OATI", "Utilidata", "UtilityAPI", "Tyba",
    "Amperon", "Kevala", "Base Power",

    # DER / solar / storage / EV
    "SunPower", "Sunnova", "Sunrun", "Tesla Energy", "sonnen",
    "Stem", "Fluence", "Fluence Mosaic", "Powin", "Eos Energy", "Form Energy",
    "Swell Energy", "Enphase", "SolarEdge", "Freewire Technologies", "Wallbox",
    "ChargePoint", "EVgo", "Blink Charging", "Nuvve", "Fermata Energy",
    "Lunar Energy", "Elephant Energy", "GoodLeap", "SB Energy",
    "BoxPower", "Anza Renewables", "Bloom Energy", "Xpansiv",
    "OptiWatt", "ev.energy", "Pivot", "Renew Home",

    # Utilities / grid software / data
    "Pacific Gas & Electric", "Xcel Energy", "Avangrid", "Eversource",
    "National Grid", "Duke Energy", "Con Edison", "Ameren", "WEC Energy",
    "Enel", "Engie", "Octopus Energy", "PowerSecure",
    "Arcadia", "Urjanet", "eSmart Systems", "GridX",
    "Sense", "Bidgely", "EnergyHub", "Logical Buildings", "Recurve Analytics",
    "LineVision", "Rhythm Energy", "ION Group", "Syso",

    # Recommended additions
    "SPAN", "Enode", "Omnidian", "Aurora Solar", "Enverus",
    "Palmetto", "Powerflex", "Copper Labs", "GridPoint", "WattBuy",
    "Electrify America", "OhmConnect", "Enbala", "AutoGrid",

    # Energy Trading
    "NextEra Energy", "LevelTen Energy", "Pexapark", "Power Ledger",

    # Energy Software Platforms
    "AspenTech", "Hitachi Energy", "Siemens Grid Software",

    # Building Electrification
    "Dandelion Energy", "BlocPower", "Quilt",

    # ESG / Sustainability Software (carbon accounting, ESG data, net-zero platforms)
    "Watershed", "Persefoni", "Measurabl", "Sweep", "Greenly",
    "Terrascope", "Sphera", "Sustain.Life", "EcoVadis",
    "Workiva", "Diligent", "Intelex",
]

# Tier 2: Fintech / AI / high-growth startups (weight: 1.0x)
FINTECH_AI_COMPANIES = [
    # Fintech
    "Stripe", "Plaid", "Brex", "Ramp", "Mercury",
    "Chime", "Robinhood", "Betterment", "Wealthfront", "Marqeta",
    "Affirm", "Klarna", "Adyen", "Checkout.com", "Modern Treasury",

    # AI / ML platforms
    "Anthropic", "OpenAI", "Cohere", "Mistral", "Hugging Face",
    "Scale AI", "Weights & Biases", "Databricks", "Snowflake", "Palantir",
    "C3.ai", "Replit", "Cursor", "Perplexity", "You.com",

    # High-growth startups (Denver/remote-friendly)
    "Guild Education", "Ibotta", "Ping Identity", "JumpCloud", "SambaSafety",
    "Conga", "Vertafore", "DISH Network", "Dish Wireless", "Boom Supersonic",

    # Industrial AI
    "Samsara", "Augury", "Sight Machine",

    # Infrastructure Software
    "Sitetracker", "Procore", "ServiceTitan",

    # Data Platform & Analytics (strong PM culture, platform products)
    "dbt Labs", "Amplitude", "Monte Carlo", "Fivetran",
    "Retool", "Rippling", "Figma",

    # IoT / Smart Building Software
    "Honeywell Forge", "Johnson Controls OpenBlue", "Turntide Technologies",
    "Willow", "Gridium",
]

# All company names flattened (used for matching)
ALL_TARGET_COMPANIES = CLIMATETECH_COMPANIES + FINTECH_AI_COMPANIES

# ============================================================
# COMPANY CAREER PAGE URLS
# Scraper auto-detects Greenhouse / Lever / Workable / Ashby
# and falls back to HTML scraping for everything else.
# ============================================================
COMPANY_CAREER_URLS = {
    "Leap Energy":          "https://apply.workable.com/leapfrog-power-inc/",
    "Uplight":              "https://jobs.ashbyhq.com/uplight",                     # fixed: was Jobvite
    "Voltus":               "https://jobs.lever.co/voltus",
    "Virtual Peaker":       "https://jobs.ashbyhq.com/virtual-peaker",              # fixed: was HTML
    "Ascend Analytics":     "https://jobs.ashbyhq.com/ascend-analytics",            # fixed: was HTML
    "Kraken":               "https://jobs.lever.co/kraken",                         # fixed: was wrong slug (kraken123)
    "Octopus Energy":       "https://octopus.energy/careers/join-us/",
    "BoxPower":             "https://boxpower.bamboohr.com/careers",
    "Weavegrid":            "https://jobs.ashbyhq.com/weavegrid",                   # fixed: was HTML
    "EnergyHub":            "https://job-boards.greenhouse.io/energyhub",           # fixed: was HTML
    "Renew Home":           "https://jobs.ashbyhq.com/renew-home",                  # fixed: was HTML
    "ev.energy":            "https://evenergy.careers.hibob.com/jobs",
    "Stem":                 "https://stem.wd12.myworkdayjobs.com/StemInc",
    "OptiWatt":             "https://apply.workable.com/optiwatt/",
    "Pivot":                "https://www.pivotenergy.net/careers",
    "Base Power":           "https://jobs.ashbyhq.com/base-power",                  # fixed: was HTML
    "LineVision":           "https://jobs.ashbyhq.com/linevision",                  # fixed: was HTML
    "Sunrun":               "https://careers.sunrun.com/search-jobs/product%20manager/Colorado%2C%20US/21632/1/3/6252001-5417618/39x00027/-105x50083/50/2",
    "Syso":                 "https://www.sysotechnologies.com/join/",
    "Arcadia":              "https://job-boards.greenhouse.io/arcadiacareers",        # FIX: was jobs.lever.co/arcadia (arcadia.io = healthcare data, WRONG company); arcadiacareers = arcadia.com (clean energy / community solar)
    "UtilityAPI":           "https://job-boards.greenhouse.io/utilityapi",
    "Utilidata":            "https://jobs.ashbyhq.com/utilidata",                   # fixed: was HTML
    "Yes Energy":           "https://job-boards.greenhouse.io/yesenergy",
    "GridX":                "https://jobs.ashbyhq.com/gridx",                       # fixed: was HTML
    "Camus Energy":         "https://jobs.ashbyhq.com/camus-energy",                # fixed: was HTML
    "Rhythm Energy":        "https://ats.rippling.com/rhythm-energy/jobs",
    "Bidgely":              "https://jobs.ashbyhq.com/bidgely",                     # fixed: was HTML
    # "Dynamic Grid" removed — no such energy company found; URL was pointing to Grid Dynamics (tech consulting), which is a different company entirely
    "Modo Energy":          "https://job-boards.eu.greenhouse.io/modoenergy",
    "SB Energy":            "https://jobs.ashbyhq.com/sb-energy",                   # fixed: was HTML
    "GridBeyond":           "https://gridbeyond.com/about-us/careers-2/",
    "Engie":                "https://www.engie.com/en/careers",
    "David Energy":         "https://jobs.ashbyhq.com/davidenergy",
    "Lunar Energy":         "https://jobs.ashbyhq.com/lunar-energy",                # fixed: was HTML
    "Kaluza":               "https://jobs.ashbyhq.com/kaluza",                      # fixed: was HTML
    "Swell Energy":         "https://jobs.ashbyhq.com/swell-energy",                # fixed: was HTML
    "Evergen":              "https://evergen.energy/careers-at-evergen/",
    "Next Kraftwerke":      "https://www.next-kraftwerke.com/jobs",
    "GoodLeap":             "https://jobs.lever.co/goodleap",                       # fixed: was HTML
    "Elephant Energy":      "https://jobs.ashbyhq.com/elephant-energy",             # fixed: was HTML
    "Equilibrium Energy":   "https://jobs.ashbyhq.com/equilibrium-energy",          # fixed: was HTML
    "GridStatus.io":        "https://www.gridstatus.io/jobs",
    "Enel":                 "https://jobs.enel.com/en_US/careers/JobOpeningsUSA/product",
    "CPower":               "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=b2431733-235a-437c-978d-011f4e00c432&ccId=19000101_000001&type=JS&lang=en_US",
    "PowerSecure":          "https://recruiting.ultipro.com/POW1009POWS/JobBoard/42398959-f1c7-48da-a3e2-94e525e29808/",
    "Enersponse":           "https://www.enersponse.com/careers",
    "Blueprint Power":      "https://jobs.ashbyhq.com/blueprint-power",             # fixed: was wrong (Austrian company URL)
    "Fluence":              "https://fluenceenergy.wd12.myworkdayjobs.com/en-US/fluenceenergy-jobs",
    "Tyba":                 "https://jobs.ashbyhq.com/tyba",                        # fixed: was HTML
    "Habitat Energy":       "https://jobs.ashbyhq.com/habitat-energy",              # fixed: was HTML
    "Amperon":              "https://jobs.ashbyhq.com/amperon",                     # fixed: was HTML
    "Xpansiv":              "https://jobs.ashbyhq.com/xpansiv",                     # fixed: was HTML
    "OATI":                 "https://www.oati.com/careers/",
    "ION Group":            "https://jobs.lever.co/ion",
    "PCI Energy Solutions": "https://jobs.ashbyhq.com/pci-energy",                  # fixed: was wrong (Westinghouse Nuclear URL)
    "Bloom Energy":         "https://bloomenergy.wd1.myworkdayjobs.com/BloomEnergyCareers",
    "Anza Renewables":      "https://ats.rippling.com/anza-re-llc/jobs",
    "Kevala":               "https://jobs.ashbyhq.com/kevala",                      # fixed: was HTML
    "EVgo":                 "https://jobs.ashbyhq.com/evgo",                        # fixed: was HTML
    "ChargePoint":          "https://job-boards.greenhouse.io/chargepoint",
    "Form Energy":          "https://jobs.ashbyhq.com/formenergy",

    # --- Recommended additions based on profile ---
    "SPAN":                 "https://jobs.ashbyhq.com/span",                        # fixed: was HTML
    "Enode":                "https://jobs.ashbyhq.com/enode",                       # fixed: was HTML
    "Omnidian":             "https://jobs.lever.co/omnidian",
    "Aurora Solar":         "https://jobs.ashbyhq.com/aurorasolar",                 # fixed: was HTML
    "Enverus":              "https://jobs.ashbyhq.com/enverus",                     # fixed: was HTML
    "Palmetto":             "https://jobs.ashbyhq.com/palmetto",                    # fixed: was HTML
    "Powerflex":            "https://jobs.ashbyhq.com/powerflex",                   # fixed: was HTML
    "Copper Labs":          "https://jobs.ashbyhq.com/copper-labs",                 # fixed: was HTML
    "GridPoint":            "https://jobs.ashbyhq.com/gridpoint",                   # fixed: was HTML
    # WattBuy: removed — 404, URL dead
    "Electrify America":    "https://jobs.ashbyhq.com/electrify-america",           # fixed: was HTML
    # OhmConnect: removed — 404, URL dead
    # Enbala: removed — SSL cert expired, may be defunct
    "AutoGrid":             "https://jobs.ashbyhq.com/autogrid",                    # fixed: was HTML

    # --- Energy Trading ---
    "NextEra Energy":       "https://jobs.nexteraenergy.com/",
    "LevelTen Energy":      "https://job-boards.greenhouse.io/leveltenenergy",
    "Pexapark":             "https://jobs.pexapark.com/jobs",
    "Power Ledger":         "https://powerledger.io/careers/",

    # --- Energy Software Platforms ---
    "GE Vernova":           "https://gevernova.wd5.myworkdayjobs.com/Vernova_ExternalSite",
    "AspenTech":            "https://aspentech.wd5.myworkdayjobs.com/AspenTech",
    "Hitachi Energy":       "https://careers.hitachi.com/search/hitachi-energy/jobs",
    "Siemens Grid Software": "https://jobs.siemens-energy.com/en_US/jobs/Jobs/Grid%20technologies?listFilterMode=1",

    # --- Building Electrification ---
    "Dandelion Energy":     "https://job-boards.greenhouse.io/dandelionenergy",
    "BlocPower":            "https://job-boards.greenhouse.io/blocpower",
    "Quilt":                "https://job-boards.greenhouse.io/quilt",

    # --- Industrial AI ---
    "Samsara":              "https://boards.greenhouse.io/samsara",
    "Augury":               "https://job-boards.greenhouse.io/augury",
    "Sight Machine":        "https://ats.rippling.com/sightmachine/jobs",

    # --- Infrastructure Software ---
    "Sitetracker":          "https://www.sitetracker.com/company/careers/",
    "Procore":              "https://procore.wd12.myworkdayjobs.com/Procore_External_Careers",
    "ServiceTitan":         "https://servicetitan.wd1.myworkdayjobs.com/ServiceTitan",

    # --- Fintech Infrastructure ---
    "Stripe":               "https://stripe.com/jobs/search",
    "Plaid":                "https://jobs.lever.co/plaid",
    "Marqeta":              "https://job-boards.greenhouse.io/marqeta",              # fixed: was HTML
    "Modern Treasury":      "https://jobs.ashbyhq.com/modern-treasury",             # fixed: was HTML

    # --- ESG / Sustainability Software ---
    "Watershed":            "https://jobs.ashbyhq.com/watershed",
    "Persefoni":            "https://job-boards.greenhouse.io/persefoni",
    "Measurabl":            "https://job-boards.greenhouse.io/measurabl",
    "Sweep":                "https://jobs.lever.co/sweep",
    "Greenly":              "https://jobs.lever.co/greenly",
    "Terrascope":           "https://jobs.ashbyhq.com/terrascope",
    "Sphera":               "https://job-boards.greenhouse.io/sphera",
    "EcoVadis":             "https://job-boards.greenhouse.io/ecovadis",
    "Workiva":              "https://workiva.wd1.myworkdayjobs.com/Workiva",
    "Diligent":             "https://job-boards.greenhouse.io/diligent",

    # --- Data Platform & Analytics ---
    "dbt Labs":             "https://job-boards.greenhouse.io/dbtlabs",
    "Amplitude":            "https://job-boards.greenhouse.io/amplitude",
    "Monte Carlo":          "https://jobs.lever.co/montecarlodata",
    "Fivetran":             "https://job-boards.greenhouse.io/fivetran",
    "Retool":               "https://jobs.ashbyhq.com/retool",
    "Rippling":             "https://jobs.ashbyhq.com/rippling",
    "Figma":                "https://job-boards.greenhouse.io/figma",

    # --- IoT / Smart Building Software ---
    "Turntide Technologies": "https://job-boards.greenhouse.io/turntide",
    "Willow":               "https://jobs.lever.co/willowtwin",
    "Gridium":              "https://jobs.lever.co/gridium",
}

def get_company_tier(company_name: str) -> str:
    """Return tier for a company name (case-insensitive partial match)."""
    name_lower = company_name.lower()
    for c in CLIMATETECH_COMPANIES:
        if c.lower() in name_lower or name_lower in c.lower():
            return "climatetech"
    for c in FINTECH_AI_COMPANIES:
        if c.lower() in name_lower or name_lower in c.lower():
            return "fintech_ai"
    return "other"
