#!/usr/bin/env tsx
/**
 * Manual V2 API Test Script
 *
 * Quick test to verify v2 API integration works.
 *
 * Usage:
 *   npm run test:v2
 *   or
 *   npx tsx scripts/test-v2-api.ts
 */

import {
  createV2Session,
  sendMessage,
  getMessages,
  healthCheck,
} from "../app/lib/v2";

const TEST_TOKEN = process.env.TEST_AUTH_TOKEN;

async function main() {
  console.log("🧪 Testing V2 API Integration\n");

  try {
    // 1. Health check
    console.log("1️⃣  Health check...");
    const isHealthy = await healthCheck();
    console.log(`   ✅ API is ${isHealthy ? "healthy" : "unhealthy"}\n`);

    if (!isHealthy) {
      console.error(
        "   ❌ API is not healthy. Make sure fm-app is running on localhost:8080",
      );
      process.exit(1);
    }

    // Check for token
    if (!TEST_TOKEN) {
      console.error("   ❌ TEST_AUTH_TOKEN environment variable not set");
      console.error(
        "   ℹ️  Get a token from the web app (DevTools > Network > Authorization header)",
      );
      console.error(
        '   ℹ️  Then run: TEST_AUTH_TOKEN="your-token" npm run test:v2',
      );
      process.exit(1);
    }

    // 2. Create session
    console.log("2️⃣  Creating session...");
    const session = await createV2Session(
      {
        name: "API Test Session",
        tags: "test,manual",
      },
      TEST_TOKEN,
    );
    console.log(`   ✅ Session created: ${session.session_id}`);
    console.log(`   📊 API version: ${session.api_version}`);
    console.log(`   📝 Initial messages: ${session.messages.length}\n`);

    // 3. Send message
    console.log("3️⃣  Sending message...");
    const messageResponse = await sendMessage(
      session.session_id,
      {
        role: "user",
        kind: "interactive_query",
        content: "Show me the top 10 transactions by value",
      },
      TEST_TOKEN,
    );
    console.log(`   ✅ Message sent: ${messageResponse.message.id}`);
    console.log(`   📄 Content: "${messageResponse.message.content}"`);
    console.log(`   📊 Status: ${messageResponse.message.status}\n`);

    // 4. Get messages
    console.log("4️⃣  Fetching messages...");
    const messages = await getMessages(
      session.session_id,
      { limit: 10 },
      TEST_TOKEN,
    );
    console.log(`   ✅ Retrieved ${messages.messages.length} messages`);
    console.log(`   📊 Total count: ${messages.total_count}`);
    console.log(`   📄 Has more: ${messages.has_more}\n`);

    // 5. Display messages
    console.log("5️⃣  Message list:");
    messages.messages.forEach((msg, idx) => {
      console.log(`   ${idx + 1}. [${msg.role}] ${msg.kind} - ${msg.status}`);
      console.log(
        `      "${msg.content.substring(0, 60)}${msg.content.length > 60 ? "..." : ""}"`,
      );
    });

    console.log("\n✅ All tests passed!\n");
  } catch (error) {
    console.error("\n❌ Test failed:", error);
    if (error instanceof Error) {
      console.error("   Message:", error.message);
      console.error("   Stack:", error.stack);
    }
    process.exit(1);
  }
}

main();
