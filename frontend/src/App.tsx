import {
  Route,
  Routes,
} from "react-router";

import {
  AppShell,
} from "./components/layout/AppShell";

import {
  DashboardPage,
} from "./pages/DashboardPage";

import {
  ExperimentsPage,
} from "./pages/ExperimentsPage";

import {
  PlaceholderPage,
} from "./pages/PlaceholderPage";

import {
  RunExperimentPage,
} from "./pages/RunExperimentPage";
function App() {

  return (
    <Routes>

      <Route
        element={
          <AppShell />
        }
      >

        <Route
          index
          element={
            <DashboardPage />
          }
        />


        <Route
          path="experiments"
          element={
            <ExperimentsPage />
          }
        />


        <Route
          path="runs"
          element={
            <PlaceholderPage
              title="Runs"
              description="Run query, detail and replay timeline."
            />
          }
        />


        <Route
          path="comparison"
          element={
            <PlaceholderPage
              title="Comparison"
              description="Compare baseline and candidate experiments."
            />
          }
        />


        <Route
          path="gate"
          element={
            <PlaceholderPage
              title="Regression Gate"
              description="Evaluate release gate policy."
            />
          }
        />

        <Route
          path="experiments/run"
          element={
            <RunExperimentPage />
          }
        />
      </Route>

    </Routes>
  );
}


export default App;