import { getAccessToken } from "@auth0/nextjs-auth0";
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import client from "@/app/lib/gptAPI";

const GET = async (req: NextRequest) => {
  try {
    const limit = Number(req.nextUrl.searchParams.get("limit") || "100");
    const offset = Number(req.nextUrl.searchParams.get("offset") || "0");
    const status: any = req.nextUrl.searchParams.get("status") || undefined;
    const search = req.nextUrl.searchParams.get("search") || undefined;
    const hasFeedback =
      req.nextUrl.searchParams.get("has_feedback") === "true" || undefined;
    const isTestParam = req.nextUrl.searchParams.get("is_test");
    const isFixedParam = req.nextUrl.searchParams.get("is_fixed");
    const needsFixingParam = req.nextUrl.searchParams.get("needs_fixing");
    const isTest =
      isTestParam === "true" ? true : isTestParam === "false" ? false : null;
    const isFixed =
      isFixedParam === "true" ? true : isFixedParam === "false" ? false : null;
    const needsFixing =
      needsFixingParam === "true"
        ? true
        : needsFixingParam === "false"
          ? false
          : null;
    const token = await getAccessToken({ scopes: ["admin:requests"] });

    if (!token) {
      return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
    }
    const res = await client.GET("/api/v1/admin/requests", {
      params: {
        query: {
          limit,
          offset,
          status,
          search,
          has_feedback: hasFeedback,
          is_test: isTest,
          is_fixed: isFixed,
          needs_fixing: needsFixing,
        },
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
