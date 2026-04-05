import React, { useState } from 'react';
import './CommunitySummary.css';

const CommunitySummary = ({ communityId, postsCount }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [summary, setSummary] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  const fetchSummary = async () => {
    if (summary) {
      setIsExpanded(!isExpanded);
      return;
    }

    setIsLoading(true);
    setError('');
    setIsExpanded(true);

    try {
      const token = localStorage.getItem('accessToken');
      const response = await fetch(`/communities/${communityId}/summary`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });

      const data = await response.json();

      if (data.success) {
        // Simulate AI generation delay for better UX
        setTimeout(() => {
          setSummary(data.summary);
          setIsLoading(false);
        }, 2000);
      } else {
        setError(data.error || 'Failed to generate summary');
        setIsLoading(false);
      }
    } catch (err) {
      setError('Network error occurred');
      setIsLoading(false);
    }
  };

  // Don't show button if no posts
  if (postsCount === 0) {
    return null;
  }

  return (
    <div className="community-summary-container">
      <button 
        className="whats-happening-btn"
        onClick={fetchSummary}
        disabled={isLoading}
      >
        <div className="btn-content">
          <div className="sparkle-icon">✨</div>
          <span>What's happening in this community</span>
          <div className={`chevron ${isExpanded ? 'expanded' : ''}`}>▼</div>
        </div>
      </button>

      {isExpanded && (
        <div className="summary-panel">
          {isLoading ? (
            <div className="ai-loading">
              <div className="loading-header">
                <div className="ai-icon">🤖</div>
                <span>AI is analyzing community discussions...</span>
              </div>
              <div className="loading-animation">
                <div className="typing-dots">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
              <div className="loading-text">
                Reviewing latest {Math.min(postsCount, 5)} posts
              </div>
            </div>
          ) : error ? (
            <div className="error-state">
              <div className="error-icon">⚠️</div>
              <span>{error}</span>
            </div>
          ) : summary ? (
            <div className="summary-content">
              <div className="summary-header">
                <div className="ai-badge">
                  <span className="ai-icon">🤖</span>
                  <span>AI Summary</span>
                </div>
              </div>
              <div className="summary-text">
                {summary}
              </div>
              <div className="summary-footer">
                Based on the latest {Math.min(postsCount, 5)} posts
              </div>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
};

export default CommunitySummary;
