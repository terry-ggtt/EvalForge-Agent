import {
  useQuery,
} from "@tanstack/react-query";

import {
  Link,
  useParams,
} from "react-router";

import {
  getRun,
} from "../api/runs";


export function RunDetailPage() {

  const {
    runId,
  } = useParams<{
    runId: string;
  }>();


  const query =
    useQuery({
      queryKey: [
        "run",
        runId,
      ],

      queryFn:
        () =>
          getRun(
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
        Loading run...
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
        Failed to load run.
      </div>
    );
  }


  const run =
    query.data;


  return (
    <div
      className="
        space-y-8
      "
    >

      <div
        className="
          flex
          items-start
          justify-between
          gap-4
        "
      >

        <div>

          <Link
            to="/runs"

            className="
              text-sm
              text-slate-500
              hover:underline
            "
          >
            ← Runs
          </Link>

          <h2
            className="
              mt-2
              text-2xl
              font-semibold
            "
          >
            Run Detail
          </h2>

          <p
            className="
              mt-1
              break-all
              text-sm
              text-slate-500
            "
          >
            {run.run_id}
          </p>

        </div>


        <Link
          to={
            `/runs/${run.run_id}/timeline`
          }

          className="
            rounded-lg
            bg-slate-900
            px-4
            py-2
            text-sm
            font-medium
            text-white
          "
        >
          View Timeline
        </Link>

      </div>


      <div
        className="
          grid
          gap-4
          md:grid-cols-4
        "
      >

        <InfoCard
          label="Status"
          value={
            run.status
          }
        />

        <InfoCard
          label="Case"
          value={
            run.case.id
            ?? "-"
          }
        />

        <InfoCard
          label="Score"
          value={
            String(
              run.result.score
            )
          }
        />

        <InfoCard
          label="Metrics"
          value={
            String(
              run
                .result
                .metrics
                .length
            )
          }
        />

      </div>


      <section
        className="
          rounded-xl
          border
          border-slate-200
          bg-white
          p-6
        "
      >

        <h3
          className="
            font-semibold
          "
        >
          Test Case
        </h3>


        <div
          className="
            mt-5
            space-y-5
          "
        >

          <TextBlock
            label="Input"
            value={
              run.case.input_text
            }
          />

          <TextBlock
            label="Expected Output"
            value={
              run
                .case
                .expected_output
            }
          />

          <TextBlock
            label="Actual Output"
            value={
              run
                .result
                .actual_output
              ?? "-"
            }
          />

        </div>

      </section>


      <section
        className="
          rounded-xl
          border
          border-slate-200
          bg-white
        "
      >

        <div
          className="
            border-b
            border-slate-200
            px-6
            py-4
          "
        >
          <h3
            className="
              font-semibold
            "
          >
            Metrics
          </h3>
        </div>


        <table
          className="
            w-full
            text-left
            text-sm
          "
        >

          <thead
            className="
              bg-slate-50
              text-slate-500
            "
          >

            <tr>

              <th className="px-6 py-3">
                Metric
              </th>

              <th className="px-6 py-3">
                Score
              </th>

              <th className="px-6 py-3">
                Value
              </th>

              <th className="px-6 py-3">
                Unit
              </th>

            </tr>

          </thead>


          <tbody>

            {
              run.result.metrics.map(
                metric => (

                  <tr
                    key={
                      metric.name
                    }

                    className="
                      border-t
                      border-slate-100
                    "
                  >

                    <td
                      className="
                        px-6
                        py-3
                        font-medium
                      "
                    >
                      {
                        metric.name
                      }
                    </td>

                    <td className="px-6 py-3">
                      {
                        metric.score
                        ?? "-"
                      }
                    </td>

                    <td className="px-6 py-3">
                      {
                        metric.value
                        ?? "-"
                      }
                    </td>

                    <td className="px-6 py-3">
                      {
                        metric.unit
                        ?? "-"
                      }
                    </td>

                  </tr>

                )
              )
            }

          </tbody>

        </table>

      </section>


      {
        run.result.error
        && (
          <section
            className="
              rounded-xl
              border
              border-red-200
              bg-red-50
              p-5
            "
          >
            <h3
              className="
                font-semibold
                text-red-800
              "
            >
              Error
            </h3>

            <p
              className="
                mt-2
                text-sm
                text-red-700
              "
            >
              {
                run.result.error
              }
            </p>
          </section>
        )
      }

    </div>
  );
}


function InfoCard(
  {
    label,
    value,
  }: {
    label: string;
    value: string;
  }
) {

  return (
    <div
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
        {label}
      </p>

      <p
        className="
          mt-2
          break-all
          font-semibold
        "
      >
        {value}
      </p>

    </div>
  );
}


function TextBlock(
  {
    label,
    value,
  }: {
    label: string;
    value: string;
  }
) {

  return (
    <div>

      <p
        className="
          text-sm
          font-medium
          text-slate-500
        "
      >
        {label}
      </p>

      <div
        className="
          mt-2
          whitespace-pre-wrap
          rounded-lg
          bg-slate-50
          p-4
          text-sm
        "
      >
        {value}
      </div>

    </div>
  );
}