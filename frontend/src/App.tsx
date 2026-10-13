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

import {
  RunsPage,
} from "./pages/RunsPage";

import {
  RunDetailPage,
} from "./pages/RunDetailPage";

import {
  RunTimelinePage,
} from "./pages/RunTimelinePage";
import { EvaluationJobsPage } from "./pages/EvaluationJobsPage";
import { EvaluationJobDetailPage } from "./pages/EvaluationJobDetailPage";
import { CreateEvaluationJobPage } from "./pages/CreateEvaluationJobPage";
import { ExperimentDetailPage } from "./pages/ExperimentDetailPage";

/** @returns Existing dashboard routes and asynchronous evaluation management routes. */
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
            <RunsPage />
          }
        />


        <Route
          path="runs/:runId/timeline"
          element={
            <RunTimelinePage />
          }
        />


        <Route
          path="runs/:runId"
          element={
            <RunDetailPage />
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
        <Route path="evaluation-jobs" element={<EvaluationJobsPage />} />
        <Route path="evaluation-jobs/new" element={<CreateEvaluationJobPage />} />
        <Route path="evaluation-jobs/:jobId" element={<EvaluationJobDetailPage />} />
        <Route path="experiments/:experimentId" element={<ExperimentDetailPage />} />
      </Route>

    </Routes>
  );
}


export default App;