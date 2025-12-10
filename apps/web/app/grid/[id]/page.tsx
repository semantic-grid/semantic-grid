import { Suspense } from "react";

import { GridSessionProvider } from "@/app/contexts/GridSession";
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
import { getNewSessionWelcome, getSuggestedPrompts } from "@/app/lib/payload";
import type { SuggestedPrompt } from "@/app/lib/payload-types";
import type { TChat } from "@/app/lib/types";

import { InteractiveDashboard } from "./interactive-dashboard";

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
            m.status !== "Cancelled"),
      ),
  };
};

const InteractiveQueryPage = async ({
  params: { id },
}: {
  params: { id: string };
}) => {
  try {
    const { metadata, messages, pending, ancestors, successors } =
      await getChatMessages(id);

    // Load CMS content for new sessions (with error handling)
    let welcomeMessage: string | null = null;
    let suggestedPrompts: string[] = [];

    try {
      [welcomeMessage, suggestedPrompts] = await Promise.all([
        getNewSessionWelcome(),
        getSuggestedPrompts().then((p) =>
          p.map((p: SuggestedPrompt) => p.text),
        ),
      ]);
    } catch (error) {
      console.error("Failed to load CMS content (welcome/prompts):", error);
      // Continue rendering without welcome message/prompts
    }

    return (
      <Suspense fallback={<div>Loading messages...</div>}>
        <GridSessionProvider
          sessionId={id}
          chat={{ messages } as TChat}
          metadata={metadata}
          pendingRequest={pending as any}
          ancestors={ancestors}
          successors={successors}
        >
          <InteractiveDashboard
            key={id}
            id={id}
            metadata={metadata}
            ancestors={ancestors}
            welcomeMessage={welcomeMessage}
            suggestedPrompts={suggestedPrompts}
          />
        </GridSessionProvider>
      </Suspense>
    );
  } catch (error) {
    console.error("Failed to load grid session:", error);
    // Return error UI instead of crashing the entire page
    return (
      <div style={{ padding: "2rem", textAlign: "center" }}>
        <h2>Unable to load session</h2>
        <p>
          There was an error loading this session. Please try refreshing the
          page.
        </p>
        {error instanceof Error && (
          <details style={{ marginTop: "1rem" }}>
            <summary>Error details</summary>
            <pre
              style={{
                textAlign: "left",
                overflow: "auto",
                maxWidth: "800px",
                margin: "0 auto",
              }}
            >
              {error.message}
            </pre>
          </details>
        )}
      </div>
    );
  }
};

export default InteractiveQueryPage;
