// API base. Local development: same origin. Production: the Render API.
const API_BASE = location.origin.includes("localhost") || location.hostname === "127.0.0.1"
  ? "http://127.0.0.1:8000"
  : "https://prompt-injection-gatekeeper.onrender.com";
