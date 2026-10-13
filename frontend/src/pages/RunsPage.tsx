import {
  useState,
} from "react";

import {
  useQuery,
} from "@tanstack/react-query";

import {
  Link,
} from "react-router";

import {
  getRuns,
} from "../api/runs";

import type {
  RunStatus,
} from "../types/api";


const PAGE_SIZE = 20;


export function RunsPage() {

  const [
    caseId,
    setCaseId,
  ] = useState("");


  const [
    status,
    setStatus,
  ] = useState<
    RunStatus | ""
  >("");


  const [
    offset,
    setOffset,
  ] = useState(0);


  const query =
    useQuery({
      queryKey: [
        "runs",
        caseId,
        status,
        offset,
      ],

      queryFn:
        () =>
          getRuns({
            caseId:
              caseId.trim()
              || undefined,

            status,

            limit:
              PAGE_SIZE,

            offset,

            order:
              "started_at_desc",
          }),
    });


  const runs =
    query.data
      ?.items
    ?? [];


  const total =
    query.data
      ?.total
    ?? 0;


  const hasPrevious =
    offset > 0;


  const hasNext =
    offset
    + PAGE_SIZE
    < total;


  return (
    <div
      className="
        space-y-6
      "
    >

      <div>

        <h2
          className="
            text-2xl
            font-semibold
          "
        >
          Runs
        </h2>

        <p
          className="
            mt-1
            text-sm
            text-slate-500
          "
        >
          Search and inspect individual
          evaluation runs.
        </p>

      </div>


      <div
        className="
          grid
          gap-4
          rounded-xl
          border
          border-slate-200
          bg-white
          p-5
          md:grid-cols-3
        "
      >

        <label
          className="
            space-y-2
          "
        >

          <span
            className="
              text-sm
              font-medium
            "
          >
            Case ID
          </span>

          <input
            value={
              caseId
            }

            onChange={
              event => {
                setCaseId(
                  event
                    .target
                    .value
                );

                setOffset(0);
              }
            }

            placeholder="case-001"

            className="
              w-full
              rounded-lg
              border
              border-slate-300
              px-3
              py-2
              text-sm
            "
          />

        </label>


        <label
          className="
            space-y-2
          "
        >

          <span
            className="
              text-sm
              font-medium
            "
          >
            Status
          </span>

          <select
            value={
              status
            }

            onChange={
              event => {
                setStatus(
                  event
                    .target
                    .value as RunStatus | ""
                );

                setOffset(0);
              }
            }

            className="
              w-full
              rounded-lg
              border
              border-slate-300
              px-3
              py-2
              text-sm
            "
          >

            <option value="">
              All
            </option>

            <option value="succeeded">
              Succeeded
            </option>

            <option value="failed">
              Failed
            </option>

            <option value="timed_out">
              Timed Out
            </option>

          </select>

        </label>


        <div
          className="
            flex
            items-end
          "
        >

          <div
            className="
              text-sm
              text-slate-500
            "
          >
            Total:{" "}
            <span
              className="
                font-medium
                text-slate-900
              "
            >
              {total}
            </span>
          </div>

        </div>

      </div>


      {
        query.isLoading
        && (
          <div
            className="
              text-sm
              text-slate-500
            "
          >
            Loading runs...
          </div>
        )
      }


      {
        query.isError
        && (
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
            Failed to load runs.
          </div>
        )
      }


      {
        !query.isLoading
        && !query.isError
        && (
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
                    Run ID
                  </th>

                  <th className="px-4 py-3">
                    Case
                  </th>

                  <th className="px-4 py-3">
                    Status
                  </th>

                  <th className="px-4 py-3">
                    Score
                  </th>

                  <th className="px-4 py-3">
                    Started
                  </th>

                </tr>

              </thead>


              <tbody>

                {
                  runs.map(
                    run => (

                      <tr
                        key={
                          run.run_id
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

                          <Link
                            to={
                              `/runs/${run.run_id}`
                            }

                            className="
                              hover:underline
                            "
                          >
                            {
                              run.run_id
                            }
                          </Link>

                        </td>


                        <td
                          className="
                            px-4
                            py-3
                            text-slate-600
                          "
                        >
                          {
                            run.case_id
                            ?? "-"
                          }
                        </td>


                        <td
                          className="
                            px-4
                            py-3
                          "
                        >
                          {
                            run.status
                          }
                        </td>


                        <td
                          className="
                            px-4
                            py-3
                          "
                        >
                          {
                            run.score
                            ?? "-"
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
                              run.started_at
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
              runs.length
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
                  No runs found.
                </div>
              )
            }

          </div>
        )
      }


      <div
        className="
          flex
          items-center
          justify-between
        "
      >

        <button
          type="button"

          disabled={
            !hasPrevious
          }

          onClick={
            () =>
              setOffset(
                current =>
                  Math.max(
                    0,
                    current
                    - PAGE_SIZE,
                  )
              )
          }

          className="
            rounded-lg
            border
            border-slate-300
            bg-white
            px-4
            py-2
            text-sm
            disabled:opacity-40
          "
        >
          Previous
        </button>


        <span
          className="
            text-sm
            text-slate-500
          "
        >
          {
            total === 0
              ? "0 results"
              : (
                `${offset + 1}`
                + " - "
                + `${Math.min(
                  offset
                  + PAGE_SIZE,
                  total
                )}`
                + ` of ${total}`
              )
          }
        </span>


        <button
          type="button"

          disabled={
            !hasNext
          }

          onClick={
            () =>
              setOffset(
                current =>
                  current
                  + PAGE_SIZE
              )
          }

          className="
            rounded-lg
            border
            border-slate-300
            bg-white
            px-4
            py-2
            text-sm
            disabled:opacity-40
          "
        >
          Next
        </button>

      </div>

    </div>
  );
}