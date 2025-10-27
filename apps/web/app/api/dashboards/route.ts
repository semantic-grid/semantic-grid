import { NextResponse } from "next/server";
import { z } from "zod";

import {
  // createDashboard,
  getDashboardByPath,
  getDashboards,
} from "@/app/lib/payload";

const CreateDash = z.object({
  name: z.string().min(1),
  slug: z
    .string()
    .min(1)
    .regex(/^\/[a-z0-9-/]*$/i),
  description: z.string().optional(),
});

export async function GET(_: Request, { query }: { query: { slug: string } }) {
  if (query.slug) {
    const slug = decodeURIComponent(
      query.slug.startsWith("%2F") ? query.slug : `/${query.slug}`,
    );
    const d = await getDashboardByPath(slug);
    if (!d) return NextResponse.json({ error: "Not found" }, { status: 404 });
    return NextResponse.json(d);
  }
  const data = await getDashboards();
  return NextResponse.json(data);
}

export async function POST(req: Request) {
  const body = await req.json();
  const parsed = CreateDash.safeParse(body);
  if (!parsed.success)
    return NextResponse.json({ error: parsed.error.format() }, { status: 400 });
  const row = null; // = await createDashboard(parsed.data);
  return NextResponse.json(row, { status: 201 });
}
