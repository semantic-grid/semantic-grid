import { getAccessToken } from "@auth0/nextjs-auth0";
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import client from "@/app/lib/gptAPI";

const PATCH = async (
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) => {
  try {
    const { id } = await params;
    const body = await req.json();
    const token = await getAccessToken({ scopes: ["admin:requests"] });

    if (!token) {
      return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
    }

    const res = await client.PATCH("/api/v1/admin/requests/{request_id}", {
      params: {
        path: { request_id: id },
      },
      body,
      headers: { Authorization: `Bearer ${token.accessToken}` },
    });

    if (res.error) {
      return NextResponse.json(
        { error: res.error },
        { status: res.response.status },
      );
    }

    return NextResponse.json(res.data);
  } catch (error: any) {
    console.error("Error updating request:", error);
    if (error.code === "ERR_EXPIRED_ACCESS_TOKEN") {
      return NextResponse.json(
        { error: "Error updating request: token expired" },
        { status: 401 },
      );
    }
    return NextResponse.json(
      { error: "Error updating request" },
      { status: 500 },
    );
  }
};

export { PATCH };
