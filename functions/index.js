// functions/index.js
const { onRequest } = require("firebase-functions/v2/https");
const { defineSecret } = require("firebase-functions/params");
const logger = require("firebase-functions/logger");
const { GoogleGenAI } = require("@google/genai");

// ✅ Secret you created: firebase functions:secrets:set GEMINI_API_KEY
const GEMINI_API_KEY = defineSecret("GEMINI_API_KEY");

// ✅ Local JSON database: functions/data/campus.json
const campusData = require("./data/campus.json");

// ---------- Helpers ----------
function normalize(s) {
  return String(s || "")
    .toLowerCase()
    // remove punctuation/symbols, keep letters/numbers/spaces
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function searchCampusFAQ(userText) {
  const q = normalize(userText);
  if (!q) return null;

  const qWords = q.split(" ").filter(Boolean);

  let bestItem = null;
  let bestScore = 0;

  for (const item of campusData.faqs || []) {
    const keywords = (item.keywords || []).map(normalize).filter(Boolean);
    const question = normalize(item.question);
    const answer = normalize(item.answer);

    let score = 0;

    // Strong: keyword contained in the query
    for (const kw of keywords) {
      if (kw && q.includes(kw)) score += 3;
    }

    // Medium: query words appear in question/answer
    for (const w of qWords) {
      if (w.length < 3) continue;
      if (question.includes(w)) score += 1;
      if (answer.includes(w)) score += 1;
    }

    // Keep best
    if (score > bestScore) {
      bestScore = score;
      bestItem = item;
    }
  }

  // Threshold: tune this based on your data.
  // With keyword scoring, 3 means "at least one keyword matched".
  if (bestScore >= 3 && bestItem) return { item: bestItem, score: bestScore };
  return null;
}

// ---------- Function ----------
exports.chatWithGemini = onRequest(
  {
    secrets: [GEMINI_API_KEY],
  },
  async (req, res) => {
    // CORS for browser calls
    res.set("Access-Control-Allow-Origin", "*");
    res.set("Access-Control-Allow-Methods", "POST, OPTIONS");
    res.set("Access-Control-Allow-Headers", "Content-Type");

    // Preflight
    if (req.method === "OPTIONS") {
      return res.status(204).send("");
    }

    try {
      if (req.method !== "POST") {
        return res.status(405).json({ error: "Use POST" });
      }

      const message = req.body && req.body.message;
      if (!message || typeof message !== "string") {
        return res.status(400).json({ error: "message (string) is required" });
      }

      // 1) Search JSON first
      const match = searchCampusFAQ(message);
      if (match) {
        return res.json({
          source: "campus_json",
          matchedId: match.item.id,
          reply: match.item.answer,
        });
      }

      // 2) Fallback to Gemini
      const apiKey = GEMINI_API_KEY.value();
      if (!apiKey) {
        return res.status(500).json({ error: "Missing GEMINI_API_KEY secret" });
      }

      const ai = new GoogleGenAI({ apiKey });

      const response = await ai.models.generateContent({
        model: "gemini-3-flash-preview",
        contents: message,
      });

      return res.json({
        source: "gemini",
        reply: response.text || "",
      });
    } catch (err) {
      logger.error("chatWithGemini failed", err);
      return res.status(500).json({
        error: "Function crashed",
        details: err && err.message ? err.message : String(err),
      });
    }
  }
);
