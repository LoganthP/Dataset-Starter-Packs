import { MotionConfig } from "framer-motion";
import type React from "react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Link, RouterProvider } from "react-router-dom";
import Layout from "./components/Layout";
import "./index.css";

// Each page is its own chunk, loaded when first visited: the first load no longer downloads every page's code.
const page = (load: () => Promise<Record<string, unknown>>, name = "default") => async () => ({ Component: (await load())[name] as React.ComponentType });

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
    // Shown only on the very first load, while the first page's code arrives.
    hydrateFallbackElement: <div className="grid min-h-screen place-items-center text-ink-soft" role="status">Loading…</div>,
    children: [
      { path: "/", lazy: page(() => import("./pages/LandingPage")) },
      { path: "/discover", lazy: page(() => import("./pages/Discover")) },
      { path: "/packs", lazy: page(() => import("./pages/CuratedPacks")) },
      { path: "/packs/:slug", lazy: page(() => import("./pages/PackPage")) },
      { path: "/datasets/:id", lazy: page(() => import("./pages/DatasetPage")) },
      { path: "/compare", lazy: page(() => import("./pages/ComparePage")) },
      { path: "/compare/:reportId", lazy: page(() => import("./pages/ComparePage"), "ComparisonReportPage") },
      { path: "/analyses/:id", lazy: page(() => import("./pages/AnalysisPage")) },
      { path: "/datasets/:id/run", lazy: page(() => import("./pages/DatasetRunPage")) },
      { path: "/runs", lazy: page(() => import("./pages/RunsPage"), "RunsPage") },
      { path: "/runs/:id", lazy: page(() => import("./pages/RunsPage"), "RunDetailPage") },
      { path: "/sources", lazy: page(() => import("./pages/SourcesPage")) },
      { path: "/settings", lazy: page(() => import("./pages/SettingsPage")) },
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
