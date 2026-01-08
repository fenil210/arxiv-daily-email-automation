import os
import smtplib
import arxiv
from google import genai
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict
from datetime import datetime

class Configuration:
    def __init__(self):
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        self.email_address = os.getenv("EMAIL_ADDRESS")
        self.email_password = os.getenv("EMAIL_PASSWORD")
        self.receiver_emails = os.getenv("RECEIVER_EMAILS", "").split(",")
        # Ensure we have at least one receiver
        if not self.receiver_emails or self.receiver_emails == ['']:
             # Fallback or strict check, user said list in env var
             pass
        self.model_name = "gemini-3-flash-preview"

    def validate(self):
        if not all([self.gemini_api_key, self.email_address, self.email_password, self.receiver_emails]):
            raise ValueError("Missing required environment variables.")

class ArxivFetcher:
    def fetch_papers(self, limit: int = 100) -> List[Dict]:
        client = arxiv.Client()
        search = arxiv.Search(
            query="cat:cs.AI OR cat:cs.LG",
            max_results=limit,
            sort_by=arxiv.SortCriterion.SubmittedDate
        )
        papers = []
        for result in client.results(search):
            papers.append({
                "title": result.title,
                "abstract": result.summary,
                "url": result.entry_id,
                "published": result.published.strftime("%Y-%m-%d")
            })
        return papers

class GeminiSummarizer:
    def __init__(self, api_key: str, model_name: str):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name

    def generate_digest(self, papers: List[Dict]) -> str:
        paper_text = "\n\n".join([f"ID: {i}\nTitle: {p['title']}\nAbstract: {p['abstract']}" for i, p in enumerate(papers)])
        
        selection_prompt = f"""
        Role: You are a Distinguished AI Research Scientist and Senior Editor for a top-tier AI journal.
        Task: Review the following {len(papers)} AI paper abstracts and identify the top 3 most ground-breaking, novel, or impactful papers.
        
        Selection Criteria:
        1. **Novelty**: Does this propose a new architecture, paradigm, or solve a long-standing problem?
        2. **Impact**: potential to change the field or wide applicability.
        3. **Rigor**: (Inferred from abstract) Methodology looks sound.
        
        Avoid: Incremental improvements (e.g., "X% better on Y dataset") unless the method is radically new.
        
        Output:
        Return ONLY a comma-separated list of the 3 IDs corresponding to your choices. Example: 0, 15, 42
        
        Papers:
        {paper_text}
        """
        
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=selection_prompt
            )
            # robust cleanup for response
            text = response.text.strip()
            # remove any brackets or explanatory text if model fails to obey strict "ONLY"
            import re
            ids = re.findall(r'\d+', text)
            selected_indices = [int(i) for i in ids[:3]]
            selected_papers = [papers[i] for i in selected_indices if 0 <= i < len(papers)]
        except Exception as e:
            print(f"Selection failed: {e}. Defaulting to first 3.")
            selected_papers = papers[:3]
            selected_indices = [0, 1, 2]
            
        return self._create_summary_content(selected_papers, papers, selected_indices)

    def _create_summary_content(self, selected_papers: List[Dict], all_papers: List[Dict], selected_indices: List[int]) -> str:
        summary_html = f"<h1>Daily AI Research Digest</h1><p>{datetime.now().strftime('%B %d, %Y')}</p><hr>"
        
        for paper in selected_papers:
            prompt = f"""
            Role: Tech Journalist covering breakthrough AI research.
            Task: Write a compelling, insight-dense summary for the following paper.
            
            Paper Title: {paper['title']}
            Abstract: {paper['abstract']}
            
            Guidelines:
            - **The Big Idea**: What is the core innovation in 1 sentence?
            - **Key Details**: How does it work? (2-3 sentences)
            - **Why it Matters**: Impact on the field.
            - Tone: Professional, enthusiastic, clear.
            
            Output strictly HTML format (no markdown code blocks):
            <div style="margin-bottom: 30px;">
                <h3><a href="{paper['url']}" style="color: #2c3e50; text-decoration: none;">{paper['title']}</a></h3>
                <p style="color: #666; font-size: 0.9em;"><em>Published: {paper['published']}</em></p>
                <p><strong>🚀 The Big Idea:</strong> [Content]</p>
                <p><strong>⚙️ How it Works:</strong> [Content]</p>
                <p><strong>💡 Why it Matters:</strong> [Content]</p>
            </div>
            """
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt
                )
                content = response.text.replace("```html", "").replace("```", "")
                summary_html += content
            except Exception as e:
                print(f"Summary generation failed for {paper['title']}: {e}")
        
        import random
        remaining_papers = [p for i, p in enumerate(all_papers) if i not in selected_indices]
        bonus_papers = random.sample(remaining_papers, min(3, len(remaining_papers)))
        
        summary_html += "<hr><h2>📚 Read More Good Articles</h2>"
        summary_html += "<ul style='line-height: 1.8;'>"
        for paper in bonus_papers:
            summary_html += f"<li><a href='{paper['url']}' style='color: #3498db;'>{paper['title']}</a></li>"
        summary_html += "</ul>"
                
        return summary_html

class EmailSender:
    def __init__(self, sender_email: str, password: str):
        self.sender_email = sender_email
        self.password = password

    def send_email(self, receivers: List[str], subject: str, html_content: str):
        msg = MIMEMultipart()
        msg['From'] = self.sender_email
        msg['Subject'] = subject
        msg.attach(MIMEText(html_content, 'html'))

        try:
            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.starttls()
                server.login(self.sender_email, self.password)
                # Send to all receivers at once or loop? 
                # sendmail accepts a list for BCC effect or individual send.
                # For this user, single email object to multiple recipients is fine (Visible list).
                msg['To'] = ", ".join(receivers)
                server.sendmail(self.sender_email, receivers, msg.as_string())
        except Exception as e:
            print(f"Error sending email: {e}")

class DailyDigestApp:
    def __init__(self):
        self.config = Configuration()
        self.config.validate()
        self.fetcher = ArxivFetcher()
        self.summarizer = GeminiSummarizer(self.config.gemini_api_key, self.config.model_name)
        self.sender = EmailSender(self.config.email_address, self.config.email_password)

    def run(self):
        print("Fetching papers...")
        papers = self.fetcher.fetch_papers()
        
        print("Generating digest...")
        digest_html = self.summarizer.generate_digest(papers)
        
        print("Sending email...")
        self.sender.send_email(
            self.config.receiver_emails,
            f"AI Research Digest - {datetime.now().strftime('%Y-%m-%d')}",
            digest_html
        )
        print("Done.")

if __name__ == "__main__":
    app = DailyDigestApp()
    app.run()
