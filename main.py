import os
import re
import sqlite3
import feedparser
import smtplib
from email.mime.text import MIMEText
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import tool
from dotenv import load_dotenv

# Load env variables
load_dotenv()

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Database setup
DB_FILE = "subscribers.db"
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS subscribers (email TEXT PRIMARY KEY)")
conn.commit()

# LLM setup
gemini_llm = LLM(model="gemini/gemini-2.0-flash", temperature=0.3)

# ---- Scraper Tool ----
@tool("Market News Scraper")
def scrape_news() -> str:
    try:
        url = "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-IN&gl=IN&ceid=IN:en"
        feed = feedparser.parse(url)
        articles = []
        for entry in feed.entries[:10]:
            articles.append({
                "title": entry.title,
                "link": entry.link,
                "published": entry.published
            })
        return str(articles)
    except Exception as e:
        return str([{"error": str(e)}])

# ---- Agents ----
market_researcher = Agent(
    role="Market Researcher",
    goal="Fetch only the most relevant and high-impact market and finance headlines.",
    backstory="A financial news scout that tracks only the most impactful updates shaping Indian and global markets.",
    tools=[scrape_news],
    llm=gemini_llm,
    verbose=True
)

data_analyst = Agent(
    role="Data Analyst",
    goal="Summarize market news into 4–5 insights with global and Indian perspective.",
    backstory="A sharp market analyst who converts raw headlines into clear, decision-ready takeaways.",
    llm=gemini_llm,
    verbose=True
)

statistician = Agent(
    role="Statistician",
    goal="Extract useful numbers: % moves, counts, and sentiment balance in one short block.",
    backstory="Keeps things numerical and precise for decision-making.",
    llm=gemini_llm,
    verbose=True
)

report_writer = Agent(
    role="Report Writer",
    goal="Deliver a 7–10 line, high-impact morning market briefing that is concise, clear, and actionable.",
    backstory="Writes daily executive market briefs that leaders can read in under a minute.",
    llm=gemini_llm,
    verbose=True
)

# ---- Crew ----
task1 = Task(description="Scrape top finance and market news from India.", agent=market_researcher)
task2 = Task(description="Summarize into 4–5 key insights.", agent=data_analyst)
task3 = Task(description="Give short numeric snapshot.", agent=statistician)
task4 = Task(description="Write final 7–10 line briefing.", agent=report_writer)

crew = Crew(
    agents=[market_researcher, data_analyst, statistician, report_writer],
    tasks=[task1, task2, task3, task4],
    process=Process.sequential,
    verbose=True
)

# ---- Utils ----
def clean_markdown(text: str) -> str:
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"##+", "", text)
    text = re.sub(r"[*_`#>-]", "", text)
    return text.strip()

def send_email(report: str, to_email: str):
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")

    msg = MIMEText(report, "plain", "utf-8")
    msg["Subject"] = "Daily India Market Briefing"
    msg["From"] = sender
    msg["To"] = to_email

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, to_email, msg.as_string())

# ---- FastAPI Routes ----
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/subscribe")
def subscribe(email: str = Form(...)):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO subscribers (email) VALUES (?)", (email,))
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # already subscribed
    conn.close()
    return RedirectResponse("/", status_code=303)

@app.get("/send-daily")
def run_daily_report():
    result = crew.kickoff()
    cleaned_result = clean_markdown(str(result))

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT email FROM subscribers")
    subscribers = cursor.fetchall()
    conn.close()

    for sub in subscribers:
        send_email(cleaned_result, sub[0])

    return {"status": "✅ Daily Market Briefing sent to all subscribers"}
