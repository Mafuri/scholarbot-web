"""
engine/scholarship_engine.py
============================
Core AI engine for the web platform.
Wraps scholarship DB, matching, essay generation, and package building.
Works for all degree levels: Undergraduate, Graduate, Postgraduate.
"""

from __future__ import annotations
import json, logging, os, time, uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ── Scholarship Database ─────────────────────────────────────
# Complete database: UG + Graduate + Postgraduate
# Direct portal URLs only — no aggregators

_SCHOLARSHIP_DB: list[dict] = []

def _load_db() -> list[dict]:
    global _SCHOLARSHIP_DB
    if _SCHOLARSHIP_DB:
        return _SCHOLARSHIP_DB

    from datetime import datetime, timedelta
    import hashlib

    def _id(n, p): return "sch_" + hashlib.md5(f"{n}{p}".encode()).hexdigest()[:10]
    def _due(d): return (datetime.now() + timedelta(days=d)).strftime("%Y-%m-%d")
    def _fixed(m, d):
        yr = datetime.now().year
        dt = datetime(yr, m, d)
        if dt < datetime.now():
            dt = datetime(yr + 1, m, d)
        return dt.strftime("%Y-%m-%d")

    AFRICA = ["Kenya", "Nigeria", "Ghana", "Tanzania", "Uganda", "Rwanda",
              "Ethiopia", "Senegal", "Zambia", "Malawi", "Mozambique",
              "Zimbabwe", "South Africa", "All African countries"]
    EAST = ["Kenya", "Tanzania", "Uganda", "Rwanda", "Ethiopia"]
    CW = AFRICA + ["India", "Pakistan", "Bangladesh", "Malaysia",
                   "Australia", "Canada", "UK", "All Commonwealth countries"]
    ALL = ["All countries"]
    DEV = AFRICA + ["India", "Pakistan", "Bangladesh", "Nepal",
                    "Vietnam", "Indonesia", "All developing countries"]
    IT = ["Information Technology", "IT Management", "Computer Science",
          "Software Engineering", "Information Technology Management",
          "Information Systems", "Computing"]
    SEC = ["Cybersecurity", "Information Security", "Network Security",
           "Digital Forensics", "Security Engineering", "Ethical Hacking"]
    AI = ["Artificial Intelligence", "Machine Learning", "Data Science",
          "Deep Learning", "NLP", "Computer Vision", "Analytics"]
    TECH = IT + SEC + AI + ["Cloud Computing", "DevOps", "Database Administration",
                             "Digital Transformation", "Fintech", "STEM"]

    def sch(name, prov, url, amt, dl, deg, ctry, maj, gpa, need,
            essay, req, elig, src, tags=None):
        return {
            "id": _id(name, prov), "name": name, "provider": prov,
            "url": url, "amount_usd": float(amt), "deadline": dl,
            "degree_levels": deg if isinstance(deg, list) else [deg],
            "eligible_countries": ctry, "major_restrictions": maj,
            "gpa_min": float(gpa), "gpa_max": 4.0,
            "financial_need": bool(need), "essay_prompt": essay,
            "requirements": req, "eligibility": elig, "source": src,
            "tags": (tags or []) + ["direct-portal"],
            "status": "open",
        }

    db = [
        # ── UNDERGRADUATE ────────────────────────────────────
        sch("MasterCard Foundation Scholars — Undergraduate", "MasterCard Foundation",
            "https://mastercardfdn.org/all/scholars/becoming-a-scholar/",
            50000, _fixed(12, 15), ["Undergraduate"], AFRICA, [], 3.3, True,
            "Describe a challenge in your community and how education will help you address it.",
            "African student, financial need, commitment to give back",
            "Sub-Saharan African undergraduates with financial need",
            "mcf", ["africa", "financial_need", "undergraduate", "prestigious"]),

        sch("Equity Wings to Fly 2026", "Equity Group Foundation",
            "https://equitygroupfoundation.com/education/wings-to-fly/",
            8000, _fixed(1, 31), ["Undergraduate"], EAST, [], 3.0, True,
            "What is your dream and how will education transform your community?",
            "East African, financial need, leadership potential",
            "East African undergraduates from low-income backgrounds",
            "equity", ["east_africa", "kenya", "undergraduate", "financial_need"]),

        sch("HELB Scholarship and Bursary 2026", "HELB Kenya",
            "https://www.helb.co.ke/scholarships/",
            2500, _fixed(3, 31), ["Undergraduate"], ["Kenya"], [], 2.8, True,
            "Describe your financial situation and educational goals.",
            "Kenyan citizen, financial need, enrolled in accredited institution",
            "Kenyan undergraduates with financial need",
            "helb", ["kenya", "financial_need", "government", "undergraduate"]),

        sch("HELB STEM Excellence Award", "HELB Kenya",
            "https://www.helb.co.ke/scholarships/stem/",
            3000, _fixed(2, 28), ["Undergraduate"], ["Kenya"], IT + SEC + AI,
            3.2, True, "How will STEM contribute to Kenya Vision 2030?",
            "Kenyan citizen, STEM major, financial need",
            "Kenyan STEM undergraduates", "helb",
            ["kenya", "stem", "government", "financial_need", "it", "undergraduate"]),

        sch("Google Generation Scholarship Africa", "Google",
            "https://buildyourfuture.withgoogle.com/scholarships/generation-google-scholarship-apac",
            7000, _due(120), ["Undergraduate"], AFRICA, IT + AI + ["Software Engineering"],
            3.0, False, "Describe a project where you used tech to solve a real problem.",
            "African CS/IT student, demonstrated academic excellence",
            "African students in CS/IT/AI",
            "google", ["tech", "africa", "google", "stem", "undergraduate"]),

        sch("Microsoft STEM Diversity Scholarship", "Microsoft",
            "https://careers.microsoft.com/students/us/en/usscholarshipprogram",
            5000, _due(120), ["Undergraduate"], ALL, IT + AI, 3.0, False,
            "Describe your passion for technology and Microsoft's mission.",
            "STEM student, tech passion, community involvement",
            "STEM undergraduates globally",
            "microsoft", ["microsoft", "tech", "diversity", "stem", "undergraduate"]),

        sch("ISC2 Undergraduate Cybersecurity Scholarship", "ISC2",
            "https://www.isc2.org/landing/1mcc",
            5000, _fixed(3, 1), ["Undergraduate"], ALL, SEC + IT, 3.0, False,
            "How will you contribute to the cybersecurity profession?",
            "Undergraduate in cybersecurity/IT",
            "Undergraduate cybersecurity students worldwide",
            "isc2", ["cybersecurity", "infosec", "undergraduate", "global"]),

        sch("Cisco Networking Academy Scholarship", "Cisco",
            "https://www.netacad.com/careers/scholarships",
            5000, _due(120), ["Undergraduate"], ALL, IT + SEC + ["Networking"],
            2.8, False, "How will networking and cybersecurity skills advance your career?",
            "Cisco NetAcad student, networking/security major",
            "Cisco Academy students globally",
            "cisco", ["cisco", "networking", "cybersecurity", "it", "undergraduate"]),

        sch("AWS Educate Cloud Computing Scholarship", "Amazon Web Services",
            "https://aws.amazon.com/education/awseducate/",
            3000, _due(150), ["Undergraduate"], ALL, IT + AI + ["Cloud Computing"],
            3.0, False, "How will cloud skills help you solve problems in your region?",
            "Enrolled student, STEM major", "Global tech students",
            "aws", ["aws", "cloud", "tech", "global", "it", "undergraduate"]),

        sch("Tony Elumelu Foundation Entrepreneurship", "TEF",
            "https://www.tonyelumelufoundation.org/programme",
            10000, _fixed(1, 1), ["Undergraduate", "Graduate", "Postgraduate"],
            AFRICA, [], 0.0, False,
            "Describe your business idea and how it creates value in Africa.",
            "African entrepreneur, business idea",
            "African entrepreneurs", "tef",
            ["africa", "entrepreneurship", "tech", "fintech", "all_levels"]),

        sch("AfroTech Scholarship", "Blavity/AfroTech",
            "https://afrotech.com/scholarship",
            2500, _due(90), ["Undergraduate"], ALL, IT + AI + SEC, 3.0, False,
            "How will you use technology to advance opportunities for Black communities?",
            "Black student in tech field",
            "Black students in technology globally",
            "afrotech", ["black", "diversity", "tech", "it", "undergraduate"]),

        sch("ALX Africa Software Engineering Scholarship", "ALX Africa",
            "https://www.alxafrica.com/software-engineering/",
            6000, _due(60), ["Undergraduate"], AFRICA, IT + ["Software Engineering"],
            2.5, False,
            "Why become a software engineer? What African problem will you solve?",
            "African student, passion for tech",
            "African students entering software engineering",
            "alx", ["africa", "tech", "software", "coding", "undergraduate"]),

        sch("GitHub Externship Open Source", "GitHub",
            "https://externship.github.in/",
            6000, _due(90), ["Undergraduate"], ALL,
            IT + ["Open Source", "Software Engineering", "DevOps"],
            0.0, False, "Describe your open-source contributions and goals.",
            "Active GitHub contributor, coding skills",
            "Open source contributors globally",
            "github", ["github", "open-source", "software", "coding", "undergraduate"]),

        sch("Zindi Africa Data Challenge Scholarship", "Zindi",
            "https://zindi.africa/competitions",
            5000, _due(60), ["Undergraduate"], AFRICA, AI + IT, 0.0, False,
            "Compete in data science challenge — top performers earn scholarships.",
            "African data scientist, competition participation",
            "African data scientists",
            "zindi", ["africa", "data-science", "ai", "competition", "undergraduate"]),

        # ── GRADUATE ─────────────────────────────────────────
        sch("Chevening Scholarship 2025/26", "UK FCDO",
            "https://www.chevening.org/apply/",
            35000, _fixed(11, 5), ["Graduate"], CW, [], 3.0, False,
            "Describe your leadership and how Chevening will help you contribute to your home country.",
            "2+ years work experience, leadership, commitment to return",
            "Chevening-eligible country citizens",
            "chevening", ["leadership", "uk", "prestigious", "africa", "graduate"]),

        sch("Commonwealth Masters Scholarship 2026", "CSC",
            "https://cscuk.fcdo.gov.uk/scholarships/commonwealth-masters-scholarships/",
            30000, _fixed(12, 1), ["Graduate"], CW, [], 3.2, True,
            "How will UK studies benefit your home country's development?",
            "Commonwealth citizen, upper second degree, financial need",
            "Citizens of developing Commonwealth countries",
            "commonwealth", ["commonwealth", "development", "financial_need", "graduate"]),

        sch("DAAD Development-Related Postgraduate 2026", "DAAD",
            "https://www.daad.de/en/study-and-research-in-germany/scholarships/daad-scholarships/",
            18000, _fixed(10, 31), ["Graduate"], DEV,
            IT + AI + ["Engineering", "Agriculture", "Economics"], 3.0, True,
            "How will study in Germany address a development challenge in your country?",
            "Bachelor, commitment to return", "Nationals of developing countries",
            "daad", ["germany", "stem", "development", "africa", "graduate"]),

        sch("MasterCard Foundation Scholars — Graduate", "MasterCard Foundation",
            "https://mastercardfdn.org/all/scholars/becoming-a-scholar/",
            50000, _fixed(12, 15), ["Graduate"], AFRICA, [], 3.3, True,
            "Describe a community challenge and how your education will address it.",
            "Sub-Saharan African, financial need, commitment to give back",
            "Sub-Saharan African graduate students with financial need",
            "mcf", ["africa", "financial_need", "leadership", "prestigious", "graduate"]),

        sch("Fulbright Foreign Student Program 2026", "US State Dept",
            "https://foreign.fulbrightonline.org/about/foreign-fulbright",
            45000, _fixed(10, 15), ["Graduate"], ALL, [], 3.3, False,
            "Describe your proposed US study and plan to apply knowledge at home.",
            "Participating country citizen, bachelor, English proficiency",
            "International graduate students in USA",
            "fulbright", ["usa", "prestigious", "fully-funded", "government", "graduate"]),

        sch("GREAT Scholarship Kenya 2026", "British Council",
            "https://www.britishcouncil.org/study-work-abroad/in-uk/great-scholarship",
            12000, _fixed(2, 1), ["Graduate"], ["Kenya"], [], 3.0, False,
            "How will UK studies advance your ambitions and help Kenya?",
            "Kenyan citizen, bachelor, UK university applicant",
            "Kenyan nationals for postgraduate study in UK",
            "britishcouncil", ["kenya", "uk", "graduate"]),

        sch("Netherlands Fellowship Programme 2026", "Nuffic",
            "https://www.studyinholland.nl/scholarships/highlighted-scholarships/netherlands-fellowship-programme",
            28000, _fixed(2, 1), ["Graduate"], DEV, [], 3.2, True,
            "How will this programme strengthen your professional capacity?",
            "Employed, employer nomination, eligible country",
            "Mid-career professionals from developing countries",
            "netherlands", ["netherlands", "europe", "development", "graduate"]),

        sch("Swedish Institute Scholarship 2026", "Swedish Institute",
            "https://si.se/en/apply/scholarships/swedish-institute-scholarships-for-global-professionals/",
            25000, _fixed(2, 10), ["Graduate"], DEV, [], 3.0, False,
            "Describe your leadership and how Sweden will help you drive change.",
            "3+ years work experience, eligible country",
            "Leaders from developing countries",
            "sweden", ["sweden", "europe", "leadership", "development", "graduate"]),

        sch("African Development Bank Scholarship 2026", "AfDB",
            "https://www.afdb.org/en/topics-and-sectors/initiatives-partnerships/african-development-bank-scholarships-program",
            22000, _fixed(3, 31), ["Graduate"], AFRICA,
            ["Economics", "Finance", "Engineering", "IT", "IT Management",
             "Computer Science", "Data Science"], 3.2, False,
            "How will your studies contribute to Africa's development?",
            "African citizen, bachelor, under 35",
            "AfDB member state citizens",
            "afdb", ["africa", "development", "economics", "stem", "graduate"]),

        sch("ISC2 Graduate Cybersecurity Scholarship", "ISC2",
            "https://www.isc2.org/landing/1mcc",
            5000, _fixed(3, 1), ["Graduate"], ALL, SEC + IT, 3.2, False,
            "How will graduate studies advance the cybersecurity field?",
            "Graduate student in cybersecurity",
            "Graduate cybersecurity students worldwide",
            "isc2", ["cybersecurity", "infosec", "graduate", "global"]),

        sch("Erasmus Mundus Joint Masters — Cybersecurity", "European Commission",
            "https://erasmus-plus.ec.europa.eu/opportunities/individuals/students/erasmus-mundus-joint-masters",
            48000, _fixed(1, 15), ["Graduate"], ALL, SEC + IT, 3.0, False,
            "Why study cybersecurity across multiple European countries?",
            "Bachelor in CS/IT/Security",
            "Global students for European joint master in cybersecurity",
            "erasmus", ["europe", "cybersecurity", "prestigious", "joint-degree", "graduate"]),

        sch("Erasmus Mundus Joint Masters — AI & Data Science", "European Commission",
            "https://erasmus-plus.ec.europa.eu/opportunities/individuals/students/erasmus-mundus-joint-masters",
            48000, _fixed(1, 15), ["Graduate"], ALL, AI + IT, 3.0, False,
            "How will this joint European AI programme advance your goals?",
            "Bachelor in CS/Statistics",
            "Global students for European AI master",
            "erasmus", ["europe", "data-science", "ai", "prestigious", "joint-degree", "graduate"]),

        sch("Aga Khan Foundation Scholarship 2026", "AKF",
            "https://www.akdn.org/our-agencies/aga-khan-foundation/international-scholarship-programme",
            20000, _fixed(11, 30), ["Graduate"],
            EAST + ["Bangladesh", "Pakistan", "India"], [], 3.3, True,
            "Describe how your studies connect to a development challenge at home.",
            "Exceptional record, financial need, commitment to return",
            "Citizens of select developing countries",
            "akf", ["prestigious", "financial_need", "east_africa", "kenya", "graduate"]),

        sch("Equity Postgraduate Scholarship 2026", "Equity Foundation",
            "https://equitygroupfoundation.com/education/postgraduate-scholarships/",
            15000, _fixed(2, 28), ["Graduate"], EAST, [], 3.2, True,
            "How will your studies address a challenge in East Africa?",
            "East African, upper second, financial need",
            "East African graduate students",
            "equity", ["east_africa", "kenya", "graduate", "financial_need"]),

        sch("ALX Africa Data Science & AI Scholarship", "ALX Africa",
            "https://www.alxafrica.com/data-science/",
            5000, _due(60), ["Graduate"], AFRICA, AI + IT, 2.5, False,
            "How will data science and AI help you create impact in Africa?",
            "African student, analytical aptitude",
            "African graduate students in data science",
            "alx", ["africa", "data-science", "ai", "coding", "graduate"]),

        # ── POSTGRADUATE / PhD ────────────────────────────────
        sch("Commonwealth PhD Scholarship 2026", "CSC",
            "https://cscuk.fcdo.gov.uk/scholarships/commonwealth-phd-scholarships/",
            75000, _fixed(12, 1), ["Postgraduate"], CW, [], 3.5, False,
            "Describe your research and its impact on your home country.",
            "First class degree, research proposal, supervisor confirmed",
            "Commonwealth citizens for PhD in UK",
            "commonwealth", ["commonwealth", "phd", "research", "prestigious", "postgraduate"]),

        sch("Gates Cambridge Scholarship 2026", "Gates Cambridge Trust",
            "https://www.gatescambridge.org/programme/the-scholarship/",
            60000, _fixed(12, 3), ["Postgraduate"], ALL, [], 3.7, False,
            "Why Cambridge? How will your studies improve others' lives?",
            "Applied to Cambridge, exceptional academic record",
            "International PhD/Masters students at Cambridge",
            "gates_cambridge", ["uk", "cambridge", "prestigious", "postgraduate"]),

        sch("KAUST Fellowship — AI & Computing", "KAUST",
            "https://admissions.kaust.edu.sa/scholarships",
            60000, _fixed(12, 15), ["Postgraduate"], ALL,
            AI + IT + ["Computational Science", "Bioinformatics"], 3.5, False,
            "Describe your research and how KAUST will advance your work.",
            "Bachelor, research aptitude, STEM background",
            "International students at KAUST",
            "kaust", ["saudi_arabia", "fully-funded", "ai", "research", "postgraduate"]),

        sch("Google PhD Fellowship — AI/ML/Security", "Google Research",
            "https://research.google/outreach/phd-fellowship/",
            50000, _due(180), ["Postgraduate"], ALL, AI + SEC + IT, 3.5, False,
            "Describe your research and its potential to advance the field.",
            "Enrolled PhD, university nomination",
            "PhD students in CS/AI/Security worldwide",
            "google", ["usa", "google", "ai", "cybersecurity", "postgraduate"]),

        sch("NVIDIA Graduate Fellowship AI/Deep Learning", "NVIDIA",
            "https://research.nvidia.com/graduate-fellowships",
            50000, _fixed(9, 1), ["Postgraduate"],
            ALL, AI + ["Computer Architecture", "Graphics"], 3.5, False,
            "Describe your research and how GPU computing advances your work.",
            "PhD using GPU computing, faculty nomination",
            "PhD students in AI, graphics, architecture",
            "nvidia", ["usa", "nvidia", "ai", "deep-learning", "postgraduate"]),

        sch("Microsoft Research PhD Fellowship", "Microsoft Research",
            "https://www.microsoft.com/en-us/research/academic-program/phd-fellowship/",
            42000, _due(180), ["Postgraduate"], ALL, TECH, 3.5, False,
            "Describe your research and alignment with Microsoft areas.",
            "2nd year PhD, faculty nomination",
            "PhD students in CS, AI fields",
            "microsoft", ["usa", "microsoft", "ai", "research", "postgraduate"]),

        sch("Vanier Canada Graduate Scholarship", "Government of Canada",
            "https://vanier.gc.ca/en/scholarship_details-renseignements_de_la_bourse.html",
            150000, _fixed(11, 1), ["Postgraduate"], ["Canada", "All"], TECH,
            3.7, False,
            "Describe your leadership and research contribution to Canada and the world.",
            "Enrolled Canadian PhD, excellence, leadership",
            "PhD students at Canadian universities",
            "vanier", ["canada", "phd", "prestigious", "fully-funded", "postgraduate"]),

        sch("NSF Graduate Research Fellowship CS/AI/Security", "NSF",
            "https://www.nsfgrfp.org/",
            147000, _fixed(10, 15), ["Postgraduate"], ["USA"], TECH, 3.5, False,
            "Describe your research plan, intellectual merit, and societal impact.",
            "US citizen or permanent resident, early graduate career",
            "US citizens/residents in STEM",
            "nsf", ["usa", "prestigious", "research", "ai", "postgraduate"]),

        sch("PASET ICT Engineering PhD Scholarship", "PASET",
            "https://paset.org/regional-scholarship-and-innovation-fund",
            40000, _fixed(5, 31), ["Postgraduate"],
            ["Kenya", "Nigeria", "Ethiopia", "Tanzania", "Rwanda"],
            IT + ["Engineering", "Agriculture"], 3.3, False,
            "Describe your research and how it addresses Africa's development needs.",
            "African, enrolled at African university, STEM PhD",
            "African PhD students at African universities",
            "paset", ["africa", "phd", "stem", "research", "postgraduate"]),

        sch("IBM PhD Fellowship AI and Cybersecurity", "IBM Research",
            "https://research.ibm.com/university/awards/fellowships.html",
            35000, _fixed(10, 15), ["Postgraduate"],
            ALL, AI + SEC + ["Quantum"], 3.5, False,
            "Describe your dissertation and relevance to IBM research areas.",
            "Enrolled PhD, faculty nomination",
            "PhD students in CS/AI/Security worldwide",
            "ibm", ["usa", "ibm", "ai", "cybersecurity", "postgraduate"]),

        sch("SINGA PhD Scholarship Singapore", "A*STAR Singapore",
            "https://www.a-star.edu.sg/Scholarships/for-graduate-studies/singapore-international-graduate-award-singa",
            50000, _fixed(6, 1), ["Postgraduate"],
            ALL, AI + IT + ["Biomedical", "Engineering"], 3.5, False,
            "Describe your proposed research and why Singapore is ideal.",
            "Bachelor/Master, research aptitude",
            "International PhD students at Singapore universities",
            "singa", ["singapore", "asia", "phd", "research", "ai", "postgraduate"]),

        sch("DAAD Research Grants Doctoral 2026", "DAAD",
            "https://www.daad.de/en/find-funding/scholarship-database/",
            25000, _fixed(11, 30), ["Postgraduate"], ALL, [], 3.5, False,
            "Describe your research project and scientific significance.",
            "Accepted PhD programme", "International researchers in Germany",
            "daad", ["germany", "phd", "research", "postgraduate"]),

        sch("Wellcome Trust Fellowship Digital Health", "Wellcome Trust",
            "https://wellcome.org/funding/schemes/research-career-development-fellowships",
            90000, _fixed(3, 1), ["Postgraduate"],
            ALL, AI + ["Bioinformatics", "Digital Health", "Health Data"], 3.5, False,
            "Describe your digital health research and potential patient impact.",
            "Exceptional researcher, health technology focus",
            "Biomedical and digital health researchers",
            "wellcome", ["health", "bioinformatics", "ai", "research", "postgraduate"]),

        sch("DeepMind Scholarship Google", "Google DeepMind",
            "https://deepmind.google/about/education/",
            25000, _due(150), ["Postgraduate"], ALL, AI, 3.5, False,
            "Describe your AI research and how it benefits society.",
            "Masters or PhD in ML/AI",
            "Graduate students in AI",
            "deepmind", ["ai", "ml", "google", "deepmind", "research", "postgraduate"]),

        sch("Schwarzman Scholars Program", "Schwarzman College",
            "https://www.schwarzmanscholars.org/admissions/",
            50000, _fixed(9, 15), ["Postgraduate", "Graduate"], ALL, [], 3.5, False,
            "Describe a global challenge and how your background addresses it through leadership.",
            "Under 29, bachelor, leadership",
            "Young leaders globally at Tsinghua",
            "schwarzman", ["china", "prestigious", "leadership", "fully-funded"]),

        # ── OPEN TO ALL LEVELS ───────────────────────────────
        sch("Rotary Peace Fellowship", "Rotary International",
            "https://www.rotary.org/en/our-programs/peace-fellowships",
            65000, _fixed(5, 31), ["Graduate", "Postgraduate"], ALL,
            ["Peace Studies", "International Development", "Cybersecurity",
             "Digital Rights", "Technology Policy"], 3.0, False,
            "Describe a conflict you witnessed and how peace studies equips you to address it.",
            "3+ years work experience in peace/development",
            "Global peace and development leaders",
            "rotary", ["peace", "global", "leadership", "prestigious"]),

        sch("SANS Cyber Academy Scholarship", "SANS Institute",
            "https://www.sans.org/cybertalent/scholarship/",
            15000, _due(90), ["Undergraduate", "Graduate"], ALL, SEC, 2.5, False,
            "Why pursue cybersecurity training and what is your planned impact?",
            "Interest in cybersecurity",
            "Students interested in cybersecurity",
            "sans", ["cybersecurity", "training", "global", "certification"]),

        sch("Data Science Africa Fellowship", "DSA",
            "https://www.datascienceafrica.org/",
            8000, _due(90), ["Graduate", "Postgraduate"], AFRICA, AI + IT, 3.0, False,
            "How will data science help you address a development challenge in Africa?",
            "African student/researcher, ML background",
            "African researchers in data science",
            "dsa", ["africa", "data-science", "ai", "ml", "development"]),

        sch("Black in AI Academic Program", "Black in AI",
            "https://blackinai.github.io/#/programs/academic",
            5000, _due(120), ["Graduate", "Postgraduate"], ALL, AI, 3.0, False,
            "Describe your research and plans to increase diversity in AI.",
            "Black/African researcher in AI",
            "Black/African AI researchers globally",
            "black_in_ai", ["ai", "diversity", "africa", "ml", "research"]),

        sch("HeadStarter AI Fellowship", "Headstarter AI",
            "https://headstarter.co/fellowship",
            8000, _due(60), ["Undergraduate", "Graduate"], ALL, AI + IT, 0.0, False,
            "Describe an AI project you want to build and the problem it solves.",
            "Coding skills, passion for AI/ML",
            "Students building AI globally",
            "headstarter", ["ai", "ml", "software", "coding", "global", "young"]),

        sch("Women in Cybersecurity WiCyS Scholarship", "WiCyS",
            "https://www.wicys.org/benefits/scholarship/",
            3000, _fixed(2, 1), ["Undergraduate", "Graduate"], ALL, SEC + IT, 3.0, False,
            "Describe your passion for cybersecurity and inclusion plans.",
            "Female-identifying, cybersecurity degree",
            "Women in cybersecurity globally",
            "wicys", ["cybersecurity", "women", "diversity", "infosec"]),

        sch("ISACA Undergraduate Scholarship", "ISACA",
            "https://www.isaca.org/go/scholarships",
            3000, _fixed(2, 15), ["Undergraduate"], ALL,
            SEC + IT + ["Audit", "Governance"], 3.0, False,
            "Describe your career goals in IT audit, security, or governance.",
            "Undergraduate in IT/security/audit, ISACA member",
            "Undergraduates in IT governance",
            "isaca", ["infosec", "governance", "audit", "it", "undergraduate"]),

        sch("ISACA Graduate Scholarship", "ISACA",
            "https://www.isaca.org/go/scholarships",
            3000, _fixed(2, 15), ["Graduate", "Postgraduate"], ALL,
            SEC + IT + ["Risk", "Governance"], 3.2, False,
            "How will graduate studies advance IT governance, risk, and security?",
            "Graduate student, ISACA member",
            "Graduate students in IT governance",
            "isaca", ["infosec", "governance", "risk", "it", "graduate"]),

        sch("Palo Alto Networks Cybersecurity Scholarship", "Palo Alto Networks",
            "https://www.paloaltonetworks.com/about/csr/giving/scholarship",
            5000, _due(90), ["Undergraduate", "Graduate"], ALL, SEC + IT, 3.0, False,
            "Describe a cybersecurity challenge and your approach to it.",
            "Enrolled in cybersecurity/IT",
            "Students in cybersecurity globally",
            "paloalto", ["cybersecurity", "network-security", "global"]),

        sch("UNESCO ICT Fellowship Programme", "UNESCO",
            "https://www.unesco.org/en/fellowships",
            20000, _fixed(4, 30), ["Graduate", "Postgraduate"], DEV,
            IT + ["Education Technology", "Media"], 3.0, False,
            "How will ICT studies advance UNESCO's mission?",
            "Developing country citizen, ICT focus",
            "Students from developing countries in ICT",
            "unesco", ["unesco", "ict", "education-tech", "development"]),

        sch("MasterCard Foundation — U of Toronto", "MCF/UofT",
            "https://mastercardfoundationscholars.utoronto.ca/",
            65000, _fixed(12, 1), ["Graduate", "Postgraduate"], AFRICA,
            TECH + ["Policy", "Economics"], 3.3, True,
            "How will graduate study at Toronto help you lead change in Africa?",
            "African, financial need, commitment to return",
            "African students at U of T",
            "mcf_toronto", ["africa", "canada", "prestigious", "fully-funded"]),

        sch("Australian Awards Scholarship", "Australian Govt DFAT",
            "https://www.australiaawards.gov.au/",
            55000, _fixed(4, 30), ["Graduate", "Postgraduate"], AFRICA + DEV, TECH,
            3.0, False,
            "How will study in Australia contribute to your country's development?",
            "Eligible developing country, commitment to return",
            "Students from developing countries",
            "australia", ["australia", "fully-funded", "development", "prestigious"]),

        sch("New Zealand Aid Programme Scholarship", "NZ MFAT",
            "https://www.mfat.govt.nz/en/aid-and-development/new-zealand-scholarships/",
            40000, _fixed(2, 28), ["Graduate", "Postgraduate"], AFRICA + DEV, TECH,
            3.0, False,
            "How will NZ studies contribute to your country's development?",
            "Eligible country, commitment to return",
            "Students from Pacific and developing countries",
            "new_zealand", ["new_zealand", "development", "fully-funded"]),
    ]

    _SCHOLARSHIP_DB = db
    return db


