import os
import requests
import pdfplumber
import feedparser
import urllib.parse
from typing import TypedDict, List, Callable
from langgraph.graph import StateGraph, END
from langchain_ollama import ChatOllama
from langchain_core.callbacks.base import BaseCallbackHandler
from dotenv import load_dotenv

load_dotenv()

class AgentState(TypedDict):
    query: str
    papers: List[dict]
    pdf_path: str
    extracted_text: str
    answer: str

llm = ChatOllama(model="llama3", temperature=0.0)

def search_papers(state: AgentState, callback: Callable[[str], None] = lambda msg: None) -> dict:
    query = state["query"]
    api_key = os.getenv("CORE_API_KEY")
    papers = []

    callback(f"🔍 Searching CORE API for: {query}")
    try:
        url = "https://api.core.ac.uk/v3/search/works/"
        response = requests.get(url, params={"q": query, "apiKey": api_key}, timeout=10)
        data = response.json()
        papers = data.get("results") or data.get("data") or []
        if papers:
            callback(f"✅ Found {len(papers)} papers from CORE API")
            return {"papers": papers}
        callback("⚠️ No CORE papers found, trying arXiv...")
    except Exception as e:
        callback(f"❌ CORE API failed: {e}")

    callback(f"🔍 Searching arXiv for: {query}")
    arxiv_url = "http://export.arxiv.org/api/query"
    encoded_query = urllib.parse.quote(query)
    feed = feedparser.parse(f"{arxiv_url}?search_query=all:{encoded_query}&start=0&max_results=5")
    entries = feed.entries

    if not entries:
        raise Exception("No papers found on CORE or arXiv.")

    for entry in entries:
        pdf_link = next((link.href for link in entry.links if link.type == "application/pdf"), None)
        papers.append({
            "title": entry.title,
            "description": entry.summary,
            "pdf_url": pdf_link,
        })

    callback(f"✅ Found {len(papers)} papers from arXiv")
    return {"papers": papers}

def download_pdf(state: AgentState, callback: Callable[[str], None] = lambda msg: None) -> dict:
    import mimetypes

    papers = state["papers"]

    for idx, paper in enumerate(papers):
        title = paper.get("title", "No title")
        callback(f"📄 Checking paper {idx+1}: {title}")
        
        url = None
        if "openAccessPdf" in paper and paper["openAccessPdf"]:
            url = paper["openAccessPdf"].get("url")
        if not url and "pdf_url" in paper:
            url = paper["pdf_url"]
        if not url and "links" in paper:
            download_links = [link.get("url") for link in paper["links"] if link.get("type") == "download"]
            if download_links:
                url = download_links[0]
        if not url and "sourceFulltextUrls" in paper:
            if isinstance(paper["sourceFulltextUrls"], list) and paper["sourceFulltextUrls"]:
                url = paper["sourceFulltextUrls"][0]

        if url and "arxiv.org/abs/" in url:
            url = url.replace("arxiv.org/abs/", "arxiv.org/pdf/") + ".pdf"

        if url:
            callback(f"🔗 Found PDF URL: {url}")
            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                if 'application/pdf' not in response.headers.get('Content-Type', '') and not response.content.startswith(b'%PDF'):
                    raise Exception("Not a valid PDF file")
                path = "temp.pdf"
                with open(path, "wb") as f:
                    f.write(response.content)
                callback("✅ Valid PDF successfully downloaded.")
                return {"pdf_path": path}
            except Exception as e:
                callback(f"❌ Error downloading or validating PDF: {e}")
        else:
            callback("⚠️ No downloadable PDF URL found.")

    callback("⚠️ No valid PDF found in any fallback. Will use abstract instead.")
    return {}

