import { v4 as uuid } from "uuid";

import type { TChatMessage, TResponseResult } from "@/app/lib/types";

export const examples = [
  "What is Helium",
  "What is MOBILE token?",
  "What can I do with MOBILE token?",
];

export const wait = (ms = 1000) =>
  new Promise((resolve) => {
    setTimeout(resolve, ms);
  });

const text = (r: TResponseResult) => {
  const t = r.response || r.csv || r.err || r.intent || "";
  // console.log("Response text:", r.response, t);
  return t;
};

export const responseToHumanMessage = (r: any) =>
  ({
    text: r.request,
    uid: `${r.request_id}:${r.sequence_number}-req`,
    isBot: false,
    isNew: false,
    refs: r.refs,
  }) as TChatMessage;

export const responseToBotMessage = (r: TResponseResult) =>
  ({
    text: text(r),
    status: r.status || "",
    uid: `${r.request_id}`,
    sql: r.sql,
    isBot: true,
    isNew: false,
    isError: r.status === "Error",
    comment: r.review,
    rating: r.rating,
    query: r.query,
    view: r.view,
    query_plan: r.query_plan,
    isPending:
      !r.status ||
      (r.status !== "Error" &&
        r.status !== "Done" &&
        r.status !== "Cancelled" &&
        r.status !== "FeedbackRequested"),
    structuredResponse: {
      request: r.request,
      sql: r.sql,
      assumptions: r.assumptions,
      intent: r.intent,
      intro: r.intro,
      outro: r.outro,
      csv: r.csv,
      chart: r.chart,
      chart_url: r.chart_url,
      raw_data_labels: r.raw_data_labels,
      raw_data_rows: r.raw_data_rows,
      refs: r.refs,
      linked_session_id: r.linked_session_id,
    },
    isStructured:
      r.assumptions ||
      r.intent ||
      r.intro ||
      r.outro ||
      r.csv ||
      r.chart ||
      r.chart_url ||
      r.raw_data_labels ||
      r.raw_data_rows,
  }) as TChatMessage;

export const newPendingMessage = (text: string) =>
  ({
    isBot: false,
    text,
    uid: uuid(),
  }) as TChatMessage;

export const responseToPendingBotMessage = (r: TResponseResult) =>
  ({
    isBot: true,
    isPending: true,
    uid: r?.request_id,
  }) as TChatMessage;

export const internalErrorMessage = () =>
  ({
    isPending: false,
    isError: true,
    isBot: true,
    isNew: true,
    text: "*** Internal Error ***",
    uid: uuid(),
  }) as TChatMessage;

export const responseToSuccessBotMessage = (result: TResponseResult) =>
  ({
    isError: false,
    isPending: false,
    text:
      result.response ||
      result.csv ||
      result.err ||
      result.intent ||
      "*** NO RESPONSE OR TIMEOUT ***",
    uid: result.request_id,
    sql: result.sql,
    isBot: true,
    isNew: true,
    comment: result.review,
    rating: result.rating,
    status: result.status || "Done",
    query: result.query,
    view: result.view,
    query_plan: result.query_plan,
    structuredResponse: {
      request: result.request,
      sql: result.sql,
      assumptions: result.assumptions,
      intent: result.intent,
      intro: result.intro,
      outro: result.outro,
      csv: result.csv,
      chart: result.chart,
      chart_url: result.chart_url,
      raw_data_labels: result.raw_data_labels,
      raw_data_rows: result.raw_data_rows,
      refs: result.refs,
      linked_session_id: result.linked_session_id,
    },
    isStructured:
      result.assumptions ||
      result.intent ||
      result.intro ||
      result.outro ||
      result.csv ||
      result.chart ||
      result.chart_url ||
      result.raw_data_labels ||
      result.raw_data_rows,
  }) as TChatMessage;

type StatusUpdate = { status: string; [key: string]: any };

interface PollResponse {
  onStatus: (cb: (status: TResponseResult) => void) => void;
  waitForDone: Promise<TChatMessage>;
}

export const pollForResponse = (
  { sessionId, seqNum }: { sessionId: string; seqNum: number },
  interval = 1000,
  maxRetries = 30,
): PollResponse => {
  let statusCallback: (status: TResponseResult) => void = () => {};

  // eslint-disable-next-line no-async-promise-executor
  const waitForDone = new Promise<TChatMessage>(async (resolve, reject) => {
    let retries = 0;
    let consecutiveErrors = 0;
    const maxConsecutiveErrors = 3;

    try {
      // eslint-disable-next-line no-constant-condition
      while (true) {
        if (retries >= maxRetries) {
          console.error(
            `[Polling] Max retries (${maxRetries}) reached, stopping`,
          );
          reject(new Error("Polling timeout: maximum retries reached"));
          return;
        }

        try {
          // eslint-disable-next-line no-await-in-loop
          const response = await fetch(
            `/api/apegpt/message?sessionId=${sessionId}&seqNum=${seqNum}`,
          );

          if (!response.ok) {
            consecutiveErrors++;
            console.error(
              `[Polling] HTTP ${response.status}: ${response.statusText} (error ${consecutiveErrors}/${maxConsecutiveErrors})`,
            );

            if (consecutiveErrors >= maxConsecutiveErrors) {
              reject(
                new Error(
                  `API error: ${response.status} ${response.statusText}`,
                ),
              );
              return;
            }

            // Wait longer on errors with exponential backoff
            // eslint-disable-next-line no-await-in-loop
            await wait(interval * Math.pow(2, consecutiveErrors - 1));
            retries++;
            continue;
          }

          // eslint-disable-next-line no-await-in-loop
          const result: TResponseResult = await response.json();

          // Reset consecutive errors on success
          consecutiveErrors = 0;

          console.log("Polling result:", result.status);
          statusCallback(result); // emit update

          if (result.status === "Error") {
            reject(result.err);
            return;
          }

          if (
            result.status === "Done" ||
            result.status === "Cancelled" ||
            result.status === "FeedbackRequested"
          ) {
            resolve(responseToSuccessBotMessage(result));
            return;
          }

          // eslint-disable-next-line no-await-in-loop
          await wait(interval);
          retries++;
        } catch (fetchError) {
          consecutiveErrors++;
          console.error(
            `[Polling] Fetch error (${consecutiveErrors}/${maxConsecutiveErrors}):`,
            fetchError,
          );

          if (consecutiveErrors >= maxConsecutiveErrors) {
            reject(new Error("Network error: unable to reach API"));
            return;
          }

          // Wait longer on errors with exponential backoff
          // eslint-disable-next-line no-await-in-loop
          await wait(interval * Math.pow(2, consecutiveErrors - 1));
          retries++;
        }
      }
    } catch (error) {
      console.error("[Polling] Unexpected error:", error);
      reject(error);
    }
  });

  return {
    onStatus: (cb: (status: TResponseResult) => void) => {
      statusCallback = cb;
    },
    waitForDone,
  };
};
