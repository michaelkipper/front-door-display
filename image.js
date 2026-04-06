import { OPENAI_API_KEY } from "./config.js";

const IMAGE_CACHE_KEY = "shabbat-image-cache";

/**
 * Returns a prompt for DALL-E based on the current holiday/event context.
 */
export function getImagePrompt(events) {
  const titles = events.map(e => e.title?.toLowerCase() || "");
  const allText = titles.join(" ");

  // Check for specific holidays and return themed prompts
  if (allText.includes("pesach") || allText.includes("passover")) {
    return "A beautiful artistic still life of matzah bread on a Passover seder plate, warm golden lighting, elegant and festive, watercolor painting style";
  }
  if (allText.includes("shavuot")) {
    return "A beautiful artistic scene of rolling green hills with wildflowers, a Torah scroll, and dairy foods like cheesecake, warm sunlight, watercolor painting style";
  }
  if (allText.includes("sukkot")) {
    return "A beautiful artistic decorated sukkah with hanging fruits, palm branches, and warm string lights, cozy autumn atmosphere, watercolor painting style";
  }
  if (allText.includes("rosh hashana")) {
    return "A beautiful artistic still life of apples and honey jar with a shofar, pomegranates, festive golden light, watercolor painting style";
  }
  if (allText.includes("yom kippur")) {
    return "A beautiful artistic scene of white prayer shawls and lit memorial candles, serene and solemn atmosphere, soft white and gold tones, watercolor painting style";
  }
  if (allText.includes("chanukah") || allText.includes("hanukkah")) {
    return "A beautiful artistic menorah with glowing candles, dreidels and golden gelt, warm blue and gold festive lighting, watercolor painting style";
  }
  if (allText.includes("purim")) {
    return "A beautiful artistic scene of hamantaschen pastries, a colorful Purim mask, and a megillah scroll, joyful festive atmosphere, watercolor painting style";
  }
  if (allText.includes("simchat torah")) {
    return "A beautiful artistic scene of joyful dancing with Torah scrolls, colorful celebration, festive lights, watercolor painting style";
  }
  if (allText.includes("shmini atzeret")) {
    return "A beautiful artistic autumn scene with Torah scrolls and golden leaves, warm harvest light, watercolor painting style";
  }

  // Default Shabbat prompt
  return "A beautiful artistic still life of two braided challah breads on a table with Shabbat candles and a kiddush cup of wine, warm golden lighting, watercolor painting style";
}

/**
 * Returns a cache key based on the prompt so we don't regenerate the same image.
 */
function getCacheKey(prompt) {
  // Simple hash of the prompt string
  let hash = 0;
  for (let i = 0; i < prompt.length; i++) {
    const char = prompt.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash |= 0;
  }
  return `${IMAGE_CACHE_KEY}-${hash}`;
}

/**
 * Get the cached image blob URL if available.
 */
function getCachedImage(prompt) {
  const key = getCacheKey(prompt);
  return localStorage.getItem(key);
}

/**
 * Cache the generated image as a data URL in localStorage.
 */
function setCachedImage(prompt, dataUrl) {
  // Clear old cached images first to avoid filling localStorage
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key && key.startsWith(IMAGE_CACHE_KEY)) {
      localStorage.removeItem(key);
    }
  }
  const key = getCacheKey(prompt);
  localStorage.setItem(key, dataUrl);
}

/**
 * Generates an image using the OpenAI DALL-E API, or returns a cached version.
 * Returns a data URL string, or null if generation fails.
 */
export async function generateImage(events) {
  const apiKey = OPENAI_API_KEY;
  if (!apiKey) {
    console.log("No OpenAI API key configured — using default challah.png");
    return null;
  }

  const prompt = getImagePrompt(events);
  console.log("Image prompt:", prompt);

  // Check cache first
  const cached = getCachedImage(prompt);
  if (cached) {
    console.log("Using cached generated image");
    return cached;
  }

  console.log("Generating new image via DALL-E...");
  try {
    const response = await fetch("https://api.openai.com/v1/images/generations", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: "dall-e-3",
        prompt: prompt,
        n: 1,
        size: "1792x1024",
        response_format: "b64_json",
      }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      console.error("DALL-E API error:", response.status, error);
      return null;
    }

    const data = await response.json();
    const b64 = data.data?.[0]?.b64_json;
    if (!b64) {
      console.error("No image data in DALL-E response");
      return null;
    }

    const dataUrl = `data:image/png;base64,${b64}`;
    setCachedImage(prompt, dataUrl);
    console.log("Generated and cached new image");
    return dataUrl;
  } catch (error) {
    console.error("Failed to generate image:", error);
    return null;
  }
}