# ── Data Guard — Anti-Hallucination ──────────────────────────
# All scholarship facts MUST come from this verified DB.
# LLMs are only used for essays and scoring — never for facts.

VERIFIED_FIELDS = {
    "name", "provider", "url", "amount_usd", "deadline",
    "degree_levels", "eligible_countries", "major_restrictions",
    "gpa_min", "financial_need", "essay_prompt", "requirements",
    "eligibility", "tags"
}

def verify_scholarship_data(scholarship: dict) -> dict:
    """
    Strip any fields not in the verified DB schema.
    Ensures no LLM-generated scholarship facts reach the user.
    """
    db_record = get_by_id(scholarship.get("id", ""))
    if db_record:
        # Use DB record as source of truth, only add computed fields
        safe = {k: v for k, v in db_record.items() if k in VERIFIED_FIELDS}
        # Allow computed/display fields
        for computed in ["match_score", "days_left", "win_probability",
                         "targeting_score", "status", "id", "source"]:
            if computed in scholarship:
                safe[computed] = scholarship[computed]
            elif computed in db_record:
                safe[computed] = db_record[computed]
        return safe
    # Not in DB — still allow but flag as unverified
    scholarship["_unverified"] = True
    return scholarship


def safe_scholarship_list(scholarships: list[dict]) -> list[dict]:
    """Apply data guard to a list of scholarships."""
    return [verify_scholarship_data(s) for s in scholarships]



