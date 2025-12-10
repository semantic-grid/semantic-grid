// app/(dash)/[[...section]]/page.tsx
import { getSession } from "@auth0/nextjs-auth0";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import type { Layout } from "react-grid-layout";

import DashboardGrid from "@/app/components/DashboardGrid";
import { LoginPrompt } from "@/app/components/LoginPrompt";
// import type { DashboardItem } from "@/app/lib/dashboards";
import { getDashboardByPath, getDashboardData } from "@/app/lib/payload";
import type { DashboardItem, Query } from "@/app/lib/payload-types";

const pathFromParams = (params: { section?: string[] }) =>
  // /            -> ''
  // /tokens      -> 'tokens'
  // /trends/...  -> 'trends'
  // const seg = params.section?.[0] ?? ""; // first segment only
  // return `/${seg}`; // '' -> '/', else '/tokens'
  params.section ? `/${params.section.join("/")}` : ""; // '' -> '/', else '/tokens'

export async function generateMetadata({
  params,
}: {
  params: { section?: string[] };
}): Promise<Metadata> {
  const d = await getDashboardByPath(pathFromParams(params));
  return { title: `ApeGPT | ${d?.name || "Home"}` };
}

const typeToHash = (type: string) => {
  switch (type) {
    case "chart":
      return "chart";
    case "table":
    default:
      return "grid";
  }
};

const Page = async ({ params }: { params: { section?: string[] } }) => {
  const slugPath = pathFromParams(params); // '/' | '/tokens' | '/trends' | '/traders' | '/user'
  const isUserPage = slugPath.startsWith("/user/");
  const dMeta = await getDashboardByPath(slugPath);
  console.log("Dashboard meta:", slugPath, dMeta);
  const d = await getDashboardData(dMeta?.id || "");
  if (!dMeta || !d) {
    notFound();
  }
  const session = await getSession();

  // map to DashboardGrid items

  const items =
    (d as any).items?.map((it: DashboardItem & { layout: Layout }) => ({
      key: it.id,
      // position: it.position,
      title: it.description || it.name || "",
      id: it.id,
      href: (it.query as Query)?.queryUid
        ? `/item/${it.id}#${typeToHash(it.itemType || it.type || "table")}`
        : undefined,
      type: it.type || it.itemType,
      subtype: it.chartType,
      queryUid: (it.query as Query)?.queryUid,
      layout: it.layout,
    })) ?? [];

  items.push({
    key: "create",
    title: "Create new",
    type: "create",
    href: "/grid",
    position: Number.MAX_SAFE_INTEGER,
  });

  console.log("Dashboard items:", slugPath, items?.length, "layout", d.layout);

  return !isUserPage || session ? (
    <DashboardGrid
      slugPath={slugPath}
      title={dMeta?.name}
      items={items}
      layout={d.layout || undefined}
      maxItemsPerRow={dMeta?.maxItemsPerRow || 3}
    />
  ) : (
    <LoginPrompt slugPath={slugPath} />
  );
};

export default Page;
