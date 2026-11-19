import { MotionConfig } from "framer-motion";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Link, RouterProvider } from "react-router-dom";
import Layout from "./components/Layout";
import "./index.css";
import AnalysisPage from "./pages/AnalysisPage";
import DatasetRunPage from "./pages/DatasetRunPage";
import SettingsPage from "./pages/SettingsPage";
import ComparePage, { ComparisonReportPage } from "./pages/ComparePage";
import CuratedPacks from "./pages/CuratedPacks";
import DatasetPage from "./pages/DatasetPage";
import Discover from "./pages/Discover";
import LandingPage from "./pages/LandingPage";
import PackPage from "./pages/PackPage";
import { RunDetailPage, RunsPage } from "./pages/RunsPage";
import SourcesPage from "./pages/SourcesPage";

function NotFound() {
  return (
    <div className="glass mx-auto max-w-lg rounded-4xl p-10 text-center">
      <h1 className="text-4xl font-extrabold">Page not found</h1>
      <p className="mt-2 text-ink-soft">That address doesn't match a dataset, pack or page.</p>
      <Link className="btn-ghost mt-5" to="/discover">Go to Discover</Link>
    </div>
  );
}

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <LandingPage /> },
      { path: "/discover", element: <Discover /> },
      { path: "/packs", element: <CuratedPacks /> },
      { path: "/packs/:slug", element: <PackPage /> },
      { path: "/datasets/:id", element: <DatasetPage /> },
      { path: "/compare", element: <ComparePage /> },
      { path: "/compare/:reportId", element: <ComparisonReportPage /> },
      { path: "/analyses/:id", element: <AnalysisPage /> },
      { path: "/datasets/:id/run", element: <DatasetRunPage /> },
      { path: "/runs", element: <RunsPage /> },
      { path: "/runs/:id", element: <RunDetailPage /> },
      { path: "/sources", element: <SourcesPage /> },
      { path: "/settings", element: <SettingsPage /> },
      { path: "*", element: <NotFound /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MotionConfig reducedMotion="user">
      <RouterProvider router={router} />
    </MotionConfig>
  </StrictMode>,
);
