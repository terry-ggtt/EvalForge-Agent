import {
  NavLink,
  Outlet,
} from "react-router";


const navigation = [
  {
    label: "Dashboard",
    path: "/",
  },
  {
    label: "Experiments",
    path: "/experiments",
  },
  {
    label: "Runs",
    path: "/runs",
  },
  {
    label: "Comparison",
    path: "/comparison",
  },
  {
    label: "Regression Gate",
    path: "/gate",
  },
];


export function AppShell() {

  return (
    <div
      className="
        min-h-screen
        bg-slate-50
        text-slate-900
      "
    >

      <header
        className="
          border-b
          border-slate-200
          bg-white
        "
      >
        <div
          className="
            mx-auto
            flex
            max-w-7xl
            items-center
            justify-between
            px-6
            py-4
          "
        >

          <div>
            <h1
              className="
                text-lg
                font-semibold
              "
            >
              Agent Evaluation Harness
            </h1>

            <p
              className="
                text-sm
                text-slate-500
              "
            >
              Evaluation Platform
            </p>
          </div>


          <div
            className="
              rounded-full
              border
              border-slate-200
              px-3
              py-1
              text-xs
              text-slate-500
            "
          >
            Frontend V0.1
          </div>

        </div>
      </header>


      <div
        className="
          mx-auto
          grid
          max-w-7xl
          grid-cols-[220px_1fr]
          gap-8
          px-6
          py-8
        "
      >

        <aside>

          <nav
            className="
              flex
              flex-col
              gap-1
            "
          >

            {
              navigation.map(
                (
                  item
                ) => (

                  <NavLink
                    key={
                      item.path
                    }

                    to={
                      item.path
                    }

                    end={
                      item.path
                      === "/"
                    }

                    className={(
                      {
                        isActive,
                      }
                    ) =>
                      [
                        "rounded-lg",
                        "px-3",
                        "py-2",
                        "text-sm",
                        "font-medium",

                        isActive
                          ? (
                            "bg-slate-900 "
                            + "text-white"
                          )
                          : (
                            "text-slate-600 "
                            + "hover:bg-slate-100"
                          ),
                      ]
                      .join(" ")
                    }
                  >
                    {
                      item.label
                    }
                  </NavLink>

                )
              )
            }

          </nav>

        </aside>


        <main
          className="
            min-w-0
          "
        >
          <Outlet />
        </main>

      </div>

    </div>
  );
}