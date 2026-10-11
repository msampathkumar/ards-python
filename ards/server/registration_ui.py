"""Interactive Human & Agent Self-Registration Modal and Route."""

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from ards.models import ResourceRegistration, ResourceType
from ards.registry import registry
from ards.server.verifier import verifier
from ards.plugins.base import plugin_manager

register_router = APIRouter(tags=["registration"])

REGISTRATION_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Register Resource • ARDS</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;700&family=Roboto:wght@400;500&display=swap" rel="stylesheet">
  <style> body { font-family: 'Roboto', sans-serif; } .google-logo { font-family: 'Google Sans', sans-serif; } </style>
</head>
<body class="bg-gray-50 text-gray-800 min-h-screen flex flex-col justify-between">

  <header class="bg-white border-b border-gray-200 px-6 py-4 flex justify-between items-center">
    <div class="flex items-center space-x-3">
      <a href="/" class="google-logo text-2xl font-bold tracking-tight">
        <span class="text-blue-600">A</span><span class="text-red-500">R</span><span class="text-yellow-500">D</span><span class="text-green-500">S</span>
      </a>
      <span class="text-xs text-gray-400 font-mono">/register</span>
    </div>
    <a href="/" class="text-sm font-medium text-gray-600 hover:text-blue-600">← Back to Search</a>
  </header>

  <main class="max-w-2xl mx-auto w-full my-8 p-8 bg-white rounded-2xl shadow-sm border border-gray-200">
    <h1 class="text-2xl font-bold text-gray-900 mb-2">Register with ARDS Directory</h1>
    <p class="text-sm text-gray-500 mb-6">Submit an A2A Agent, MCP Server, or Skill. Endpoints undergo automated verification before indexing.</p>

    {% if message %}
    <div class="mb-6 p-4 rounded-lg {% if success %}bg-green-50 border border-green-200 text-green-800{% else %}bg-red-50 border border-red-200 text-red-800{% endif %} text-sm">
      {{ message }}
    </div>
    {% endif %}

    <form action="/register" method="POST" class="space-y-5">
      <div>
        <label class="block text-xs font-semibold uppercase text-gray-600 mb-1">Resource ID</label>
        <input type="text" name="id" required placeholder="e.g., agent-stockholm-warehouse" class="w-full px-4 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none">
      </div>

      <div class="grid grid-cols-2 gap-4">
        <div>
          <label class="block text-xs font-semibold uppercase text-gray-600 mb-1">Resource Type</label>
          <select name="type" required class="w-full px-4 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none">
            <option value="agent">🤖 Agent (A2A Protocol)</option>
            <option value="mcp">🔌 MCP Server</option>
            <option value="skill">⚡ Skill</option>
            <option value="plugin">🧩 Plugin</option>
          </select>
        </div>
        <div>
          <label class="block text-xs font-semibold uppercase text-gray-600 mb-1">Location / Jurisdiction</label>
          <input type="text" name="location" placeholder="e.g., Stockholm, Sweden" class="w-full px-4 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none">
        </div>
      </div>

      <div>
        <label class="block text-xs font-semibold uppercase text-gray-600 mb-1">Display Name</label>
        <input type="text" name="name" required placeholder="e.g., Nordic Freight Gateway Agent" class="w-full px-4 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none">
      </div>

      <div>
        <label class="block text-xs font-semibold uppercase text-gray-600 mb-1">Primary Endpoint URL</label>
        <input type="url" name="endpoint" required placeholder="https://api.nordic-logistics.io/a2a" class="w-full px-4 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none">
      </div>

      <div>
        <label class="block text-xs font-semibold uppercase text-gray-600 mb-1">Description</label>
        <textarea name="description" rows="3" required placeholder="Brief description of agent jurisdiction, capabilities, and data access..." class="w-full px-4 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none"></textarea>
      </div>

      <div class="grid grid-cols-2 gap-4">
        <div>
          <label class="block text-xs font-semibold uppercase text-gray-600 mb-1">Capabilities (comma-separated)</label>
          <input type="text" name="capabilities" placeholder="e.g., stock_query, dispatch" class="w-full px-4 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none">
        </div>
        <div>
          <label class="block text-xs font-semibold uppercase text-gray-600 mb-1">Tags (comma-separated)</label>
          <input type="text" name="tags" placeholder="e.g., warehouse, logistics, nordics" class="w-full px-4 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none">
        </div>
      </div>

      <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2.5 px-4 rounded-lg shadow-sm transition">
        Verify & Register Endpoint
      </button>
    </form>
  </main>

  <footer class="bg-white border-t border-gray-200 py-4 px-6 text-center text-xs text-gray-500">
    ARDS Directory Service • Decentralized Protocol Gateway
  </footer>

</body>
</html>
"""

from jinja2 import Environment

_jinja_env = Environment(autoescape=True)
_register_template = _jinja_env.from_string(REGISTRATION_PAGE_HTML)


@register_router.get("/register", response_class=HTMLResponse)
async def get_registration_page(request: Request):
    # Deprecated manual string replacement (left raw {% if success %} and empty alert box in HTML):
    # html = REGISTRATION_PAGE_HTML.replace("{% if message %}", "").replace("{% endif %}", "")
    # html = html.replace("{{ message }}", "")
    html = _register_template.render(message=None, success=False)
    return HTMLResponse(html)


@register_router.post("/register", response_class=HTMLResponse)
async def submit_registration(
    request: Request,
    id: str = Form(...),
    type: str = Form(...),
    name: str = Form(...),
    endpoint: str = Form(...),
    description: str = Form(...),
    location: str = Form(""),
    capabilities: str = Form(""),
    tags: str = Form(""),
):
    caps = [c.strip() for c in capabilities.split(",") if c.strip()]
    tgs = [t.strip() for t in tags.split(",") if t.strip()]

    item = ResourceRegistration(
        id=id.strip(),
        type=ResourceType(type),
        name=name.strip(),
        endpoint=endpoint.strip(),
        description=description.strip(),
        location=location.strip() or None,
        capabilities=caps,
        tags=tgs,
    )

    verified, msg = await verifier.verify(item)
    if not verified:
        # Deprecated manual string replacement:
        # html = REGISTRATION_PAGE_HTML.replace("{{ message }}", f"Verification Failed: {msg}")
        # html = html.replace("{% if success %}", "").replace("{% else %}", "").replace("{% endif %}", "")
        html = _register_template.render(message=f"Verification Failed: {msg}", success=False)
        return HTMLResponse(html)

    registered = registry.register(item)
    await plugin_manager.trigger_post_registration(registered)

    return RedirectResponse(url=f"/?q={registered.name}", status_code=303)
