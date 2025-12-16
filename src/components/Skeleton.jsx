import React from 'react'
import './Skeleton.css'

export function Skeleton({ width, height, circle, className = '' }) {
  const style = {
    width: width || '100%',
    height: height || '20px',
    borderRadius: circle ? '50%' : '8px'
  }

  return (
    <div className={`skeleton ${className}`} style={style}>
      <div className="skeleton-shimmer"></div>
    </div>
  )
}

export function SkeletonCard() {
  return (
    <div className="skeleton-card">
      <Skeleton height="24px" width="60%" />
      <Skeleton height="16px" width="100%" style={{ marginTop: '12px' }} />
      <Skeleton height="16px" width="80%" style={{ marginTop: '8px' }} />
    </div>
  )
}

export function SkeletonTable({ rows = 5, cols = 4 }) {
  return (
    <div className="skeleton-table">
      <div className="skeleton-table-header">
        {Array.from({ length: cols }).map((_, i) => (
          <Skeleton key={i} height="20px" width="100px" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton-table-row">
          {Array.from({ length: cols }).map((_, j) => (
            <Skeleton key={j} height="16px" width="80%" />
          ))}
        </div>
      ))}
    </div>
  )
}

export function SkeletonPill() {
  return (
    <div className="skeleton-pill">
      <Skeleton height="36px" width="120px" />
    </div>
  )
}
