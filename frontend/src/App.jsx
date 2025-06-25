import React, { useState } from "react";
import axios from "axios";

function formatDate(dateString) {
  const date = new Date(dateString);
  if (isNaN(date.getTime())) return "Data Not Available";

  return date.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export default function App() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [answer, setAnswer] = useState(null);
  const [error, setError] = useState(null);
  const [statusUpdates, setStatusUpdates] = useState([]);

  const handleSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    setAnswer(null);
    setStatusUpdates([]);

    const encodedQuery = encodeURIComponent(query.trim());
    const eventSource = new EventSource(`${import.meta.env.VITE_BACKEND_URL}/stream?query=${encodedQuery}`);

    eventSource.onmessage = (event) => {
      const message = event.data;

      if (message === "[DONE]") {
        eventSource.close();
        fetchFinalAnswer();
      } else {
        setStatusUpdates((prev) => [...prev, message]);
      }
    };

    eventSource.onerror = (err) => {
      console.error("SSE error", err);
      setError("⚠️ Connection lost or backend error. Please try again.");
      setLoading(false);
      eventSource.close();
    };
  };

  const fetchFinalAnswer = async () => {
    try {
      const res = await axios.post("http://localhost:8000/analyze", {
        query: query.trim(),
      });
      setAnswer(res.data);
    } catch (err) {
      console.error("Final fetch error", err);
      setError("Something went wrong while fetching final answer.");
    } finally {
      setLoading(false);
    }
  };

const [downloading, setDownloading] = useState(false);

  const handleDownload = async () => {
  setDownloading(true);
  try {
    const response = await axios.post(
      "http://localhost:8000/download",
      { query: query.trim() },
      { responseType: "blob" }
    );

    const url = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", "summary.txt");
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  } catch (e) {
    alert("Failed to download summary.");
  } finally {
    setDownloading(false);
  }
};


  return (
    <div className="min-h-screen bg-gray-100 text-gray-800 flex flex-col items-center justify-start py-12 px-4">
      <div className="w-full max-w-screen-2xl bg-white rounded-xl shadow-md p-6 space-y-6">
        <h1 className="text-3xl font-bold text-center flex items-center justify-center gap-2">
          <span role="img" aria-label="books">📚</span> Scientific Paper Summarizer
        </h1>

        <div className="flex flex-col sm:flex-row gap-4 justify-center items-center">
          <input
            type="text"
            placeholder="Enter your research topic..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full sm:w-1/2 p-3 border rounded-lg focus:outline-none focus:ring focus:ring-indigo-300"
          />
          <button
            onClick={handleSearch}
            disabled={loading}
            className="bg-black text-white px-6 py-3 rounded-lg hover:bg-gray-800 disabled:opacity-50"
          >
            {loading ? "Running Agent..." : "Search & Summarize"}
          </button>
        </div>

        {error && <p className="text-red-600 text-center">{error}</p>}

        {statusUpdates.length > 0 && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-md p-4 text-sm">
            <strong>Live Status:</strong>
            <ul className="list-disc list-inside space-y-1 mt-1 text-gray-700 max-h-60 overflow-y-auto">
              {statusUpdates.map((msg, i) => (
                <li key={i}>{msg}</li>
              ))}
            </ul>
          </div>
        )}

        {answer && answer.papers?.length > 0 && (
          <div className="mt-8 flex flex-col lg:flex-row gap-6">
            {/* Left side - Paper List */}
            <div className="w-full lg:w-2/3 space-y-6">
              <h2 className="text-2xl font-bold text-center lg:text-left">📄 Top Papers Found</h2>
              {answer.papers.map((paper, index) => (
                <div
                  key={index}
                  className="border border-gray-200 rounded-lg p-6 bg-gray-50 shadow-sm space-y-3"
                >
                  <div className="flex justify-between items-center gap-2">
                    <h3 className="text-xl font-semibold">{paper.title || "Untitled Paper"}</h3>
                    <button
                      onClick={() => {
                        setQuery(paper.title || "");
                        handleSearch();
                      }}
                      className="text-sm bg-indigo-600 text-white px-3 py-1 rounded hover:bg-indigo-700"
                      title="Summarize this paper"
                    >
                      Summarize
                    </button>
                  </div>

                  {paper.authors?.length > 0 && (
                    <p className="text-sm text-gray-600">
                      <strong>Authors:</strong> {paper.authors.map((a) => a.name).join(", ")}
                    </p>
                  )}

                  {paper.publishedDate && (
                    <p className="text-sm text-gray-600">
                      <strong>Published:</strong> {formatDate(paper.publishedDate)}
                    </p>
                  )}

                  {"citationCount" in paper && (
                    <p className="text-sm text-gray-600">
                      <strong>Citations:</strong> {paper.citationCount || "Data Not Available"}
                    </p>
                  )}

                  {paper.abstract && (
                    <p className="text-sm text-gray-800 whitespace-pre-wrap">
                      <strong>Abstract:</strong> {paper.abstract.slice(0, 600)}...
                    </p>
                  )}

                  {paper.openAccessPdf?.url ||
                  paper.pdf_url ||
                  paper.downloadUrl ||
                  paper.links?.find((l) => l.type === "download")?.url ? (
                    <a
                      href={
                        paper.openAccessPdf?.url ||
                        paper.pdf_url ||
                        paper.downloadUrl ||
                        paper.links?.find((l) => l.type === "download")?.url
                      }
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-block text-blue-600 underline"
                    >
                      🔗 View Full Paper
                    </a>
                  ) : (
                    <p className="text-sm text-red-500">Full paper not available</p>
                  )}
                </div>
              ))}
            </div>

            {/* Right side - LLM Summary */}
            <div className="w-full lg:w-1/3 p-4 bg-white border rounded-lg shadow space-y-4 h-fit sticky top-4 self-start">
              <h3 className="text-xl font-bold text-indigo-600">
                🧠 LLM Summary (Based on: {answer.papers[0]?.title || "First Paper"})
              </h3>
              <p className="text-gray-900 whitespace-pre-wrap text-sm">{answer.answer}</p>

              <button
              className="mt-3 bg-green-600 text-white px-5 py-2 rounded hover:bg-green-700 disabled:opacity-50"
              onClick={handleDownload}
              disabled={downloading}
            >
              {downloading ? "📄 Downloading..." : "📥 Download Summary"}
            </button>

            </div>
          </div>
        )}
      </div>
    </div>
  );
}