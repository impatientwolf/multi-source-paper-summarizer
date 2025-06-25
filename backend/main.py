# main.py
import os
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from agent import run_agent
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from tempfile import NamedTemporaryFile
from typing import Callable
import asyncio

class QueryRequest(BaseModel):
    query: str

class AnswerResponse(BaseModel):
    query: str
    papers: list
    answer: str

app = FastAPI()

origins = [
    os.getenv("FRONTEND_ORIGIN")
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/analyze", response_model=AnswerResponse)
async def analyze(req: QueryRequest):
    try:
        state = run_agent(req.query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return AnswerResponse(query=state["query"], papers=state["papers"], answer=state["answer"])

@app.post("/download")
async def download_summary(req: QueryRequest):
    try:
        state = run_agent(req.query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    papers = state["papers"]
    summary_text = f"Query: {req.query}\n\nSummary:\n{state.get('answer', 'No summary')}\n\n"

    for idx, paper in enumerate(papers):
        summary_text += f"\n--- Paper {idx + 1} ---\n"
        summary_text += f"Title: {paper.get('title', 'N/A')}\n"
        summary_text += f"Authors: {', '.join(a['name'] for a in paper.get('authors', []))}\n"
        summary_text += f"Published: {paper.get('publishedDate', 'N/A')}\n"
        summary_text += f"Citations: {paper.get('citationCount', 'N/A')}\n"
        summary_text += f"Link: {paper.get('pdf_url') or paper.get('downloadUrl') or 'N/A'}\n"
        summary_text += f"Abstract: {paper.get('abstract', '')[:500]}...\n"

    temp_file = NamedTemporaryFile(delete=False, mode="w", suffix=".txt", encoding="utf-8")
    temp_file.write(summary_text)
    temp_file.close()

    return FileResponse(temp_file.name, filename="summary.txt", media_type="text/plain")

@app.get("/stream")
async def stream_status(query: str):
    async def event_generator():
        queue = asyncio.Queue()

        def callback(msg: str):
            queue.put_nowait(msg)  # Safely enqueue message from thread

        # Running run_agent in a separate thread so it doesn't block event loop
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, run_agent, query, callback)

        try:
            while True:
                message = await queue.get()
                yield f"data: {message}\n\n"
                # Optional log
                print("[SSE] Sent:", message)
                if message.strip() == "✅ Analysis complete.":
                    yield f"data: [DONE]\n\n"
                    break
        except asyncio.CancelledError:
            print("🚫 SSE connection closed by client.")
            yield f"data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
    