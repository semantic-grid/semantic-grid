import { NextResponse } from "next/server";
import { z } from "zod";

import {
  attachQueryToDashboard,
  detachQueryFromDashboard,
} from "@/app/lib/payload";

const Attach = z.object({
  queryUid: z.string().uuid(),
  name: z.string().optional(),
  description: z.string().optional(),
  itemType: z.enum(["chart", "table"]),
  chartType: z.string().optional(),
  position: z.number().int().optional(),
});

const Detach = z.object({
  queryUid: z.string().uuid(),
  itemUid: z.string(),
});

export async function POST(
  req: Request,
  { params }: { params: { id: string } },
) {
  const body = await req.json();
  const parsed = Attach.safeParse(body);
  if (!parsed.success)
    return NextResponse.json({ error: parsed.error.format() }, { status: 400 });

  const row = await attachQueryToDashboard({
    dashboardId: params.id,
    ...parsed.data,
  });
  // row === null means already attached; still 200 with info
  return NextResponse.json({ item: row });
}

export async function DELETE(
  req: Request,
  { params }: { params: { id: string } },
) {
  const body = await req.json();
  const parsed = Detach.safeParse(body);
  if (!parsed.success)
    return NextResponse.json({ error: parsed.error.format() }, { status: 400 });

  const count = await detachQueryFromDashboard(
    params.id,
    parsed.data.queryUid,
    parsed.data.itemUid,
  );
  return NextResponse.json({ removed: count });
}