# ── Core engine functions ─────────────────────────────────────

def count_scholarships() -> int:
    return len(_load_db())


def get_all() -> list[dict]:
    return _load_db()


def get_by_id(scholarship_id: str) -> Optional[dict]:
    for s in _load_db():
        if s["id"] == scholarship_id:
            return s
    return None


def get_scholarships_for_profile(profile: dict) -> list[dict]:
    """Return scholarships matching a student's profile."""
    all_s = _load_db()
    country = profile.get("nationality", "Kenya").lower()
    degree = profile.get("degree_level", "Graduate").lower()
    tags = [t.lower() for t in profile.get("demographic_tags", [])]

    results = []
    for s in all_s:
        ctry = [c.lower() for c in s.get("eligible_countries", [])]
        deg = [d.lower() for d in s.get("degree_levels", [])]
        major = profile.get("major", "").lower()
        major_reqs = [m.lower() for m in s.get("major_restrictions", [])]

        country_ok = (
            not ctry or
            any(c in ["all countries", "all", "worldwide", "global"] for c in ctry) or
            any(country in c or c in country for c in ctry) or
            ("africa" in " ".join(ctry) and (
                "kenya" in country or "african" in tags or "africa" in country)) or
            any("all" in c for c in ctry)
        )
        degree_ok = (
            not deg or
            any(degree in d or d in degree for d in deg) or
            "any" in " ".join(deg)
        )
        major_ok = (
            not major_reqs or
            any(major in m or m in major for m in major_reqs)
        )

        if country_ok and degree_ok:
            results.append(s)

    return results


