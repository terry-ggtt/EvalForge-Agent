import {
  useQuery,
} from "@tanstack/react-query";

import {
  getHealth,
} from "../api/health";

import {
  getExperiments,
} from "../api/experiments";


export function DashboardPage() {

  const healthQuery =
    useQuery({
      queryKey:
        ["health"],

      queryFn:
        getHealth,
    });


  const experimentsQuery =
    useQuery({
      queryKey:
        ["experiments"],

      queryFn:
        () =>
          getExperiments(100),
    });


  const backendHealthy =
    healthQuery
      .data
      ?.status
    === "ok";


  const experimentCount =
    experimentsQuery
      .data
      ?.count
    ?? 0;


  return (
    <div
      className="
        p-8
      "
    >
      <div>
        <h1
          className="
            text-2xl
            font-semibold
          "
        >
          Agent Evaluation Harness
        </h1>

        <p
          className="
            mt-1
            text-sm
            text-slate-500
          "
        >
          Evaluation Platform
        </p>
      </div>


      <div
        className="
          mt-8
          grid
          gap-4
          md:grid-cols-3
        "
      >

        <section
          className="
            rounded-xl
            border
            border-slate-200
            bg-white
            p-5
          "
        >
          <p
            className="
              text-sm
              text-slate-500
            "
          >
            Backend
          </p>

          <p
            className="
              mt-3
              text-2xl
              font-semibold
            "
          >
            {
              healthQuery.isLoading
                ? "Checking..."
                : backendHealthy
                  ? "Healthy"
                  : "Unavailable"
            }
          </p>
        </section>


        <section
          className="
            rounded-xl
            border
            border-slate-200
            bg-white
            p-5
          "
        >
          <p
            className="
              text-sm
              text-slate-500
            "
          >
            Experiments
          </p>

          <p
            className="
              mt-3
              text-2xl
              font-semibold
            "
          >
            {
              experimentsQuery.isLoading
                ? "..."
                : experimentCount
            }
          </p>
        </section>


        <section
          className="
            rounded-xl
            border
            border-slate-200
            bg-white
            p-5
          "
        >
          <p
            className="
              text-sm
              text-slate-500
            "
          >
            Platform
          </p>

          <p
            className="
              mt-3
              text-2xl
              font-semibold
            "
          >
            V0.12
          </p>
        </section>

      </div>


      {
        experimentsQuery.isError
        && (
          <div
            className="
              mt-6
              rounded-xl
              border
              border-red-200
              bg-red-50
              p-4
              text-sm
              text-red-700
            "
          >
            Failed to load experiments.
          </div>
        )
      }

    </div>
  );
}