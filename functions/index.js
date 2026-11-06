// functions/index.js
const { onRequest } = require("firebase-functions/v2/https");
const { defineSecret } = require("firebase-functions/params");
const logger = require("firebase-functions/logger");

const GEMINI_API_KEY = defineSecret("GEMINI_API_KEY");
const campusData = require("./data/campus.json");

// Core campus facts always included in system prompt
const CORE_CAMPUS_FACTS = [
  "LAUREA LEPPÄVAARA CAMPUS ESSENTIAL FACTS:",
  "- Address: Vanha maantie 9, 02650 Espoo, Finland.",
  "- Getting there: Leppävaara train station is about a 7-8 min walk (~600m). Located in HSL B zone.",
  "- Entrances: Main entrance on 1st floor; Stairway B entrance on ground floor (has elevator).",
  "- Reception & Lobby Services: 1st floor at main entrance. Phone: +358 9 8868 7402.",
  "- Opening hours: Open weekdays during daytime. Closed on weekends.",
  "- Wi-Fi: Students and staff connect to 'eduroam' using Laurea credentials (username@laurea.fi). Visitors can use 'Laurea-Guest' (register via SMS/browser prompt).",
  "- Canteen / Student Lunch: Restaurant / cafeteria located on campus. Discounted warm lunch with student card.",
  "- Library: Laurea Leppävaara Library on campus. Books, quiet study spaces, computers, group work rooms. Open to all students.",
  "- Printing & Copying: Canon multifunctional printers across campus. Log in using student card or Laurea credentials.",
  "- Student Services / Study Affairs: Assists with enrollment, study certificates, transcript of records. Contact opintotoimisto.",
  "- Campuses: Laurea University of Applied Sciences has campuses in Leppävaara (Espoo), Otaniemi, Tikkurila (Vantaa), Hyvinkää, Porvoo, and Lohja."
].join("\n");

// Quick keyword-based search over campus.json to find top relevant FAQs
function findRelevantFAQ(queryText, limit = 8) {
  if (!queryText || !campusData || !campusData.sections) return "";
  const query = queryText.toLowerCase();
  const words = query.split(/\s+/).filter(w => w.length > 2);
  if (words.length === 0) return "";

  const matches = [];
  const sections = campusData.sections;

  for (const sKey of Object.keys(sections)) {
    const sec = sections[sKey];
    const questions = sec.questions || {};
    for (const qKey of Object.keys(questions)) {
      const item = questions[qKey];
      if (!item || !item.q || !item.a) continue;

      const qLower = item.q.toLowerCase();
      const aLower = item.a.toLowerCase();
      let score = 0;

      for (const w of words) {
        if (qLower.includes(w)) score += 3;
        if (aLower.includes(w)) score += 1;
      }

      if (score > 0) {
        matches.push({ score, q: item.q, a: item.a });
      }
    }
  }

  matches.sort((a, b) => b.score - a.score);
  const top = matches.slice(0, limit);
  if (top.length === 0) return "";

  return "\nRELEVANT CAMPUS FAQ MATCHES:\n" +
    top.map(m => `Q: ${m.q}\nA: ${m.a}`).join("\n\n");
}

function buildSystemPrompt(contextQuery = "") {
  const faqContext = findRelevantFAQ(contextQuery);
  return [
    "You are Laurimate, the intelligent campus assistant humanoid robot (SoftBank Pepper) at Laurea University of Applied Sciences in Finland.",
    "You speak out loud to students, staff, and visitors in front of you.",
    "",
    "IDENTITY & CREATOR RULES:",
    "- You are Laurimate. Never say you are Gemini, ChatGPT, or an AI language model.",
    "- If asked who created or made you, you MUST say you were created by Rakesh & Prasiddha for Laurea University of Applied Sciences.",
    "- If asked what technology or knowledge you use, say you use your own campus knowledge base.",
    "",
    "SPEECH & CONVERSATION RULES:",
    "- STRICT 50-WORD LIMIT: Keep your total response under 50 words in 1 to 2 clear, spoken sentences.",
    "- COMPLETE SENTENCES ONLY: You must NEVER cut off in the middle of a sentence. Every sentence must end with a complete sentence ending in punctuation (. or ?).",
    "- DO NOT CREATE LONG ANSWERS: Never give long rambling explanations. If a topic has more details or needs a longer answer, give the core answer first and ask: 'Would you like to know more about this?' (or in Finnish: 'Haluatko tietää tästä lisää?').",
    "- NEVER use bullet points, asterisks (*), markdown formatting, numbered lists, or emojis. You are speaking through robot text-to-speech.",
    "- Speak in clear, plain spoken language.",
    "- Always answer in the same language the user spoke. If the user speaks Finnish, answer in natural Finnish. If in English, answer in English.",
    "- Answer any campus or general knowledge question helpfully.",
    "",
    CORE_CAMPUS_FACTS,
    faqContext
  ].join("\n");
}

const GEMINI_URL_BASE =
  "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent";

