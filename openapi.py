"""OpenAPI schema loader for the CODESYS API."""

import json
import os


OPENAPI_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "openapi.json")


def load_openapi_schema():
    with open(OPENAPI_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def swagger_ui_html():
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>CODESYS API Docs</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
      window.ui = SwaggerUIBundle({
        url: '/openapi.json',
        dom_id: '#swagger-ui',
        deepLinking: true,
        presets: [SwaggerUIBundle.presets.apis],
        layout: 'BaseLayout'
      });
    </script>
  </body>
</html>
"""
