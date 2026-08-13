import { createRoot } from "react-dom/client";

import { App } from "./App";
import { AppRootErrorBoundary } from "./components/AppRootErrorBoundary";
import { installGlobalErrorCapture } from "./runtime/diagnostics";
import "./styles.css";

installGlobalErrorCapture();
createRoot(document.getElementById("root")!).render(<AppRootErrorBoundary><App /></AppRootErrorBoundary>);
