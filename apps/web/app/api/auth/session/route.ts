import { getSession } from "@auth0/nextjs-auth0";
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export const GET = async (req: NextRequest, res: NextResponse) => {
  try {
    const session = await getSession();
    return NextResponse.json(session);
  } catch (error) {
    console.error("???", error);
    return NextResponse.json({ error }, { status: 500 });
  }
};