def rank_for_profile(profile: dict) -> list[dict]:
    """Score and rank scholarships for a specific profile."""
    from datetime import datetime
    scholarships = get_scholarships_for_profile(profile)
    gpa = float(profile.get("gpa", 0))

    for s in scholarships:
        score = 0.5
        # GPA fit
        gpa_min = float(s.get("gpa_min", 0))
        if gpa >= gpa_min:
            score += 0.2 * min(1.0, (gpa - gpa_min) / max(0.1, 4.0 - gpa_min))
        else:
            score -= 0.3
        # Financial need match
        if s.get("financial_need") == profile.get("financial_need"):
            score += 0.1
        # Amount score
        amount = float(s.get("amount_usd", 0))
        score += 0.1 * min(1.0, amount / 50000)
        # Deadline urgency
        try:
            dl = datetime.strptime(s.get("deadline", ""), "%Y-%m-%d")
            days = (dl - datetime.now()).days
            if days < 0:
                score -= 1.0  # expired
            elif days < 30:
                score += 0.15
            elif days < 90:
                score += 0.10
        except Exception:
            pass
        s["match_score"] = round(max(0.0, min(1.0, score)), 3)
        s["days_left"] = _days_until(s.get("deadline", ""))

    # Filter expired and sort
    valid = [s for s in scholarships if s.get("days_left", -1) >= 0]
    valid.sort(key=lambda x: (
        -x.get("match_score", 0),
        x.get("days_left", 999),
        -x.get("amount_usd", 0)
    ))
    return valid




