import { createMcpHandler } from "agents/mcp/server";
import { McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";

interface Env {
  OPENAI_API_KEY: string;
}

const OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses";
const ALLOWED_MODEL = "gpt-6-astra";

function buildServer(env: Env) {
  const server = new McpServer({
    name: "APEX GPT-6 Transport",
    version: "1.0.0",
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
          "Authorization": `Bearer ${env.OPENAI_API_KEY}`,
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
    return createMcpHandler(buildServer(env))(request, env, ctx);
  },
};
