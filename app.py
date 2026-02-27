"""
Resume Tailoring System — FastAPI Backend
Uses Claude via Blackbox.ai to tailor resume to job description.
"""
import io
import json
import os
import re
import textwrap
import tempfile
import traceback
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from openai import OpenAI

from reportlab.lib.pagesizes import letter
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import black
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus.frames import Frame
from reportlab.platypus.doctemplate import PageTemplate
from pypdf import PdfReader

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
FONTS_DIR = BASE_DIR / "fonts"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Font Registration ─────────────────────────────────────────────────────────
def _register_fonts():
    """Register Carlito fonts from bundled fonts/ directory."""
    font_map = {
        "Carlito":           "Carlito-Regular.ttf",
        "Carlito-Bold":      "Carlito-Bold.ttf",
        "Carlito-Italic":    "Carlito-Italic.ttf",
        "Carlito-BoldItalic":"Carlito-BoldItalic.ttf",
    }
    for name, fname in font_map.items():
        path = FONTS_DIR / fname
        if not path.exists():
            raise FileNotFoundError(
                f"Font file missing: {path}\n"
                "Please run: python setup_fonts.py"
            )
        try:
            pdfmetrics.registerFont(TTFont(name, str(path)))
        except Exception:
            pass  # Already registered

    pdfmetrics.registerFontFamily(
        "Carlito",
        normal="Carlito",
        bold="Carlito-Bold",
        italic="Carlito-Italic",
        boldItalic="Carlito-BoldItalic"
    )

_register_fonts()

# ── Blackbox / Claude Client ──────────────────────────────────────────────────
BLACKBOX_API_KEY = os.environ.get("BLACKBOX_API_KEY", "sk-955jZX5iIrvkQxUvuwbubQ")
CLAUDE_MODEL = "claude-sonnet-4-5-20250514"  # Best Claude model available on Blackbox.ai

ai_client = OpenAI(
    api_key=BLACKBOX_API_KEY,
    base_url="https://api.blackbox.ai/v1",
)

# ── FastAPI App ───────────────────────────────────────────────────────────────
app = FastAPI(title="Resume Tailoring System")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

@app.get("/")
async def serve_index():
    return FileResponse(str(BASE_DIR / "static" / "index.html"))

# ── Request Model ─────────────────────────────────────────────────────────────
class TailorRequest(BaseModel):
    base_script: str          # The full ReportLab Python script
    jd_api_endpoint: str = "" # e.g. https://api.jobsearch.io/v1/jobs
    jd_api_key: str = ""      # Bearer token for JD API
    job_id: str = ""          # Job ID or URL
    jd_raw: str = ""          # Direct pasted JD (if no API)
    candidate_name: str = "BHARATH KUMAR RAJESH"
    target_role: str = ""
    company_name: str = ""

# ── Job Description Fetching ──────────────────────────────────────────────────
def fetch_job_description(endpoint: str, api_key: str, job_id: str) -> str:
    """Fetch job description from external API. Returns raw text/JSON string."""
    if not endpoint:
        return ""
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    headers["Accept"] = "application/json"

    # Try common URL patterns
    urls_to_try = [
        f"{endpoint.rstrip('/')}/{job_id}",
        f"{endpoint.rstrip('/')}?job_id={job_id}",
        f"{endpoint.rstrip('/')}?id={job_id}",
        job_id if job_id.startswith("http") else None,
    ]

    last_error = None
    for url in urls_to_try:
        if url is None:
            continue
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    return json.dumps(data, indent=2)
                except Exception:
                    return resp.text
        except Exception as e:
            last_error = e

    if last_error:
        raise HTTPException(
            status_code=502,
            detail=f"Could not fetch job description from API: {last_error}"
        )
    return ""

# ── Claude Tailoring ──────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are an elite technical resume writer and ATS optimization specialist.

Your task: Given a base resume's data and a job description, produce a tailored JSON resume object.

