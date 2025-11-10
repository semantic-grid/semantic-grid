/**
 * V2 Authentication Helper
 *
 * Handles token management for v2 API calls.
 * Works with both Auth0 tokens and guest tokens.
 */

import type { UserProfile } from "@auth0/nextjs-auth0/client";

/**
 * Get authentication token for API calls
 *
 * Priority:
 * 1. Auth0 user token (if logged in)
 * 2. Guest token from cookie (if anonymous)
 */
export async function getV2AuthToken(
  user?: UserProfile | null,
): Promise<string> {
  if (user) {
    // User is authenticated with Auth0
    // Fetch the token from the session endpoint
    const response = await fetch("/api/auth/session");
    const session = await response.json();

    if (session.token) {
      return session.token;
    }
  }

  // Guest user - try to get token from cookie first
  const cookies = document.cookie.split(";");
  const uidCookie = cookies.find((c) => c.trim().startsWith("uid="));

  if (uidCookie) {
    const token = uidCookie.split("=")[1];
    if (token) {
      return token;
    }
  }

  // No cookie found - fetch from V2 guest endpoint (returns JSON, doesn't redirect)
  try {
    const response = await fetch("/api/auth/v2/guest");

    if (!response.ok) {
      console.error(
        "Guest token endpoint returned error:",
        response.status,
        response.statusText,
      );
      throw new Error(
        `Failed to get guest token: ${response.status} ${response.statusText}`,
      );
    }

    const data = await response.json();
    console.log("Guest token response:", data);

    if (data.token) {
      return data.token;
    }

    throw new Error("Guest token endpoint did not return a token");
  } catch (error) {
    console.error("Failed to get guest token:", error);
    throw error;
  }
}

/**
 * Check if user has quota remaining (for guest users)
 */
export async function checkQuota(user?: UserProfile | null): Promise<{
  hasQuota: boolean;
  remaining?: number;
  limit?: number;
}> {
  if (user) {
    // Authenticated users have unlimited quota
    return { hasQuota: true };
  }

  // Check guest quota
  try {
    const response = await fetch("/api/auth/guest/verify");
    const data = await response.json();

    return {
      hasQuota: data.hasQuota,
      remaining: data.remaining,
      limit: data.limit,
    };
  } catch {
    return { hasQuota: false };
  }
}