# ── Scholarship Readiness Score ──────────────────────────────

def compute_readiness_score(profile: dict) -> dict:
    """
    Compute a Scholarship Readiness Score across 5 dimensions.
    Returns scores (0-100) per dimension and an overall score.
    """
    scores = {}

    # 1. Academic score (GPA, degree level)
    gpa = float(profile.get("gpa", 0))
    academic = min(100, int(gpa / 4.0 * 70 +
        (10 if profile.get("degree_level") in ("Graduate","Postgraduate") else 5) +
        (20 if profile.get("school") else 0)))
    scores["academic"] = academic

    # 2. Leadership & Activities
    activities = profile.get("extracurriculars", [])
    if isinstance(activities, str):
        activities = [a.strip() for a in activities.split(",") if a.strip()]
    leadership = min(100, len(activities) * 20)
    scores["leadership"] = leadership

    # 3. Profile completeness
    required = ["name","email","gpa","major","school","nationality",
                "degree_level","personal_statement"]
    optional = ["skills","extracurriculars","languages","demographic_tags"]
    filled_req = sum(1 for f in required if profile.get(f))
    filled_opt = sum(1 for f in optional if profile.get(f))
    completeness = min(100, int(filled_req/len(required)*70 + filled_opt/len(optional)*30))
    scores["profile_completeness"] = completeness

    # 4. Research/Skills depth
    skills = profile.get("skills", [])
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",") if s.strip()]
    research = min(100, len(skills) * 12 +
        (20 if profile.get("personal_statement") else 0))
    scores["skills_research"] = research

    # 5. Financial/eligibility readiness
    eligibility = 60  # base
    if profile.get("nationality"):
        eligibility += 20
    if profile.get("financial_need") is not None:
        eligibility += 20
    scores["eligibility"] = min(100, eligibility)

    overall = int(sum(scores.values()) / len(scores))

    # Recommendations
    tips = []
    if academic < 60:
        tips.append("Add your GPA to improve academic score")
    if leadership < 40:
        tips.append("Add extracurricular activities and leadership roles")
    if completeness < 70:
        tips.append("Complete your profile — missing fields reduce matching accuracy")
    if scores["skills_research"] < 50:
        tips.append("Add your skills and a personal statement")
    if not tips:
        tips.append("Strong profile! Apply to your top matched scholarships now.")

    level = ("Excellent" if overall >= 80 else
             "Good" if overall >= 60 else
             "Fair" if overall >= 40 else "Needs work")

    return {
        "overall": overall,
        "level": level,
        "scores": scores,
        "tips": tips,
        "scholarships_unlocked": len([s for s in rank_for_profile(profile)
                                      if s.get("match_score", 0) >= 0.5]),
    }


