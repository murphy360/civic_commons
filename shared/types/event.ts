/**
 * Event types for the Civic Commons platform
 */

export interface Event {
  id: number;
  sourceId: number;
  externalId?: string;
  title: string;
  description?: string;
  startTime: Date;
  endTime?: Date;
  location?: string;
  sourceUrl?: string;
  createdAt: Date;
  updatedAt: Date;
}

export interface EventWithSource extends Event {
  source: {
    name: string;
    sourceType: string;
    cityId: string;
  };
}

export interface CreateEventInput {
  sourceId: number;
  externalId?: string;
  title: string;
  description?: string;
  startTime: Date;
  endTime?: Date;
  location?: string;
  sourceUrl?: string;
  rawData?: Record<string, unknown>;
}

export interface EventFilters {
  cityId?: string;
  sourceType?: string;
  startDate?: Date;
  endDate?: Date;
  limit?: number;
  offset?: number;
}
