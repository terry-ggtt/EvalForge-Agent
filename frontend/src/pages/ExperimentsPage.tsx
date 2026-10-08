import {
  useQuery,
} from "@tanstack/react-query";

import {
  Link,
} from "react-router";

import {
  getExperiments,
} from "../api/experiments";


export function ExperimentsPage() {

  const query =
    useQuery({
      queryKey:
        ["experiments"],

      queryFn:
        () =>
          getExperiments(100),
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
        Loading experiments...
      </div>
    );
  }


  if (
    query.isError
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
        Failed to load experiments.
      </div>
    );
  }


  const experiments =
    query.data
      ?.items
    ?? [];


  return (
    <div
      className="
        space-y-8
      "
    >

      {/* 页面标题 + Run Experiment 按钮 */}
      <div
        className="
          flex
          items-start
          justify-between
          gap-4
        "
      >

        <div>

          <h2
            className="
              text-2xl
              font-semibold
            "
          >
            Experiments
          </h2>

          <p
            className="
              mt-1
              text-sm
              text-slate-500
            "
          >
            Evaluation experiment history.
          </p>

        </div>


        <Link
          to="/experiments/run"

          className="
            rounded-lg
            bg-slate-900
            px-4
            py-2
            text-sm
            font-medium
            text-white
            hover:bg-slate-700
          "
        >
          Run Experiment
        </Link>

      </div>


      {/* Experiment Table */}
      <div
        className="
          overflow-hidden
          rounded-xl
          border
          border-slate-200
          bg-white
        "
      >

        <table
          className="
            w-full
            text-left
            text-sm
          "
        >

          <thead
            className="
              border-b
              border-slate-200
              bg-slate-50
              text-slate-500
            "
          >

            <tr>

              <th className="px-4 py-3">
                Name
              </th>

              <th className="px-4 py-3">
                Status
              </th>

              <th className="px-4 py-3">
                Agent
              </th>

              <th className="px-4 py-3">
                Dataset
              </th>

              <th className="px-4 py-3">
                Runs
              </th>

              <th className="px-4 py-3">
                Created
              </th>

            </tr>

          </thead>


          <tbody>

            {
              experiments.map(
                (
                  experiment
                ) => (

                  <tr
                    key={
                      experiment
                        .experiment_id
                    }

                    className="
                      border-b
                      border-slate-100
                      last:border-0
                    "
                  >

                    <td
                      className="
                        px-4
                        py-3
                        font-medium
                      "
                    >
                      {
                        experiment.name
                      }
                    </td>


                    <td
                      className="
                        px-4
                        py-3
                      "
                    >
                      {
                        experiment.status
                      }
                    </td>


                    <td
                      className="
                        px-4
                        py-3
                        text-slate-600
                      "
                    >
                      {
                        experiment
                          .agent_version
                      }
                    </td>


                    <td
                      className="
                        px-4
                        py-3
                        text-slate-600
                      "
                    >
                      {
                        experiment
                          .dataset_version
                      }
                    </td>


                    <td
                      className="
                        px-4
                        py-3
                        text-slate-600
                      "
                    >
                      {
                        experiment
                          .run_ids
                          .length
                      }
                    </td>


                    <td
                      className="
                        px-4
                        py-3
                        text-slate-600
                      "
                    >
                      {
                        new Date(
                          experiment
                            .created_at
                        )
                        .toLocaleString()
                      }
                    </td>

                  </tr>
                )
              )
            }

          </tbody>

        </table>


        {
          experiments.length
          === 0
          && (
            <div
              className="
                p-10
                text-center
                text-sm
                text-slate-500
              "
            >
              No experiments yet.
            </div>
          )
        }

      </div>

    </div>
  );
}