import { getAccessToken } from "@auth0/nextjs-auth0";
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import client from "@/app/lib/gptAPI";

export const dynamic = "force-dynamic";

const GET = async (req: NextRequest) => {
  try {
    const limit = Number(req.nextUrl.searchParams.get("limit") || "100");
    const offset = Number(req.nextUrl.searchParams.get("offset") || "0");
    const status: any = req.nextUrl.searchParams.get("status") || "Done";
    const token = await getAccessToken({ scopes: ["admin:requests"] });
    // console.log("token", token, limit, offset);

    if (!token) {
      return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
    }
    const res = await client.GET("/api/v1/admin/requests", {
      params: {
        query: { limit, offset, status },
      },
      headers: { Authorization: `Bearer ${token.accessToken}` },
    });
    return NextResponse.json(res.data);
  } catch (error: any) {
    console.log(error);
    if (error.code === "ERR_EXPIRED_ACCESS_TOKEN") {
      return NextResponse.json(
        { error: "Error fetching sessions: token expired" },
        { status: 401 },
      );
    }
    return NextResponse.json(
      { error: "Error fetching sessions" },
      { status: 500 },
    );
  }
};

export { GET };
