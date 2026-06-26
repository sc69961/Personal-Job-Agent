"""
apply.py — Generate a tailored application package for a specific job.
Run: python apply.py --job-id <id>  OR  python apply.py --url <job_url>

Outputs:
  - Cover letter (print + save to output/)
  - Short-answer responses for common PM interview questions
  - Pre-filled form fields (name, email, phone, LinkedIn, etc.)
"""

import os
import json
import argparse
import logging
from datetime import datetime
from anthropic import Anthropic

logger = logging.getLogger(__name__)


COVER_LETTER_PROMPT = """
You are an expert PM career coach and ghostwriter. Write a compelling, specific cover letter
for this job. The letter should feel genuinely personal, not templated.

=== CANDIDATE ===
{resume}

=== PERSONAL INFO ===
Name:     {name}
Email:    {email}
Phone:    {phone}
LinkedIn: {linkedin}
Location: {location}

=== JOB ===
Title:   {title}
Company: {company}
URL:     {url}

Job Description:
{description}

=== INSTRUCTIONS ===
- 3 paragraphs, ~250 words total
- Para 1: Why THIS company and THIS role specifically (not generic enthusiasm)
- Para 2: 2-3 specific experiences from resume that directly match the JD requirements
  (use concrete numbers: $10B, $6M, 1M downloads, etc.)
- Para 3: Forward-looking — what you'd bring in first 90 days + why this mission matters to you
- Tone: Confident, direct, warm. Not sycophantic. No "I am writing to apply..."
- Do NOT use: "passion", "excited to", "thrilled", "deeply passionate"
- Sign off professionally

Write the letter now. Output ONLY the letter text, no preamble.
"""

SHORT_ANSWER_PROMPT = """
Generate concise, strong answers to these common PM application questions for this candidate.

=== CANDIDATE RESUME ===
{resume}

=== JOB ===
Title:   {title}
Company: {company}
Description (excerpt): {description}

=== OUTPUT FORMAT ===
Return a JSON array. Each item:
{{
  "question": "<the question>",
  "answer":   "<answer in 2-4 sentences, specific to candidate's background>"
}}

Questions to answer:
1. Why do you want to work at {company}?
2. Describe a product you took from 0 to 1. What was the outcome?
3. How do you prioritize when stakeholders disagree?
4. Tell us about a time you used data to make a product decision.
5. What's your experience with [relevant domain: {domain}]?
6. Where do you see yourself in 3 years?
7. What's your greatest professional achievement?

Return ONLY the JSON array.
"""


def load_job(job_id: str = None, url: str = None, jobs_file: str = "./output/scored_jobs.json") -> dict:
    """Load a job from the scored jobs JSON file by ID or URL."""
    try:
        with open(jobs_file) as f:
            jobs = json.load(f)
    except FileNotFoundError:
        raise ValueError(f"No scored jobs file found at {jobs_file}. Run main.py first.")

    if job_id:
        matches = [j for j in jobs if j.get("id") == job_id]
    elif url:
        matches = [j for j in jobs if url in j.get("url", "")]
    else:
        raise ValueError("Provide either --job-id or --url")

    if not matches:
        raise ValueError(f"Job not found. Available IDs: {[j['id'] for j in jobs[:5]]}")
    return matches[0]


def generate_cover_letter(job: dict, config: dict, client: Anthropic) -> str:
    prompt = COVER_LETTER_PROMPT.format(
        resume=config["RESUME_TEXT"],
        name=config["YOUR_NAME"],
        email=config["YOUR_EMAIL"],
        phone=config["YOUR_PHONE"],
        linkedin=config["YOUR_LINKEDIN"],
        location=config["YOUR_LOCATION"],
        title=job["title"],
        company=job["company"],
        url=job["url"],
        description=job.get("description", "")[:3000],
    )
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def generate_short_answers(job: dict, config: dict, client: Anthropic) -> list[dict]:
    # Infer domain from company tier and job keywords
    domain_map = {
        "climatetech": "DER/VPP/energy grid and demand response",
        "fintech_ai":  "fintech payments platforms or AI/ML products",
        "other":       "platform products and cross-functional delivery",
    }
    domain = domain_map.get(job.get("company_tier", "other"), "platform products")

    prompt = SHORT_ANSWER_PROMPT.format(
        resume=config["RESUME_TEXT"],
        title=job["title"],
        company=job["company"],
        description=job.get("description", "")[:2000],
        domain=domain,
    )
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def prefilled_fields(config: dict, job: dict) -> dict:
    """Standard form fields pre-filled from config."""
    return {
        "First Name":        config["YOUR_NAME"].split()[0],
        "Last Name":         config["YOUR_NAME"].split()[-1],
        "Full Name":         config["YOUR_NAME"],
        "Email":             config["YOUR_EMAIL"],
        "Phone":             config["YOUR_PHONE"],
        "LinkedIn URL":      config["YOUR_LINKEDIN"],
        "Location / City":   config["YOUR_LOCATION"],
        "How did you hear?": "LinkedIn / Job Board",
        "Desired Salary":    f"${config['SALARY_FLOOR']:,}+",
        "Work Authorization":"Yes, authorized to work in the US",
        "Sponsorship Needed":"No",
        "Role Title Applied":"",   # leave blank; paste from job title
        "Cover Letter":      "(generated — see cover_letter.txt)",
    }


