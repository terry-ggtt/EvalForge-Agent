import {
  useState,
} from "react";

import {
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

import {
  useNavigate,
} from "react-router";

import {
  runExperiment,
} from "../api/experiments";

import type {
  ExperimentTestCase,
  RunExperimentRequest,
} from "../types/api";


function createEmptyCase(
  index: number,
): ExperimentTestCase {

  return {
    id:
      `case-${index}`,

    input_text:
      "",

    expected_output:
      "",

    expected_tool_calls:
      null,

    metadata:
      {},
  };
}


export function RunExperimentPage() {

  const navigate =
    useNavigate();

  const queryClient =
    useQueryClient();


  const [
    name,
    setName,
  ] = useState(
    "frontend-smoke-test"
  );


  const [
    datasetVersion,
    setDatasetVersion,
  ] = useState(
    "demo-dataset-v1"
  );


  const [
    agentVersion,
    setAgentVersion,
  ] = useState(
    "demo-agent-v1"
  );


  const [
    modelName,
    setModelName,
  ] = useState(
    "demo"
  );


  const [
    promptVersion,
    setPromptVersion,
  ] = useState(
    "prompt-v1"
  );


  const [
    cases,
    setCases,
  ] = useState<
    ExperimentTestCase[]
  >([
    createEmptyCase(1),
  ]);


  const mutation =
    useMutation({

      mutationFn:
        runExperiment,

      onSuccess:
        async (
          experiment
        ) => {

          await queryClient
            .invalidateQueries({
              queryKey:
                ["experiments"],
            });


          navigate(
            "/experiments",
            {
              state: {
                createdExperiment:
                  experiment,
              },
            },
          );
        },
    });


  function updateCase(
    index: number,
    field:
      "id"
      | "input_text"
      | "expected_output",
    value: string,
  ) {

    setCases(
      current =>
        current.map(
          (
            item,
            itemIndex,
          ) => {

            if (
              itemIndex
              !== index
            ) {

              return item;
            }


            return {
              ...item,

              [field]:
                value,
            };
          }
        )
    );
  }


  function addCase() {

    setCases(
      current => [
        ...current,

        createEmptyCase(
          current.length
          + 1
        ),
      ]
    );
  }


  function removeCase(
    index: number,
  ) {

    setCases(
      current =>
        current.filter(
          (
            _,
            itemIndex,
          ) =>
            itemIndex
            !== index
        )
    );
  }


  function handleSubmit(
    event:
      React.FormEvent<
        HTMLFormElement
      >,
  ) {

    event.preventDefault();


    const request:
      RunExperimentRequest
      = {

        name:
          name.trim(),

        dataset_version:
          datasetVersion.trim(),

        agent_version:
          agentVersion.trim(),

        model_name:
          modelName.trim()
          || null,

        prompt_version:
          promptVersion.trim()
          || null,

        metadata: {
          source:
            "frontend-v0.1",
        },

        cases:
          cases.map(
            item => ({
              ...item,

              id:
                item.id.trim(),

              input_text:
                item
                  .input_text
                  .trim(),

              expected_output:
                item
                  .expected_output
                  .trim(),
            })
          ),
      };


    mutation.mutate(
      request
    );
  }


  return (
    <div
      className="
        space-y-8
      "
    >

      <div>
        <h2
          className="
            text-2xl
            font-semibold
          "
        >
          Run Experiment
        </h2>

        <p
          className="
            mt-1
            text-sm
            text-slate-500
          "
        >
          Execute a dataset against
          the configured agent.
        </p>
      </div>


      <form
        onSubmit={
          handleSubmit
        }

        className="
          space-y-8
        "
      >

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
            Experiment Configuration
          </h3>


          <div
            className="
              mt-5
              grid
              gap-5
              md:grid-cols-2
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
                Name
              </span>

              <input
                required

                value={
                  name
                }

                onChange={
                  event =>
                    setName(
                      event
                        .target
                        .value
                    )
                }

                className="
                  w-full
                  rounded-lg
                  border
                  border-slate-300
                  px-3
                  py-2
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
                Dataset Version
              </span>

              <input
                required

                value={
                  datasetVersion
                }

                onChange={
                  event =>
                    setDatasetVersion(
                      event
                        .target
                        .value
                    )
                }

                className="
                  w-full
                  rounded-lg
                  border
                  border-slate-300
                  px-3
                  py-2
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
                Agent Version
              </span>

              <input
                required

                value={
                  agentVersion
                }

                onChange={
                  event =>
                    setAgentVersion(
                      event
                        .target
                        .value
                    )
                }

                className="
                  w-full
                  rounded-lg
                  border
                  border-slate-300
                  px-3
                  py-2
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
                Model
              </span>

              <input
                value={
                  modelName
                }

                onChange={
                  event =>
                    setModelName(
                      event
                        .target
                        .value
                    )
                }

                className="
                  w-full
                  rounded-lg
                  border
                  border-slate-300
                  px-3
                  py-2
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
                Prompt Version
              </span>

              <input
                value={
                  promptVersion
                }

                onChange={
                  event =>
                    setPromptVersion(
                      event
                        .target
                        .value
                    )
                }

                className="
                  w-full
                  rounded-lg
                  border
                  border-slate-300
                  px-3
                  py-2
                "
              />
            </label>

          </div>

        </section>


        <section
          className="
            space-y-4
          "
        >

          <div
            className="
              flex
              items-center
              justify-between
            "
          >
            <div>
              <h3
                className="
                  font-semibold
                "
              >
                Test Cases
              </h3>

              <p
                className="
                  text-sm
                  text-slate-500
                "
              >
                Cases executed by
                the Harness.
              </p>
            </div>


            <button
              type="button"

              onClick={
                addCase
              }

              className="
                rounded-lg
                border
                border-slate-300
                bg-white
                px-4
                py-2
                text-sm
                font-medium
                hover:bg-slate-50
              "
            >
              Add Case
            </button>
          </div>


          {
            cases.map(
              (
                testCase,
                index,
              ) => (

                <div
                  key={
                    index
                  }

                  className="
                    rounded-xl
                    border
                    border-slate-200
                    bg-white
                    p-6
                  "
                >

                  <div
                    className="
                      flex
                      items-center
                      justify-between
                    "
                  >

                    <h4
                      className="
                        font-medium
                      "
                    >
                      Case {
                        index + 1
                      }
                    </h4>


                    {
                      cases.length
                      > 1
                      && (
                        <button
                          type="button"

                          onClick={
                            () =>
                              removeCase(
                                index
                              )
                          }

                          className="
                            text-sm
                            text-red-600
                          "
                        >
                          Remove
                        </button>
                      )
                    }

                  </div>


                  <div
                    className="
                      mt-5
                      space-y-4
                    "
                  >

                    <label
                      className="
                        block
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
                        required

                        value={
                          testCase.id
                        }

                        onChange={
                          event =>
                            updateCase(
                              index,
                              "id",
                              event
                                .target
                                .value,
                            )
                        }

                        className="
                          w-full
                          rounded-lg
                          border
                          border-slate-300
                          px-3
                          py-2
                        "
                      />
                    </label>


                    <label
                      className="
                        block
                        space-y-2
                      "
                    >
                      <span
                        className="
                          text-sm
                          font-medium
                        "
                      >
                        Input
                      </span>

                      <textarea
                        required

                        rows={
                          3
                        }

                        value={
                          testCase
                            .input_text
                        }

                        onChange={
                          event =>
                            updateCase(
                              index,
                              "input_text",
                              event
                                .target
                                .value,
                            )
                        }

                        className="
                          w-full
                          rounded-lg
                          border
                          border-slate-300
                          px-3
                          py-2
                        "
                      />
                    </label>


                    <label
                      className="
                        block
                        space-y-2
                      "
                    >
                      <span
                        className="
                          text-sm
                          font-medium
                        "
                      >
                        Expected Output
                      </span>

                      <textarea
                        required

                        rows={
                          3
                        }

                        value={
                          testCase
                            .expected_output
                        }

                        onChange={
                          event =>
                            updateCase(
                              index,
                              "expected_output",
                              event
                                .target
                                .value,
                            )
                        }

                        className="
                          w-full
                          rounded-lg
                          border
                          border-slate-300
                          px-3
                          py-2
                        "
                      />
                    </label>

                  </div>

                </div>
              )
            )
          }

        </section>


        {
          mutation.isError
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
              {
                mutation.error
                  instanceof Error

                  ? mutation
                      .error
                      .message

                  : (
                    "Experiment "
                    + "execution failed."
                  )
              }
            </div>
          )
        }


        <div
          className="
            flex
            justify-end
          "
        >

          <button
            type="submit"

            disabled={
              mutation.isPending
            }

            className="
              rounded-lg
              bg-slate-900
              px-5
              py-2.5
              text-sm
              font-medium
              text-white
              disabled:cursor-not-allowed
              disabled:opacity-50
            "
          >

            {
              mutation.isPending
                ? "Running..."
                : "Run Experiment"
            }

          </button>

        </div>

      </form>

    </div>
  );
}