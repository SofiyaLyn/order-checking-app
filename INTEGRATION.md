# Connect an existing HTML page

The bundle's front end is plain HTML/CSS/JavaScript. To adapt another design, preserve the local API calls in `app.js`, or use the following contract.

Serve the page from the included local server, rather than opening it with file:// for live checks.

## Session token

Keep this meta element in index.html:

```html
<meta name="app-session" content="__SESSION_TOKEN__">
```

The server replaces its placeholder when serving the page. For POST requests, use:

```javascript
const token = document.querySelector('meta[name="app-session"]').content;
const response = await fetch('/api/check', {
  method: 'POST',
  headers: {'Content-Type':'application/json','X-Order-Check-Token':token},
  body: JSON.stringify(payload)
});
const result = await response.json();
```

## Endpoints

| Method and path | Result |
|---|---|
| GET /api/health | Local app readiness |
| GET /api/samples | Fresh synthetic results, scenario manifest and sample reference data |
| GET /api/template | Example Excel order template |
| POST /api/check | One synthetic form instruction, returned as `{case: ...}` |
| POST /api/files | Local unverified .eml files, returned as `{cases: [...]}` |

`/api/check` accepts sender, subject, body, received_at and simulate_auth_failure. An optional attachment has name and data_base64. Times without an offset represent the configured Vienna demonstration timezone.

`/api/files` accepts `{files: [{name, data_base64}]}`. Authentication from uploaded file headers remains untrusted.

A case contains decision, reason, parsed lines, individual checks, proposed owner and next action. Display incoming text with textContent, not unsanitized innerHTML.

The API has file and request size limits and returns JSON errors. It is a local demonstration API, not an authenticated production order gateway.