def save_application_package(
    job: dict, cover_letter: str, short_answers: list, fields: dict, config: dict
) -> str:
    """Save everything to output/ and return the folder path."""
    safe_name = f"{job['company'].replace(' ','_')}_{job['title'].replace(' ','_')}"[:60]
    folder = f"./output/{safe_name}_{job['id']}"
    os.makedirs(folder, exist_ok=True)

    # Cover letter
    cl_path = f"{folder}/cover_letter.txt"
    with open(cl_path, "w") as f:
        f.write(f"Cover Letter — {job['title']} @ {job['company']}\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"Job URL: {job['url']}\n\n")
        f.write("=" * 60 + "\n\n")
        f.write(cover_letter)

    # Short answers
    qa_path = f"{folder}/short_answers.txt"
    with open(qa_path, "w") as f:
        f.write(f"Short Answer Questions — {job['title']} @ {job['company']}\n\n")
        for qa in short_answers:
            f.write(f"Q: {qa['question']}\n")
            f.write(f"A: {qa['answer']}\n\n")

    # Pre-filled fields
    fields_path = f"{folder}/form_fields.txt"
    with open(fields_path, "w") as f:
        f.write(f"Pre-filled Form Fields — {job['title']} @ {job['company']}\n\n")
        for k, v in fields.items():
            f.write(f"{k}:\n  {v}\n\n")

    # Full job info
    with open(f"{folder}/job_info.json", "w") as f:
        json.dump(job, f, indent=2)

    return folder


def main():
    parser = argparse.ArgumentParser(description="Generate application package for a job")
    parser.add_argument("--job-id", help="Job ID from scored_jobs.json")
    parser.add_argument("--url",    help="Job URL (partial match OK)")
    parser.add_argument("--list",   action="store_true", help="List top 20 available jobs")
    args = parser.parse_args()

    # Load config
    import sys
    sys.path.insert(0, ".")
    from config.config import (
        ANTHROPIC_API_KEY, RESUME_TEXT, YOUR_NAME, YOUR_EMAIL,
        YOUR_PHONE, YOUR_LINKEDIN, YOUR_LOCATION, SALARY_FLOOR,
    )
    config = {
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY", ""),
        "RESUME_TEXT":  RESUME_TEXT, "YOUR_NAME":  YOUR_NAME,
        "YOUR_EMAIL":   YOUR_EMAIL,  "YOUR_PHONE": YOUR_PHONE,
        "YOUR_LINKEDIN":YOUR_LINKEDIN,"YOUR_LOCATION":YOUR_LOCATION,
        "SALARY_FLOOR": SALARY_FLOOR,
    }

    if args.list:
        try:
            with open("./output/scored_jobs.json") as f:
                jobs = json.load(f)
            print(f"\nTop {min(20,len(jobs))} jobs:\n")
            for j in jobs[:20]:
                print(f"  [{j['id']}] {j['score']:>3}/100  {j['title']:<45} @ {j['company']}")
        except FileNotFoundError:
            print("No scored jobs yet. Run: python main.py")
        return

    job = load_job(job_id=args.job_id, url=args.url)
    print(f"\n📋 Generating application package for:")
    print(f"   {job['title']} @ {job['company']}  (score: {job['score']})")

    api_key = config["ANTHROPIC_API_KEY"]
    if not api_key:
        raise ValueError("Set ANTHROPIC_API_KEY in config.py or as env var")
    client = Anthropic(api_key=api_key)

    print("   Generating cover letter...")
    cover_letter = generate_cover_letter(job, config, client)

    print("   Generating short answers...")
    short_answers = generate_short_answers(job, config, client)

    print("   Generating pre-filled fields...")
    fields = prefilled_fields(config, job)

    folder = save_application_package(job, cover_letter, short_answers, fields, config)

    print(f"\n✅ Application package saved to: {folder}/")
    print("   cover_letter.txt")
    print("   short_answers.txt")
    print("   form_fields.txt")
    print("   job_info.json")
    print(f"\n--- COVER LETTER PREVIEW ---\n")
    print(cover_letter[:600] + ("..." if len(cover_letter) > 600 else ""))


if __name__ == "__main__":
    main()