def extract_text(state: AgentState, callback: Callable[[str], None] = lambda msg: None) -> dict:
    import re
    text = ""
    try:
        with pdfplumber.open(state["pdf_path"]) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if not page_text:
                    continue
                page_text = re.sub(r"(?<!\n)\n(?!\n)", " ", page_text)
                page_text = re.sub(r"-\n", "", page_text)
                if re.search(r"Figure\s+\d+|Table\s+\d+", page_text, re.IGNORECASE):
                    continue
                text += page_text + "\n"
    except Exception as e:
        callback("❌ PDF extraction failed")
        raise Exception("PDF parsing failed")

    text = text.strip()
    callback(f"📝 Cleaned text length: {len(text)} characters")
    if not text:
        raise Exception("No usable text extracted from PDF")

    return {"extracted_text": text}

def summarize_text(state: AgentState, callback: Callable[[str], None] = lambda msg: None) -> dict:
    content = state["extracted_text"][:2000]
    prompt = f"Summarize the key findings of the following paper:\n\n{content}"
    try:
        response = llm.invoke(prompt)
        callback("✅ Summary generated")
        paper = state["papers"][0]
        return {
            "answer": response.content,
            "title": paper.get("title", "No title"),
            "source": paper.get("openAccessPdf", {}).get("url") or paper.get("pdf_url", "No PDF URL")
        }
    except Exception as e:
        callback("❌ LLM summarization failed")
        raise Exception("Failed to summarize text")

def summarize_abstract(state: AgentState, callback: Callable[[str], None] = lambda msg: None) -> dict:
    abstract = state["papers"][0].get("description", "No abstract available.")
    prompt = f"Summarize the following abstract:\n\n{abstract}"
    response = llm.invoke(prompt)
    paper = state["papers"][0]
    callback("✅ Abstract summary generated")
    return {
        "answer": response.content,
        "title": paper.get("title", "No title"),
        "source": paper.get("openAccessPdf", {}).get("url") or paper.get("pdf_url", "No PDF URL")
    }

def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("search", lambda s: search_papers(s))
    builder.add_node("download", lambda s: download_pdf(s))
    builder.add_node("extract", lambda s: extract_text(s))
    builder.add_node("summarize", lambda s: summarize_text(s))
    builder.add_node("summarize_abstract", lambda s: summarize_abstract(s))

    builder.set_entry_point("search")
    builder.add_edge("search", "download")

    def choose_next_node(state: AgentState) -> str:
        return "extract" if "pdf_path" in state else "summarize_abstract"

    builder.add_conditional_edges("download", choose_next_node)
    builder.add_edge("extract", "summarize")
    builder.add_edge("summarize", END)
    builder.add_edge("summarize_abstract", END)

    return builder.compile()

# LangChain-compatible callback handler
class PrintHandler(BaseCallbackHandler):
    def __init__(self, send_update: Callable[[str], None]):
        self.send_update = send_update

    def on_text(self, text: str, **kwargs) -> None:
        self.send_update(f"→ {text}")

# run_agent function
def run_agent(query: str, callback: Callable[[str], None] = lambda msg: None):
    callback("🔍 Starting search for relevant papers...")

    state: AgentState = {
        "query": query,
        "papers": [],
        "pdf_path": "",
        "extracted_text": "",
        "answer": ""
    }

    callback("⚙️ Building LangGraph pipeline...")
    graph = build_graph()

    def with_callback(fn):
        def wrapped(state):
            callback(f"🔄 {fn.__name__.replace('_', ' ').title()} started...")
            result = fn(state, callback=callback)
            callback(f"✅ {fn.__name__.replace('_', ' ').title()} completed.")
            return result
        return wrapped

    graph.nodes["search"].func = with_callback(search_papers)
    graph.nodes["download"].func = with_callback(download_pdf)
    graph.nodes["extract"].func = with_callback(extract_text)
    graph.nodes["summarize"].func = with_callback(summarize_text)
    graph.nodes["summarize_abstract"].func = with_callback(summarize_abstract)

    final_state = graph.invoke(state)
    callback("✅ Analysis complete.")
    return final_state