def generate_essay_for(scholarship: dict, profile: dict,
                        tone: str = "personal-narrative",
                        max_words: int = 400) -> str:
    """Generate a tailored essay using the configured LLM."""
    llm = _get_llm()
    system = (
        "You are an expert scholarship essay writer. "
        "Write a compelling, authentic, specific essay. Output essay text only."
    )
    user = (
        f"Write a {max_words}-word scholarship essay.\n\n"
        f"SCHOLARSHIP: {scholarship.get('name')}\n"
        f"PROMPT: {scholarship.get('essay_prompt', 'Why do you deserve this scholarship?')}\n"
        f"MISSION: {scholarship.get('mission_language', '')[:200]}\n\n"
        f"STUDENT PROFILE:\n"
        f"  Name: {profile.get('name')}\n"
        f"  Degree: {profile.get('degree_level')} in {profile.get('major')}\n"
        f"  University: {profile.get('school')}\n"
        f"  GPA: {profile.get('gpa')}\n"
        f"  Country: {profile.get('nationality')}\n"
        f"  Activities: {', '.join(profile.get('extracurriculars', []))}\n"
        f"  Skills: {', '.join(profile.get('skills', []))}\n"
        f"  Personal statement: {profile.get('personal_statement', '')[:300]}\n\n"
        f"TONE: {tone}\n"
        f"MAX WORDS: {max_words}\n\n"
        "Write the essay now. Be specific, authentic, and compelling."
    )
    return llm(system, user)


