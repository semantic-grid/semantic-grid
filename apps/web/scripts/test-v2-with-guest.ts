#!/usr/bin/env tsx
/**
 * Test V2 API with Guest Token
 *
 * Gets a guest token from the web app and tests v2 API end-to-end.
 *
 * Usage:
 *   npm run test:v2:guest
 */

async function main() {
  console.log("🧪 Testing V2 API with Guest Token\n");

  const WEB_URL = process.env.WEB_URL || "http://localhost:3000";
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

  try {
    // Step 1: Get guest token cookie
    console.log("1️⃣  Getting guest token from web app...");
    const guestResponse = await fetch(`${WEB_URL}/api/auth/guest`, {
      redirect: "manual", // Don't follow redirect
    });

    const cookies = guestResponse.headers.get("set-cookie");
    if (!cookies) {
      throw new Error("No cookies returned from /api/auth/guest");
    }

    // Extract uid cookie (this is the JWT token)
    const uidMatch = cookies.match(/uid=([^;]+)/);
    if (!uidMatch) {
      throw new Error("No uid cookie found");
    }

    const guestToken = uidMatch[1];
    console.log(`   ✅ Got guest token: ${guestToken.substring(0, 20)}...`);
    console.log(`   📊 Cookie: uid=${guestToken.substring(0, 30)}...\n`);

    // Step 2: Health check
    console.log("2️⃣  Health check...");
    const healthResponse = await fetch(`${API_URL}/api/v2/health`);
    const health = await healthResponse.json();
    console.log(`   ✅ API is healthy: ${JSON.stringify(health)}\n`);

    // Step 3: Create session with guest token
    console.log("3️⃣  Creating session...");
    const sessionResponse = await fetch(`${API_URL}/api/v2/sessions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${guestToken}`,
      },
      body: JSON.stringify({
        name: "Guest Test Session",
        tags: "test,guest,automated",
      }),
    });

    if (!sessionResponse.ok) {
      const error = await sessionResponse.text();
      throw new Error(
        `Failed to create session: ${sessionResponse.status} ${error}`,
      );
    }

    const session = await sessionResponse.json();
    console.log(`   ✅ Session created: ${session.session_id}`);
    console.log(`   📊 API version: ${session.api_version}`);
    console.log(`   📝 Initial messages: ${session.messages.length}\n`);

    // Step 4: Send message
    console.log("4️⃣  Sending message...");
    const messageResponse = await fetch(
      `${API_URL}/api/v2/sessions/${session.session_id}/messages`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${guestToken}`,
        },
        body: JSON.stringify({
          role: "user",
          kind: "chat",
          content: "Show me the top 10 transactions by value",
        }),
      },
    );

    if (!messageResponse.ok) {
      const error = await messageResponse.text();
      throw new Error(
        `Failed to send message: ${messageResponse.status} ${error}`,
      );
    }

    const messageResult = await messageResponse.json();
    console.log(`   ✅ Message sent: ${messageResult.message_id}`);
    console.log(`   📊 Status: ${messageResult.status}\n`);

    // Step 5: Get messages
    console.log("5️⃣  Fetching messages...");
    const messagesResponse = await fetch(
      `${API_URL}/api/v2/sessions/${session.session_id}/messages?limit=10`,
      {
        headers: {
          Authorization: `Bearer ${guestToken}`,
        },
      },
    );

    if (!messagesResponse.ok) {
      const error = await messagesResponse.text();
      throw new Error(
        `Failed to get messages: ${messagesResponse.status} ${error}`,
      );
    }

    const messages = await messagesResponse.json();
    console.log(`   ✅ Retrieved ${messages.messages.length} messages`);
    console.log(`   📊 Total count: ${messages.total_count}`);
    console.log(`   📄 Has more: ${messages.has_more}\n`);

    // Step 6: Display messages
    console.log("6️⃣  Message list:");
    messages.messages.forEach((msg: any, idx: number) => {
      const content = msg.content.substring(0, 60);
      console.log(`   ${idx + 1}. [${msg.role}] ${msg.kind} - ${msg.status}`);
      console.log(`      "${content}${msg.content.length > 60 ? "..." : ""}"`);
    });

    console.log("\n✅ All tests passed with guest token!\n");
  } catch (error) {
    console.error("\n❌ Test failed:", error);
    if (error instanceof Error) {
      console.error("   Message:", error.message);
    }
    process.exit(1);
  }
}

main();
