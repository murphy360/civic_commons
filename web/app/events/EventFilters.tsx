'use client';

import { useState, useCallback, useMemo } from 'react';

interface FilterState {
  search: string;
  sources: string[];
  hasDocuments: boolean | null;
  hasVideo: boolean | null;
  hasAISummary: boolean | null;
  dateRange: 'all' | '7days' | '30days' | '90days' | 'year';
}

interface EventFiltersProps {
  availableSources: string[];
  onFilterChange: (filters: FilterState) => void;
  totalCount: number;
  filteredCount: number;
  showDateRange?: boolean;
}

export default function EventFilters({ 
  availableSources, 
  onFilterChange,
  totalCount,
  filteredCount,
  showDateRange = true
}: EventFiltersProps) {
  const [filters, setFilters] = useState<FilterState>({
    search: '',
    sources: [],
    hasDocuments: null,
    hasVideo: null,
    hasAISummary: null,
    dateRange: 'all',
  });
  
  const [showSourceDropdown, setShowSourceDropdown] = useState(false);

  const updateFilters = useCallback((updates: Partial<FilterState>) => {
    const newFilters = { ...filters, ...updates };
    setFilters(newFilters);
    onFilterChange(newFilters);
  }, [filters, onFilterChange]);

  const toggleSource = useCallback((source: string) => {
    const newSources = filters.sources.includes(source)
      ? filters.sources.filter(s => s !== source)
      : [...filters.sources, source];
    updateFilters({ sources: newSources });
  }, [filters.sources, updateFilters]);

  const clearAllFilters = useCallback(() => {
    const cleared: FilterState = {
      search: '',
      sources: [],
      hasDocuments: null,
      hasVideo: null,
      hasAISummary: null,
      dateRange: 'all',
    };
    setFilters(cleared);
    onFilterChange(cleared);
  }, [onFilterChange]);

  const hasActiveFilters = filters.search || 
    filters.sources.length > 0 || 
    filters.hasDocuments !== null ||
    filters.hasVideo !== null ||
    filters.hasAISummary !== null ||
    filters.dateRange !== 'all';

  return (
    <div className="space-y-4 mb-6">
      {/* Search and View Toggle Row */}
      <div className="flex flex-col md:flex-row gap-4">
        {/* Search */}
        <div className="relative flex-1">
          <svg 
            className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" 
            fill="none" 
            stroke="currentColor" 
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            placeholder="Search events..."
            value={filters.search}
            onChange={(e) => updateFilters({ search: e.target.value })}
            className="w-full pl-10 pr-4 py-2 border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
        
        {/* Results Count */}
        <div className="flex items-center text-sm text-muted-foreground">
          {filteredCount !== totalCount ? (
            <span>{filteredCount} of {totalCount} events</span>
          ) : (
            <span>{totalCount} events</span>
          )}
        </div>
      </div>

      {/* Filter Pills Row */}
      <div className="flex flex-wrap gap-2 items-center">
        {/* Date Range Dropdown - only shown for past events */}
        {showDateRange && (
          <select
            value={filters.dateRange}
            onChange={(e) => updateFilters({ dateRange: e.target.value as FilterState['dateRange'] })}
            className="px-3 py-1.5 text-sm border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
          >
            <option value="all">All Time</option>
            <option value="7days">Past 7 Days</option>
            <option value="30days">Past 30 Days</option>
            <option value="90days">Past 90 Days</option>
            <option value="year">Past Year</option>
          </select>
        )}

        {/* Source Filter */}
        <div className="relative">
          <button
            onClick={() => setShowSourceDropdown(!showSourceDropdown)}
            className={`px-3 py-1.5 text-sm border rounded-lg flex items-center gap-2 hover:bg-muted/50 transition-colors ${
              filters.sources.length > 0 ? 'bg-primary/10 border-primary text-primary' : ''
            }`}
          >
            <span>
              {filters.sources.length === 0 
                ? 'All Sources' 
                : filters.sources.length === 1 
                  ? filters.sources[0]
                  : `${filters.sources.length} Sources`}
            </span>
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
          
          {showSourceDropdown && (
            <div className="absolute top-full left-0 mt-1 w-64 max-h-64 overflow-y-auto bg-background border rounded-lg shadow-lg z-50">
              <div className="p-2 border-b">
                <button
                  onClick={() => updateFilters({ sources: [] })}
                  className="text-xs text-primary hover:underline"
                >
                  Clear selection
                </button>
              </div>
              <div className="p-2 space-y-1">
                {availableSources.map((source) => (
                  <label
                    key={source}
                    className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-muted/50 cursor-pointer text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={filters.sources.includes(source)}
                      onChange={() => toggleSource(source)}
                      className="rounded border-gray-300"
                    />
                    <span className="truncate">{source}</span>
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Content Filters */}
        <button
          onClick={() => updateFilters({ 
            hasDocuments: filters.hasDocuments === true ? null : true 
          })}
          className={`px-3 py-1.5 text-sm border rounded-lg flex items-center gap-1.5 hover:bg-muted/50 transition-colors ${
            filters.hasDocuments === true ? 'bg-amber-100 border-amber-300 text-amber-800' : ''
          }`}
        >
          📄 Has Docs
        </button>

        <button
          onClick={() => updateFilters({ 
            hasVideo: filters.hasVideo === true ? null : true 
          })}
          className={`px-3 py-1.5 text-sm border rounded-lg flex items-center gap-1.5 hover:bg-muted/50 transition-colors ${
            filters.hasVideo === true ? 'bg-red-100 border-red-300 text-red-800' : ''
          }`}
        >
          📹 Has Video
        </button>

        <button
          onClick={() => updateFilters({ 
            hasAISummary: filters.hasAISummary === true ? null : true 
          })}
          className={`px-3 py-1.5 text-sm border rounded-lg flex items-center gap-1.5 hover:bg-muted/50 transition-colors ${
            filters.hasAISummary === true ? 'bg-indigo-100 border-indigo-300 text-indigo-800' : ''
          }`}
        >
          ✨ AI Summary
        </button>

        {/* Clear All */}
        {hasActiveFilters && (
          <button
            onClick={clearAllFilters}
            className="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground flex items-center gap-1"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
            Clear filters
          </button>
        )}
      </div>

      {/* Active Filters Summary */}
      {filters.sources.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {filters.sources.map((source) => (
            <span
              key={source}
              className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full bg-primary/10 text-primary"
            >
              {source}
              <button 
                onClick={() => toggleSource(source)}
                className="hover:text-primary/70"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// Export the filter state type for use in parent components
export type { FilterState };