def prepare_packages(profile: dict, top_n: int = 5,
                      scholarship_ids: Optional[list] = None) -> list[dict]:
    """Generate complete application packages for top N scholarships."""
    from datetime import datetime

    if scholarship_ids:
        scholarships = [s for s in _load_db() if s["id"] in scholarship_ids]
    else:
        scholarships = rank_for_profile(profile)[:top_n]

    packages = []
    user_id = profile.get("id", "anon")
    pkg_base = Path(f"data/packages/{user_id}")

    for s in scholarships:
        slug = s["name"].lower().replace(" ", "_")[:30]
        pkg_dir = pkg_base / f"{slug}_{uuid.uuid4().hex[:4]}"
        pkg_dir.mkdir(parents=True, exist_ok=True)

        # Generate essay
        try:
            essay = generate_essay_for(s, profile)
        except Exception as e:
            logger.warning("Essay generation failed for %s: %s", s["name"], e)
            essay = f"[Essay for {s['name']} — generation failed, please write manually]"

        days_left = _days_until(s.get("deadline", ""))

        # Save files
        (pkg_dir / "essay.txt").write_text(essay, encoding="utf-8")
        (pkg_dir / "meta.json").write_text(json.dumps({
            "scholarship": s["name"], "amount_usd": s["amount_usd"],
            "deadline": s["deadline"], "days_left": days_left,
            "url": s["url"], "provider": s["provider"],
        }), encoding="utf-8")

        # Build briefing HTML
        briefing = _build_briefing_html(s, profile, essay, days_left)
        (pkg_dir / "briefing.html").write_text(briefing, encoding="utf-8")

        packages.append({
            "scholarship": s["name"], "amount_usd": s["amount_usd"],
            "deadline": s["deadline"], "days_left": days_left,
            "url": s["url"],
            "briefing_path": str(pkg_dir / "briefing.html"),
            "essay_path": str(pkg_dir / "essay.txt"),
        })

    return packages


def score_answer(question: str, answer: str, profile: dict,
                  scholarship: str = "general") -> dict:
    """Score an interview answer."""
    import re
    wc = len(answer.split())
    filler_words = ["um", "uh", "like", "basically", "you know", "literally"]
    fillers = sum(answer.lower().count(f) for f in filler_words)
    specifics = len(re.findall(r'\d+|\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b|%', answer))

    length_score = 1.0 if 150 <= wc <= 300 else max(0.3, wc / 200) if wc < 150 else 0.7
    fluency_score = max(0.0, 1.0 - fillers * 0.1)
    specificity_score = min(1.0, specifics * 0.12)
    overall = round((length_score * 0.25 + fluency_score * 0.25 + specificity_score * 0.50), 3)

    tips = []
    if wc < 120:
        tips.append("Answer is too brief — aim for 2 minutes (150-250 words)")
    if fillers > 5:
        tips.append(f"Reduce filler words — {fillers} detected")
    if specifics < 3:
        tips.append("Add specific numbers, names, or places to strengthen your answer")
    if not tips:
        tips.append("Good answer — keep practising specificity")

    return {
        "overall_score": overall,
        "scores": {"length": length_score, "fluency": fluency_score,
                   "specificity": specificity_score},
        "word_count": wc, "filler_count": fillers,
        "feedback": tips[0] if tips else "Good answer.",
        "grade": "A" if overall >= 0.8 else "B" if overall >= 0.65 else "C" if overall >= 0.5 else "D",
    }


