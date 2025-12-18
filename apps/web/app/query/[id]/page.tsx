import { Suspense } from "react";

import { ChatSessionProvider } from "@/app/contexts/ChatSession";
import { TutorialProvider } from "@/app/contexts/Tutorial";
import {
  responseToBotMessage,
  responseToHumanMessage,
} from "@/app/helpers/chat";
import { getUserAuthSession } from "@/app/lib/authUser";
import {
  getAllUserRequestsForSession,
  getUserSession,
  getUserSessions,
} from "@/app/lib/gptAPI";
import type { TChat } from "@/app/lib/types";
import { InteractiveDashboard } from "@/app/query/[id]/interactive-dashboard";
import AppBar from "@/app/query/app-bar";

function getAncestors(obj: any, indexById: Record<string, any>) {
  const ancestors = [];
  let current = obj;

  while (current?.parent) {
    const parent = indexById[current.parent];
    if (!parent) break;
    ancestors.push(parent);
    current = parent;
  }

  return ancestors;
}

const getChatMessages = async (id: string) => {
  const userSession = await getUserAuthSession();
  // console.log("userSession", userSession);
  /*
  if (
    !userSession ||
    (userSession.accessTokenExpiresAt || 0) * 1000 < Date.now() ||
    !userSession.accessToken
  ) {
    // Redirect to login if session is invalid
    redirect("/api/auth/login");
  }
   */

  const allUserSessions: any[] = await getUserSessions();
  // console.log("allUserSessions", allUserSessions);
  const indexById = Object.fromEntries(
    allUserSessions.map((obj: any) => [obj.session_id, obj]),
  );
  const currentObj = indexById[id];
  const ancestors = getAncestors(currentObj, indexById).toSorted(
    (s1: any, s2: any) =>
      new Date(s1.created_at).getTime() - new Date(s2.created_at).getTime(),
  );

  const currentSession = await getAllUserRequestsForSession({ sessionId: id });
  const session = await getUserSession({ sessionId: id });
  // console.log("currentSession", currentSession);
  /*
  console.log(
    "currentSession",
    session,
    allUserSessions.filter((s) => s.parent === id),
  );
   */
  const sorted = currentSession.sort(
    (a: any, b: any) => a.sequence_number - b.sequence_number,
  );
  return {
    user: userSession?.user || null,
    metadata: session?.metadata,
    ancestors:
      ancestors.length > 0
        ? [
            ...ancestors.map((a) => ({
              name: a.metadata?.summary,
              id: a.session_id,
            })),
            { name: session?.metadata?.summary, id: session?.session_id },
          ]
        : [{ name: session?.metadata?.summary, id: session?.session_id }],
    successors: allUserSessions
      .filter((s) => !s.tags?.includes("hidden"))
      .filter((s) => s.parent === id)
      .filter((s) => s.session_id !== id),
    messages: sorted
      .filter(Boolean)
      .flatMap((r: any) => [
        responseToHumanMessage(r),
        responseToBotMessage(r),
      ]),
    pending: sorted
      .slice(-1)
      .find(
        (m) =>
          !m.status ||
          (m.status !== "Done" &&
            m.status !== "Error" &&
            m.status !== "Cancelled" &&
            m.status !== "FeedbackRequested"),
      ),
  };
};

const InteractiveQueryPage = async ({
  params: { id },
}: {
  params: { id: string };
}) => {
  const { metadata, messages, pending, ancestors, successors } =
    await getChatMessages(id);
  // console.log("messages", messages);

  return (
    <Suspense fallback={<div>Loading messages...</div>}>
      <TutorialProvider id={id}>
        <ChatSessionProvider
          sessionId={id}
          chat={{ messages } as TChat}
          metadata={metadata}
          pendingRequest={pending as any}
          ancestors={ancestors}
          successors={successors}
        >
          <AppBar id={id} successors={successors} ancestors={ancestors} />
          <InteractiveDashboard
            key={id}
            id={id}
            // user={user}
            metadata={metadata}
            pendingRequest={pending}
            ancestors={ancestors}
            // successors={successors}
          />
        </ChatSessionProvider>
      </TutorialProvider>
    </Suspense>
  );
};

export default InteractiveQueryPage;
