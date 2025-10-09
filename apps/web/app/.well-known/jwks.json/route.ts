import { NextApiRequest, NextApiResponse } from "next";
import * as jose from "jose";
import { NextResponse } from "next/server";
import { readFile } from "node:fs/promises";

export const dynamic = "force-dynamic";

// Paths provided via env (point to mounted files)
const PUB_PATH = process.env.JWT_PUBLIC_KEY!;

// simple in-memory cache for the PEMs & CryptoKeys
let pubPem: string | undefined;
let pubKey: CryptoKey | undefined;

async function getPublicKey(): Promise<CryptoKey> {
  if (pubKey) return pubKey;
  if (!pubPem) {
    pubPem = (await readFile(PUB_PATH, "utf8")).trim();
  }
  // Basic sanity check to avoid the SPKI error
  if (!pubPem.includes("-----BEGIN PUBLIC KEY-----")) {
    throw new Error("Public key must be SPKI PEM (BEGIN PUBLIC KEY)");
  }
  pubKey = await jose.importSPKI(pubPem, "RS256");
  return pubKey;
}

export const GET = async (req: NextApiRequest, res: NextApiResponse) => {
  if (req.method !== "GET") return res.status(405).end();

  const publicKey = await getPublicKey();
  const jwk = await jose.exportJWK(publicKey);
  
  return NextResponse.json({
    keys: [
      {
        ...jwk,
        kid: "guest-key", // Key ID
        alg: "RS256",
        typ: "JWT",
        use: "sig", // Signature key
      },
    ],
  });
};
