import { createMcpHandler } from "agents/mcp/server";
import { McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";

interface Env {
  OPENAI_API_KEY: string;
  APEX_RELAY_TOKEN: string;
}

const OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses";
const ALLOWED_MODEL = "gpt-6-astra";
const RELAY_VERSION = "1.3.0";
const SELF_TEST_OK = "APEX_RELAY_OK";

type DiagnosticResult = {
  result: "PASS" | "FAIL";
  stage: string;
  reason: string;
  model: string;
  openai_response_id: string | null;
  request_sha256: string | null;
  openai_error_type?: string | null;
  openai_error_code?: string | null;
};

const SELF_TEST_HTML = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>APEX GPT-6 Relay Self-Test</title>
  <style>
    body{font-family:system-ui,-apple-system,sans-serif;max-width:680px;margin:48px auto;padding:0 18px;background:#0b0d10;color:#f4f6f8}
    .card{background:#151922;border:1px solid #2b3240;border-radius:14px;padding:22px}
    input,button{box-sizing:border-box;width:100%;font:inherit;border-radius:9px;padding:12px}
    input{background:#0f131a;color:#fff;border:1px solid #3a4456;margin:10px 0 12px}
    button{border:0;background:#fff;color:#111;font-weight:700;cursor:pointer}
    pre{white-space:pre-wrap;word-break:break-word;background:#0f131a;border-radius:9px;padding:12px;min-height:100px}
    small{color:#aeb7c5}
  </style>
</head>
<body>
  <div class="card">
    <h1>APEX GPT-6 Relay Self-Test</h1>
    <small>Relay ${RELAY_VERSION}. The relay token is sent only in the Authorization Bearer header and is never placed in the URL. Secret values are never returned.</small>
    <input id="token" type="password" autocomplete="off" spellcheck="false" placeholder="Paste APEX_RELAY_TOKEN" />
    <button id="run">Run self-test</button>
    <pre id="out">READY</pre>
  </div>
  <script>
    const tokenEl = document.getElementById('token');
    const outEl = document.getElementById('out');
    const runEl = document.getElementById('run');
    runEl.addEventListener('click', async () => {
      const token = tokenEl.value;
      if (!token) {
        outEl.textContent = JSON.stringify({ result: 'FAIL', stage: 'TOKEN_GATE', reason: 'TOKEN_NOT_PROVIDED' }, null, 2);
        return;
      }
      runEl.disabled = true;
      outEl.textContent = 'RUNNING';
      try {
        const r = await fetch('/self-test/run', {
          method: 'POST',
          headers: { 'Authorization': 'Bearer ' + token },
          cache: 'no-store'
        });
        const j = await r.json();
        outEl.textContent = JSON.stringify(j, null, 2);
      } catch (_) {
        outEl.textContent = JSON.stringify({ result: 'FAIL', stage: 'BROWSER_REQUEST', reason: 'SELF_TEST_RESPONSE_UNAVAILABLE' }, null, 2);
      } finally {
        runEl.disabled = false;
      }
    });
  </script>
</body>
</html>`;

function bearerAuthorized(request: Request, env: Env): boolean {
  if (!env.APEX_RELAY_TOKEN) return false;
  const authorization = request.headers.get("Authorization") ?? "";
  return authorization === `Bearer ${env.APEX_RELAY_TOKEN}`;
}

function unauthorized(): Response {
  return new Response("Unauthorized", {
    status: 401,
    headers: {
      "Cache-Control": "no-store",
      "WWW-Authenticate": 'Bearer realm="APEX GPT-6 Transport"',
    },
  });
}

function diagnostic(body: DiagnosticResult, status = 200): Response {
  return Response.json(body, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("");
}

function extractOutputText(obj: any): string {
  if (typeof obj?.output_text === "string") return obj.output_text;
  const parts: string[] = [];
  for (const item of Array.isArray(obj?.output) ? obj.output : []) {
    for (const content of Array.isArray(item?.content) ? item.content : []) {
      if (typeof content?.text === "string") parts.push(content.text);
    }
  }
  return parts.join("");
}

function safeOpenAIError(obj: any): { type: string | null; code: string | null } {
  const error = obj && typeof obj === "object" ? obj.error : null;
  return {
    type: typeof error?.type === "string" ? error.type : null,
    code: typeof error?.code === "string" ? error.code : null,
  };
}

async function runSelfTest(env: Env): Promise<Response> {
  const payload = {
    model: ALLOWED_MODEL,
    reasoning: { effort: "low" },
    input: "Reply with exactly APEX_RELAY_OK and nothing else.",
    max_output_tokens: 20,
  };
  const body = JSON.stringify(payload);
  const requestSha = await sha256Hex(body);

  if (!env.OPENAI_API_KEY) {
    return diagnostic({
      result: "FAIL",
      stage: "WORKER_CONFIG",
      reason: "OPENAI_API_KEY_MISSING",
      model: ALLOWED_MODEL,
      openai_response_id: null,
      request_sha256: requestSha,
    });
  }

  let upstream: Response;
  try {
    upstream = await fetch(OPENAI_RESPONSES_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.OPENAI_API_KEY}`,
        "Content-Type": "application/json",
      },
      body,
    });
  } catch {
    return diagnostic({
      result: "FAIL",
      stage: "OPENAI_REQUEST",
      reason: "NETWORK_ERROR",
      model: ALLOWED_MODEL,
      openai_response_id: null,
      request_sha256: requestSha,
    });
  }

  const text = await upstream.text();
  let obj: any;
  try {
    obj = JSON.parse(text);
  } catch {
    return diagnostic({
      result: "FAIL",
      stage: "OPENAI_RESPONSE",
      reason: upstream.ok ? "INVALID_JSON" : `OPENAI_HTTP_${upstream.status}`,
      model: ALLOWED_MODEL,
      openai_response_id: null,
      request_sha256: requestSha,
    });
  }

  const openaiResponseId = typeof obj?.id === "string" ? obj.id : null;

  if (!upstream.ok) {
    const safeError = safeOpenAIError(obj);
    return diagnostic({
      result: "FAIL",
      stage: "OPENAI_REQUEST",
      reason: `OPENAI_HTTP_${upstream.status}`,
      model: ALLOWED_MODEL,
      openai_response_id: openaiResponseId,
      request_sha256: requestSha,
      openai_error_type: safeError.type,
      openai_error_code: safeError.code,
    });
  }

  if (!obj || typeof obj !== "object") {
    return diagnostic({
      result: "FAIL",
      stage: "OPENAI_RESPONSE",
      reason: "INVALID_RESPONSE",
      model: ALLOWED_MODEL,
      openai_response_id: openaiResponseId,
      request_sha256: requestSha,
    });
  }

  if (typeof obj.model === "string" && obj.model !== ALLOWED_MODEL) {
    return diagnostic({
      result: "FAIL",
      stage: "MODEL_CHECK",
      reason: "MODEL_MISMATCH",
      model: typeof obj.model === "string" ? obj.model : ALLOWED_MODEL,
      openai_response_id: openaiResponseId,
      request_sha256: requestSha,
    });
  }

  const output = extractOutputText(obj).trim();
  if (output !== SELF_TEST_OK) {
    return diagnostic({
      result: "FAIL",
      stage: "OUTPUT_CHECK",
      reason: output ? "OUTPUT_MISMATCH" : "OUTPUT_MISSING",
      model: typeof obj.model === "string" ? obj.model : ALLOWED_MODEL,
      openai_response_id: openaiResponseId,
      request_sha256: requestSha,
    });
  }

  return diagnostic({
    result: "PASS",
    stage: "COMPLETE",
    reason: SELF_TEST_OK,
    model: typeof obj.model === "string" ? obj.model : ALLOWED_MODEL,
    openai_response_id: openaiResponseId,
    request_sha256: requestSha,
  });
}

function buildServer(env: Env) {
  const server = new McpServer({
    name: "APEX GPT-6 Transport",
    version: RELAY_VERSION,
  });

  server.registerTool(
    "run_apex_gpt6_response",
    {
      description:
        "Execute one frozen APEX terminal-selector Responses API payload. " +
        "This tool has zero engine-dispatch authority and cannot alter lineup membership upstream.",
      inputSchema: {
        request_sha256: z.string().regex(/^[0-9a-f]{64}$/),
        payload: z.record(z.string(), z.unknown()),
      },
    },
    async ({ request_sha256, payload }) => {
      const model = String((payload as Record<string, unknown>).model ?? "");
      if (model !== ALLOWED_MODEL) {
        throw new Error(`APEX_MODEL_NOT_ALLOWED:${model}`);
      }
      if (!env.OPENAI_API_KEY) {
        throw new Error("APEX_OPENAI_SECRET_MISSING");
      }

      const upstream = await fetch(OPENAI_RESPONSES_URL, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.OPENAI_API_KEY}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      const text = await upstream.text();
      if (!upstream.ok) {
        throw new Error(`APEX_OPENAI_HTTP_${upstream.status}`);
      }

      let obj: unknown;
      try {
        obj = JSON.parse(text);
      } catch {
        throw new Error("APEX_OPENAI_RESPONSE_INVALID_JSON");
      }

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({
              _apex_request_sha256: request_sha256,
              ...(obj as Record<string, unknown>),
            }),
          },
        ],
      };
    },
  );

  return server;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/self-test") {
      return new Response(SELF_TEST_HTML, {
        headers: {
          "Content-Type": "text/html; charset=utf-8",
          "Cache-Control": "no-store",
          "Referrer-Policy": "no-referrer",
        },
      });
    }

    if (request.method === "POST" && url.pathname === "/self-test/run") {
      if (!env.APEX_RELAY_TOKEN) {
        return diagnostic({
          result: "FAIL",
          stage: "WORKER_CONFIG",
          reason: "APEX_RELAY_TOKEN_MISSING",
          model: ALLOWED_MODEL,
          openai_response_id: null,
          request_sha256: null,
        }, 500);
      }
      if (!bearerAuthorized(request, env)) {
        return diagnostic({
          result: "FAIL",
          stage: "TOKEN_GATE",
          reason: "UNAUTHORIZED",
          model: ALLOWED_MODEL,
          openai_response_id: null,
          request_sha256: null,
        }, 401);
      }
      return runSelfTest(env);
    }

    if (!env.APEX_RELAY_TOKEN) {
      return new Response("APEX_RELAY_TOKEN_MISSING", {
        status: 500,
        headers: { "Cache-Control": "no-store" },
      });
    }

    if (!bearerAuthorized(request, env)) {
      return unauthorized();
    }

    return createMcpHandler(buildServer(env))(request, env, ctx);
  },
};