RULES:
1. Do NOT fabricate experience, companies, dates, degrees, or publications.
2. DO rewrite bullet points to mirror JD language, responsibilities, and keywords naturally.
3. DO prioritize: impact > measurable metrics > technical depth.
4. DO use strong action verbs. Do NOT start multiple bullets with the same verb.
5. DO insert relevant skills that are present in the base resume but might be reordered/highlighted.
6. KEEP all existing metrics (percentages, response times, user counts, uptime %).
7. ATS optimization: naturally embed JD keywords without stuffing.
8. Keep bullets concise — each must fit in ~2-3 lines on a single-page PDF.
9. Preserve the candidate's voice and authenticity.
10. Single-page constraint: if condensing is needed, shorten bullets not cut them entirely.

OUTPUT FORMAT — return ONLY valid JSON, no markdown, no code fences:
{
  "summary": "One paragraph, 3-4 sentences, aligned to JD",
  "skills": {
    "Languages": "Python (Advanced), Java (Advanced), ...",
    "Backend & APIs": "...",
    "Databases": "...",
    "Web Applications": "...",
    "Infrastructure": "...",
    "Engineering": "...",
    "Tools": "..."
  },
  "experience": [
    {
      "role": "Job Title",
      "company": "Company Name",
      "location": "City, ST",
      "start": "Mon YYYY",
      "end": "Mon YYYY or Present",
      "bullets": ["bullet 1", "bullet 2", "bullet 3", "bullet 4"]
    }
  ],
  "projects": [
    {
      "name": "Project Name | Tech Stack",
      "year": "YYYY",
      "bullets": ["bullet 1"]
    }
  ],
  "education": [
    {
      "school": "University Name",
      "location": "City, ST",
      "degree": "Degree | GPA: X.XX/4.0",
      "start": "Mon YYYY",
      "end": "Mon YYYY"
    }
  ],
  "certifications": [
    "**Cert Name** | Issuer | Date"
  ],
  "changes_summary": "A 2-3 sentence plain-English summary of what was changed and why, for the candidate to review."
}"""

def base_resume_data() -> dict:
    """Returns the structured base resume data extracted from the script."""
    return {
        "summary": (
            "Software Engineer with production experience building multi-tier, scalable, high-volume web applications and "
            "distributed backend services using Python, Java, and JavaScript on AWS. Designed and delivered 24x7 user-centric "
            "applications serving 10,000+ daily requests at 99.5% uptime with RESTful APIs, relational databases, and "
            "continuous integration. Strong competencies in data structures, algorithms, software design, and performance "
            "optimization. M.S. Computer Science (3.86 GPA) with published research (Springer Nature)."
        ),
        "skills": {
            "Languages": "Python (Advanced), Java (Advanced), JavaScript (ES6+), TypeScript, SQL, HTML/CSS, Go (Familiar)",
            "Backend & APIs": "Spring Boot, FastAPI, Flask, Django, Node.js, RESTful API Development, Microservices, Async/Sync Patterns",
            "Databases": "PostgreSQL (Advanced), MySQL, MongoDB, Redis, Database Design, SQL Optimization, Distributed Transactions, Indexing",
            "Web Applications": "React, AJAX, Multi-Tier Architecture, User-Centric Design, 24x7 High-Availability, Performance Optimization",
            "Infrastructure": "Docker, Kubernetes, AWS (EC2, S3, RDS, Lambda, SQS, ALB), CI/CD, GitHub Actions, Terraform, Jenkins",
            "Engineering": "Data Structures, Algorithms, Software Design Patterns, Code Reviews, Unit Testing (JUnit, Pytest, Jest), TDD",
            "Tools": "Git, Linux (RHCSA), Agile/Scrum, JIRA, Prometheus, Grafana, Technical Documentation, Cross-Functional Collaboration"
        },
        "experience": [
            {
                "role": "Graduate Assistant, Distributed Applications & Web Services",
                "company": "Pace University",
                "location": "New York, NY",
                "start": "Mar 2025",
                "end": "Present",
                "bullets": [
                    "Scaled distributed applications applying synchronous and asynchronous design patterns: built multi-tier, high-volume backend services (Python/FastAPI, Java/Spring Boot) with RESTful APIs, message queues (SQS), and event-driven architecture on AWS serving 10,000+ daily requests at 99.5% uptime; made architectural trade-offs balancing speediness and quality across microservices.",
                    "Developed scalable, reliable, user-centric web applications operating 24x7: built React frontend with JavaScript/AJAX consuming multi-tier backend APIs; implemented performance optimization through Redis caching, database query tuning (PostgreSQL), connection pooling, and CDN delivery achieving sub-100ms response times; monitored with Prometheus and Grafana dashboards.",
                    "Produced high quality software that is unit tested, code reviewed, and checked in regularly for continuous integration: maintained 85%+ code coverage (JUnit, Pytest, Jest); built CI/CD pipelines (GitHub Actions) with automated testing, Docker image builds, and deployment to AWS; performed regular code reviews enforcing best engineering practices and software design patterns.",
                    "Provided technical leadership on cross-functional initiatives: integrated AI/ML components (LangChain, OpenAI API) into web services; collaborated with researchers, engineers, and stakeholders; identified opportunities to improve engineering productivity by automating workflows saving 15+ hours/week."
                ]
            },
            {
                "role": "Software Development Intern",
                "company": "Let's Be The Change",
                "location": "Bangalore, India",
                "start": "Sep 2023",
                "end": "May 2024",
                "bullets": [
                    "Built multi-tier production web application with Java/Spring Boot backend and PostgreSQL on AWS serving 1,000+ users at 99.2% uptime; reduced API latency by 80% through performance optimization; integrated third-party web services (Stripe, SendGrid, Twilio); delivered with speediness and quality in Agile sprints.",
                    "Led A/B testing improving user retention by 20%; designed database architecture with relational schema, indexing, and query optimization; code reviewed PRs; presented data-driven insights to stakeholders."
                ]
            },
            {
                "role": "Software Engineer Intern",
                "company": "Alltramatic",
                "location": "New York, NY (Remote)",
                "start": "Mar 2023",
                "end": "Apr 2023",
                "bullets": [
                    "Built automated testing framework with unit tests improving reliability by 30%; contributed to web application serving 1,000+ users; practiced continuous integration and code reviews."
                ]
            },
            {
                "role": "ML Engineering Intern",
                "company": "Compsoft Technologies (Pantechelearning)",
                "location": "Bangalore, India",
                "start": "Aug 2023",
                "end": "Sep 2023",
                "bullets": [
                    "Built production web service API (Python/Flask) with database design on AWS EC2 with Docker; optimized performance on 50K+ records; practiced software design patterns and unit testing."
                ]
            }
        ],
        "projects": [
            {
                "name": "Distributed Web Platform | Java, Spring Boot, React, PostgreSQL, Redis, Docker, AWS",
                "year": "2025",
                "bullets": [
                    "Multi-tier, scalable web application with synchronous and asynchronous APIs, relational database architecture, Redis caching, CI/CD, and 85%+ test coverage; designed for 24x7 high-availability on AWS."
                ]
            },
            {
                "name": "AI-Powered Web Service | Python, FastAPI, LangChain, React, PostgreSQL, Docker",
                "year": "2025",
                "bullets": [
                    "User-centric web application integrating AI into scalable backend services; RESTful API development, database design, performance optimization, and continuous integration. Paper in preparation."
                ]
            }
        ],
        "education": [
            {
                "school": "Pace University, Seidenberg School",
                "location": "New York, NY",
                "degree": "M.S. Computer Science | GPA: 3.86/4.0",
                "start": "Aug 2024",
                "end": "May 2026"
            },
            {
                "school": "Visvesvaraya Technological University (VTU)",
                "location": "Bangalore, India",
                "degree": "B.E. Computer Science",
                "start": "2020",
                "end": "2024"
            }
        ],
        "certifications": [
            "<b>AWS Certified Solutions Architect - Associate</b> | Amazon Web Services | Jan 2026",
            "<b>Red Hat Certified System Administrator (RHCSA)</b> | Red Hat | Jul 2022",
            '<b>Published:</b> "Deep Learning for Plant Disease Classification" - Springer Nature (Sep 2023)'
        ]
    }

def call_claude(jd_text: str, base_data: dict, target_role: str, company_name: str) -> dict:
    """Call Claude via Blackbox.ai to tailor the resume. Returns parsed JSON dict."""
    role_hint = f"\n\nTARGET ROLE: {target_role}" if target_role else ""
    company_hint = f"\nTARGET COMPANY: {company_name}" if company_name else ""

    user_msg = (
        f"BASE RESUME DATA (JSON):\n{json.dumps(base_data, indent=2)}"
        f"\n\nJOB DESCRIPTION:\n{jd_text}"
        f"{role_hint}{company_hint}"
        f"\n\nTailor the resume to this job. Return ONLY valid JSON."
    )

    response = ai_client.chat.completions.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        temperature=0.3,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg}
        ]
    )

    raw = response.choices[0].message.content.strip()

    # Strip markdown fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        # Try to extract JSON from response
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Claude returned invalid JSON: {e}\nRaw: {raw[:500]}")

# ── PDF Generation ────────────────────────────────────────────────────────────
PAGE_WIDTH, PAGE_HEIGHT = letter
LM = 30
RM = PAGE_WIDTH - 582
TM = 18
BM = 12
CW = PAGE_WIDTH - LM - RM

def make_styles():
    ns  = ParagraphStyle("N",  fontName="Carlito-Bold",    fontSize=13, alignment=TA_CENTER,  spaceAfter=0, leading=14)
    cs_ = ParagraphStyle("C",  fontName="Carlito",         fontSize=9,  alignment=TA_CENTER,  spaceAfter=0, leading=11)
    ss  = ParagraphStyle("S",  fontName="Carlito-Bold",    fontSize=10, alignment=TA_LEFT,    spaceBefore=0, spaceAfter=0, leading=11)
    bst = ParagraphStyle("B",  fontName="Carlito",         fontSize=9,  alignment=TA_JUSTIFY, leading=10.8, leftIndent=10, firstLineIndent=0, spaceAfter=0.5)
    kst = ParagraphStyle("K",  fontName="Carlito",         fontSize=9,  alignment=TA_LEFT,    leading=11, spaceAfter=0)
    ust = ParagraphStyle("U",  fontName="Carlito",         fontSize=9,  alignment=TA_JUSTIFY, leading=10.8, spaceAfter=0)
    cwst= ParagraphStyle("CW", fontName="Carlito",         fontSize=9,  leading=11, spaceAfter=2)
    return ns, cs_, ss, bst, kst, ust, cwst

def build_pdf(tailored: dict, candidate_name: str, out_path: str):
    """Build the PDF from tailored resume data dict."""
    ns, cs_, ss, bst, kst, ust, cwst = make_styles()
    story = []

    def sh(t):
        story.append(Spacer(1, 3))
        story.append(Paragraph(t, ss))
        story.append(Spacer(1, 1))
        story.append(HRFlowable(width="100%", thickness=0.5, color=black, spaceAfter=2, spaceBefore=0))

    def tc(lt, rt, lf="Carlito-Bold", rf="Carlito-Bold"):
        l = ParagraphStyle("L", fontName=lf, fontSize=9, leading=11, alignment=TA_LEFT)
        r = ParagraphStyle("R", fontName=rf, fontSize=9, leading=11, alignment=TA_RIGHT)
        t = Table([[Paragraph(lt, l), Paragraph(rt, r)]], colWidths=[CW * 0.73, CW * 0.27])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(t)

    def rl(t, d): tc(t, d)
    def cl(c, l): tc(c, l, "Carlito-Italic", "Carlito-Italic")
    def ed(d, dt): tc(d, dt, "Carlito-Italic", "Carlito-Italic")
    def b(t): story.append(Paragraph(f"\u2022  {t}", bst))
    def pl(t, y): tc(t, y)
    def sk(label, items): story.append(Paragraph(f"<b>{label}</b> {items}", kst))
    def ct(t): story.append(Paragraph(t, kst))

    # ── Header ──
    story.append(Paragraph(candidate_name.upper(), ns))
    story.append(Spacer(1, 1))
    story.append(Paragraph("New York, NY | (551) 371-2918 | bharath.kr702@gmail.com", cs_))
    story.append(Paragraph(
        '<link href="https://linkedin.com/in/thebharathkumar" color="blue"><u>LinkedIn</u></link>'
        ' | <link href="https://github.com/thebharathkumar" color="blue"><u>GitHub</u></link>'
        ' | <link href="https://thebharath.co" color="blue"><u>thebharath.co</u></link>', cs_))

    # ── Summary ──
    sh("SUMMARY")
    story.append(Paragraph(tailored.get("summary", ""), ust))

    # ── Education ──
    sh("EDUCATION")
    for edu in tailored.get("education", []):
        rl(edu["school"], edu["location"])
        ed(edu["degree"], f"{edu['start']} - {edu['end']}")
        if edu["school"].startswith("Pace"):
            story.append(Paragraph(
                "Coursework: Algorithms, Data Structures, Software Design, Distributed Systems, Cloud Computing, Database Architecture",
                cwst))

    # ── Technical Skills ──
    sh("TECHNICAL SKILLS")
    skills = tailored.get("skills", {})
    for label, items in skills.items():
        sk(f"{label}:", f" {items}")

    # ── Experience ──
    sh("EXPERIENCE")
    for i, exp in enumerate(tailored.get("experience", [])):
        rl(exp["role"], f"{exp['start']} - {exp['end']}")
        cl(exp["company"], exp["location"])
        for bullet in exp.get("bullets", []):
            b(bullet)
        if i < len(tailored.get("experience", [])) - 1:
            story.append(Spacer(1, 2))

    # ── Projects ──
    sh("PROJECTS")
    for i, proj in enumerate(tailored.get("projects", [])):
        pl(proj["name"], proj.get("year", ""))
        for bullet in proj.get("bullets", []):
            b(bullet)
        if i < len(tailored.get("projects", [])) - 1:
            story.append(Spacer(1, 1))

    # ── Certifications ──
    sh("CERTIFICATIONS & PUBLICATIONS")
    for cert in tailored.get("certifications", []):
        ct(cert)

    # ── Build Doc ──
    doc = SimpleDocTemplate(
        out_path, pagesize=letter,
        leftMargin=LM, rightMargin=RM, topMargin=TM, bottomMargin=BM
    )
    frame = Frame(LM, BM, CW, PAGE_HEIGHT - TM - BM,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="main")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame])])
    doc.build(story)

def validate_pages(pdf_path: str) -> int:
    return len(PdfReader(pdf_path).pages)

def condense_prompt(tailored: dict) -> dict:
    """Ask Claude to shorten bullets when PDF exceeds 1 page."""
    msg = (
        "The resume overflowed to 2 pages. Condense bullet points to be shorter (1-2 lines each max). "
        "Preserve all key metrics and tech keywords. Return ONLY the same JSON structure, condensed.\n\n"
        f"CURRENT JSON:\n{json.dumps(tailored, indent=2)}"
    )
    response = ai_client.chat.completions.create(
        model=CLAUDE_MODEL,
        max_tokens=3000,
        temperature=0.2,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": msg}
        ]
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)

def generate_python_script(tailored: dict, candidate_name: str, output_path: str) -> str:
    """Generate a runnable ReportLab Python script from tailored data."""
    lines = []
    lines.append('from reportlab.lib.pagesizes import letter')
    lines.append('from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY')
    lines.append('from reportlab.lib.styles import ParagraphStyle')
    lines.append('from reportlab.lib.colors import black')
    lines.append('from reportlab.platypus import (')
    lines.append('    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable')
    lines.append(')')
    lines.append('from reportlab.pdfbase import pdfmetrics')
    lines.append('from reportlab.pdfbase.ttfonts import TTFont')
    lines.append('from reportlab.platypus.frames import Frame')
    lines.append('from reportlab.platypus.doctemplate import PageTemplate')
    lines.append('from pathlib import Path')
    lines.append('')
    lines.append('FONTS_DIR = Path(__file__).parent / "fonts"')
    lines.append("pdfmetrics.registerFont(TTFont('Carlito', str(FONTS_DIR / 'Carlito-Regular.ttf')))")
    lines.append("pdfmetrics.registerFont(TTFont('Carlito-Bold', str(FONTS_DIR / 'Carlito-Bold.ttf')))")
    lines.append("pdfmetrics.registerFont(TTFont('Carlito-Italic', str(FONTS_DIR / 'Carlito-Italic.ttf')))")
    lines.append("pdfmetrics.registerFont(TTFont('Carlito-BoldItalic', str(FONTS_DIR / 'Carlito-BoldItalic.ttf')))")
    lines.append("pdfmetrics.registerFontFamily('Carlito', normal='Carlito', bold='Carlito-Bold', italic='Carlito-Italic', boldItalic='Carlito-BoldItalic')")
    lines.append('')
    lines.append('PAGE_WIDTH, PAGE_HEIGHT = letter')
    lines.append('LM = 30; RM = PAGE_WIDTH - 582; TM = 18; BM = 12')
    lines.append('CW = PAGE_WIDTH - LM - RM')
    lines.append('')
    lines.append("ns  = ParagraphStyle('N', fontName='Carlito-Bold',    fontSize=13, alignment=TA_CENTER,  spaceAfter=0, leading=14)")
    lines.append("cs_ = ParagraphStyle('C', fontName='Carlito',         fontSize=9,  alignment=TA_CENTER,  spaceAfter=0, leading=11)")
    lines.append("ss  = ParagraphStyle('S', fontName='Carlito-Bold',    fontSize=10, alignment=TA_LEFT,    spaceBefore=0, spaceAfter=0, leading=11)")
    lines.append("bst = ParagraphStyle('B', fontName='Carlito',         fontSize=9,  alignment=TA_JUSTIFY, leading=10.8, leftIndent=10, firstLineIndent=0, spaceAfter=0.5)")
    lines.append("kst = ParagraphStyle('K', fontName='Carlito',         fontSize=9,  alignment=TA_LEFT,    leading=11, spaceAfter=0)")
    lines.append("ust = ParagraphStyle('U', fontName='Carlito',         fontSize=9,  alignment=TA_JUSTIFY, leading=10.8, spaceAfter=0)")
    lines.append("cwst= ParagraphStyle('CW',fontName='Carlito',         fontSize=9,  leading=11, spaceAfter=2)")
    lines.append('')
    lines.append('story = []')
    lines.append('')
    lines.append('def sh(t):')
    lines.append('    story.append(Spacer(1,3)); story.append(Paragraph(t,ss)); story.append(Spacer(1,1))')
    lines.append('    story.append(HRFlowable(width="100%",thickness=0.5,color=black,spaceAfter=2,spaceBefore=0))')
    lines.append('')
    lines.append('def tc(lt,rt,lf="Carlito-Bold",rf="Carlito-Bold"):')
    lines.append('    l=ParagraphStyle("L",fontName=lf,fontSize=9,leading=11,alignment=TA_LEFT)')
    lines.append('    r=ParagraphStyle("R",fontName=rf,fontSize=9,leading=11,alignment=TA_RIGHT)')
    lines.append('    t=Table([[Paragraph(lt,l),Paragraph(rt,r)]],colWidths=[CW*0.73,CW*0.27])')
    lines.append('    t.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0)]))')
    lines.append('    story.append(t)')
    lines.append('')
    lines.append('def rl(t,d): tc(t,d)')
    lines.append('def cl(c,l): tc(c,l,"Carlito-Italic","Carlito-Italic")')
    lines.append('def ed(d,dt): tc(d,dt,"Carlito-Italic","Carlito-Italic")')
    lines.append('def b(t): story.append(Paragraph(f"\\u2022  {t}",bst))')
    lines.append('def pl(t,y): tc(t,y)')
    lines.append('def sk(label,items): story.append(Paragraph(f"<b>{label}</b> {items}",kst))')
    lines.append('def ct(t): story.append(Paragraph(t,kst))')
    lines.append('')

    # Header
    name_upper = candidate_name.upper()
    lines.append(f"story.append(Paragraph('{name_upper}', ns))")
    lines.append("story.append(Spacer(1, 1))")
    lines.append("story.append(Paragraph('New York, NY | (551) 371-2918 | bharath.kr702@gmail.com', cs_))")
    lines.append("story.append(Paragraph('<link href=\"https://linkedin.com/in/thebharathkumar\" color=\"blue\"><u>LinkedIn</u></link> | <link href=\"https://github.com/thebharathkumar\" color=\"blue\"><u>GitHub</u></link> | <link href=\"https://thebharath.co\" color=\"blue\"><u>thebharath.co</u></link>', cs_))")
    lines.append('')

    # Summary
    summary = tailored.get("summary", "").replace("'", "\\'")
    lines.append("sh('SUMMARY')")
    lines.append(f"story.append(Paragraph('{summary}', ust))")
    lines.append('')

    # Education
    lines.append("sh('EDUCATION')")
    for edu in tailored.get("education", []):
        sch = edu['school'].replace("'", "\\'")
        loc = edu['location'].replace("'", "\\'")
        deg = edu['degree'].replace("'", "\\'").replace('"', '\\"')
        lines.append(f"rl('{sch}', '{loc}')")
        lines.append(f"ed('{deg}', '{edu['start']} - {edu['end']}')")
        if "Pace" in edu["school"]:
            lines.append("story.append(Paragraph('Coursework: Algorithms, Data Structures, Software Design, Distributed Systems, Cloud Computing, Database Architecture', cwst))")
    lines.append('')

    # Skills
    lines.append("sh('TECHNICAL SKILLS')")
    for label, items in tailored.get("skills", {}).items():
        items_esc = items.replace("'", "\\'")
        lines.append(f"sk('{label}:', ' {items_esc}')")
    lines.append('')

    # Experience
    lines.append("sh('EXPERIENCE')")
    exps = tailored.get("experience", [])
    for i, exp in enumerate(exps):
        role = exp['role'].replace("'", "\\'")
        company = exp['company'].replace("'", "\\'")
        loc = exp['location'].replace("'", "\\'")
        lines.append(f"rl('{role}', '{exp['start']} - {exp['end']}')")
        lines.append(f"cl('{company}', '{loc}')")
        for bullet in exp.get("bullets", []):
            bullet_esc = bullet.replace("'", "\\'").replace("\\\\", "\\")
            lines.append(f"b('{bullet_esc}')")
        if i < len(exps) - 1:
            lines.append("story.append(Spacer(1, 2))")
    lines.append('')

    # Projects
    lines.append("sh('PROJECTS')")
    projs = tailored.get("projects", [])
    for i, proj in enumerate(projs):
        name = proj['name'].replace("'", "\\'").replace("|", "\\u007c")
        lines.append(f"pl('{name}', '{proj.get('year', '')}')")
        for bullet in proj.get("bullets", []):
            bullet_esc = bullet.replace("'", "\\'")
            lines.append(f"b('{bullet_esc}')")
        if i < len(projs) - 1:
            lines.append("story.append(Spacer(1, 1))")
    lines.append('')

    # Certifications
    lines.append("sh('CERTIFICATIONS & PUBLICATIONS')")
    for cert in tailored.get("certifications", []):
        cert_esc = cert.replace("'", "\\'").replace('"', '\\"')
        lines.append(f"ct('{cert_esc}')")
    lines.append('')

    # Build
    lines.append(f"doc = SimpleDocTemplate('{output_path}',")
    lines.append("    pagesize=letter, leftMargin=LM, rightMargin=RM, topMargin=TM, bottomMargin=BM)")
    lines.append("frame = Frame(LM, BM, CW, PAGE_HEIGHT-TM-BM, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id='main')")
    lines.append("doc.addPageTemplates([PageTemplate(id='main', frames=[frame])])")
    lines.append("doc.build(story)")
    lines.append('')
    lines.append("from pypdf import PdfReader")
    lines.append(f"p = len(PdfReader('{output_path}').pages)")
    lines.append("print(f'Pages: {p} {\"OK\" if p==1 else \"OVER\"}')")

    return "\n".join(lines)

# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.post("/tailor")
async def tailor_resume(req: TailorRequest):
    try:
        # 1. Get job description text
        jd_text = req.jd_raw or ""
        if not jd_text and req.jd_api_endpoint and req.job_id:
            jd_text = fetch_job_description(req.jd_api_endpoint, req.jd_api_key, req.job_id)

        if not jd_text:
            raise HTTPException(status_code=400, detail="No job description provided. Either paste JD directly or provide API endpoint + job ID.")

        # 2. Get base resume data
        base_data = base_resume_data()

        # 3. Claude tailoring
        tailored = call_claude(jd_text, base_data, req.target_role, req.company_name)

        # 4. Generate PDF (with retry for overflow)
        changes_summary = tailored.get("changes_summary", "Resume tailored successfully.")
        for attempt in range(3):
            out_path = str(OUTPUT_DIR / "tailored_resume.pdf")
            build_pdf(tailored, req.candidate_name, out_path)
            pages = validate_pages(out_path)
            if pages == 1:
                break
            if attempt < 2:
                tailored = condense_prompt(tailored)
            else:
                # Force truncation as last resort — remove last exp bullet
                for exp in tailored.get("experience", []):
                    if len(exp.get("bullets", [])) > 2:
                        exp["bullets"] = exp["bullets"][:-1]
                        break

        # 5. Return PDF
        def iterfile():
            with open(out_path, "rb") as f:
                yield from f

        return StreamingResponse(
            iterfile(),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="Bharath_Kumar_Tailored_Resume.pdf"',
                "X-Pages": str(pages),
                "X-Changes-Summary": changes_summary[:500]  # Header size limit
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/script")
async def get_script(req: TailorRequest):
    """Returns the tailored Python script instead of the PDF."""
    try:
        jd_text = req.jd_raw or ""
        if not jd_text and req.jd_api_endpoint and req.job_id:
            jd_text = fetch_job_description(req.jd_api_endpoint, req.jd_api_key, req.job_id)

        if not jd_text:
            raise HTTPException(status_code=400, detail="No job description provided.")

        base_data = base_resume_data()
        tailored = call_claude(jd_text, base_data, req.target_role, req.company_name)

        # Generate script
        output_pdf_path = "/tmp/Bharath_Kumar_Tailored_Resume.pdf"
        script = generate_python_script(tailored, req.candidate_name, output_pdf_path)
        changes_summary = tailored.get("changes_summary", "Resume tailored successfully.")

        return JSONResponse({
            "script": script,
            "changes_summary": changes_summary,
        })

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok", "model": CLAUDE_MODEL}
