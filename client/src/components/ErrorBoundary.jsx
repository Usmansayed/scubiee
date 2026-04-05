import React from 'react';
import { MdRefresh } from 'react-icons/md';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { 
      hasError: false,
      error: null,
      errorInfo: null,
      componentName: props.componentName || 'this component'
    };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    this.setState({ errorInfo });
    console.error(`Error caught by ${this.state.componentName} ErrorBoundary:`, error, errorInfo);
    
    // Log to analytics or monitoring service here if needed
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
    
    // Force a hard refresh if this.props.forceRefresh is true
    if (this.props.forceRefresh) {
      window.location.reload();
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col justify-center items-center h-full w-full bg-transparent text-white p-6 rounded-2xl">
          <div className="mb-4 text-red-500">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-16 w-16" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <h3 className="text-xl font-bold mb-2">Something went wrong</h3>
          <p className="text-gray-400 text-center mb-6">
            {this.props.errorMessage || `${this.state.componentName} encountered an error and couldn't continue.`}
          </p>
          <button 
            onClick={this.handleReset}
            className="flex items-center justify-center bg-primary hover:bg-primary/80 text-white py-2 px-4 rounded-lg transition duration-200"
          >
            <MdRefresh className="mr-2" size={20} /> 
            {this.props.resetButtonText || "Try Again"}
          </button>
          {this.props.showErrorDetails && (
            <details className="mt-4 p-2 border border-gray-700 rounded text-xs text-gray-400">
              <summary className="cursor-pointer">Technical Details</summary>
              <p className="mt-2">{this.state.error?.toString()}</p>
              <pre className="mt-2 whitespace-pre-wrap">
                {this.state.errorInfo?.componentStack}
              </pre>
            </details>
          )}
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
