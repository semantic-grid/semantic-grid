import { getAccessToken } from "@auth0/nextjs-auth0";
import { cookies } from "next/headers";
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import client from "@/app/lib/gptAPI";

export const dynamic = "force-dynamic";

const GET = async (req: NextRequest, res: NextResponse) => {
  try {
    const guestToken = cookies().get("uid")?.value;
    let token = null; //
    try {
      token = await getAccessToken();
    } catch (error: any) {
      token = { accessToken: guestToken };
    }
    if (!token) {
      return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
    }
    // console.log("token", token);
    const res = await client.GET("/api/v1/session", {
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
