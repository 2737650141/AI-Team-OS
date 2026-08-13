import { Component, type ErrorInfo, type ReactNode } from "react";

import { reportFrontendError } from "../runtime/diagnostics";
import { RuntimeRecoveryView } from "./RuntimeRecoveryView";

export class AppRootErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error, info: ErrorInfo) {
    void reportFrontendError("react_error", error.message, info.componentStack ?? "");
  }
  render() {
    if (this.state.failed) return <RuntimeRecoveryView kind="ui" onDiagnostics={() => {
      window.history.replaceState({}, "", "/settings");
      this.setState({ failed: false });
    }} />;
    return this.props.children;
  }
}
