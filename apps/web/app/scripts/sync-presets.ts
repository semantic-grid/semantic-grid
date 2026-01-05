// scripts/sync-presets.ts
import "dotenv/config";

import { eq, inArray } from "drizzle-orm";
import { drizzle } from "drizzle-orm/postgres-js";
import { migrate } from "drizzle-orm/postgres-js/migrator";
import postgres from "postgres";

import { db } from "@/app/db"; // your drizzle db instance
import {
  dashboardItems as tItems,
  dashboards as tDashboards,
  queries as tQueries,
} from "@/app/db/schema";
import { dashboardItems, dashboards, queries } from "@/app/presets";

type SyncMode = "merge" | "prune-per-dashboard" | "prune-global";

/**
 * Options:
 * - mode = "merge": only upsert; never delete
 * - mode = "prune-per-dashboard": keep each dashboard in sync (delete items not present in preset for that dashboard)
 * - mode = "prune-global": also delete dashboards/queries not present in presets (destructive)
 */
const OPTIONS: { mode: SyncMode } = {
  mode: (process.env.PRESETS_SYNC_MODE as SyncMode) || "merge",
};

async function runMigrations() {
  const client = postgres(process.env.DATABASE_URL!, {
    max: 1,
    ssl: "require",
  });
  const db = drizzle(client);
  await migrate(db, { migrationsFolder: "./drizzle" });
  await client.end();
}

