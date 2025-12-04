import { getAccessToken } from "@auth0/nextjs-auth0";
import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

/**
 * SSE proxy route for system telemetry (worker stats, DB pool stats).
 * Proxies to backend /api/v1/telemetry/sse endpoint.
 */
export async function GET(request: NextRequest) {
  try {
    // Get authentication token
    const guestToken = cookies().get("uid")?.value;
    let token = null;

    try {
      token = await getAccessToken();
    } catch {
      // Fallback to guest token if Auth0 fails
      token = { accessToken: guestToken };
    }

    if (!token || !token.accessToken) {
      return new Response("Unauthorized", { status: 401 });
    }

    // Get backend URL from environment
    const backendUrl = process.env.APEGPT_API_URL || "http://localhost:8080";

    // Connect to backend SSE endpoint
    const sseUrl = `${backendUrl}/api/v1/telemetry/sse`;

    const response = await fetch(sseUrl, {
      headers: {
        Authorization: `Bearer ${token.accessToken}`,
        Accept: "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      },
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error(
        `[Telemetry SSE] Backend returned ${response.status}: ${response.statusText}`,
      );
      return new Response(
        `Backend error: ${response.statusText} - ${errorText}`,
        { status: response.status },
      );
    }

    if (!response.body) {
      return new Response("No response body", { status: 500 });
    }

    // Stream the response back to the client
    const headers = new Headers({
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    });

    return new Response(response.body, {
      status: 200,
      headers,
    });
  } catch (error: any) {
    console.error("[Telemetry SSE] Error:", error);

    if (error.code === "ERR_EXPIRED_ACCESS_TOKEN") {
      return new Response("Token expired", { status: 401 });
    }

    return new Response(`Error: ${error.message || "Internal server error"}`, {
      status: 500,
    });
  }
}

export const dynamic = "force-dynamic";
export const revalidate = 0;
