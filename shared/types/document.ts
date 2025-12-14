/**
 * Document types for the Civic Commons platform
 */

export interface Document {
  id: number;
  sourceId: number;
  externalId?: string;
  title: string;
  documentType?: string;
  contentText?: string;
  contentMarkdown?: string;
  sourceUrl?: string;
  fileUrl?: string;
  fileHash?: string;
  publishedDate?: Date;
  createdAt: Date;
  updatedAt: Date;
}

export interface DocumentWithSource extends Document {
  source: {
    name: string;
    sourceType: string;
    cityId: string;
  };
}

export interface CreateDocumentInput {
  sourceId: number;
  externalId?: string;
  title: string;
  documentType?: string;
  contentText?: string;
  contentMarkdown?: string;
  sourceUrl?: string;
  fileUrl?: string;
  fileHash?: string;
  publishedDate?: Date;
  rawData?: Record<string, unknown>;
}

export interface DocumentSearchResult {
  id: number;
  title: string;
  documentType?: string;
  sourceUrl?: string;
  publishedDate?: Date;
  sourceName: string;
  sourceType: string;
  relevanceScore: number;
  snippet?: string;
}

export interface DocumentFilters {
  cityId?: string;
  sourceType?: string;
  documentType?: string;
  query?: string;
  startDate?: Date;
  endDate?: Date;
  limit?: number;
  offset?: number;
}

export type DocumentType =
  | 'agenda'
  | 'minutes'
  | 'ordinance'
  | 'resolution'
  | 'report'
  | 'notice'
  | 'newsletter'
  | 'other';
