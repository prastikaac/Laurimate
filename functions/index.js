// functions/index.js
const { onRequest } = require("firebase-functions/v2/https");
const { defineSecret } = require("firebase-functions/params");
const logger = require("firebase-functions/logger");

const GEMINI_API_KEY = defineSecret("GEMINI_API_KEY");
const campusData = require("./data/campus.json");

function buildCampusContext(data) {
  var lines = ["LAUREA UNIVERSITY OF APPLIED SCIENCES - CAMPUS INFORMATION\n"];
  var faqs = data.faqs || [];
  for (var i = 0; i < faqs.length; i++) {
    var item = faqs[i];
    if (item.question && item.answer) {
      lines.push("Q: " + item.question);
      lines.push("A: " + item.answer);
      lines.push("");
    }
  }
  return lines.join("\n");
}

var CAMPUS_CONTEXT = buildCampusContext(campusData);

var SYSTEM_PROMPT = [
  "You are Laurimate, an intelligent assistant robot at Laurea University of Applied Sciences in Finland.",
  "You can answer any question on any topic — just like a smart, knowledgeable friend.",
  "",
  "IMPORTANT IDENTITY RULES:",
  "- You are Laurimate. Never say you are Gemini, ChatGPT, or any AI product.",
  "- Never say you were made by Google, Anthropic, OpenAI, or any tech company.",
  "- If asked who made you, say you were created by Rakesh & Prasiddha for Laurea University of Applied Sciences.",
  "- If asked what AI you use, say you use your own knowledge base.",
  "",
  "RESPONSE RULES:",
  "- Answer every question freely and fully — no topic is off limits except harmful or offensive content.",
  "- Never say you cannot search the web, do not have access to information, or cannot help.",
  "- Never say your information is limited or that you only know about the campus.",
  "- If you know the answer, say it directly. If you are not 100% sure, give your best answer naturally.",
  "- Keep answers concise — 2 to 4 sentences. You speak out loud through a robot.",
  "- Never use bullet points, markdown, asterisks, numbered lists, or special characters.",
  "- Speak in plain natural sentences only.",
  "- For campus questions, prioritize the campus data below.",
  "",
  "LAUREA CAMPUS FACTS YOU KNOW:",
  "- Laurea Leppävaara campus address: Vanha maantie 9, 02650 Espoo, Finland.",
  "- Laurea is a university of applied sciences with campuses across the Helsinki metropolitan area.",
  "- Other campuses include Otaniemi, Tikkurila, Hyvinkää, Porvoo, and Laurea Lohja.",
  "",
  "Here is more detailed campus information:",
  "",
  CAMPUS_CONTEXT
].join("\n");

var GEMINI_URL =
  "https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent";

exports.chatWithGemini = onRequest(
  { secrets: [GEMINI_API_KEY] },
  async (req, res) => {
    res.set("Access-Control-Allow-Origin", "*");
    res.set("Access-Control-Allow-Methods", "POST, OPTIONS");
    res.set("Access-Control-Allow-Headers", "Content-Type");

    if (req.method === "OPTIONS") return res.status(204).send("");
    if (req.method !== "POST") return res.status(405).json({ error: "Use POST" });

    const message = req.body && req.body.message;
    if (!message || typeof message !== "string") {
      return res.status(400).json({ error: "message (string) is required" });
    }

    const apiKey = GEMINI_API_KEY.value();
    if (!apiKey) return res.status(500).json({ error: "Missing GEMINI_API_KEY" });

    try {
      const response = await fetch(GEMINI_URL + "?key=" + apiKey, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contents: [
            {
              role: "user",
              parts: [{ text: SYSTEM_PROMPT }]
            },
            {
              role: "model",
              parts: [{ text: "Got it. I am Laurimate, and I will answer any question freely and helpfully." }]
            },
            {
              role: "user",
              parts: [{ text: message }]
            }
          ],
          generationConfig: {
            maxOutputTokens: 200,
            temperature: 0.5
          }
        })
      });

      if (!response.ok) {
        const errText = await response.text();
        logger.error("Gemini error", response.status, errText);
        return res.status(500).json({ error: "Gemini error", details: errText });
      }

      const data = await response.json();
      const reply =
        data.candidates &&
        data.candidates[0] &&
        data.candidates[0].content &&
        data.candidates[0].content.parts &&
        data.candidates[0].content.parts[0] &&
        data.candidates[0].content.parts[0].text
          ? data.candidates[0].content.parts[0].text.trim()
          : "";

      logger.info("OK: " + reply.substring(0, 80));
      return res.json({ source: "gemini", model: "gemini-2.5-flash", reply: reply });

    } catch (err) {
      logger.error("chatWithGemini crashed", err);
      return res.status(500).json({
        error: "Function crashed",
        details: err && err.message ? err.message : String(err)
      });
    }
  }
);

// firebase deploy --only functions