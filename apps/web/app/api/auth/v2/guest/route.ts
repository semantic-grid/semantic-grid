// app/api/auth/v2/guest/route.ts
// V2-specific guest token endpoint that returns JSON instead of redirecting
// This allows client-side components to get the token without navigation

import { readFile } from "node:fs/promises";
import * as jose from "jose";
import { cookies } from "next/headers";
import { type NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

const PUB_PATH = process.env.JWT_PUBLIC_KEY!;
const PRIV_PATH = process.env.JWT_PRIVATE_KEY!;

let pubPem: string | undefined;
let privPem: string | undefined;
let pubKey: CryptoKey | undefined;
let privKey: CryptoKey | undefined;

async function getPublicKey(): Promise<CryptoKey> {
  if (pubKey) return pubKey;
  if (!pubPem) {
    try {
      pubPem = (await readFile(PUB_PATH, "utf8")).trim();
    } catch (e) {
      pubPem = process.env.JWT_PUBLIC_KEY!;
    }
  }
  if (!pubPem.includes("-----BEGIN PUBLIC KEY-----")) {
    throw new Error("Public key must be SPKI PEM (BEGIN PUBLIC KEY)");
  }
  pubKey = await jose.importSPKI(pubPem, "RS256");
  return pubKey;
}

async function getPrivateKey(): Promise<CryptoKey> {
  if (privKey) return privKey;
  if (!privPem) {
    try {
      privPem = (await readFile(PRIV_PATH, "utf8")).trim();
    } catch (e) {
      privPem = process.env.JWT_PRIVATE_KEY!;
    }
  }
  if (!privPem.includes("-----BEGIN PRIVATE KEY-----")) {
    throw new Error("Private key must be PKCS#8 PEM (BEGIN PRIVATE KEY)");
  }
  privKey = await jose.importPKCS8(privPem, "RS256");
  return privKey;
}

export const GET = async (req: NextRequest) => {
  // Check if user already has a token
  const uidCookie = cookies().get("uid")?.value;

  if (uidCookie) {
    // Verify existing token
    try {
      const publicKey = await getPublicKey();
      const jwt = await jose.jwtVerify(uidCookie, publicKey);
      const trialCookie = cookies().get("apegpt-trial")?.value;
      const trialQuota = parseInt(process.env.FREE_TIER_QUOTA || "5", 10);
      const hasQuota = trialCookie
        ? parseInt(trialCookie, 10) < trialQuota
        : false;

      return NextResponse.json({
        token: uidCookie,
        uid: jwt.payload.sub,
        hasQuota
      });
    } catch (error) {
      // Token is invalid, create a new one
      console.error("Invalid existing token:", error);
    }
  }

  // Create new guest token
  const guestId = `guest-${crypto.randomUUID()}`;
  const privateKey = await getPrivateKey();

  const jwt = await new jose.SignJWT({ sub: guestId })
    .setProtectedHeader({ alg: "RS256", kid: "guest-key" })
    .setAudience(process.env.AUTH0_AUDIENCE!)
    .setIssuer("https://apegpt.ai")
    .setExpirationTime("365d")
    .sign(privateKey);

  // Set cookies
  const response = NextResponse.json({
    token: jwt,
    uid: guestId,
    hasQuota: true,
  });

  response.cookies.set("uid", jwt, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 365 * 24 * 60 * 60,
  });

  response.cookies.set("apegpt-trial", "0", {
    httpOnly: false,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
  });

  return response;
};
