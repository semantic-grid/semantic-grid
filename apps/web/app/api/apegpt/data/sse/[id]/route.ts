import { getAccessToken } from "@auth0/nextjs-auth0";
import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

const ORIGIN_BASE = process.env.APEGPT_API_URL ?? "https://api.apegpt.ai";

export const GET = async (
  req: NextRequest,
  { params: { id } }: { params: { id: string } },
) => {
  try {
    console.log(`[SSE Data Proxy] Request for query ${id}`);

    // 1) Auth
    const guestToken = cookies().get("uid")?.value;
    let token: { accessToken?: string } | null = null;
    try {
      token = await getAccessToken();
    } catch (e) {
      console.log("[SSE Data Proxy] Auth0 failed, using guest token");
      token = { accessToken: guestToken };
    }
    if (!token?.accessToken) {
      console.error("[SSE Data Proxy] No token available");
      // Return SSE-formatted error so frontend can detect auth failure
      const sseError = `event: auth_error\ndata: ${JSON.stringify({ error: "Not authenticated", redirect: "/api/auth/login" })}\n\n`;
      return new Response(sseError, {
        status: 200, // SSE needs 200 to deliver the message
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
        },
      });
    }

    // 2) Build upstream SSE URL (preserve query string)
    const url = new URL(`${ORIGIN_BASE}/api/v1/data/sse/${id}`);
    req.nextUrl.searchParams.forEach((v, k) => url.searchParams.set(k, v));

    // 3) Fetch SSE stream from origin
    const upstream = await fetch(url.toString(), {
      method: "GET",
      headers: {
        Authorization: `Bearer ${token.accessToken}`,
        Accept: "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      },
      // Important: don't set a timeout for SSE
    });

    if (!upstream.ok) {
      const error = await upstream.text();
      // Handle 401 from backend with SSE auth_error event
      if (upstream.status === 401) {
        const sseError = `event: auth_error\ndata: ${JSON.stringify({ error: "Session expired", redirect: "/api/auth/login" })}\n\n`;
        return new Response(sseError, {
          status: 200,
          headers: {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
          },
        });
      }
      return new Response(error, {
        status: upstream.status,
        headers: { "Content-Type": "application/json" },
      });
    }

    if (!upstream.body) {
      return new Response("No response body", {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }

    // 4) Return SSE stream to client
    const headers = new Headers({
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no", // Disable nginx buffering
    });

    console.log(`[SSE Data Proxy] Streaming data for query ${id}`);

    return new Response(upstream.body, {
      status: 200,
      headers,
    });
  } catch (error: any) {
    console.error("[SSE Data Proxy] Error:", error);
    return new Response(
      JSON.stringify({ error: error.message || "Internal server error" }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      },
    );
  }
};

// Disable static optimization for this route
export const dynamic = "force-dynamic";
// Disable response caching
export const revalidate = 0;
// Set max duration for SSE streaming (in seconds)
export const maxDuration = 300; // 5 minutes
