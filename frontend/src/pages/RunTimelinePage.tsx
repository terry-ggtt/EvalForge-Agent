import {
  useQuery,
} from "@tanstack/react-query";

import {
  Link,
  useParams,
} from "react-router";

import {
  getRunTimeline,
} from "../api/runs";


export function RunTimelinePage() {

  const {
    runId,
  } = useParams<{
    runId: string;
  }>();


  const query =
    useQuery({
      queryKey: [
        "run-timeline",
        runId,
      ],

      queryFn:
        () =>
          getRunTimeline(
            runId!
          ),

      enabled:
        Boolean(
          runId
        ),
    });


  if (
    query.isLoading
  ) {
    return (
      <div
        className="
          text-sm
          text-slate-500
        "
      >
        Loading timeline...
      </div>
    );
  }


  if (
    query.isError
    || !query.data
  ) {
    return (
      <div
        className="
          rounded-xl
          border
          border-red-200
          bg-red-50
          p-4
          text-sm
          text-red-700
        "
      >
        Failed to load timeline.
      </div>
    );
  }


  const timeline =
    query.data;


  return (
    <div
      className="
        space-y-8
      "
    >

      <div>

        <Link
          to={
            `/runs/${timeline.run_id}`
          }

          className="
            text-sm
            text-slate-500
            hover:underline
          "
        >
          ← Run Detail
        </Link>


        <h2
          className="
            mt-2
            text-2xl
            font-semibold
          "
        >
          Run Timeline
        </h2>


        <p
          className="
            mt-1
            text-sm
            text-slate-500
          "
        >
          Duration:{" "}
          {
            timeline.duration_ms
          } ms
        </p>

      </div>


      <div
        className="
          space-y-3
        "
      >

        {
          timeline.events.map(
            event => (

              <div
                key={
                  event.sequence
                }

                className="
                  grid
                  grid-cols-[100px_1fr]
                  gap-5
                "
              >

                <div
                  className="
                    pt-4
                    text-right
                  "
                >

                  <p
                    className="
                      text-sm
                      font-medium
                    "
                  >
                    +{
                      event.relative_ms
                    } ms
                  </p>

                  <p
                    className="
                      mt-1
                      text-xs
                      text-slate-400
                    "
                  >
                    Δ {
                      event.delta_ms
                    } ms
                  </p>

                </div>


                <div
                  className="
                    rounded-xl
                    border
                    border-slate-200
                    bg-white
                    p-5
                  "
                >

                  <div
                    className="
                      flex
                      items-center
                      justify-between
                      gap-4
                    "
                  >

                    <div>

                      <p
                        className="
                          font-semibold
                        "
                      >
                        {
                          event.event_type
                        }
                      </p>

                      {
                        event.attempt_id
                        && (
                          <p
                            className="
                              mt-1
                              text-xs
                              text-slate-500
                            "
                          >
                            Attempt:{" "}
                            {
                              event.attempt_id
                            }
                          </p>
                        )
                      }

                    </div>


                    <span
                      className="
                        text-xs
                        text-slate-400
                      "
                    >
                      #{
                        event.sequence
                      }
                    </span>

                  </div>


                  {
                    Object.keys(
                      event.payload
                    ).length
                    > 0
                    && (
                      <pre
                        className="
                          mt-4
                          overflow-x-auto
                          rounded-lg
                          bg-slate-50
                          p-4
                          text-xs
                        "
                      >
                        {
                          JSON.stringify(
                            event.payload,
                            null,
                            2,
                          )
                        }
                      </pre>
                    )
                  }

                </div>

              </div>

            )
          )
        }

      </div>

    </div>
  );
}