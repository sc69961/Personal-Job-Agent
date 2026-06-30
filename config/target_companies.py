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
    "Weavegrid", "DERAPI", "Camus Energy", "GridBeyond", "Dynamic Grid",
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
    "Uplight":              "https://jobs.jobvite.com/uplight/jobs",
    "Voltus":               "https://jobs.lever.co/voltus",
    "Virtual Peaker":       "https://virtual-peaker.com/company/careers/",
    "Ascend Analytics":     "https://www.ascendanalytics.com/about-us/careers",
    "Kraken":               "https://jobs.lever.co/kraken123",
    "Octopus Energy":       "https://octopus.energy/careers/join-us/",
    "BoxPower":             "https://boxpower.bamboohr.com/careers",
    "Weavegrid":            "https://www.weavegrid.com/careers/job-openings",
    "EnergyHub":            "https://www.energyhub.com/careers/job-listings",
    "Renew Home":           "https://www.renewhome.com/careers#jobs",
    "ev.energy":            "https://evenergy.careers.hibob.com/jobs",
    "Stem":                 "https://stem.wd12.myworkdayjobs.com/StemInc",
    "OptiWatt":             "https://apply.workable.com/optiwatt/",
    "Pivot":                "https://www.pivotenergy.net/careers",
    "Base Power":           "https://www.basepowercompany.com/open-roles",
    "LineVision":           "https://www.linevisioninc.com/careers",
    "Sunrun":               "https://careers.sunrun.com/search-jobs/product%20manager/Colorado%2C%20US/21632/1/3/6252001-5417618/39x00027/-105x50083/50/2",
    "Syso":                 "https://www.sysotechnologies.com/join/",
    "Arcadia":              "https://www.arcadia.com/careers#job-openings",
    "UtilityAPI":           "https://job-boards.greenhouse.io/utilityapi",
    "Utilidata":            "https://utilidata.com/careers#openings",
    "Yes Energy":           "https://job-boards.greenhouse.io/yesenergy",
    "GridX":                "https://gridx.com/careers/#listings",
    "Camus Energy":         "https://www.camus.energy/careers/job-openings",
    "Rhythm Energy":        "https://ats.rippling.com/rhythm-energy/jobs",
    "Bidgely":              "https://www.bidgely.com/careers/#job-openings",
    "Dynamic Grid":         "https://www.griddynamics.com/careers/discover-openings",
    "Modo Energy":          "https://job-boards.eu.greenhouse.io/modoenergy",
    "SB Energy":            "https://sbenergy.com/careers/",
    "GridBeyond":           "https://gridbeyond.com/about-us/careers-2/",
    "Engie":                "https://www.engie.com/en/careers",
    "David Energy":         "https://jobs.ashbyhq.com/davidenergy",
    "Lunar Energy":         "https://www.lunarenergy.com/careers",
    "Kaluza":               "https://careers.kaluza.com/open-jobs",
    "Swell Energy":         "https://www.swellenergy.com/jobs/",
    "Evergen":              "https://evergen.energy/careers-at-evergen/",
    "Next Kraftwerke":      "https://www.next-kraftwerke.com/jobs",
    "GoodLeap":             "https://www.goodleap.com/careers#job-postings",
    "Elephant Energy":      "https://www.elephantenergy.com/careers",
    "Equilibrium Energy":   "https://www.equilibriumenergy.com/careers",
    "GridStatus.io":        "https://www.gridstatus.io/jobs",
    "Enel":                 "https://jobs.enel.com/en_US/careers/JobOpeningsUSA/product",
    "CPower":               "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=b2431733-235a-437c-978d-011f4e00c432&ccId=19000101_000001&type=JS&lang=en_US",
    "PowerSecure":          "https://recruiting.ultipro.com/POW1009POWS/JobBoard/42398959-f1c7-48da-a3e2-94e525e29808/",
    "Enersponse":           "https://www.enersponse.com/careers",
    "Blueprint Power":      "https://www.blueprintenergy.at/projects",
    "Fluence":              "https://fluenceenergy.wd12.myworkdayjobs.com/en-US/fluenceenergy-jobs",
    "Tyba":                 "https://www.tyba.ai/careers/#roles",
    "Habitat Energy":       "https://habitat.energy/careers/",
    "Amperon":              "https://www.amperon.co/careers",
    "Xpansiv":              "https://www.xpansiv.com/careers#careers",
    "OATI":                 "https://www.oati.com/careers/",
    "ION Group":            "https://jobs.lever.co/ion",
    "PCI Energy Solutions": "https://careers.westinghousenuclear.com/go/All-Careers/8736400/",
    "Bloom Energy":         "https://bloomenergy.wd1.myworkdayjobs.com/BloomEnergyCareers",
    "Anza Renewables":      "https://ats.rippling.com/anza-re-llc/jobs",
    "Kevala":               "https://www.kevala.com/careers#open-roles",
    "EVgo":                 "https://www.evgo.com/company/careers/#open_positions",

    # --- Recommended additions based on profile ---
    "SPAN":                 "https://www.span.io/job-board",          # Smart panel + DER integration
    "Enode":                "https://www.enode.com/careers",          # DER/EV API platform (YC)
    "Omnidian":             "https://jobs.lever.co/omnidian",         # Solar ops platform
    "Aurora Solar":         "https://aurorasolar.com/careers/",       # Solar design + AI
    "Enverus":              "https://www.enverus.com/careers/",       # Energy data, Denver-based
    "Palmetto":             "https://palmetto.com/careers",           # Residential solar/battery
    "Powerflex":            "https://www.powerflex.com/careers",      # Commercial EV + solar + storage
    "Copper Labs":          "https://www.copperlabs.com/careers",     # Home energy intelligence (401 errors — may be gated)
    "GridPoint":            "https://www.gridpoint.com/careers/",     # Commercial energy management
    # WattBuy: removed — 404, URL dead
    "Electrify America":    "https://www.electrifyamerica.com/careers/", # EV charging
    # OhmConnect: removed — 404, URL dead
    # Enbala: removed — SSL cert expired, may be defunct
    "AutoGrid":             "https://www.auto-grid.com/careers/",     # AI for energy flexibility

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
    "Marqeta":              "https://www.marqeta.com/company/careers",
    "Modern Treasury":      "https://www.moderntreasury.com/about#careers",
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
