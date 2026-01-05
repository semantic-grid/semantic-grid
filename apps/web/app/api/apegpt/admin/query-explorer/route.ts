import { getAccessToken } from "@auth0/nextjs-auth0";
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import client from "@/app/lib/gptAPI";

const GET = async (req: NextRequest) => {
  try {
    const limit = Number(req.nextUrl.searchParams.get("limit") || "50");
    const offset = Number(req.nextUrl.searchParams.get("offset") || "0");
    const search = req.nextUrl.searchParams.get("search") || undefined;
    const hasFeedback =
      req.nextUrl.searchParams.get("has_feedback") === "true" || undefined;
    const token = await getAccessToken({ scopes: ["admin:requests"] });

    if (!token) {
      return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
    }
    const res = await client.GET("/api/v1/admin/query-explorer", {
      params: {
        query: {
          limit,
          offset,
          search,
          has_feedback: hasFeedback,
        },
      },
      headers: { Authorization: `Bearer ${token.accessToken}` },
    });
    if (res.error) {
      console.log("Backend error:", res.error);
      return NextResponse.json(
        { error: "Error fetching queries from backend" },
        { status: 500 },
      );
    }
    return NextResponse.json(res.data);
  } catch (error: any) {
    console.log(error);
    if (error.code === "ERR_EXPIRED_ACCESS_TOKEN") {
      return NextResponse.json(
        { error: "Error fetching queries: token expired" },
        { status: 401 },
      );
    }
    return NextResponse.json(
      { error: "Error fetching queries" },
      { status: 500 },
    );
  }
};

export { GET };
