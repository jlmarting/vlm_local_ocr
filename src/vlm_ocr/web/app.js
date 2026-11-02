const token = new URLSearchParams(location.hash.slice(1)).get("token") || "";

async function health() {
  const status = document.getElementById("status");
  try {
    const response = await fetch("/api/health");
    if (!response.ok) {
      throw new Error(String(response.status));
    }
    const payload = await response.json();
    status.textContent = `v${payload.version}`;
  } catch (error) {
    status.textContent = "sin conexión";
  }
}

if (token) {
  sessionStorage.setItem("vlm-token", token);
}

health();
