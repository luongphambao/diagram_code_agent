import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-surface-canvas p-8">
          <div className="max-w-md rounded-2xl border border-red-500/20 bg-red-950/20 p-6">
            <p className="mb-2 text-sm font-semibold text-red-300">Something went wrong rendering the UI</p>
            <p className="mb-4 break-words text-xs text-slate-400">{this.state.error.message}</p>
            <button
              onClick={() => window.location.reload()}
              className="rounded-xl bg-red-700 px-4 py-2 text-xs font-semibold text-white hover:bg-red-600"
            >
              Reload
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
