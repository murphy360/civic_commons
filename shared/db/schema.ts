import {
  pgTable,
  serial,
  varchar,
  text,
  timestamp,
  boolean,
  integer,
  jsonb,
  index,
  uniqueIndex,
  primaryKey,
} from 'drizzle-orm/pg-core';
import { relations } from 'drizzle-orm';

// =============================================================================
// City Configuration
// =============================================================================

export const cities = pgTable('cities', {
  id: serial('id').primaryKey(),
  cityId: varchar('city_id', { length: 64 }).notNull().unique(),
  displayName: varchar('display_name', { length: 256 }).notNull(),
  assistantName: varchar('assistant_name', { length: 128 }),
  assistantPersona: text('assistant_persona'),
  timezone: varchar('timezone', { length: 64 }),  // Should come from config
  metadata: jsonb('metadata').$type<Record<string, unknown>>(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
}, (table) => ({
  cityIdIdx: uniqueIndex('cities_city_id_idx').on(table.cityId),
}));

export const citiesRelations = relations(cities, ({ many }) => ({
  sources: many(sources),
}));

// =============================================================================
// Data Sources
// =============================================================================

export const sources = pgTable('sources', {
  id: serial('id').primaryKey(),
  cityId: varchar('city_id', { length: 64 }).notNull(),
  name: varchar('name', { length: 256 }).notNull(),
  sourceType: varchar('source_type', { length: 64 }).notNull(),
  driverType: varchar('driver_type', { length: 64 }).notNull(),
  url: text('url').notNull(),
  config: jsonb('config').$type<Record<string, unknown>>(),
  isEnabled: boolean('is_enabled').default(true).notNull(),
  scheduleInterval: integer('schedule_interval').default(3600), // seconds
  lastFetchedAt: timestamp('last_fetched_at'),
  lastSuccessAt: timestamp('last_success_at'),
  lastError: text('last_error'),
  consecutiveFailures: integer('consecutive_failures').default(0).notNull(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
}, (table) => ({
  cityIdIdx: index('sources_city_id_idx').on(table.cityId),
  sourceTypeIdx: index('sources_source_type_idx').on(table.sourceType),
}));

export const sourcesRelations = relations(sources, ({ one, many }) => ({
  city: one(cities, {
    fields: [sources.cityId],
    references: [cities.cityId],
  }),
  events: many(events),
  documents: many(documents),
}));

// =============================================================================
// Events
// =============================================================================

export const events = pgTable('events', {
  id: serial('id').primaryKey(),
  sourceId: integer('source_id').notNull(),
  externalId: varchar('external_id', { length: 256 }),
  title: varchar('title', { length: 512 }).notNull(),
  description: text('description'),
  startTime: timestamp('start_time').notNull(),
  endTime: timestamp('end_time'),
  location: varchar('location', { length: 512 }),
  sourceUrl: text('source_url'),
  rawData: jsonb('raw_data').$type<Record<string, unknown>>(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
}, (table) => ({
  sourceIdIdx: index('events_source_id_idx').on(table.sourceId),
  startTimeIdx: index('events_start_time_idx').on(table.startTime),
  externalIdIdx: index('events_external_id_idx').on(table.sourceId, table.externalId),
}));

export const eventsRelations = relations(events, ({ one }) => ({
  source: one(sources, {
    fields: [events.sourceId],
    references: [sources.id],
  }),
}));

// =============================================================================
// Documents
// =============================================================================
// Content lifecycle statuses:
//   discovered        - Found by scraper, metadata only (visible as placeholder)
//   download_pending  - Queued for download
//   downloading       - Currently downloading
//   downloaded        - File saved locally
//   extraction_pending - Queued for text extraction
//   extracting        - Currently extracting text
//   extracted         - Text available
//   ai_pending        - Queued for AI summary
//   ai_processing     - AI generating summary
//   complete          - Fully processed
//   failed            - Processing failed
//   skipped           - Non-processable content

export const documents = pgTable('documents', {
  id: serial('id').primaryKey(),
  sourceId: integer('source_id').notNull(),
  externalId: varchar('external_id', { length: 256 }),
  title: varchar('title', { length: 512 }).notNull(),
  documentType: varchar('document_type', { length: 64 }),
  contentText: text('content_text'),
  contentMarkdown: text('content_markdown'),
  sourceUrl: text('source_url'),
  fileUrl: text('file_url'),
  fileHash: varchar('file_hash', { length: 64 }),
  localPath: text('local_path'),
  fileSizeBytes: integer('file_size_bytes'),
  mimeType: varchar('mime_type', { length: 128 }),
  aiSummary: text('ai_summary'),
  aiSummaryUpdatedAt: timestamp('ai_summary_updated_at'),
  aiModelUsed: varchar('ai_model_used', { length: 64 }),
  publishedDate: timestamp('published_date'),
  meetingDate: timestamp('meeting_date'),
  // Unified content lifecycle tracking
  contentStatus: varchar('content_status', { length: 32 }).default('discovered'),
  errorMessage: text('error_message'),
  retryCount: integer('retry_count').default(0),
  retryAfter: timestamp('retry_after'),
  // Processing timestamps
  discoveredAt: timestamp('discovered_at'),
  downloadStartedAt: timestamp('download_started_at'),
  downloadCompletedAt: timestamp('download_completed_at'),
  extractionStartedAt: timestamp('extraction_started_at'),
  extractionCompletedAt: timestamp('extraction_completed_at'),
  aiStartedAt: timestamp('ai_started_at'),
  aiCompletedAt: timestamp('ai_completed_at'),
  rawData: jsonb('raw_data').$type<Record<string, unknown>>(),
  // Note: search_vector is managed via PostgreSQL trigger
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
}, (table) => ({
  sourceIdIdx: index('documents_source_id_idx').on(table.sourceId),
  documentTypeIdx: index('documents_document_type_idx').on(table.documentType),
  publishedDateIdx: index('documents_published_date_idx').on(table.publishedDate),
  externalIdIdx: index('documents_external_id_idx').on(table.sourceId, table.externalId),
  contentStatusIdx: index('documents_content_status_idx').on(table.contentStatus),
}));

export const documentsRelations = relations(documents, ({ one }) => ({
  source: one(sources, {
    fields: [documents.sourceId],
    references: [sources.id],
  }),
}));

// =============================================================================
// NextAuth Tables
// =============================================================================

export const users = pgTable('users', {
  id: text('id').primaryKey(),
  name: text('name'),
  email: text('email').notNull().unique(),
  emailVerified: timestamp('email_verified', { mode: 'date' }),
  image: text('image'),
  role: varchar('role', { length: 32 }).default('user').notNull(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
});

export const accounts = pgTable('accounts', {
  userId: text('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  type: text('type').notNull(),
  provider: text('provider').notNull(),
  providerAccountId: text('provider_account_id').notNull(),
  refresh_token: text('refresh_token'),
  access_token: text('access_token'),
  expires_at: integer('expires_at'),
  token_type: text('token_type'),
  scope: text('scope'),
  id_token: text('id_token'),
  session_state: text('session_state'),
}, (table) => ({
  pk: primaryKey({ columns: [table.provider, table.providerAccountId] }),
}));

export const sessions = pgTable('sessions', {
  sessionToken: text('session_token').primaryKey(),
  userId: text('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  expires: timestamp('expires', { mode: 'date' }).notNull(),
});

export const verificationTokens = pgTable('verification_tokens', {
  identifier: text('identifier').notNull(),
  token: text('token').notNull(),
  expires: timestamp('expires', { mode: 'date' }).notNull(),
}, (table) => ({
  pk: primaryKey({ columns: [table.identifier, table.token] }),
}));

// =============================================================================
// Scraper Logs (for admin dashboard)
// =============================================================================

export const scraperLogs = pgTable('scraper_logs', {
  id: serial('id').primaryKey(),
  sourceId: integer('source_id').notNull(),
  status: varchar('status', { length: 32 }).notNull(), // 'success', 'error', 'warning'
  message: text('message'),
  eventsFound: integer('events_found').default(0),
  documentsFound: integer('documents_found').default(0),
  duration: integer('duration'), // milliseconds
  errorDetails: jsonb('error_details').$type<Record<string, unknown>>(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
}, (table) => ({
  sourceIdIdx: index('scraper_logs_source_id_idx').on(table.sourceId),
  statusIdx: index('scraper_logs_status_idx').on(table.status),
  createdAtIdx: index('scraper_logs_created_at_idx').on(table.createdAt),
}));

export const scraperLogsRelations = relations(scraperLogs, ({ one }) => ({
  source: one(sources, {
    fields: [scraperLogs.sourceId],
    references: [sources.id],
  }),
}));