exports.chatWithGemini = onRequest(
  { secrets: [GEMINI_API_KEY] },
  async (req, res) => {
    res.set("Access-Control-Allow-Origin", "*");
    res.set("Access-Control-Allow-Methods", "POST, OPTIONS");
    res.set("Access-Control-Allow-Headers", "Content-Type");

    if (req.method === "OPTIONS") return res.status(204).send("");
    if (req.method !== "POST") return res.status(405).json({ error: "Use POST" });

    const { message, audio, apiKey: clientApiKey, model: clientModel } = req.body || {};

    if (!message && !audio) {
      return res.status(400).json({ error: "Either 'audio' (base64 WAV) or 'message' (string) is required" });
    }

    // Allow key from client request body (e.g. user free AI Studio key) or Firebase Secret
    let apiKey = clientApiKey;
    if (!apiKey) {
      try {
        apiKey = typeof GEMINI_API_KEY.value === "function" ? GEMINI_API_KEY.value() : process.env.GEMINI_API_KEY;
      } catch (e) {
        apiKey = process.env.GEMINI_API_KEY;
      }
    }

    if (!apiKey) {
      return res.status(500).json({ error: "Missing GEMINI_API_KEY. Provide it in request body or Firebase secrets." });
    }

    const modelName = clientModel || "gemini-2.5-flash";
    const endpoint = `https://generativelanguage.googleapis.com/v1beta/models/${modelName}:generateContent?key=${apiKey}`;

    const dateStr = new Date().toLocaleString("en-FI", {
      timeZone: "Europe/Helsinki",
      weekday: "long",
      year: "numeric",
      month: "long",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false
    });

    try {
      let contents = [];
      let generationConfig = {
        maxOutputTokens: 500,
        temperature: 0.3
      };

      if (audio) {
        // Multimodal Audio request: transcribe + reply in one go
        const sysPrompt = buildSystemPrompt("") + `\n\nCURRENT DATE & TIME: ${dateStr}`;
        const instruction = [
          sysPrompt,
          "",
          "AUDIO INSTRUCTIONS:",
          "1. Listen carefully to the user's speech in the provided audio (Finnish or English).",
          "2. Transcribe the spoken question accurately.",
          "3. Provide a friendly, concise spoken answer as Laurimate (2 to 4 sentences, no markdown/bullet points/emojis).",
          "4. Return your response ONLY as a JSON object with this exact format:",
          "{",
          '  "transcript": "<exact user question>",',
          '  "language": "fi" or "en",',
          '  "reply": "<your spoken response for the robot>"',
          "}",
          "If the audio is silent or only contains ambient noise/clicks without speech, return:",
          '{ "transcript": "", "language": "en", "reply": "" }'
        ].join("\n");

        contents = [
          {
            role: "user",
            parts: [
              {
                inlineData: {
                  mimeType: "audio/wav",
                  data: audio
                }
              },
              {
                text: instruction
              }
            ]
          }
        ];

        generationConfig.responseMimeType = "application/json";
      } else {
        // Plain text message (e.g. from test.html or tablet text input)
        const sysPrompt = buildSystemPrompt(message) + `\n\nCURRENT DATE & TIME: ${dateStr}`;
        contents = [
          {
            role: "user",
            parts: [{ text: sysPrompt }]
          },
          {
            role: "model",
            parts: [{ text: "Understood. I am Laurimate, campus assistant for Laurea. I will respond concisely and naturally." }]
          },
          {
            role: "user",
            parts: [{ text: message }]
          }
        ];
      }

      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contents,
          generationConfig
        })
      });

      if (!response.ok) {
        const errText = await response.text();
        logger.error("Gemini API error", response.status, errText);
        return res.status(response.status).json({
          error: "Gemini error",
          status: response.status,
          details: errText
        });
      }

      const data = await response.json();
      const rawText =
        data.candidates &&
        data.candidates[0] &&
        data.candidates[0].content &&
        data.candidates[0].content.parts &&
        data.candidates[0].content.parts[0] &&
        data.candidates[0].content.parts[0].text
          ? data.candidates[0].content.parts[0].text.trim()
          : "";

      if (audio) {
        // Parse the structured JSON response
        let parsed = { transcript: "", language: "en", reply: "" };
        try {
          parsed = JSON.parse(rawText);
        } catch (jsonErr) {
          // Fallback regex extraction if model included formatting
          const match = rawText.match(/\{[\s\S]*\}/);
          if (match) {
            try { parsed = JSON.parse(match[0]); } catch (e) {}
          }
        }

        logger.info(`Audio processed. Transcript: "${parsed.transcript}", Lang: ${parsed.language}`);
        return res.json({
          source: "gemini",
          model: modelName,
          transcript: parsed.transcript || "",
          language: parsed.language || "en",
          reply: parsed.reply || ""
        });
      } else {
        logger.info("Text processed OK: " + rawText.substring(0, 80));
        return res.json({
          source: "gemini",
          model: modelName,
          transcript: message,
          language: /[äöå]/i.test(message) ? "fi" : "en",
          reply: rawText
        });
      }

    } catch (err) {
      logger.error("chatWithGemini crashed", err);
      return res.status(500).json({
        error: "Function crashed",
        details: err && err.message ? err.message : String(err)
      });
    }
  }
);