async function main() {
  await runMigrations();

  const started = Date.now();
  const summary = {
    dashboards: { upserted: 0, untouched: 0, deleted: 0 },
    queries: { upserted: 0, untouched: 0, deleted: 0 },
    items: { upserted: 0, untouched: 0, deleted: 0 },
  };

  await db.transaction(async (trx) => {
    // 1) Upsert Dashboards (keyed by slug)
    const existingDash = await trx.select().from(tDashboards);
    const slugToExisting = new Map(existingDash.map((d) => [d.slug, d]));
    const legacyIdToNewId = new Map<string, string>(); // map preset dashboard.id -> DB id

    for (const d of dashboards) {
      const prev = slugToExisting.get(d.slug);
      if (!prev) {
        const [row] = await trx
          .insert(tDashboards)
          .values({
            name: d.name,
            slug: d.slug,
            description: d.description ?? null,
            // createdAt/updatedAt are defaults
          })
          .returning();
        if (row) {
          summary.dashboards.upserted++;
          legacyIdToNewId.set(d.id, row.id);
        }
      } else {
        legacyIdToNewId.set(d.id, prev.id);
        // Update only if something changed
        const needsUpdate =
          (d.description ?? null) !== (prev.description ?? null) ||
          d.name !== prev.name;
        if (needsUpdate) {
          await trx
            .update(tDashboards)
            .set({ name: d.name, description: d.description ?? null })
            .where(eq(tDashboards.id, prev.id));
          summary.dashboards.upserted++;
        } else {
          summary.dashboards.untouched++;
        }
      }
    }

    // 2) Upsert Queries (keyed by query_uid)
    const existingQueries = await trx.select().from(tQueries);
    const uidToExisting = new Map(existingQueries.map((q) => [q.queryUid, q]));
    const presetQueryUidSet = new Set<string>();
    const presetQueryIdToRealId = new Map<string, string>(); // preset Query.id -> DB id

    for (const q of queries) {
      const uid = q.queryUid; // external UID from your arrays
      presetQueryUidSet.add(uid);
      const prev = uidToExisting.get(uid as any);
      if (!prev) {
        const [row] = await trx
          .insert(tQueries)
          .values({
            queryUid: uid as any,
            description: q.description ?? null,
          })
          .returning();
        if (row) {
          summary.queries.upserted++;
          presetQueryIdToRealId.set(q.id, row.id);
        }
      } else {
        presetQueryIdToRealId.set(q.id, prev.id);
        const needsUpdate =
          (q.description ?? null) !== (prev.description ?? null);
        if (needsUpdate) {
          await trx
            .update(tQueries)
            .set({ description: q.description ?? null })
            .where(eq(tQueries.id, prev.id));
          summary.queries.upserted++;
        } else {
          summary.queries.untouched++;
        }
      }
    }

    // 3) Upsert Dashboard Items (keyed by unique (dashboard_id, query_id))
    //    Also track for pruning per dashboard.
    const allItems = await trx.select().from(tItems);
    // Build a multimap of existing items by dashId
    const existingByDash = new Map<string, typeof allItems>();
    for (const it of allItems) {
      const arr = existingByDash.get(it.dashboardId) || [];
      arr.push(it);
      existingByDash.set(it.dashboardId, arr);
    }

    // Create/Add/Update items
    for (const it of dashboardItems) {
      const dashId = legacyIdToNewId.get(it.dashboardId);
      const qPreset = queries.find((q) => q.id === it.queryId);
      if (!dashId || !qPreset) {
        // If preset references unknown dashboard or query, skip
        continue;
      }
      const qDbId = presetQueryIdToRealId.get(qPreset.id)!;

      // Try to find existing row for (dashboard_id, query_id)
      const existingForDash = existingByDash.get(dashId) || [];
      const prev = existingForDash.find((row) => row.queryId === qDbId);

      const position = it.position ?? 0;

      if (!prev) {
        const [row] = await trx
          .insert(tItems)
          .values({
            dashboardId: dashId as any,
            queryId: qDbId as any,
            name: it.name ?? null,
            description: it.description ?? null,
            itemType: it.itemType,
            chartType: it.chartType ?? null,
            position,
          })
          .onConflictDoNothing() // also protected by unique (dashboard_id, query_id)
          .returning();
        if (row) summary.items.upserted++;
        // Keep local map in sync to help pruning logic
        const arr = existingByDash.get(dashId) || [];
        if (row) arr.push(row);
        existingByDash.set(dashId, arr);
      } else {
        // Update if anything changed
        const needsUpdate =
          (it.name ?? null) !== (prev.name ?? null) ||
          (it.description ?? null) !== (prev.description ?? null) ||
          (it.chartType ?? null) !== (prev.chartType ?? null) ||
          it.itemType !== prev.itemType ||
          position !== (prev.position ?? 0);

        if (needsUpdate) {
          await trx
            .update(tItems)
            .set({
              name: it.name ?? null,
              description: it.description ?? null,
              itemType: it.itemType,
              chartType: it.chartType ?? null,
              position,
            })
            .where(eq(tItems.id, prev.id));
          summary.items.upserted++;
        } else {
          summary.items.untouched++;
        }
      }
    }

    // 4) Prune (optional)
    if (
      OPTIONS.mode === "prune-per-dashboard" ||
      OPTIONS.mode === "prune-global"
    ) {
      // Per dashboard: remove items not present in preset for that dashboard
      const presetByDash = new Map<string, Set<string>>(); // dashDbId -> set(queryDbId)
      for (const it of dashboardItems) {
        const dashDbId = legacyIdToNewId.get(it.dashboardId);
        const qPreset = queries.find((q) => q.id === it.queryId);
        if (!dashDbId || !qPreset) continue;
        const qDbId = presetQueryIdToRealId.get(qPreset.id)!;
        const set = presetByDash.get(dashDbId) || new Set<string>();
        set.add(qDbId);
        presetByDash.set(dashDbId, set);
      }

      for (const [dashDbId, existing] of existingByDash.entries()) {
        const keepSet = presetByDash.get(dashDbId) || new Set<string>();
        const toDelete = existing.filter((row) => !keepSet.has(row.queryId));
        if (toDelete.length > 0) {
          const ids = toDelete.map((r) => r.id);
          const res = await trx
            .delete(tItems)
            .where(inArray(tItems.id, ids as any));
          summary.items.deleted += res.length ?? 0;
        }
      }

      if (OPTIONS.mode === "prune-global") {
        // Dashboards not in presets
        const keepSlugs = new Set(dashboards.map((d) => d.slug));
        const unwantedDash = existingDash.filter((d) => !keepSlugs.has(d.slug));
        if (unwantedDash.length > 0) {
          const ids = unwantedDash.map((d) => d.id);
          const res = await trx
            .delete(tDashboards)
            .where(inArray(tDashboards.id, ids as any));
          summary.dashboards.deleted += res.length ?? 0;
        }

        // Queries not in presets (by queryUid)
        const keepUids = new Set(queries.map((q) => q.queryUid));
        const unwantedQueries = existingQueries.filter(
          (q) => !keepUids.has(q.queryUid),
        );
        if (unwantedQueries.length > 0) {
          const ids = unwantedQueries.map((q) => q.id);
          const res = await trx
            .delete(tQueries)
            .where(inArray(tQueries.id, ids as any));
          summary.queries.deleted += res.length ?? 0;
        }
      }
    }
  });

  const ms = Date.now() - started;
  console.log(
    `[presets] done in ${ms}ms\n` +
      `  dashboards: upserted=${summary.dashboards.upserted}, untouched=${summary.dashboards.untouched}, deleted=${summary.dashboards.deleted}\n` +
      `  queries:    upserted=${summary.queries.upserted}, untouched=${summary.queries.untouched}, deleted=${summary.queries.deleted}\n` +
      `  items:      upserted=${summary.items.upserted}, untouched=${summary.items.untouched}, deleted=${summary.items.deleted}`,
  );
}

main().catch((err) => {
  console.error("[presets] failed:", err);
  process.exit(1);
});
