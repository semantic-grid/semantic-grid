import { getAccessToken } from "@auth0/nextjs-auth0";
import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

/**
 * SSE proxy route for real-time request status updates
 *
 * This route:
 * 1. Authenticates the user (Auth0 or guest token)
 * 2. Connects to the backend SSE endpoint
 * 3. Streams events back to the browser
 *
 * Browser EventSource cannot send custom headers, so we handle
 * authentication here and proxy the SSE stream.
 */
export async function GET(
  request: NextRequest,
  { params }: { params: { session_id: string } },
) {
  try {
    const { session_id } = params;

    // Get authentication token
    const guestToken = cookies().get("uid")?.value;
    let token = null;

    try {
      token = await getAccessToken();
      console.log("[SSE Proxy] Using Auth0 token");
    } catch (error: any) {
      // Fallback to guest token if Auth0 fails
      console.log("[SSE Proxy] Auth0 failed, using guest token");
      token = { accessToken: guestToken };
    }

    if (!token || !token.accessToken) {
      console.error("[SSE Proxy] No token available");
      return new Response("Unauthorized", { status: 401 });
    }

    // Get backend URL from environment
    const backendUrl =
      process.env.APEGPT_API_URL || "http://localhost:8080";

    // Connect to backend SSE endpoint
    const sseUrl = `${backendUrl}/api/v1/sse/${session_id}`;
    console.log(`[SSE Proxy] Connecting to backend: ${sseUrl}`);

    const response = await fetch(sseUrl, {
      headers: {
        Authorization: `Bearer ${token.accessToken}`,
        Accept: "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      },
      // Important: don't set a timeout, SSE connections are long-lived
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error(
        `[SSE Proxy] Backend returned ${response.status}: ${response.statusText}`,
      );
      console.error(`[SSE Proxy] Error body: ${errorText}`);
      return new Response(
        `Backend error: ${response.statusText} - ${errorText}`,
        {
          status: response.status,
        },
      );
    }

    if (!response.body) {
      console.error("[SSE Proxy] No response body from backend");
      return new Response("No response body", { status: 500 });
    }

    // Stream the response back to the client
    // Set proper SSE headers
    const headers = new Headers({
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no", // Disable nginx buffering
    });

    console.log(`[SSE Proxy] Streaming events for session ${session_id}`);

    // Return the streaming response
    return new Response(response.body, {
      status: 200,
      headers,
    });
  } catch (error: any) {
    console.error("[SSE Proxy] Error:", error);

    if (error.code === "ERR_EXPIRED_ACCESS_TOKEN") {
      return new Response("Token expired", { status: 401 });
    }

    return new Response(`Error: ${error.message || "Internal server error"}`, {
      status: 500,
    });
  }
}

// Disable static optimization for this route
export const dynamic = "force-dynamic";
// Disable response caching
export const revalidate = 0;