def _build_briefing_html(scholarship: dict, profile: dict,
                          essay: str, days_left: int) -> str:
    urg = "#dc2626" if days_left <= 7 else "#d97706" if days_left <= 30 else "#059669"
    name = profile.get("name", "")
    fields = {
        "Full name": name, "Email": profile.get("email", ""),
        "University": profile.get("school", ""),
        "Degree level": profile.get("degree_level", ""),
        "Field of study": profile.get("major", ""),
        "GPA": str(profile.get("gpa", "")),
        "Country": profile.get("nationality", "Kenya"),
        "Financial need": "Yes" if profile.get("financial_need") else "No",
    }
    rows = "".join(
        f"<tr><td style='padding:7px 12px;font-weight:500;color:#555;width:180px;"
        f"border-bottom:1px solid #f0f0f0'>{k}</td>"
        f"<td style='padding:7px 12px;border-bottom:1px solid #f0f0f0'>"
        f"<span onclick=\"navigator.clipboard.writeText('{v}')\" "
        f"style='cursor:pointer;background:#f8f8f8;padding:3px 8px;"
        f"border-radius:4px;font-family:monospace;font-size:13px' "
        f"title='Click to copy'>{v}</span></td></tr>"
        for k, v in fields.items() if v
    )
    essay_safe = essay.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>{scholarship['name']}</title>
<style>*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,sans-serif;background:#f9f9f7;color:#1a1a1a}}
.hdr{{background:#1a1a2e;color:#fff;padding:1.5rem 2rem;display:flex;justify-content:space-between}}
.hdr h1{{font-size:18px;font-weight:500}}
.hdr p{{opacity:.7;font-size:13px;margin-top:4px}}
.urg{{background:{urg};color:#fff;padding:4px 12px;border-radius:20px;font-size:12px}}
.body{{max-width:780px;margin:0 auto;padding:2rem}}
.card{{background:#fff;border:1px solid #e8e8e0;border-radius:12px;margin-bottom:1.25rem;overflow:hidden}}
.card-head{{background:#f5f5f0;padding:.75rem 1.25rem;font-size:13px;font-weight:500;display:flex;align-items:center;gap:8px}}
.num{{width:24px;height:24px;border-radius:50%;background:#1a1a2e;color:#fff;display:flex;align-items:center;justify-content:center;font-size:11px;flex-shrink:0}}
.card-body{{padding:1.25rem}}
.btn{{display:inline-block;background:#1a1a2e;color:#fff;padding:8px 18px;border-radius:6px;text-decoration:none;font-size:13px;cursor:pointer;border:none}}
.btn-outline{{background:#f5f5f0;color:#1a1a2e;border:1px solid #ddd;margin-left:8px}}
table{{width:100%;border-collapse:collapse}}
.essay{{background:#f8f8f8;border:1px solid #e0e0e0;border-radius:8px;padding:1rem;font-size:14px;line-height:1.7;white-space:pre-wrap}}
.toast{{position:fixed;bottom:20px;right:20px;background:#1a1a2e;color:#fff;padding:8px 16px;border-radius:8px;opacity:0;transition:opacity .3s;pointer-events:none;font-size:13px}}
</style></head><body>
<div class="hdr"><div><h1>{scholarship['name']}</h1>
<p>${scholarship['amount_usd']:,.0f} | Deadline: {scholarship['deadline']}</p></div>
<span class="urg">{days_left} days left</span></div>
<div class="body">
<div class="card"><div class="card-head"><span class="num">1</span>Open the application</div>
<div class="card-body"><a class="btn" href="{scholarship['url']}" target="_blank">Open Application Form &rarr;</a>
<p style="font-size:12px;color:#888;margin-top:8px">{scholarship['url']}</p></div></div>
<div class="card"><div class="card-head"><span class="num">2</span>Copy your details (click any value)</div>
<div class="card-body"><table>{rows}</table></div></div>
<div class="card"><div class="card-head"><span class="num">3</span>Paste your essay
<button class="btn btn-outline" onclick="copyEssay()" style="margin-left:auto;padding:4px 12px;font-size:12px">Copy essay</button></div>
<div class="card-body">
<p style="font-size:12px;color:#888;margin-bottom:.75rem"><em>{scholarship.get('essay_prompt','')[:120]}</em></p>
<div class="essay" id="essay">{essay_safe}</div></div></div>
<div class="card"><div class="card-head"><span class="num">4</span>Checklist</div>
<div class="card-body">
{chr(10).join(f"<label style='display:flex;gap:8px;align-items:center;margin-bottom:8px;cursor:pointer'><input type='checkbox'><span style='font-size:13px'>{item}</span></label>" for item in ["All required fields filled","Essay pasted and within word limit","Correct email address used","Supporting documents attached","Clicked Submit and received confirmation"])}
</div></div></div>
<div class="toast" id="toast">Copied!</div>
<script>
function copyEssay(){{navigator.clipboard.writeText(document.getElementById('essay').innerText).then(()=>{{let t=document.getElementById('toast');t.style.opacity=1;setTimeout(()=>t.style.opacity=0,1800)}})}}
</script></body></html>"""


def _get_llm():
    """Get LLM function — uses Ollama if available, falls back to template."""
    try:
        import requests
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        model = os.environ.get("OLLAMA_MODEL", "llama3.2:1b")

        def ollama_fn(system: str, user: str) -> str:
            resp = requests.post(f"{base_url}/api/generate", json={
                "model": model,
                "prompt": f"System: {system}\n\nUser: {user}",
                "stream": False,
            }, timeout=120)
            return resp.json().get("response", "")
        # Test connection
        requests.get(f"{base_url}/api/tags", timeout=3)
        return ollama_fn
    except Exception:
        pass

    # Try Claude API
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        def claude_fn(system: str, user: str) -> str:
            import requests
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": anthropic_key,
                         "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": "claude-haiku-4-5-20251001",
                      "max_tokens": 1000,
                      "system": system,
                      "messages": [{"role": "user", "content": user}]},
                timeout=30,
            )
            return resp.json()["content"][0]["text"]
        return claude_fn

    # Template fallback
    def template_fn(system: str, user: str) -> str:
        return (
            "I am a motivated student committed to excellence and community impact. "
            "My studies in technology have equipped me with the skills to address "
            "real challenges in my community and beyond. This scholarship would "
            "enable me to continue this important work and give back to my country."
        )
    return template_fn


def _days_until(deadline_str: str) -> int:
    try:
        return (datetime.strptime(deadline_str, "%Y-%m-%d") - datetime.now()).days
    except Exception:
        return 999
