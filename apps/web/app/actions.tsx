"use server";

import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { getUserAuthSession } from "@/app/lib/authUser";
import { sendEmail } from "@/app/lib/awsSes";
import {
  createLinkedUserSession,
  createUserRequest,
  createUserRequestFromQuery,
  createUserSession,
  getAllUserRequestsForSession,
  getQuery,
  getSingleUserRequest,
  getUserSessions,
  updateUserRequest,
  updateUserSession,
} from "@/app/lib/gptAPI";
import {
  attachQueryToDashboard,
  attachQueryToUserDashboard,
  changeDefaultView,
  detachQueryFromDashboard,
  ensureUserAndDashboard,
} from "@/app/lib/payload";

const byTime = (a: any, b: any) =>
  new Date(b.created_at).getTime() - new Date(a.created_at).getTime();

// ApeGPT API

export const getSessions = async () => getUserSessions();

export const createSession = async ({ name, tags }: any) => {
  const res = await createUserSession({ name, tags });
  revalidatePath("/query/[id]", "page");
  return res;
};

export const createSessionWithWelcome = async ({ name, tags }: any) => {
  const session = await createUserSession({ name, tags });
  if (session) {
    // Initialize with /new request
    await createUserRequest({
      sessionId: session.session_id,
      request: "/new",
      requestType: "discovery",
      flow: "Interactive",
      model: "OpenAI",
      db: "V2",
      refs: null,
      queryId: null,
    });
  }
  revalidatePath("/query/[id]", "page");
  return session;
};

export const createLinkedSession = async ({
  name,
  tags,
  parentId,
  flow,
  request,
  model,
  db,
  refs,
}: any) => {
  const res = await createLinkedUserSession({
    name,
    tags,
    parentId,
    flow,
    request,
    model,
    db,
    refs,
  });
  revalidatePath("/query/[id]", "page");
  return res;
};

export const getOrCreateSession = async ({ name, tags }: any) => {
  try {
    const sessions = await getUserSessions();
    if (!sessions || sessions.length === 0) {
      const res = await createSession({ name, tags });
      revalidatePath("/", "page");
      return res;
    }
    return sessions.sort(byTime)?.[0];
  } catch (e) {
    console.error(e);
    return null;
  }
};

export const updateSession = async ({ sessionId, name, tags }: any) => {
  await updateUserSession({ sessionId, name, tags });
  revalidatePath("/query/[id]", "page");
};

export const createRequest = async ({
  sessionId,
  request,
  requestType,
  flow,
  model,
  refs,
  db,
  queryId,
}: any) => {
  try {
    return await createUserRequest({
      sessionId,
      request,
      requestType,
      flow,
      model,
      db,
      refs,
      queryId,
    });
  } catch (e) {
    console.error(e);
    return redirect("/login?returnTo=/?error=access_denied");
  }
};

export const createRequestFromQuery = async ({
  sessionId,
  queryId,
}: {
  sessionId: string;
  queryId: string;
}) => {
  try {
    return await createUserRequestFromQuery({
      sessionId,
      queryId,
    });
  } catch (e) {
    console.error(e);
    return redirect("/login?returnTo=/?error=access_denied");
  }
};

export const updateRequest = async ({ sessionId, requestId, data }: any) => {
  await updateUserRequest({ requestId, data });
  // revalidatePath("/", "layout");
  if (sessionId) {
    console.log("revalidatePath", `/grid/${sessionId}`);
    // console.log("revalidatePath", `/query/${sessionId}`, `/grid/${sessionId}`);
    // revalidatePath(`/query/${sessionId}`, "page");
    revalidatePath(`/grid/${sessionId}`, "page");
  }
};

export const getSingleRequest = async ({ sessionId, seqNum }: any) => {
  const res = await getSingleUserRequest({ sessionId, seqNum });
  return res;
};

export const getAllRequests = async ({ sessionId }: any) =>
  getAllUserRequestsForSession({ sessionId });

export const requestAccess = async ({
  email,
  name,
  description,
}: {
  email: string;
  name: string;
  description: string;
}) => {
  console.log("Requesting access", email, name, description);
  const res = await sendEmail(email, name, description);
  console.log("Email sent", res);
  return res;
};

export const updatePage = async ({ sessionId }: any) => {
  console.log("refreshPage", `/query/${sessionId}`);
  revalidatePath(`/query/${sessionId}`, "page");
};

export const getUserAuth = async () => {
  console.log("get auth");
  return getUserAuthSession().then((r) => r?.user);
};

export const getQueryById = async (id: string) => getQuery({ queryId: id });

// app/actions/ensure-session.ts

export const ensureSession = async () => {
  // Try Auth0 session first, fall back to guest cookie
  const { getSession } = await import("@auth0/nextjs-auth0");
  const { auth0SubToUuid } = await import("@/app/lib/userIdUtils");
  const authSession = await getSession();

  let sid: string | undefined;
  if (authSession?.user?.sub) {
    // Authenticated user - convert Auth0 ID to UUID v5
    sid = auth0SubToUuid(authSession.user.sub);
    console.log("Auth user converted:", authSession.user.sub, "→", sid);
  } else {
    // Guest user - use guest JWT cookie
    sid = cookies().get("uid")?.value;
  }

  const { userId, dashboardId, uid } = await ensureUserAndDashboard({ sid });
  console.log("ensuring session, sid:", userId, dashboardId);

  return { uid, dashboardId, userId };
};

export const addQueryToDashboard = async ({
  queryUid,
  itemType = "table",
}: {
  queryUid: string;
  itemType?: "table" | "chart";
}) => {
  const { uid, dashboardId, userId } = await ensureSession();
  console.log("addQueryToDashboard", { uid, dashboardId, queryUid });
  if (!dashboardId) throw new Error("No dashboardId");
  if (!queryUid) throw new Error("No queryId");

  await attachQueryToDashboard({ dashboardId, queryUid, itemType });

  revalidatePath(`/user/${userId}`, "page");
};

export const addQueryToUserDashboard = async ({
  queryUid,
  itemType = "table",
  name,
}: {
  queryUid: string;
  itemType?: "table" | "chart";
  name?: string;
}) => {
  const { uid, userId } = await ensureSession();
  console.log("addQueryToUserDashboard", { uid, queryUid, userId, name });
  if (!uid) throw new Error("No user");
  if (!queryUid) throw new Error("No queryId");

  await attachQueryToUserDashboard({ userId: uid, queryUid, itemType, name });

  revalidatePath(`/user/${userId}`, "page");
  return `/user/${userId}`;
};

export const editDefaultItemView = async ({
  itemId,
  itemType,
  chartType,
}: {
  itemId: string;
  itemType: "table" | "chart";
  chartType?: string;
}) => {
  const { uid, dashboardId } = await ensureSession();
  console.log("editDefaultItemView", { uid, itemId });
  // if (!dashboardId) throw new Error("No dashboardId");

  await changeDefaultView({ itemId, itemType, chartType });

  revalidatePath(`/user/${uid}`, "page");
};

export const deleteQueryFromDashboard = async ({
  itemUid,
  queryUid,
}: {
  itemUid: string;
  queryUid: string;
}) => {
  const { uid, dashboardId, userId } = await ensureSession();
  console.log("deleteQueryFromDashboard", { uid, dashboardId, queryUid });
  if (!dashboardId) throw new Error("No dashboardId");
  // if (!queryUid) throw new Error("No queryId");

  await detachQueryFromDashboard(dashboardId, queryUid, itemUid);

  revalidatePath(`/user/${userId}`, "page");
};
