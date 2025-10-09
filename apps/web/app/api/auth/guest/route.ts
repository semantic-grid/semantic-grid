// app/api/auth/guest/route.ts
import { readFile } from "node:fs/promises";

import * as jose from "jose";
import { cookies } from "next/headers";
import { type NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs"; // ensure fs is available

// Paths provided via env (point to mounted files)
const PUB_PATH = process.env.JWT_PUBLIC_KEY!;
const PRIV_PATH = process.env.JWT_PRIVATE_KEY!;

// simple in-memory cache for the PEMs & CryptoKeys
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
  // Basic sanity check to avoid the SPKI error
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
  const uidCookie = cookies().get("uid")?.value;

  if (uidCookie) {
    const publicKey = await getPublicKey();
    const jwt = await jose.jwtVerify(uidCookie, publicKey);
    const trialCookie = cookies().get("apegpt-trial")?.value;
    const trialQuota = parseInt(process.env.FREE_TIER_QUOTA || "5", 10);
    const hasQuota = trialCookie
      ? parseInt(trialCookie, 10) < trialQuota
      : false;
    return NextResponse.json({ uid: jwt.payload.sub, hasQuota });
  }

  const host = req.headers.get("host");
  const schema = req.headers.get("x-forwarded-proto") || "http";

  if (req.method !== "GET") {
    return NextResponse.json("Method not allowed", { status: 405 });
  }

  const guestId = `guest-${crypto.randomUUID()}`;
  const privateKey = await getPrivateKey();

  const jwt = await new jose.SignJWT({ sub: guestId })
    .setProtectedHeader({ alg: "RS256", kid: "guest-key" })
    .setAudience(process.env.AUTH0_AUDIENCE!)
    .setIssuer(process.env.GUEST_AUTH_ISSUER!)
    .setExpirationTime("365d")
    .sign(privateKey);

  const response = NextResponse.redirect(`${schema}://${host}/query`);
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
