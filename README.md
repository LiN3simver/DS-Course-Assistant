# SCU Course Assistant

A local AI assistant for exploring Soochow University's Data Science courses and faculty. It combines retrieval-augmented generation (RAG), structured queries, and a chat interface with traceable sources.

**Local LLM · RAG · Data Engineering · Full-stack Development**

## Highlights

- **Course Q&A:** Find course content, instructors, and grading criteria with semester and course filters.
- **Grade comparisons:** Rank historical average grades directly from structured data.
- **Faculty discovery:** Search research interests using Chinese semantic embeddings.
- **Source-backed answers:** Inspect citations and expandable source excerpts.
- **Answer verification:** Check scope, citations, and numbers in code, followed by a separate local model review.
- **Responsive chat:** Includes conversation history, theme switching, and mobile navigation. Controls are in English; source content remains in Chinese.

## Architecture

```text
Course & faculty pages → Crawling & cleaning → JSON → BGE embeddings / Chroma
Chat UI → FastAPI → Semantic retrieval / structured queries → Ollama
        → Programmatic checks + model review → Answer with citations
```

Retrieval, generation, and model review share a **10-second budget**. On timeout, model unavailability, or failed verification, the API returns computed rankings or matching source excerpts without calling the LLM or embedding model. Fallbacks are labeled **Computed from data** or **Source excerpts**. The backend response budget is 14 seconds; the browser timeout is 15 seconds.

## Stack & Data

- **Data:** Python, Playwright, BeautifulSoup, JSON
- **Retrieval:** BGE-small-zh-v1.5, Sentence Transformers, Chroma, LangChain Text Splitters
- **Backend & inference:** FastAPI, HTTPX, Ollama, Qwen3-VL 4B Instruct
- **Frontend & tests:** HTML, CSS, JavaScript, unittest, jsdom

The bundled snapshots contain **92 courses and 16 faculty profiles** across semesters **113-2 and 114-1**. Records include course descriptions, grading criteria, historical grades, and source references where available.

## Run Locally

Use Python 3.13 and install Ollama. In PowerShell, with Ollama running:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
ollama pull qwen3-vl:4b-instruct
python scripts/download_embedding.py
python build_vectordb_Chroma.py
.\run_backend.ps1
```

Open **http://127.0.0.1:8000**. Initial setup downloads model weights; subsequent retrieval and inference run locally. Configure models and deadlines in `.env`.

Run backend tests with `python -m unittest discover -s tests`. Optional frontend tests require Node.js: run `npm ci`, then `npm test`.

## Limitations

This portfolio prototype uses fixed semester snapshots with some missing fields. Historical grades do not predict course difficulty or future results, and verification with the same model can share blind spots. Future work includes broader data coverage and a systematic Q&A evaluation set.
