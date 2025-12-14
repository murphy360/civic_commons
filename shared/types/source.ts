/**
 * Source types for the Civic Commons platform
 */

export interface Source {
  id: number;
  cityId: string;
  name: string;
  sourceType: string;
  driverType: string;
  url: string;
  config?: Record<string, unknown>;
  isEnabled: boolean;
  scheduleInterval?: number;
  lastFetchedAt?: Date;
  lastSuccessAt?: Date;
  lastError?: string;
  consecutiveFailures: number;
  createdAt: Date;
  updatedAt: Date;
}

export interface SourceHealth {
  id: number;
  name: string;
  sourceType: string;
  status: 'healthy' | 'degraded' | 'unhealthy' | 'unknown';
  lastSuccess?: Date;
  lastError?: string;
  isEnabled: boolean;
}

export interface CreateSourceInput {
  cityId: string;
  name: string;
  sourceType: string;
  driverType: string;
  url: string;
  config?: Record<string, unknown>;
  isEnabled?: boolean;
  scheduleInterval?: number;
}

export interface UpdateSourceInput {
  name?: string;
  url?: string;
  config?: Record<string, unknown>;
  isEnabled?: boolean;
  scheduleInterval?: number;
}

export type SourceType =
  | 'city_council'
  | 'school_board'
  | 'library'
  | 'parks_and_rec'
  | 'metroparks'
  | 'historical_society'
  | 'chamber_of_commerce'
  | 'social_media'
  | 'other';

export type DriverType =
  | 'civic_plus'
  | 'aspnet_generic'
  | 'rss'
  | 'libcal'
  | 'json_api'
  | 'static_html'
  | 'custom';
